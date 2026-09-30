#!/bin/bash
# 回归测试: orchestrator-playbook-session-start.sh
# 跑法: bash hooks/tests/orchestrator-playbook-session-start.test.sh
HOOK="$(dirname "$0")/../orchestrator-playbook-session-start.sh"
PLAYBOOK="$(dirname "$0")/../../orchestrator-playbook.md"
PASS=0; FAIL=0
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# check <描述> [环境变量赋值...] —— 注入内容须与 hook 同级上一层的 playbook 逐字相等
check() {
  local desc="$1"; shift
  local got
  got=$(env "$@" bash "$HOOK" </dev/null 2>/dev/null | python3 -c '
import json,sys
want=open(sys.argv[1],encoding="utf-8").read()
try: o=json.load(sys.stdin)["hookSpecificOutput"]
except Exception: print("bad-json"); raise SystemExit
if o.get("hookEventName")!="SessionStart": print("wrong-event")
elif o.get("additionalContext")!=want: print("content-mismatch")
else: print("ok")
' "$PLAYBOOK")
  if [ "$got" = "ok" ]; then
    PASS=$((PASS+1)); printf '  ✅ %-50s [%s]\n' "$desc" "$got"
  else
    FAIL=$((FAIL+1)); printf '  ❌ %-50s 实际=%s\n' "$desc" "$got"
  fi
}

echo "── 注入 playbook 全文 ──"
check "默认环境下注入的内容与 playbook 逐字相等"
check "HOME 指向空目录时仍从脚本所在仓库读 playbook" HOME="$TMP"

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
