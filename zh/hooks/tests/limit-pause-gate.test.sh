#!/bin/bash
# 回归测试: limit-pause-gate.sh
# 跑法: bash hooks/tests/limit-pause-gate.test.sh
HOOK="$(dirname "$0")/../limit-pause-gate.sh"
PASS=0; FAIL=0
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
CACHE="$TMP/usage.json"
RL="$TMP/rate-limits.json"

# rl <五小时用量%> <距重置秒数> [越过 95% 在几秒前] —— 写状态栏落盘的 rate_limits（Claude Code 原样字段，
# 另带 statusline-tee.sh 记的 pause_since）
rl() {
  python3 -c '
import json, sys, time
d = {"five_hour": {"used_percentage": float(sys.argv[2]), "resets_at": int(time.time() + float(sys.argv[3]))}}
if len(sys.argv) > 4:
    d["pause_since"] = time.time() - float(sys.argv[4])
json.dump(d, open(sys.argv[1], "w"))' "$RL" "$@"
}

# tx <事件...> —— 造主线程 transcript 到 $TX。事件 <种类>:<几秒前>：
#   human  回合开头本人输入          qhuman  回合中途本人插话（queued_command 附件）
#   notify 后台通知开启的回合        qnotify 回合中途插进来的后台通知
#   peer   子智能体回报              wake    句点保活唤醒       final  最后一次保活唤醒
#   tool   只含工具结果的用户角色行  meta    isMeta 用户角色行（Stop 钩子拦截反馈）
#   launch 后台派出子智能体 a_old 的工具结果（主 transcript 里出现它的编号）
TX="$TMP/main.jsonl"
tx() {
  python3 - "$TX" "$@" <<'PY'
import json, sys, time
from datetime import datetime, timezone
out, events = sys.argv[1], sys.argv[2:]
def ts(ago): return datetime.fromtimestamp(time.time() - float(ago), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
WAKE = "<task-notification>\n<summary>Stop hook feedback</summary>\n</task-notification>\n[保活] 只回复一个句点，不做别的。"
FINAL = "<task-notification>\n<summary>Stop hook feedback</summary>\n</task-notification>\n[保活] 用户已离开近 8 小时，这是最后一次保活。"
lines = []
for e in events:
    k, _, ago = e.partition(":")
    def user(content, kind, **kw):
        d = {"type": "user", "timestamp": ts(ago), "message": {"role": "user", "content": content},
             "origin": {"kind": kind} if kind else None}
        d.update(kw); lines.append(d)
    def queued(prompt, kind):
        lines.append({"type": "attachment", "timestamp": ts(ago),
                      "attachment": {"type": "queued_command", "prompt": prompt, "origin": {"kind": kind}}})
    if k == "human":     user("帮我看看", "human", promptSource="typed")
    elif k == "notify":  user("<task-notification><task-id>b1</task-id></task-notification>", "task-notification")
    elif k == "peer":    user("Another Claude session sent a message: hi", "peer", isMeta=True)
    elif k == "wake":    user(WAKE, "task-notification")
    elif k == "final":   user(FINAL, "task-notification")
    elif k == "qhuman":  queued("顺便看下这个", "human")
    elif k == "qnotify": queued("<task-notification><task-id>b2</task-id></task-notification>", "task-notification")
    elif k == "tool":    user([{"type": "tool_result", "tool_use_id": "t", "content": "ok"}], None)
    elif k == "meta":    user("Stop hook feedback:\n回复以提议问句收尾。", None, isMeta=True)
    elif k == "launch":  user([{"type": "tool_result", "tool_use_id": "t", "content": "Async agent launched successfully. agentId: a_old"}], None)
    lines.append({"type": "assistant", "timestamp": ts(ago), "message": {"role": "assistant", "content": []}})
with open(out, "w") as f:
    for d in lines: f.write(json.dumps(d, ensure_ascii=False) + "\n")
PY
}

# cache <五小时用量%> <距重置秒数> —— 写 claude-hud 用量缓存
cache() {
  python3 - "$CACHE" "$1" "$2" <<'PY'
import json, sys, time
from datetime import datetime, timezone
out, pct, secs = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
at = datetime.fromtimestamp(time.time() + secs, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
json.dump({"data": {"fiveHour": pct, "fiveHourResetAt": at}, "timestamp": int(time.time() * 1000)}, open(out, "w"))
PY
}

# verdict [Bash 命令] —— 跑钩子；transcript 取 $TX（存在时），子智能体内时设 $AGENT。跑钩子（单次最多睡 1 秒），归成 allow|approve|deny|其他，另记耗时到 $TMP/secs。
# allow ＝无输出放行（照常走权限流程）；approve ＝输出 permissionDecision allow（跳过审批）。
verdict() {
  local rc s e
  if [ ! -f "$HOOK" ]; then echo "脚本不存在"; return; fi
  s=$(python3 -c 'import time;print(time.time())')
  python3 -c '
import json, os, sys
p = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": sys.argv[1]}}
if os.path.isfile(sys.argv[2]): p["transcript_path"] = sys.argv[2]
if sys.argv[3]: p["agent_id"] = sys.argv[3]
print(json.dumps(p))' "${1:-ls}" "$TX" "$AGENT" |
    LIMIT_PAUSE_CACHE="$CACHE" LIMIT_PAUSE_RL="$RL" LIMIT_PAUSE_OFF="$TMP/off" LIMIT_PAUSE_MAX_SLEEP="${SLP:-1}" bash "$HOOK" >"$TMP/out" 2>"$TMP/err"
  rc=$?
  e=$(python3 -c 'import time;print(time.time())')
  python3 -c "print(round($e-$s,1))" >"$TMP/secs"
  python3 - "$rc" "$TMP/out" "$TMP/err" <<'PY'
import json, sys
rc, out, err = sys.argv[1], open(sys.argv[2]).read(), open(sys.argv[3]).read()
if rc == "0" and not out.strip() and not err: print("allow"); sys.exit()
try:
    h = json.loads(out)["hookSpecificOutput"]
    if rc == "0" and h["permissionDecision"] == "deny" and "用户发来了新消息" in h["permissionDecisionReason"]:
        print("human"); sys.exit()
    if rc == "0" and h["permissionDecision"] == "deny" and "限额暂停" in h["permissionDecisionReason"]:
        print("deny"); sys.exit()
    if rc == "0" and h["permissionDecision"] == "allow":
        print("approve"); sys.exit()
except Exception:
    pass
print("退出%s stdout=%r stderr=%r" % (rc, out[:80], err[:80]))
PY
}

report() {  # report <期望> <实际> <描述>
  if [ "$1" = "$2" ]; then
    PASS=$((PASS+1)); printf '  ✅ %-44s [%s]\n' "$3" "$2"
  else
    FAIL=$((FAIL+1)); printf '  ❌ %-44s 期望=%s 实际=%s\n' "$3" "$1" "$2"
  fi
}

echo "── 判定 ──"
report allow "$(verdict)" "用量缓存不存在，放行"
cache 94 7200;  report allow "$(verdict)" "用量 94%，放行"
cache 95 -10;   report allow "$(verdict)" "用量 95% 但已过重置时间，放行"
cache 100 7200; report deny  "$(verdict)" "用量 100%、离重置 2 小时：睡一轮后拦下转保活"
cache 95 7200;  report deny  "$(verdict)" "用量 95%、离重置 2 小时：睡一轮后拦下转保活"
s=$(cat "$TMP/secs"); report yes "$(python3 -c "print('yes' if $s >= 0.9 else 'no')")" "拦下之前确实睡满一轮（${s}s）"
report yes "$(python3 -c "import json,sys;r=json.load(open(sys.argv[1]))['hookSpecificOutput']['permissionDecisionReason'];print('yes' if '用量已到 95%，' in r and '\`: 限额暂停\`' in r else r)" "$TMP/out")" "拦截理由带用量与保活命令"
cache 95 0.5;   report allow "$(verdict)" "离重置不到一轮：睡到重置后放行"
s=$(cat "$TMP/secs"); report yes "$(python3 -c "print('yes' if 0.4 <= $s < 0.95 else 'no')")" "只睡到重置为止（${s}s）"
cache 95 0.5;   report approve "$(verdict ': 限额暂停')" "暂停命令到重置后放行，并跳过权限审批"
cache 95 7200;  report deny "$(verdict ': 限额暂停')" "暂停命令未到重置：睡一轮后再拦下"
cache 50 7200;  report approve "$(verdict ': 限额暂停')" "用量已低于阈值时暂停命令也跳过审批"
echo "── 两个来源取未过重置的最高值（同一窗口内用量只增不减，较低的是旧值） ──"
cache 50 7200; sleep 0.1; rl 96 7200; report deny  "$(verdict)" "插件缓存 50%、状态栏数据 96%：拦下"
cache 99 7200; sleep 0.1; rl 40 7200; report deny  "$(verdict)" "插件缓存 99%、较新写入的状态栏数据 40%：拦下"
rl 96 7200; sleep 0.1; cache 50 7200; report deny  "$(verdict)" "状态栏数据 96%、较新写入的插件缓存 50%：拦下"
cache 99 -5; rl 40 7200;              report allow "$(verdict)" "插件缓存 99% 已过重置、状态栏新窗口 40%：放行"
rm -f "$CACHE"; rl 99 -5;  report allow "$(verdict)" "只有状态栏数据且已过重置：放行"
printf 'garbage' >"$RL"; cache 99 7200; report deny "$(verdict)" "状态栏数据损坏时退回插件缓存"
rm -f "$RL"

echo "── 越过 95% 之后本人发起的输入不拦（表驱动：期望|描述|越过在几秒前|子智能体|事件...） ──"
rm -f "$CACHE"
while IFS='|' read -r want desc since agent events; do
  [ -z "$want" ] && continue
  rl 97 7200 "$since"
  # shellcheck disable=SC2086
  tx $events
  report "$want" "$(AGENT="$agent" verdict)" "$desc"
done <<'TABLE'
allow|越过之后本人发起的回合|100||human:10 tool:5
deny|越过之前就开始的回合（全自动长任务）|100||human:200 tool:50 tool:5
deny|本人回合中途插进后台通知，之后的调用照常拦|100||human:30 qnotify:10 tool:5
allow|中途通知之后本人又插话，又不拦|100||human:30 qnotify:20 qhuman:10 tool:5
allow|越过之后本人在回合中途插话也算|100||human:200 tool:150 qhuman:10 tool:5
deny|后台通知开启的回合|100||human:200 notify:10 tool:5
deny|子智能体回报开启的回合|100||human:200 peer:10 tool:5
deny|句点保活唤醒的回合|100||human:200 wake:10 tool:5
allow|最后一次保活唤醒的回合（写交接）|100||human:200 final:10 tool:5
allow|Stop 钩子拦截反馈（isMeta）不改变回合归属|100||human:10 tool:8 meta:5 tool:3
deny|子智能体内一律照常拦|100|a_01|human:10 tool:5
allow|最后一次保活那一轮新派的子智能体（写交接）|100|a_new|human:200 final:10 tool:5
deny|最后一次保活之前就在跑的后台子智能体|100|a_old|human:200 launch:100 final:10 tool:5
deny|句点保活那一轮派的子智能体|100|a_new|human:200 wake:10 tool:5
TABLE
rl 97 7200; tx human:10 tool:5
report deny "$(verdict)" "不知道何时越过 95%：本人回合也照常拦"

echo "── 挂起期间本人发来消息：立即结束挂起，让消息送达 ──"
enq() { printf '%s\n' "{\"type\":\"queue-operation\",\"operation\":\"enqueue\",\"content\":\"$1\"}" >>"$TX"; }
rl 97 7200 100; tx human:200 tool:5
(sleep 1; enq "在吗，先看个小问题") &
report human "$(SLP=6 verdict)" "主线程挂起中本人发来消息：结束挂起"
wait; s=$(cat "$TMP/secs"); report yes "$(python3 -c "print('yes' if $s < 5 else 'no')")" "几秒内结束挂起（${s}s）"
tx human:200 tool:5
(sleep 1; enq "<task-notification><task-id>b9</task-id></task-notification>") &
report deny "$(SLP=3 verdict)" "挂起中来的是后台通知：照常挂满"
wait
tx human:200 tool:5
(sleep 1; enq "在吗") &
report deny "$(SLP=3 AGENT=a_01 verdict)" "子智能体挂起中不看主线程消息"
wait
rm -f "$TX"; rl 97 7200 100
report deny "$(verdict)" "没有 transcript：照常拦"
touch "$TMP/off"; report allow "$(verdict)" "手动开关文件存在：一律放行"
rm -f "$TMP/off" "$RL"
printf 'not json' >"$CACHE"; report allow "$(verdict)" "用量缓存损坏，放行"

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
