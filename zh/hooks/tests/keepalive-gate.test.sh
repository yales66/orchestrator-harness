#!/bin/bash
# 回归测试: keepalive-gate.sh
# 跑法: bash hooks/tests/keepalive-gate.test.sh
HOOK="$(dirname "$0")/../keepalive-gate.sh"
PASS=0; FAIL=0
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
KEEP_PROMPT='[保活] 若本对话里找不到设定本任务的记录（例如已 /clear），用 CronList 找到以 [保活] 开头的任务并 CronDelete；否则只回复一个句点，不做别的。'

# mk <文件名> <事件...> —— 按事件顺序造 transcript，回传路径。事件：
#   user:<几小时前>      用户本人消息        keep:<几小时前>    保活触发的提示
#   agentmsg:<几小时前>  子智能体回报        notify:<几小时前>  后台通知
#   peer:<几小时前>      另一会话发来的消息  toolres            一条只含工具结果的用户角色消息
#   asst:<token>         主线程 assistant    side:<token>       子智能体（isSidechain）assistant
#   dup:<token>          与上一条 assistant 同 message.id 的续行
#   create:<id>          以 [保活] 开头的 CronCreate 及其结果  other:<id>  不以 [保活] 开头的 CronCreate
#   delete:<id>          CronDelete
mk() {
  local f="$TMP/$1"; shift
  KEEP_PROMPT="$KEEP_PROMPT" python3 - "$f" "$@" <<'PY'
import json, os, sys, time
from datetime import datetime, timezone
out, events = sys.argv[1], sys.argv[2:]
keep = os.environ["KEEP_PROMPT"]
now = time.time()
def ts(hours):
    return datetime.fromtimestamp(now - float(hours) * 3600, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
lines, n, last_id = [], 0, "msg_0"
def user(content, hours=0, **kw):
    d = {"type": "user", "timestamp": ts(hours), "message": {"role": "user", "content": content}}
    d.update(kw); lines.append(d)
def asst(tok, mid, side=False, content=None):
    lines.append({"type": "assistant", "isSidechain": side, "timestamp": ts(0),
                  "message": {"role": "assistant", "id": mid, "content": content or [{"type": "text", "text": "ok"}],
                              "usage": {"input_tokens": 2, "cache_read_input_tokens": int(tok) - 2,
                                        "cache_creation_input_tokens": 0}}})
def tool(name, inp, result, tur=None):
    global n
    n += 1; tid = "toolu_%d" % n
    asst(1000, "msg_t%d" % n, content=[{"type": "tool_use", "id": tid, "name": name, "input": inp}])
    user([{"type": "tool_result", "tool_use_id": tid, "content": result}], toolUseResult=tur)
for e in events:
    k, _, v = e.partition(":")
    if k == "user":     user("帮我看看这个", v)
    elif k == "keep":   user(keep, v)
    elif k == "agentmsg": user('<agent-message from="worker">做完了</agent-message>', v)
    elif k == "notify": user("<task-notification><task-id>b1</task-id></task-notification>", v)
    elif k == "peer":   user("Another Claude session sent a message: hi", v)
    elif k == "toolres":
        n += 1; user([{"type": "tool_result", "tool_use_id": "toolu_x%d" % n, "content": "[]"}])
    elif k in ("asst", "side"):
        n += 1; last_id = "msg_%d" % n; asst(v, last_id, side=(k == "side"))
    elif k == "dup":    asst(v, last_id)
    elif k == "create":
        tool("CronCreate", {"cron": "7,37 * * * *", "recurring": True, "prompt": keep},
             "Scheduled recurring job %s (7,37 * * * *)" % v, {"id": v})
    elif k == "other":
        tool("CronCreate", {"cron": "7 * * * *", "recurring": True, "prompt": "检查部署"},
             "Scheduled recurring job %s (7 * * * *)" % v, {"id": v})
    elif k == "delete": tool("CronDelete", {"id": v}, "Cancelled job %s." % v)
with open(out, "w", encoding="utf-8") as f:
    for d in lines:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")
print(out)
PY
}

# payload <transcript> [额外 JSON 字段]
payload() { printf '{"hook_event_name":"Stop","transcript_path":"%s"%s}' "$1" "${2:+,$2}"; }

# verdict <输入JSON> [环境变量赋值...] —— 把钩子输出归成 allow|create|delete|其他
verdict() {
  local p="$1"; shift
  if [ ! -f "$HOOK" ]; then echo "脚本不存在"; return; fi
  printf '%s' "$p" | env "$@" bash "$HOOK" 2>/dev/null | python3 -c '
import json,sys
raw=sys.stdin.read().strip()
if not raw: print("allow"); raise SystemExit
try: o=json.loads(raw)
except Exception: print("非JSON输出"); raise SystemExit
r=o.get("reason","") if o.get("decision")=="block" else ""
if r.startswith("保活已满 8 小时"): print("delete")
elif r.startswith("上下文已过 150k") and "CronCreate" in r: print("create")
else: print("格式不符")
'
}

report() {  # report <期望> <实际> <描述>
  if [ "$1" = "$2" ]; then
    PASS=$((PASS+1)); printf '  ✅ %-52s [%s]\n' "$3" "$2"
  else
    FAIL=$((FAIL+1)); printf '  ❌ %-52s 期望=%s 实际=%s\n' "$3" "$1" "$2"
  fi
}

echo "── 判定顺序（表驱动：期望|描述|额外字段|事件...） ──"
while IFS='|' read -r want desc extra events; do
  [ -z "$want" ] && continue
  # shellcheck disable=SC2086
  t=$(mk "case$((PASS+FAIL)).jsonl" $events)
  report "$want" "$(verdict "$(payload "$t" "$extra")")" "$desc"
done <<'TABLE'
allow|stop_hook_active 为真放行|"stop_hook_active":true|user:0 asst:200000
allow|子智能体内放行|"agent_id":"a_01"|user:0 asst:200000
allow|上下文 149,999 放行||user:0 asst:149999
create|上下文 150,000 且无保活要设||user:0 asst:150000
allow|已有有效保活放行||user:1 asst:150000 create:job1 user:0 asst:160000
create|保活被 CronDelete 后再次要设||user:1 asst:150000 create:job1 delete:job1 user:0 asst:160000
allow|删掉的是别的任务，保活仍有效||user:1 asst:150000 create:job1 delete:job2 user:0 asst:160000
create|不以 [保活] 开头的 CronCreate 不算保活||user:0 asst:150000 other:job3 asst:160000
delete|保活回合且用户最后消息 9 小时前要删||user:9 asst:150000 create:job1 keep:0 asst:160000
allow|保活回合且用户最后消息 1 小时前放行||user:1 asst:150000 create:job1 keep:0 asst:160000
delete|子智能体回报不算用户本人消息||user:9 asst:150000 create:job1 agentmsg:1 asst:155000 keep:0 asst:160000
delete|后台通知不算用户本人消息||user:9 asst:150000 create:job1 notify:1 asst:155000 keep:0 asst:160000
delete|另一会话发来的消息不算用户本人消息||user:9 asst:150000 create:job1 peer:1 asst:155000 keep:0 asst:160000
delete|保活回合里调过工具（工具结果在后）仍算保活回合||user:9 asst:150000 create:job1 keep:0 asst:155000 toolres asst:160000
delete|上下文很小时保活回合照样按 8 小时删||user:9 asst:1000 create:job1 keep:0 asst:2000
allow|用户 9 小时前但本回合不是保活回合，有效保活放行||user:9 asst:150000 create:job1 agentmsg:0 asst:160000
allow|子智能体的大 usage 不算主线程上下文||user:0 asst:100000 side:400000
create|同一 message.id 的续行取主线程最后一次||user:0 asst:100000 dup:150000
TABLE

echo "── cron 分钟由钩子按当前时间算好，避开 0 与 30（表驱动：当前分钟|期望 cron） ──"
T_BIG=$(mk big.jsonl user:0 asst:200000)
while IFS='|' read -r minute want; do
  [ -z "$minute" ] && continue
  now=$(python3 -c 'import time,sys;t=list(time.localtime());t[4]=int(sys.argv[1]);t[5]=0;print(int(time.mktime(tuple(t))))' "$minute")
  got=$(printf '%s' "$(payload "$T_BIG")" | KEEPALIVE_NOW_EPOCH="$now" bash "$HOOK" 2>/dev/null | python3 -c '
import json,re,sys
try: r=json.loads(sys.stdin.read()).get("reason","")
except Exception: r=""
m=re.search(r"合并成 \"([0-9]+,[0-9]+) \* \* \* \*\"",r)
print(m.group(1) if m else "无")
')
  report "$want" "$got" "当前第 $minute 分"
done <<'TABLE'
0|1,31
30|1,31
7|7,37
45|15,45
59|29,59
TABLE

echo "── 设保活的理由里提示词原样给出 ──"
got=$(printf '%s' "$(payload "$T_BIG")" | bash "$HOOK" 2>/dev/null | KEEP_PROMPT="$KEEP_PROMPT" python3 -c '
import json,os,sys
try: r=json.loads(sys.stdin.read()).get("reason","")
except Exception: r=""
print("yes" if r.endswith("prompt 原样为：" + os.environ["KEEP_PROMPT"] + "设好后直接结束，不要回复别的。") else "no")
')
report yes "$got" "理由含原样提示词与收尾要求"

echo "── 异常一律放行 ──"
report allow "$(verdict '{"hook_event_name":"Stop","transcript_path":"/nope/x.jsonl"}')" "transcript 路径不存在"
report allow "$(verdict '{"hook_event_name":"Stop"}')" "缺 transcript_path"
report allow "$(verdict 'not json')" "非 JSON 输入"
report allow "$(verdict '')" "空输入"

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
