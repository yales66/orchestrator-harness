#!/bin/bash
# 回归测试: production-mode-hint.sh
# 跑法: bash hooks/tests/production-mode-hint.test.sh
HOOK="$(dirname "$0")/../production-mode-hint.sh"
PASS=0; FAIL=0
MARK='git config claude.production true'

# prompt_json <消息>：造 UserPromptSubmit 输入，原文不经 shell 转义
prompt_json() {
  V="$1" python3 -c 'import json,os; print(json.dumps({"hook_event_name":"UserPromptSubmit","cwd":"/tmp","prompt":os.environ["V"]}))'
}

# check <期望 inject|silent> <描述> <消息>；inject 要求 additionalContext 含切换命令，silent 要求无任何输出
check() {
  local want="$1" desc="$2" out got
  out=$(prompt_json "$3" | bash "$HOOK" 2>/dev/null)
  if [ ! -f "$HOOK" ]; then
    got="脚本不存在"
  elif [ -z "$out" ]; then
    got="silent"
  else
    got=$(printf '%s' "$out" | python3 -c '
import json,sys
try:
    h=json.load(sys.stdin).get("hookSpecificOutput",{})
except Exception:
    print("非JSON输出"); raise SystemExit
ok=h.get("hookEventName")=="UserPromptSubmit" and sys.argv[1] in h.get("additionalContext","")
print("inject" if ok else "格式不符")
' "$MARK")
  fi
  if [ "$got" = "$want" ]; then
    PASS=$((PASS+1)); printf '  ✅ %-40s [%s]\n' "$desc" "$got"
  else
    FAIL=$((FAIL+1)); printf '  ❌ %-40s 期望=%s 实际=%s\n' "$desc" "$want" "$got"
  fi
}

echo "── 注入说明 ──"
check inject "含「生产模式」"            '把这个仓库切到生产模式'
check inject "含「Production Mode」"     'switch this repo to Production Mode please'

echo "── 不输出 ──"
check silent "子智能体回报"              'Another Claude session sent a message:
<agent-message from="a1">已切到生产模式</agent-message>'
check silent "后台任务通知"              '<task-notification><summary>生产模式钩子</summary></task-notification>'
check silent "无关消息"                  '帮我看一下测试为什么挂了'

echo
echo "PASS=$PASS  FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
