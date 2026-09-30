#!/bin/bash
# 回归测试: rule-file-edit-check.sh
# 跑法: bash hooks/tests/rule-file-edit-check.test.sh
# 表征测试：钉住现状。hook 只看 tool_input.file_path，命中 LLM 规则文件就注入提醒，
# 其余一律不输出；它从不拒绝或拦截。
HOOK="$(dirname "$0")/../rule-file-edit-check.sh"
PASS=0; FAIL=0

# check <期望 remind|silent> <描述> <file_path 取值>，以 Edit 的 PostToolUse 输入喂给 hook
check() {
  local want="$1" desc="$2" path="$3"
  check_payload "$want" "$desc" "$(python3 -c '
import json,sys
print(json.dumps({"hook_event_name":"PostToolUse","tool_name":"Edit",
                  "tool_input":{"file_path":sys.argv[1],"old_string":"a","new_string":"b"}}))
' "$path")"
}

# check_payload <期望 remind|silent> <描述> <hook 输入原文>
check_payload() {
  local want="$1" desc="$2" payload="$3" got
  got=$(printf '%s' "$payload" | bash "$HOOK" 2>/dev/null | python3 -c '
import json,sys
raw=sys.stdin.read().strip()
if not raw: print("silent"); raise SystemExit
try: o=json.loads(raw)["hookSpecificOutput"]
except Exception: print("bad-json"); raise SystemExit
ctx=o.get("additionalContext","")
if o.get("hookEventName")=="PostToolUse" and "rule-file-editing" in ctx: print("remind")
else: print("other")
')
  if [ "$got" = "$want" ]; then
    PASS=$((PASS+1)); printf '  ✅ %-52s [%s]\n' "$desc" "$got"
  else
    FAIL=$((FAIL+1)); printf '  ❌ %-52s 期望=%s 实际=%s\n' "$desc" "$want" "$got"
  fi
}

echo "── 必须提醒（路径命中 LLM 规则文件）──"
check remind "项目 CLAUDE.md"                        /work/proj/CLAUDE.md
check remind "CLAUDE.local.md"                       /work/proj/CLAUDE.local.md
check remind "AGENTS.md"                             /work/proj/AGENTS.md
check remind "skill 的 SKILL.md"                     /home/u/.claude/skills/x/SKILL.md
check remind ".claude/commands 下的 md"              /work/proj/.claude/commands/ship.md
check remind ".claude/commands 子目录下的 md"        /work/proj/.claude/commands/sub/ship.md
check remind ".claude/agents 下的 md"                /work/proj/.claude/agents/reviewer.md
check remind ".claude/output-styles 下任意文件"      /work/proj/.claude/output-styles/terse
check_payload remind "Write 工具同样提醒" \
  '{"hook_event_name":"PostToolUse","tool_name":"Write","tool_input":{"file_path":"/p/CLAUDE.md","content":"x"}}'

echo "── 必须不输出（不是规则文件，或只是名字相近）──"
check silent "普通 README.md"                        /work/proj/README.md
check silent "文件名只是以 CLAUDE.md 结尾"           /work/proj/MYCLAUDE.md
check silent "CLAUDE.md 的备份"                      /work/proj/CLAUDE.md.bak
check silent "小写 claude.md"                        /work/proj/claude.md
check silent "不带目录的相对路径 CLAUDE.md"          CLAUDE.md
check silent ".claude/commands 下的非 md 文件"       /work/proj/.claude/commands/ship.txt
check silent ".claude/agents 下的非 md 文件"         /work/proj/.claude/agents/notes.json
check silent "skills 下的其他 md"                    /home/u/.claude/skills/x/reference.md

echo "── 输入异常一律放行（不输出）──"
check_payload silent "缺 tool_input"                 '{"hook_event_name":"PostToolUse","tool_name":"Edit"}'
check_payload silent "file_path 为空串"              '{"tool_input":{"file_path":""}}'
check_payload silent "file_path 为 null"             '{"tool_input":{"file_path":null}}'
check_payload silent "非 JSON 输入"                  'not json at all'
check_payload silent "空输入"                        ''

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
