#!/bin/bash
# 回归测试: handoff-guard.sh
# 跑法: bash hooks/tests/handoff-guard.test.sh
HOOK="$(dirname "$0")/../handoff-guard.sh"
PASS=0; FAIL=0
REASON="交接文件只由 handoff 技能生成"
FIN='bash ~/.claude/skills/handoff/scripts/finalize.sh'

# bash_json <命令> / file_json <工具名> <路径字段> <路径> —— 造 PreToolUse 输入，原文不经 shell 转义
bash_json() {
  V="$1" python3 -c 'import json,os; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":"Bash","cwd":"/p","tool_input":{"command":os.environ["V"]}}))'
}
file_json() {
  T="$1" K="$2" V="$3" python3 -c 'import json,os; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":os.environ["T"],"tool_input":{os.environ["K"]:os.environ["V"],"old_string":"a","new_string":"b","content":"x"}}))'
}

# check <期望 deny|allow> <描述> <hook 输入 JSON>；deny 时同时要求理由指向 handoff 技能
check() {
  local want="$1" desc="$2" payload="$3" got
  got=$(printf '%s' "$payload" | bash "$HOOK" 2>/dev/null | python3 -c '
import json,sys
try:
    h=json.load(sys.stdin).get("hookSpecificOutput",{})
except Exception:
    print("allow"); raise SystemExit
d=h.get("permissionDecision","allow")
print(d if d!="deny" or sys.argv[1] in h.get("permissionDecisionReason","") else "deny-无理由")
' "$REASON")
  desc=${desc//$'\n'/⏎}
  if [ "$got" = "$want" ]; then
    PASS=$((PASS+1)); printf '  ✅ %-60s [%s]\n' "$desc" "$got"
  else
    FAIL=$((FAIL+1)); printf '  ❌ %-60s 期望=%s 实际=%s\n' "$desc" "$want" "$got"
  fi
}
# deny_cmd / allow_cmd <命令>：描述即命令本身
deny_cmd()  { check deny  "$1" "$(bash_json "$1")"; }
allow_cmd() { check allow "$1" "$(bash_json "$1")"; }

echo "── 文件工具：文件名恰为 HANDOFF.md 才拒绝 ──"
check deny  "Edit /p/HANDOFF.md"              "$(file_json Edit file_path /p/HANDOFF.md)"
check deny  "Write 相对路径 HANDOFF.md"        "$(file_json Write file_path HANDOFF.md)"
check deny  "MultiEdit /p/HANDOFF.md"         "$(file_json MultiEdit file_path /p/HANDOFF.md)"
check deny  "NotebookEdit notebook_path"      "$(file_json NotebookEdit notebook_path /p/HANDOFF.md)"
check allow "Write HANDOFF.new.md"            "$(file_json Write file_path /p/HANDOFF.new.md)"
check allow "Edit HANDOFF-x.md（分轨道交接）"   "$(file_json Edit file_path /p/HANDOFF-x.md)"
check allow "Edit PROGRESS.md"                "$(file_json Edit file_path /p/PROGRESS.md)"
check allow "Edit handoff.md（大小写敏感）"     "$(file_json Edit file_path /p/handoff.md)"
check allow "Edit HANDOFF.md.bak"             "$(file_json Edit file_path /p/HANDOFF.md.bak)"
check allow "Read HANDOFF.md（不在守卫范围）"   "$(file_json Read file_path /p/HANDOFF.md)"

echo "── Bash：重定向与 tee ──"
deny_cmd 'echo x > HANDOFF.md'
deny_cmd 'printf x >> /p/HANDOFF.md'
deny_cmd 'echo x >"$D/HANDOFF.md"'
deny_cmd 'cd /p && echo x>HANDOFF.md'
deny_cmd $'cat > /p/HANDOFF.md <<\'EOF\'\n# 交接\nEOF'
deny_cmd 'echo x | tee HANDOFF.md'
deny_cmd 'echo x | tee -a /p/HANDOFF.md >/dev/null'

echo "── Bash：原地编辑类 ──"
deny_cmd "sed -i '' 's/a/b/' HANDOFF.md"
deny_cmd "sed -i.bak -e 's/a/b/' /p/HANDOFF.md"
deny_cmd "perl -pi -e 's/a/b/' HANDOFF.md"
deny_cmd "awk -i inplace '{print}' HANDOFF.md"
deny_cmd $'ed -s HANDOFF.md <<EOF\n1d\nw\nEOF'
deny_cmd 'ex -s +%d +wq HANDOFF.md'
deny_cmd 'truncate -s 0 HANDOFF.md'

echo "── Bash：cp/mv/rm/ln 以它为目标或源 ──"
deny_cmd 'cp notes.md HANDOFF.md'
deny_cmd 'cp /p/HANDOFF.md /tmp/x.md'
deny_cmd 'mv HANDOFF.new.md HANDOFF.md'
deny_cmd 'rm -f /p/HANDOFF.md'
deny_cmd 'rm HANDOFF*'
deny_cmd 'ln -sf other.md HANDOFF.md'
deny_cmd 'sudo rm HANDOFF.md'

echo "── Bash：解释器内联代码里出现它 ──"
deny_cmd "python3 -c \"open('HANDOFF.md','w').write('x')\""
deny_cmd "python -c 'import os; os.remove(\"/p/HANDOFF.md\")'"
deny_cmd "node -e \"require('fs').writeFileSync('HANDOFF.md','x')\""
deny_cmd "ruby -e 'File.write(\"HANDOFF.md\", \"x\")'"
deny_cmd "perl -e 'unlink \"HANDOFF.md\"'"
deny_cmd $'python3 - <<\'EOF\'\nopen("/p/HANDOFF.md", "a").write("x")\nEOF'
deny_cmd "python3 <<< 'open(\"HANDOFF.md\",\"w\")'"

echo "── Bash：包在 shell -c、命令替换里，或与 finalize 同行 ──"
deny_cmd "bash -c 'echo x > HANDOFF.md'"
deny_cmd 'echo "$(rm HANDOFF.md)"'
deny_cmd "$FIN /p && echo x >> /p/HANDOFF.md"
deny_cmd 'git checkout -- HANDOFF.md'
deny_cmd 'git restore /p/HANDOFF.md'

echo "── Bash：只读命令放行 ──"
allow_cmd 'cat HANDOFF.md'
allow_cmd 'head -20 /p/HANDOFF.md'
allow_cmd "grep -n '③' HANDOFF.md"
allow_cmd "sed -n '1,40p' HANDOFF.md"
allow_cmd 'wc -l HANDOFF.md'
allow_cmd 'diff HANDOFF.md HANDOFF.new.md'
allow_cmd 'git diff -- HANDOFF.md'
allow_cmd 'git log -p -- HANDOFF.md'
allow_cmd 'git show HEAD:HANDOFF.md'
allow_cmd 'awk "{print}" HANDOFF.md'
allow_cmd "perl -ne 'print' HANDOFF.md"
allow_cmd 'grep HANDOFF.md notes.txt > hits.txt'
allow_cmd 'echo "see HANDOFF.md" >> PROGRESS.md'

echo "── Bash：其他文件名与 finalize 放行 ──"
allow_cmd 'echo x > HANDOFF-x.md'
allow_cmd 'echo x >> /p/PROGRESS.md'
allow_cmd "sed -i '' 's/a/b/' HANDOFF.new.md"
allow_cmd 'cp HANDOFF.new.md /tmp/review.md'
allow_cmd 'rm /p/HANDOFF.new.md'
allow_cmd 'mv draft.md HANDOFF.new.md'
allow_cmd $'cat > /p/HANDOFF.new.md <<\'EOF\'\n> 引用 HANDOFF.md 的一行\nmv a HANDOFF.md\necho x > HANDOFF.md\nEOF'
allow_cmd "$FIN /p/dir"
allow_cmd "bash \"\$HOME/.claude/skills/handoff/scripts/finalize.sh\" /p/dir && cat /p/dir/HANDOFF.md"
allow_cmd "python3 ~/.claude/skills/handoff/scripts/extract.py --out /p/dir"

echo "── 异常一律 fail-open ──"
check allow "非 JSON 输入" 'not json at all'
check allow "空输入" ''
check allow "缺 tool_input" '{"tool_name":"Edit"}'
check allow "command 不是字符串" '{"tool_name":"Bash","tool_input":{"command":["rm","HANDOFF.md"]}}'
check allow "file_path 不是字符串" '{"tool_name":"Write","tool_input":{"file_path":null}}'

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
