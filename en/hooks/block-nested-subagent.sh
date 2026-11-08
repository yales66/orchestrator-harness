#!/bin/bash
# PreToolUse(Agent|Task|Workflow) hook: subagent 内只许再派 haiku 工人，其余一律拒。
# 层数上限由 settings.json 的 CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=2 保证（工人那层拿不到 Agent 工具）。
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

tool = payload.get("tool_name") or ""
model = str((payload.get("tool_input") or {}).get("model") or "").lower()
if tool in ("Agent", "Task") and (model == "haiku" or model.startswith("claude-haiku")):
    sys.exit(0)                      # subagent 派 haiku 工人做短活，放行

print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "子 agent 内只能再派 model 显式为 haiku 的工人（短活、上下文控制在 5 万 token 内），不能派别的模型，也不能跑 workflow。其余拆分把结论和建议写进返回值，由主线程的编排者决定怎么派。"
}}))
sys.exit(0)
' 2>/dev/null
exit 0
