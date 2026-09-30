#!/bin/bash
# 回归测试: block-no-verify-commit.sh
# 跑法: bash hooks/tests/block-no-verify-commit.test.sh
HOOK="$(dirname "$0")/../block-no-verify-commit.sh"
PASS=0; FAIL=0

# check <期望 deny|allow> <描述> <命令>
check() {
  local want="$1" desc="$2" cmd="$3"
  local got
  # 解析 JSON 判定，不依赖输出的空格格式
  got=$(python3 -c '
import json,sys
print(json.dumps({"tool_input":{"command":sys.argv[1]}}))
' "$cmd" | bash "$HOOK" 2>/dev/null | python3 -c '
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

echo "── 必须拦截（真的在绕过 commit-msg 校验）──"
check deny  "git commit --no-verify"            'git commit --no-verify -m "x"'
check deny  "git commit -n"                     'git commit -n -m "x"'
check deny  "git -C /p commit -n"               'git -C /path commit -n -m "x"'
check deny  "git commit -m x --no-verify"       'git commit -m "x" --no-verify'
check deny  "; 之后的 git commit -n"              'git status; git commit -n -m "x"'
check deny  "换行之后的 git commit -n"            $'git status\ngit commit -n -m "x"'
check deny  "\$(git commit -n) 命令替换里"        'echo $(git commit -n -m "x")'
check deny  "反引号命令替换里的 git commit -n"    'echo `git commit -n -m "x"`'

echo "── 必须放行（正常提交与无关命令）──"
check allow "普通 git commit"                    'git commit -m "x"'
check allow "npm run commit"                    'npm run commit'
check allow "git log 普通用法"                   'git log --max-count=5 --pretty=oneline'
check allow "非 commit 子命令带 -n"             'git log -n 5 --oneline'

echo "── 回归: 2026-07-15 实际误伤的用例（须同时含 git…commit 字样 与 -n）──"
check allow "git log + echo commit 字样 + [ -n \$C ]" 'git log --pretty=oneline -- f.md; echo "=== 引入 commit 的记录 ==="; C=$(git log -S x --pretty=format:%H); [ -n "$C" ] && git show "$C"'
check allow "git log 查历史 + -n 测试变量"        'C=$(git log --pretty=format:%H -- commit.md); [ -n "$C" ] && echo "$C"'
check allow "commit message 文本里含 -n 字样"     'git commit -m "add -n flag support"'
check allow "commit -m 的值恰好是 -n"             'git commit -m -n'
check allow "grep 命令里出现 commit 与 -n"        'grep -n "commit" ~/.claude/hooks/block-no-verify-commit.sh'

echo
echo "PASS=$PASS  FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
