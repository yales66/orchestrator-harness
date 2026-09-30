#!/bin/bash
# PreToolUse(Agent|Task|Workflow) hook: subagent 内禁止再派 subagent。
#
# 判据用 agent_id 而非 agent_type：agent_id 只在 hook 从 subagent 内触发时出现，
# 主线程恒无——包括 --agent 启动的会话，那种会话主线程只带 agent_type。
# 按 agent_type 判会把 --agent 会话的主线程一并误伤。
#
# Workflow 同拦：workflow 脚本从 subagent 里跑起来同样是一层不受编排者控制的 fan-out。
# 主线程跑 Workflow 不受影响。
python3 -c '
import json, sys

try:
    payload = json.load(sys.stdin)
except Exception:
    sys.exit(0)                      # 输入异常一律放行，hook 不该卡死会话

if not isinstance(payload, dict) or not str(payload.get("agent_id") or "").strip():
    sys.exit(0)                      # 主线程调用，放行

print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "子 agent 内不能再派子 agent 或跑 workflow。自己把这一步做完；确实需要拆分时，把结论和拆分建议写进返回值，由主线程的编排者决定怎么派。"
}}))
sys.exit(0)
' 2>/dev/null
exit 0
