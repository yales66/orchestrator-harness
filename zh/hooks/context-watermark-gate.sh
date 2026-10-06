#!/usr/bin/env bash
# Stop hook: 主线程 context 水位闸门。
#
# 水位从 transcript 末条 assistant 消息的 usage 直接读出——
# input_tokens + cache_read_input_tokens + cache_creation_input_tokens 就是
# 这一轮真实送进模型的量。Stop hook 的输入 JSON 不带任何 token 字段,只能这么拿。
#
# 两道线:WARN 每个会话只提醒一次(scratchpad 里记标记;没有 scratchpad 时每轮提醒),
# HARD 拦一次,按 playbook §3 的时机权衡落盘交接;越线后再涨 REDELTA 再拦时要求立即落盘。
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
sd = p.get("scratchpad_dir") or ""
sd = sd if sd and os.path.isdir(sd) else ""

if pct < WARN:                                 # 压缩后回落:清标记,再越线时照常提醒与拦截
    for name in (".context-watermark-warned", ".context-watermark-last-block") if sd else ():
        try:
            os.remove(os.path.join(sd, name))
        except Exception:
            pass
    allow()

if pct < HARD:
    warned = os.path.join(sd, ".context-watermark-warned") if sd else ""
    if warned and os.path.isfile(warned):
        allow()
    if warned:
        try:
            open(warned, "w").write("%.3f" % pct)
        except Exception:
            pass
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "Stop",
        "additionalContext": (
            "主线程 context 已过提醒线。不必现在写交接;手头工作与新工作块照常做,"
            "即使预计会越过硬线也照常开工,过硬线后按 playbook §3 的时机规则处理。"
        )}}))
    sys.exit(0)

mark = os.path.join(sd, ".context-watermark-last-block") if sd else ""
reblock = False
if mark and os.path.isfile(mark):
    try:
        prev = float(open(mark).read().strip())
    except Exception:
        prev = 0.0
    if pct < prev + REDELTA:
        allow()
    reblock = True
if mark:
    try:
        open(mark, "w").write("%.3f" % pct)
    except Exception:
        pass

if reblock:
    reason = ("主线程 context 过硬线后又涨了 %g 个点。现在就用 handoff 技能落盘交接"
              "(就近放在本任务的工作目录),把未完成的步骤写进 ③,并提示用户换新会话。" % REDELTA)
else:
    reason = ("主线程 context 已过硬线。剩下的事靠已有上下文能做完就做完;接下来要读新材料、"
              "做新判断的大块工作时,先用 handoff 技能落盘交接(就近放在本任务的工作目录)"
              "并提示用户换新会话。")
reason += "（transcript: %s）" % tp
print(json.dumps({"decision": "block", "reason": reason}))
sys.exit(0)
' 2>/dev/null
exit 0
