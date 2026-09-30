#!/bin/bash
# 回归测试: block-nested-subagent.sh
# 跑法: bash hooks/tests/block-nested-subagent.test.sh
HOOK="$(dirname "$0")/../block-nested-subagent.sh"
PASS=0; FAIL=0

# check <期望 deny|allow> <描述> <hook 输入 JSON>
check() {
  local want="$1" desc="$2" payload="$3" got
  got=$(printf '%s' "$payload" | bash "$HOOK" 2>/dev/null | python3 -c '
import json,sys
try:
    print(json.load(sys.stdin).get("hookSpecificOutput",{}).get("permissionDecision","allow"))
except Exception:
    print("allow")
')
  if [ "$got" = "$want" ]; then
    PASS=$((PASS+1)); printf '  ✅ %-52s [%s]\n' "$desc" "$got"
  else
    FAIL=$((FAIL+1)); printf '  ❌ %-52s 期望=%s 实际=%s\n' "$desc" "$want" "$got"
  fi
}

echo "── 必须拦截（调用方在 subagent 内，agent_id 存在）──"
check deny "subagent 内调 Agent" \
  '{"hook_event_name":"PreToolUse","tool_name":"Agent","agent_id":"a_01","agent_type":"general-purpose","tool_input":{"subagent_type":"Explore","prompt":"x"}}'
check deny "subagent 内调 Task（旧工具名）" \
  '{"hook_event_name":"PreToolUse","tool_name":"Task","agent_id":"a_02","agent_type":"claude","tool_input":{"subagent_type":"claude"}}'
check deny "subagent 内调 Workflow（等价 fan-out）" \
  '{"hook_event_name":"PreToolUse","tool_name":"Workflow","agent_id":"a_03","agent_type":"claude","tool_input":{"script":"..."}}'
check deny "workflow agent 再派 agent" \
  '{"hook_event_name":"PreToolUse","tool_name":"Agent","agent_id":"a_04","agent_type":"workflow","tool_input":{"subagent_type":"fork"}}'

echo "── 必须放行（调用方是主线程，agent_id 缺席）──"
check allow "主线程派 subagent" \
  '{"hook_event_name":"PreToolUse","tool_name":"Agent","agent_type":"claude","tool_input":{"subagent_type":"Explore"}}'
check allow "主线程跑 Workflow" \
  '{"hook_event_name":"PreToolUse","tool_name":"Workflow","tool_input":{"scriptPath":"/x/some-workflow.js"}}'

echo "── 关键区分: --agent 会话的主线程只有 agent_type、没有 agent_id，不能误伤 ──"
check allow "--agent 会话主线程派 subagent" \
  '{"hook_event_name":"PreToolUse","tool_name":"Agent","agent_type":"code-reviewer","tool_input":{"subagent_type":"Explore"}}'
check allow "agent_id 为空串等同缺席" \
  '{"hook_event_name":"PreToolUse","tool_name":"Agent","agent_id":"","tool_input":{"subagent_type":"Explore"}}'
check allow "agent_id 为 null 等同缺席" \
  '{"hook_event_name":"PreToolUse","tool_name":"Agent","agent_id":null,"tool_input":{"subagent_type":"Explore"}}'

echo "── 输入异常必须 fail-open，不能卡死会话 ──"
check allow "非 JSON 输入" 'not json at all'
check allow "空输入" ''

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
