#!/bin/bash
# 回归测试: keepalive-gate.sh
# 跑法: bash hooks/tests/keepalive-gate.test.sh
HOOK="$(dirname "$0")/../keepalive-gate.sh"
PASS=0; FAIL=0
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
WAKE_PROMPT='[保活] 只回复一个句点，不做别的。'
HANDOFF_PROMPT='[保活] 用户已离开近 8 小时，这是最后一次保活。本会话还有要交给新会话接着做的事，就用 handoff 技能交接，走完该技能的全部步骤就结束；只剩提交、推送、开 PR、合并等收尾，或在等用户答复、答复后还有工作，也算要交接，本回合不做这些收尾，也不重新提问。任务已做完，或剩下的只有用户本人能做、做完后不用会话接着做的事（如人工登录、人工审核），或已有的交接或计划文件已写全剩余工作且之后没有新进展，就只回一个句点。不做别的。'
# 唤醒提示进 transcript 时的样子（Claude Code 包成后台通知）
rewake_of() { printf '<task-notification>\n<summary>Stop hook feedback</summary>\n</task-notification>\n<system-reminder>\nStop hook blocking error from command "Stop": %s\n</system-reminder>' "$1"; }
REWAKE=$(rewake_of "$WAKE_PROMPT")
REWAKE_HO=$(rewake_of "$HANDOFF_PROMPT")
# 探测地址：file:// 指向的文件存在就算连得上，测试里用它模拟网络通断
UP="$TMP/up"; touch "$UP"
DOWN="$TMP/down"

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
def asst(tok, mid, side=False, ttl=None):
    u = {"input_tokens": 2, "cache_read_input_tokens": int(tok) - 2, "cache_creation_input_tokens": 0}
    if ttl is not None:
        w = 0 if ttl == "0" else 100
        u["cache_read_input_tokens"] -= w
        u["cache_creation_input_tokens"] = w
        u["cache_creation"] = {"ephemeral_5m_input_tokens": w if ttl == "5m" else 0,
                               "ephemeral_1h_input_tokens": w if ttl == "1h" else 0}
    lines.append({"type": "assistant", "isSidechain": side, "timestamp": ts(0),
                  "message": {"role": "assistant", "id": mid, "content": [{"type": "text", "text": "ok"}],
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

# verdict <输入JSON> [钩子睡眠期间对 $T 做的动作] —— 归成 allow|wake|handoff|其他。
# allow ＝退出 0 且无任何输出；wake／handoff ＝退出 2、stdout 为空、stderr 恰为句点／交接提示。
# 钩子睡 1 秒（KEEPALIVE_SLEEP=1），起跑 3 秒后为唤醒截止（KEEPALIVE_DEADLINE，可由 $DL 改），
# 连不上时每 0.2 秒再探；探测地址取 $PROBE，缺省连得上。动作在钩子起跑 0.5 秒后执行。
# 入口取 $EP，缺省为交互终端的 cli。
verdict() {
  local p="$1" act="$2" rc
  if [ ! -f "$HOOK" ]; then echo "脚本不存在"; return; fi
  if [ -n "$act" ]; then (sleep 0.5; eval "$act") & fi
  printf '%s' "$p" | CLAUDE_CODE_ENTRYPOINT="${EP:-cli}" KEEPALIVE_SLEEP="${SL:-1}" KEEPALIVE_DEADLINE="${DL:-3}" \
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
