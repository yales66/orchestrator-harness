#!/bin/bash
# 回归测试: keepalive-gate.sh
# 跑法: bash hooks/tests/keepalive-gate.test.sh
HOOK="$(dirname "$0")/../keepalive-gate.sh"
PASS=0; FAIL=0
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
# 大部分用例按中文安装跑（唤醒提示里约定回「完」）；末尾一组不设 REPLY_LANG，按英文安装跑（约定回 Done）
export REPLY_LANG=zh
WAKE_PROMPT_EN='[保活] 只回复一个句点，不做别的；下列任一成立时，改为只回一个 Done，不带别的字：A. 本会话的任务已做完，没有待用户答复的问题，也没有在跑的后台任务或子智能体。B. 本会话已用 handoff 技能写出交接文件，把剩余工作交给别的会话：剩余工作、待用户答复的问题和仍在跑的任务都已写进交接文件，写完之后本会话没有新进展（交接里已登记的任务发来完成通知不算新进展）。'
WAKE_PROMPT='[保活] 只回复一个句点，不做别的；下列任一成立时，改为只回一个「完」字，不带别的字：A. 本会话的任务已做完，没有待用户答复的问题，也没有在跑的后台任务或子智能体。B. 本会话已用 handoff 技能写出交接文件，把剩余工作交给别的会话：剩余工作、待用户答复的问题和仍在跑的任务都已写进交接文件，写完之后本会话没有新进展（交接里已登记的任务发来完成通知不算新进展）。'
HANDOFF_PROMPT='[保活] 用户已离开近 8 小时，这是最后一次保活。本回合不做提交、推送、开 PR、合并等收尾，也不重新提问，按第一条成立的做完就结束：A. 还有要新会话接着做的实质工作，或有待用户答复的问题（不论答复后剩什么）：用 handoff 技能交接，走完该技能的全部步骤。B. 剩下的只有收尾（提交、推送、开 PR、合并、在跑任务回报后收尾），可夹带用户本人要做的事：在本任务的进度源末尾追加一节，逐条写剩下的动作和各自的核对命令，在跑任务写明产物路径，用户本人要做的事一并写进（没有进度源就在工作目录新建只追加的 PROGRESS.md），然后回一个句点。C. 任务已做完，或剩下的只有用户本人能做、做完后不用会话接着做的事（如人工登录、人工审核），或已有的交接或计划文件已写全剩余工作且之后没有新进展：只回一个句点。'
# 唤醒提示进 transcript 时的样子（Claude Code 包成后台通知）
rewake_of() { printf '<task-notification>\n<summary>Stop hook feedback</summary>\n</task-notification>\n<system-reminder>\nStop hook blocking error from command "Stop": %s\n</system-reminder>' "$1"; }
REWAKE=$(rewake_of "$WAKE_PROMPT")
REWAKE_HO=$(rewake_of "$HANDOFF_PROMPT")
# 探测地址：file:// 指向的文件存在就算连得上，测试里用它模拟网络通断
UP="$TMP/up"; touch "$UP"
DOWN="$TMP/down"
# 已结束会话的标记目录，测试不碰真实的 ~/.claude/state
ENDED="$TMP/ended"
# 父会话标记目录（分片），测试不碰真实的 ~/.claude/state；缺省为空目录，即没有任何父会话标记
SHARD="$TMP/sharding"

