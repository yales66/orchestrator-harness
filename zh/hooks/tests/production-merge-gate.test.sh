#!/bin/bash
# 回归测试: production-merge-gate.sh
# 跑法: bash hooks/tests/production-merge-gate.test.sh
HOOK="$(dirname "$0")/../production-merge-gate.sh"
PASS=0; FAIL=0
REASON="该仓库为生产模式，合并需用户当场同意 / Production repository: merging needs the user's approval"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

# make_repo <目录名> <production 值，空则不设>：建临时仓库，origin 指向 github.com/me/<目录名>
make_repo() {
  local d="$TMP/$1"
  git init -q "$d"
  git -C "$d" remote add origin "https://github.com/me/$1.git"
  [ -n "$2" ] && git -C "$d" config claude.production "$2"
  printf '%s' "$d"
}

# bash_json <cwd> <命令>：造 PreToolUse 输入，原文不经 shell 转义
bash_json() {
  C="$1" V="$2" python3 -c 'import json,os; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":"Bash","cwd":os.environ["C"],"tool_input":{"command":os.environ["V"]}}))'
}

# check <期望 ask|allow> <描述> <cwd> <命令>；ask 时同时要求理由写明生产模式
check() {
  local want="$1" desc="$2" got
  got=$(bash_json "$3" "$4" | bash "$HOOK" 2>/dev/null | python3 -c '
import json,sys
try:
    h=json.load(sys.stdin).get("hookSpecificOutput",{})
except Exception:
    print("allow"); raise SystemExit
d=h.get("permissionDecision","allow")
print(d if d!="ask" or sys.argv[1] in h.get("permissionDecisionReason","") else "ask-无理由")
' "$REASON")
  if [ "$got" = "$want" ]; then
    PASS=$((PASS+1)); printf '  ✅ %-52s [%s]\n' "$desc" "$got"
  else
    FAIL=$((FAIL+1)); printf '  ❌ %-52s 期望=%s 实际=%s\n' "$desc" "$want" "$got"
  fi
}

PLAIN=$(make_repo plain "")
PROD=$(make_repo prod true)
OFF=$(make_repo off false)

echo "── 放行 ──"
check allow "生产仓库里的非合并命令"            "$PROD"  'gh pr create --fill'
check allow "未标生产的仓库合并"                "$PLAIN" 'gh pr merge 12 --squash'
check allow "claude.production=false 合并"      "$OFF"   'gh pr merge 12'
check allow "-R 指向 cwd 所在仓库且未标生产"    "$PLAIN" 'gh pr merge 12 -R me/plain'
check allow "PR 网址指向 cwd 所在仓库且未标生产" "$PLAIN" 'gh pr merge https://github.com/me/plain/pull/12'
check allow "GH_REPO 指向 cwd 所在仓库且未标生产" "$PLAIN" 'GH_REPO=me/plain gh pr merge 12'
check allow "cd 到未标生产的仓库再合并"         "$PROD"  "cd '$PLAIN' && gh pr merge 12"

echo "── 须用户当场同意 ──"
check ask   "claude.production=true 合并"       "$PROD"  'gh pr merge 12 --squash'
check ask   "链式命令里的合并"                  "$PROD"  'git push && gh pr merge --auto'
check ask   "-R 指向别的仓库"                   "$PLAIN" 'gh pr merge 12 -R other/repo'
check ask   "--repo=别的仓库"                   "$PLAIN" 'gh pr merge 12 --repo=other/repo'
check ask   "-R 指向 cwd 所在仓库且标了生产"    "$PROD"  'gh pr merge 12 -R me/prod'
check ask   "cd 到生产仓库再合并"               "$PLAIN" "cd '$PROD' && gh pr merge 12 --squash"
check ask   "PR 网址指向别的仓库"               "$PLAIN" 'gh pr merge https://github.com/other/repo/pull/12'
check ask   "GH_REPO 指向别的仓库"              "$PLAIN" 'GH_REPO=other/repo gh pr merge 12'

echo
echo "PASS=$PASS  FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
