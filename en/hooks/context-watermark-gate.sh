#!/usr/bin/env bash
# Stop hook: 主线程 context 水位闸门。
#
# 水位从 transcript 末条 assistant 消息的 usage 直接读出——
# input_tokens + cache_read_input_tokens + cache_creation_input_tokens 就是
# 这一轮真实送进模型的量。Stop hook 的输入 JSON 不带任何 token 字段,只能这么拿。
#
# 两道线:WARN 只提醒(additionalContext),HARD 拦一次要求落盘交接。
# 拦截只发生在 stop_hook_active 为假时——为真说明上一轮已经拦过、Claude 正因此续跑,
# 但它只在那一轮为真,用户下一条消息就重置,只靠它会变成硬线以上每轮都拦。故另把
# 拦截时的水位记进 scratchpad,之后除非再涨 CONTEXT_REBLOCK_DELTA_PCT 个点(默认 5)
# 才再拦——落完盘接着干活不会被反复打断,又不会一路放行到底。
# 再拦就是循环。harness 另有连续 8 次拦截上限兜底,但不该靠它。
#
# subagent 内(agent_id 存在)一律放行:它有自己的生命周期,水位归主线程管。
# 任何异常一律放行,hook 不该卡死会话。

python3 -c '
import json, os, sys

WINDOW = int(os.environ.get("CONTEXT_WINDOW_TOKENS") or 1000000)
WARN = float(os.environ.get("CONTEXT_WARN_PCT") or 35)
HARD = float(os.environ.get("CONTEXT_HARD_PCT") or 40)
REDELTA = float(os.environ.get("CONTEXT_REBLOCK_DELTA_PCT") or 5)

def allow():
    sys.exit(0)

try:
    p = json.load(sys.stdin)
except Exception:
    allow()

if not isinstance(p, dict):
    allow()
if str(p.get("agent_id") or "").strip():      # subagent 内,不管
    allow()
if p.get("stop_hook_active"):                  # 已拦过一次,防循环
    allow()

tp = p.get("transcript_path") or ""
if not tp or not os.path.isfile(tp):
    allow()

used = 0
try:
    with open(tp, encoding="utf-8") as f:
        for line in f:
            try:
                o = json.loads(line)
            except Exception:
                continue
            m = o.get("message")
            u = m.get("usage") if isinstance(m, dict) else None
            if isinstance(u, dict):
                t = (u.get("input_tokens") or 0) + \
                    (u.get("cache_read_input_tokens") or 0) + \
                    (u.get("cache_creation_input_tokens") or 0)
                if t:
                    used = t
except Exception:
    allow()

if not used:
    allow()

pct = used * 100.0 / WINDOW
if pct < WARN:
    allow()

if pct < HARD:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "Stop",
        "additionalContext": (
            "主线程 context 已过提醒线。在下一个自然断点按 playbook §3 的交接格式落盘,"
            "落完继续当前任务。"
        )}}))
    sys.exit(0)

mark = ""
sd = p.get("scratchpad_dir") or ""
if sd and os.path.isdir(sd):
    mark = os.path.join(sd, ".context-watermark-last-block")
if mark and os.path.isfile(mark):
    try:
        prev = float(open(mark).read().strip())
    except Exception:
        prev = 0.0
    if pct < prev + REDELTA:
        allow()
if mark:
    try:
        open(mark, "w").write("%.3f" % pct)
    except Exception:
        pass

print(json.dumps({"decision": "block", "reason": (
    "主线程 context 已过硬线。停下之前先按 playbook §3 的交接格式落盘"
    "(就近放在本任务的工作目录),写完告诉用户换新会话并给出起手指令,再停。"
)}))
sys.exit(0)
' 2>/dev/null
exit 0