# mk <文件名> <事件...> —— 按事件顺序造 transcript，回传路径。事件：
#   user:<几小时前>      用户本人消息        rewake:<几小时前>  保活唤醒进 transcript 的消息
#   rewakeho:<几小时前>  最后一次保活（视情况写交接）的唤醒消息
#   agentmsg:<几小时前>  子智能体回报        notify:<几小时前>  后台通知
#   peer:<几小时前>      另一会话发来的消息  meta:<几小时前>    isMeta 的用户角色消息
#   toolres              一条只含工具结果的用户角色消息
#   askans:<几小时前>    用户回答选择题（AskUserQuestion 的工具结果，顶层带 toolUseResult.questions）
#   askafk:<几小时前>    选择题无人回答、超时自动提交（toolUseResult 另带 afkTimeoutMs）
#   asst:<token>         主线程 assistant    side:<token>       子智能体（isSidechain）assistant
#   dup:<token>          与上一条 assistant 同 message.id 的续行
#   w5m:<token> w1h:<token> w0:<token>  主线程 assistant，usage.cache_creation 按 5 分钟／1 小时写入，
#                        或两档都为 0；asst 不带 cache_creation 字段
#   s5m:<token>          子智能体（isSidechain）assistant，按 5 分钟写入
#   summary              Stop 之后 Claude Code 自己写的 stop_hook_summary 与 turn_duration
#   blob                 Claude Code 2.1.300 起写的 api-request-blob 行：带用户角色的 message、没有时间戳
#   done:<token>         主线程 assistant，正文只有「完」（保活回合里表示任务已做完）
#   doneen:<token>       同上，正文只有 Done；doneenq 为 "Done."；notdone 为以 Done 开头的一句话
#   doneq:<token>        同上，正文照抄成「「完」。」
mk() {
  local f="$TMP/$1"; shift
  REWAKE="$REWAKE" REWAKE_HO="$REWAKE_HO" python3 - "$f" "$@" <<'PY'
import json, os, sys, time
from datetime import datetime, timezone
out, events = sys.argv[1], sys.argv[2:]
now = time.time()
def ts(hours):
    return datetime.fromtimestamp(now - float(hours) * 3600, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
lines, n, last_id = [], 0, "msg_0"
def user(content, hours=0, **kw):
    d = {"type": "user", "timestamp": ts(hours), "message": {"role": "user", "content": content}}
    d.update(kw); lines.append(d)
def asst(tok, mid, side=False, ttl=None, text="ok"):
    u = {"input_tokens": 2, "cache_read_input_tokens": int(tok) - 2, "cache_creation_input_tokens": 0}
    if ttl is not None:
        w = 0 if ttl == "0" else 100
        u["cache_read_input_tokens"] -= w
        u["cache_creation_input_tokens"] = w
        u["cache_creation"] = {"ephemeral_5m_input_tokens": w if ttl == "5m" else 0,
                               "ephemeral_1h_input_tokens": w if ttl == "1h" else 0}
    lines.append({"type": "assistant", "isSidechain": side, "timestamp": ts(0),
                  "message": {"role": "assistant", "id": mid, "content": [{"type": "text", "text": text}],
                              "usage": u}})
for e in events:
    k, _, v = e.partition(":")
    if k == "user":     user("帮我看看这个", v)
    elif k == "rewake": user(os.environ["REWAKE"], v)
    elif k == "rewakeho": user(os.environ["REWAKE_HO"], v)
    elif k == "agentmsg": user('<agent-message from="worker">做完了</agent-message>', v)
    elif k == "notify": user("<task-notification><task-id>b1</task-id></task-notification>", v)
    elif k == "peer":   user("Another Claude session sent a message: hi", v)
    elif k == "meta":   user("Stop hook feedback:\n回复以提议问句收尾。", v, isMeta=True)
    elif k == "askans":
        n += 1
        user([{"type": "tool_result", "tool_use_id": "toolu_q%d" % n, "content": "Your questions have been answered"}], v,
             toolUseResult={"questions": [{"question": "选哪个？"}], "answers": {"选哪个？": "A"}})
    elif k == "askafk":
        n += 1
        user([{"type": "tool_result", "tool_use_id": "toolu_q%d" % n, "content": "No response after 3000s"}], v,
             toolUseResult={"questions": [{"question": "选哪个？"}], "answers": {}, "afkTimeoutMs": 3000000})
    elif k == "toolres":
        n += 1; user([{"type": "tool_result", "tool_use_id": "toolu_x%d" % n, "content": "[]"}])
    elif k in ("asst", "side"):
        n += 1; last_id = "msg_%d" % n; asst(v, last_id, side=(k == "side"))
    elif k == "dup":    asst(v, last_id)
    elif k == "done":
        n += 1; last_id = "msg_%d" % n; asst(v, last_id, text="完")
    elif k == "doneq":
        n += 1; last_id = "msg_%d" % n; asst(v, last_id, text="「完」。")
    elif k == "doneen":
        n += 1; last_id = "msg_%d" % n; asst(v, last_id, text="Done")
    elif k == "doneenq":
        n += 1; last_id = "msg_%d" % n; asst(v, last_id, text="\"Done.\"")
    elif k == "notdone":
        n += 1; last_id = "msg_%d" % n; asst(v, last_id, text="Done with the tests, still open")
    elif k == "blob":
        lines.append({"type": "api-request-blob", "hash": "h%d" % len(lines),
                      "message": {"role": "user", "content": [{"type": "text", "text": "<system-reminder>\nx\n</system-reminder>"}]}})
    elif k in ("w5m", "w1h", "w0"):
        n += 1; last_id = "msg_%d" % n; asst(v, last_id, ttl=k[1:])
    elif k == "s5m":
        n += 1; asst(v, "msg_%d" % n, side=True, ttl="5m")
    elif k == "summary":
        lines.append({"type": "system", "subtype": "stop_hook_summary", "timestamp": ts(0), "hookCount": 1})
        lines.append({"type": "system", "subtype": "turn_duration", "timestamp": ts(0), "durationMs": 10})
with open(out, "w", encoding="utf-8") as f:
    for d in lines:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")
print(out)
PY
}

# payload <transcript> [额外 JSON 字段]
payload() { printf '{"hook_event_name":"Stop","transcript_path":"%s"%s}' "$1" "${2:+,$2}"; }
# end_session <session_id> —— 以 SessionEnd（/clear）事件调用钩子
end_session() {
  printf '{"hook_event_name":"SessionEnd","session_id":"%s","reason":"clear"}' "$1" |
    KEEPALIVE_ENDED_DIR="$ENDED" bash "$HOOK"
}

# verdict <输入JSON> [钩子睡眠期间对 $T 做的动作] —— 归成 allow|wake|handoff|其他。
# allow ＝退出 0 且无任何输出；wake／handoff ＝退出 2、stdout 为空、stderr 恰为句点／交接提示。
# 钩子睡 1 秒（KEEPALIVE_SLEEP=1），起跑 3 秒后为唤醒截止（KEEPALIVE_DEADLINE，可由 $DL 改），
# 连不上时每 0.2 秒再探；探测地址取 $PROBE，缺省连得上。动作在钩子起跑 0.5 秒后执行。
# 入口取 $EP，缺省为交互终端的 cli。
verdict() {
  local p="$1" act="$2" rc
  if [ ! -f "$HOOK" ]; then echo "脚本不存在"; return; fi
  if [ -n "$act" ]; then (sleep 0.5; eval "$act") & fi
  printf '%s' "$p" | CLAUDE_CODE_ENTRYPOINT="${EP:-cli}" KEEPALIVE_ENDED_DIR="$ENDED" KEEPALIVE_SHARDING_DIR="$SHARD" KEEPALIVE_SLEEP="${SL:-1}" KEEPALIVE_DEADLINE="${DL:-3}" \
    KEEPALIVE_RETRY=0.2 KEEPALIVE_PROBE_URL="${PROBE:-file://$UP}" bash "$HOOK" >"$TMP/out" 2>"$TMP/err"
  rc=$?
  wait
  WAKE_PROMPT="$WAKE_PROMPT" HANDOFF_PROMPT="$HANDOFF_PROMPT" python3 - "$rc" "$TMP/out" "$TMP/err" <<'PY'
import os, sys
rc, out, err = sys.argv[1], open(sys.argv[2], "rb").read(), open(sys.argv[3], "rb").read()
if rc == "0" and not out and not err: print("allow")
elif rc == "2" and not out and err == os.environ["WAKE_PROMPT"].encode("utf-8"): print("wake")
elif rc == "2" and not out and err == os.environ["HANDOFF_PROMPT"].encode("utf-8"): print("handoff")
else: print("退出%s stdout=%r stderr=%r" % (rc, out[:60], err[:60]))
PY
}

report() {  # report <期望> <实际> <描述>
  if [ "$1" = "$2" ]; then
    PASS=$((PASS+1)); printf '  ✅ %-52s [%s]\n' "$3" "$2"
  else
    FAIL=$((FAIL+1)); printf '  ❌ %-52s 期望=%s 实际=%s\n' "$3" "$1" "$2"
  fi
}

echo "── 判定（表驱动：期望|描述|额外字段|事件...；睡眠期间 transcript 不动） ──"
while IFS='|' read -r want desc extra events; do
  [ -z "$want" ] && continue
  # shellcheck disable=SC2086
  t=$(mk "case$((PASS+FAIL)).jsonl" $events)
  report "$want" "$(verdict "$(payload "$t" "$extra")")" "$desc"
done <<'TABLE'
wake|stop_hook_active 为真照常计时（保活唤醒的那一轮结束时就是这样）|"stop_hook_active":true|user:0 asst:200000
allow|子智能体内不唤醒|"agent_id":"a_01"|user:0 asst:200000
allow|上下文 149,999 不唤醒||user:0 asst:149999
wake|上下文 150,000 且期间无活动唤醒||user:0 asst:150000
wake|Stop 后 Claude Code 写的系统行不妨碍唤醒||user:0 asst:150000 summary
allow|用户最后消息 9 小时前不唤醒||user:9 asst:150000
wake|用户最后消息 7 小时前唤醒||user:7 asst:150000
wake|保活回合结束后接着计时||user:1 asst:150000 rewake:0 asst:150500
allow|保活唤醒消息不算用户本人消息||user:9 asst:150000 rewake:0 asst:150500
allow|子智能体回报不算用户本人消息||user:9 asst:150000 agentmsg:0 asst:160000
allow|后台通知不算用户本人消息||user:9 asst:150000 notify:0 asst:160000
allow|另一会话发来的消息不算用户本人消息||user:9 asst:150000 peer:0 asst:160000
allow|isMeta 消息不算用户本人消息||user:9 asst:150000 meta:0 asst:160000
allow|只含工具结果的消息不算用户本人消息||user:9 asst:150000 toolres asst:160000
allow|transcript 里没有用户本人消息不唤醒||rewake:0 asst:150000
wake|用户刚回答选择题算本人在场||user:9 asst:150000 askans:0 asst:160000
allow|选择题回答在 9 小时前不唤醒||user:10 asst:150000 askans:9 asst:160000
allow|选择题超时自动提交不算本人在场||user:9 asst:150000 askafk:0 asst:160000
allow|子智能体的大 usage 不算主线程上下文||user:0 asst:100000 side:400000
wake|同一 message.id 的续行取主线程最后一次||user:0 asst:100000 dup:150000
allow|5 分钟 TTL 不唤醒||user:0 w5m:200000
wake|1 小时 TTL 唤醒||user:0 w1h:150000
allow|两档写入都为 0 时往前找到 5 分钟||user:0 w5m:150000 w0:160000
wake|两档写入都为 0 时往前找到 1 小时||user:0 w1h:100000 w0:150000
wake|往前也找不到写入按 1 小时||user:0 w0:150000
wake|子智能体的 5 分钟写入不算主线程||user:0 w1h:150000 s5m:1000
wake|最后一次写入为 1 小时、之前 5 分钟，按 1 小时||user:0 w5m:150000 w1h:160000
wake|api-request-blob 行不算用户本人消息||user:0 asst:150000 blob asst:150500
allow|保活回合回「完」后不再计时||user:1 asst:150000 rewake:0 done:150500
allow|回「完」之后的保活外回合也不计时||user:1 asst:150000 rewake:0 done:150500 notify:0 asst:151000
wake|回「完」之后用户本人又发消息，恢复计时||user:2 asst:150000 rewake:1 done:150500 user:0 asst:151000
wake|非保活回合里回「完」不算||user:0 done:150000
allow|回「完」带引号和句号也认得||user:1 asst:150000 rewake:0 doneq:150500
wake|回「完」后用户本人回答选择题，恢复计时||user:2 asst:150000 rewake:1 done:150500 askans:0 asst:151000
wake|保活回合回「完」后下一次保活回句点，恢复计时||user:1 asst:150000 rewake:0.5 done:150500 rewake:0 asst:151000
allow|保活回合回 Done 后不再计时||user:1 asst:150000 rewake:0 doneen:150500
allow|回 Done 带引号和句号也认得||user:1 asst:150000 rewake:0 doneenq:150500
wake|以 Done 开头的一句话不算||user:1 asst:150000 rewake:0 notdone:150500
TABLE

echo "── 睡眠期间 transcript 的变化（表驱动：期望|描述|动作） ──"
while IFS='|' read -r want desc act; do
  [ -z "$want" ] && continue
  t=$(mk "act$((PASS+FAIL)).jsonl" user:0 asst:200000)
  report "$want" "$(T="$t" verdict "$(payload "$t")" "$act")" "$desc"
done <<'TABLE'
allow|期间用户发了消息不唤醒|printf '%s\n' '{"type":"user","message":{"role":"user","content":"在吗"}}' >>"$T"
allow|期间主线程有 assistant 调用不唤醒|printf '%s\n' '{"type":"assistant","message":{"role":"assistant","content":[]}}' >>"$T"
wake|期间只多了系统行与排队记录仍唤醒|printf '%s\n' '{"type":"system","subtype":"away_summary"}' '{"type":"queue-operation","operation":"enqueue"}' >>"$T"
allow|期间 transcript 被删不唤醒|rm -f "$T"
allow|期间 transcript 变短不唤醒|: >"$T"
wake|起跑后才落盘、时间戳早于起跑的 assistant 行仍唤醒|printf '%s\n' '{"type":"assistant","timestamp":"2020-01-01T00:00:00.000Z","message":{"role":"assistant","content":[]}}' >>"$T"
wake|起跑后才落盘、时间戳早于起跑的 user 行仍唤醒|printf '%s\n' '{"type":"user","timestamp":"2020-01-01T00:00:00.000Z","message":{"role":"user","content":"在吗"}}' >>"$T"
allow|时间戳晚于起跑的 assistant 行不唤醒|printf '%s\n' '{"type":"assistant","timestamp":"2099-01-01T00:00:00.000Z","message":{"role":"assistant","content":[]}}' >>"$T"
TABLE

echo "── 保活回合的「完」在钩子起跑后才落盘 ──"
t=$(mk "late.jsonl" user:1 asst:150000 rewake:0)
printf '%s\n' '{"type":"assistant","timestamp":"2020-01-01T00:00:00.000Z","message":{"role":"assistant","content":[{"type":"text","text":"完"}]}}' >"$TMP/late-done.jsonl"
# shellcheck disable=SC2016  # 动作由 verdict 在子 shell 里 eval，变量到那时才展开
report allow "$(T="$t" verdict "$(payload "$t")" 'cat "$TMP/late-done.jsonl" >>"$T"')" "起跑后才落盘的「完」也停"

echo "── 英文安装（不设 REPLY_LANG）：唤醒提示约定回 Done，回「完」与 Done 都认 ──"
t=$(mk "en1.jsonl" user:0 asst:150000)
report wake "$(unset REPLY_LANG; WAKE_PROMPT="$WAKE_PROMPT_EN" verdict "$(payload "$t")")" "英文安装的句点唤醒提示约定回 Done"
t=$(mk "en2.jsonl" user:1 asst:150000 rewake:0 doneen:150500)
report allow "$(unset REPLY_LANG; WAKE_PROMPT="$WAKE_PROMPT_EN" verdict "$(payload "$t")")" "英文安装回 Done 后不再计时"
t=$(mk "en3.jsonl" user:1 asst:150000 rewake:0 done:150500)
report allow "$(unset REPLY_LANG; WAKE_PROMPT="$WAKE_PROMPT_EN" verdict "$(payload "$t")")" "英文安装回「完」也认"

echo "── 最后一次保活写交接 ──"
# 这一组睡 3 秒、截止 5 秒：mk 的时间戳截到整秒，睡眠周期要比这 1 秒抖动长得多才分得清边界
while IFS='|' read -r want desc events; do
  [ -z "$want" ] && continue
  # shellcheck disable=SC2086
  t=$(mk "ho$((PASS+FAIL)).jsonl" $events)
  report "$want" "$(SL=3 DL=5 verdict "$(payload "$t")")" "$desc"
done <<'TABLE'
handoff|离 8 小时只剩 4.5 秒，下一次唤醒会越过上限，这次改为写交接|user:7.99875 asst:150000
wake|下一次唤醒仍在 8 小时内，照常回句点|user:7.99 asst:150000
allow|用户最后一条消息之后已发过最后一次保活唤醒，不再计时|user:7.99 asst:150000 rewakeho:0 asst:151000
wake|最后一次保活唤醒在用户最后一条消息之前，照常计时|rewakeho:3 user:1 asst:150000
TABLE

echo "── 会话被 /clear 或切走后不唤醒 ──"
# /clear 后进程里换成了新会话，旧会话起的计时到点会把唤醒打进新会话
t=$(mk "end1.jsonl" user:0 asst:200000)
report allow "$(verdict "$(payload "$t" '"session_id":"s-end1"')" 'end_session s-end1')" "睡眠期间本会话结束，不唤醒"
t=$(mk "end2.jsonl" user:0 asst:200000)
report wake "$(verdict "$(payload "$t" '"session_id":"s-end2"')" 'end_session s-other')" "别的会话结束不影响本会话"
t=$(mk "end3.jsonl" user:0 asst:200000)
end_session s-end3 >/dev/null 2>&1
report allow "$(verdict "$(payload "$t" '"session_id":"s-end3"')")" "已结束的会话起跑即不计时"
printf '{"hook_event_name":"SessionEnd","session_id":"s-quiet","reason":"clear"}' >"$TMP/se.json"
report allow "$(verdict "$(cat "$TMP/se.json")")" "SessionEnd 调用本身无输出、退出 0"
mkdir -p "$ENDED"; touch -t 202001010000 "$ENDED/s-stale"
end_session s-fresh >/dev/null 2>&1
report gone "$([ -e "$ENDED/s-stale" ] && echo kept || echo gone)" "超过一天的结束标记顺手清掉"

echo "── 唤醒前探测网络，只在缓存期限内重试 ──"
t=$(mk "net.jsonl" user:0 asst:200000)
report allow "$(PROBE="file://$DOWN" verdict "$(payload "$t")")" "一直连不上，到截止不唤醒"
rm -f "$DOWN"
report wake "$(PROBE="file://$DOWN" verdict "$(payload "$t")" "sleep 1; touch '$DOWN'")" "截止前网络恢复，恢复后唤醒"
rm -f "$DOWN"
printf '%s\n' '{"type":"user","message":{"role":"user","content":"在吗"}}' >"$TMP/back.jsonl"
# shellcheck disable=SC2016  # 动作由 verdict 在子 shell 里 eval，变量到那时才展开
report allow "$(PROBE="file://$DOWN" T="$t" verdict "$(payload "$t")" 'sleep 1; cat "$TMP/back.jsonl" >>"$T"')" "重试期间用户回来了，不唤醒"
t=$(mk "net2.jsonl" user:0 asst:200000)
report allow "$(SL=2 DL=1 verdict "$(payload "$t")")" "醒来已过截止（如合盖睡眠），不唤醒"
# 本地 HTTP 服务，绑定后把端口写进文件。用 socketserver.TCPServer 而非 http.server.HTTPServer：后者绑定时
# 调 socket.getfqdn() 做反向 DNS 查询，CI 的 macOS 机器上卡住超过 10 秒
python3 -c '
import http.server, socketserver, sys
s = socketserver.TCPServer(("127.0.0.1", 0), http.server.SimpleHTTPRequestHandler)
open(sys.argv[1] + ".tmp", "w").write(str(s.server_address[1]))
__import__("os").replace(sys.argv[1] + ".tmp", sys.argv[1])
s.serve_forever()' "$TMP/http.port" >"$TMP/http.log" 2>&1 &
HTTP_PID=$!
trap 'kill $HTTP_PID 2>/dev/null; rm -rf "$TMP"' EXIT
for _ in $(seq 50); do [ -s "$TMP/http.port" ] && break; sleep 0.2; done
PORT=$(cat "$TMP/http.port" 2>/dev/null)
[ -n "$PORT" ] || { echo "测试用 HTTP 服务 10 秒内没起来："; cat "$TMP/http.log"; exit 1; }
report wake "$(PROBE="http://127.0.0.1:$PORT/no-such-path" verdict "$(payload "$t")")" "服务端回 404 也算连得上"
kill $HTTP_PID 2>/dev/null; wait $HTTP_PID 2>/dev/null
report allow "$(PROBE="http://127.0.0.1:$PORT/" verdict "$(payload "$t")")" "端口关着算连不上"

echo "── 睡眠期间脚本被原地改写 ──"
# bash 边读边执行脚本：睡眠期间原地改写钩子文件，醒来后不能从旧偏移读新内容报错，仍照常唤醒
cp "$HOOK" "$TMP/kg.sh"
t=$(mk "rewrite.jsonl" user:0 asst:200000)
# shellcheck disable=SC2016  # 动作由 verdict 在子 shell 里 eval，变量到那时才展开
report wake "$(HOOK="$TMP/kg.sh" T="$t" verdict "$(payload "$t")" '{ printf "#%0300d\n" 0; cat "$HOOK"; } >"$TMP/kg.new"; cat "$TMP/kg.new" >"$HOOK"')" "睡眠期间脚本被原地改写仍照常唤醒"

echo "── 父会话有在跑的子会话（分片） ──"
# mkshard <会话 id> <状态目录名> <轨道:状态:ended:几小时前|轨道:-:-:->... —— 造父会话标记与状态目录：
# 标记指向 $TMP/<状态目录名>；状态为 - 的轨道只出现在 tracks.json、没有 status 文件
mkshard() {
  local sid="$1" st="$2"; shift 2
  STATE="$TMP/$st" SHARD="$SHARD" SID="$sid" python3 - "$@" <<'PY'
import json, os, sys, time
from datetime import datetime, timezone
d, shard, sid = os.environ["STATE"], os.environ["SHARD"], os.environ["SID"]
os.makedirs(d, exist_ok=True); os.makedirs(shard, exist_ok=True)
tracks = {}
for e in sys.argv[1:]:
    name, status, ended, hours = e.split(":")
    tracks[name] = {"name": "x-" + name, "worktree": "x-" + name}
    if status == "-":
        continue
    at = datetime.fromtimestamp(time.time() - float(hours) * 3600, timezone.utc).isoformat(timespec="seconds")
    with open(os.path.join(d, name + ".status.json"), "w", encoding="utf-8") as f:
        json.dump({"track": name, "session_id": "k-" + name, "event": "stop", "at": at,
                   "context_tokens": 1000, "status": status, "status_line": "状态：" + status,
                   "last_message": "状态：" + status, "ended": ended == "true"}, f, ensure_ascii=False)
with open(os.path.join(d, "tracks.json"), "w", encoding="utf-8") as f:
    json.dump({"change_id": "x", "repo": "/abs", "parent": "p", "parent_session": sid, "tracks": tracks}, f)
with open(os.path.join(shard, sid + ".json"), "w", encoding="utf-8") as f:
    json.dump({"state": d, "registered_at": "2026-10-20T00:00:00+00:00"}, f)
PY
}
# 标记里的 sid 要和 payload 的 session_id 一致；每个用例用不同的 sid，互不影响
t=$(mk "kid1.jsonl" user:0 asst:20000)
mkshard s-kid1 kidst1 P1:待答:false:0.1
report wake "$(verdict "$(payload "$t" '"session_id":"s-kid1"')")" "有在跑的子会话（待答）：上下文 2 万也计时唤醒"
t=$(mk "kid2.jsonl" user:0 asst:20000)
mkshard s-kid2 kidst2 P1:完成:false:0.1 P2:完成:false:0.2
report allow "$(verdict "$(payload "$t" '"session_id":"s-kid2"')")" "子会话全部完成：上下文 2 万仍不计时"
t=$(mk "kid3.jsonl" user:0 asst:20000)
mkshard s-kid3 kidst3 P1:完成:false:0.1 P2:待答:true:0.1
report allow "$(verdict "$(payload "$t" '"session_id":"s-kid3"')")" "子会话已 ended 的不算在跑：上下文 2 万不计时"
t=$(mk "kid4.jsonl" user:0 asst:20000)
mkshard s-kid4 kidst4 P1:完成:false:0.1 P2:-:-:-
report wake "$(verdict "$(payload "$t" '"session_id":"s-kid4"')")" "tracks.json 里有轨道没有 status 文件算在跑"
t=$(mk "kid5.jsonl" user:9 asst:20000)
mkshard s-kid5 kidst5 P1:待答:false:1.5
report wake "$(verdict "$(payload "$t" '"session_id":"s-kid5"')")" "子会话动静晚于用户 7.5 小时、用户已过 9 小时：不因 8 小时上限放弃"
t=$(mk "kid7.jsonl" user:9 asst:20000)
mkshard s-kid7 kidst7 P1:待答:false:1.5
report wake "$(SL=3 DL=5 verdict "$(payload "$t" '"session_id":"s-kid7"')")" "同上（睡 3 秒、截止 5 秒）：仍是句点而非最后一次保活"
t=$(mk "kid8.jsonl" user:0 asst:20000)
printf '%s' '{ 损坏' >"$SHARD/s-kid8.json"
report allow "$(verdict "$(payload "$t" '"session_id":"s-kid8"')")" "父会话标记损坏：按原规则，上下文 2 万不计时"
t=$(mk "kid9.jsonl" user:0 asst:20000)
mkshard s-kid9 kidst9 P1:待答:false:0.1
printf '%s' '{ 损坏' >"$TMP/kidst9/tracks.json"
report allow "$(verdict "$(payload "$t" '"session_id":"s-kid9"')")" "tracks.json 损坏：按原规则，上下文 2 万不计时"
t=$(mk "kid11.jsonl" user:1 asst:20000 rewake:0 done:20500)
mkshard s-kid11 kidst11 P1:待答:false:0.1
report wake "$(verdict "$(payload "$t" '"session_id":"s-kid11"')")" "有在跑的子会话时回「完」不停"
t=$(mk "kid10.jsonl" user:0 asst:150000)
mkshard s-kid10 kidst10 P1:完成:false:0.1
report wake "$(verdict "$(payload "$t" '"session_id":"s-kid10"')")" "子会话全部完成：上下文 15 万仍按原规则计时"

echo "── 会话入口 ──"
t=$(mk "ep.jsonl" user:0 asst:200000)
report allow "$(EP=sdk-cli verdict "$(payload "$t")")" "-p 无头会话（sdk-cli）不计时"
report wake "$(EP=claude-desktop verdict "$(payload "$t")")" "其他入口照常计时"

echo "── 异常一律不唤醒 ──"
report allow "$(verdict '{"hook_event_name":"Stop","transcript_path":"/nope/x.jsonl"}')" "transcript 路径不存在"
report allow "$(verdict '{"hook_event_name":"Stop"}')" "缺 transcript_path"
report allow "$(verdict 'not json')" "非 JSON 输入"
report allow "$(verdict '')" "空输入"

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
