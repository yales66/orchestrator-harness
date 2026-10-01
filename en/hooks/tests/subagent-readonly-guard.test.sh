#!/bin/bash
# 回归测试: subagent-readonly-guard.sh
# 跑法: bash hooks/tests/subagent-readonly-guard.test.sh
HOOK="$(dirname "$0")/../subagent-readonly-guard.sh"
PASS=0; FAIL=0
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/repo/src"
echo 'print(1)' > "$TMP/repo/src/app.py"
echo 'notes' > "$TMP/repo/notes.md"

# tool_json <tool_name> <路径> [agent_type] [agent_id] —— agent_type/agent_id 传空串即缺席
tool_json() {
  T="$1" P="$2" AT="${3-researcher}" AID="${4-a_01}" CWD="$TMP/repo" python3 -c '
import json, os
p = {"hook_event_name": "PreToolUse", "tool_name": os.environ["T"], "cwd": os.environ["CWD"]}
key = "notebook_path" if os.environ["T"] == "NotebookEdit" else "file_path"
p["tool_input"] = {key: os.environ["P"], "content": "x"}
if os.environ["AT"]: p["agent_type"] = os.environ["AT"]
if os.environ["AID"]: p["agent_id"] = os.environ["AID"]
print(json.dumps(p))
'
}

# bash_json <命令> [agent_type] [agent_id] —— 命令原文不经 shell 转义，cwd 是临时仓库
bash_json() {
  C="$1" AT="${2-researcher}" AID="${3-a_01}" CWD="$TMP/repo" python3 -c '
import json, os
p = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": os.environ["CWD"],
     "tool_input": {"command": os.environ["C"]}}
if os.environ["AT"]: p["agent_type"] = os.environ["AT"]
if os.environ["AID"]: p["agent_id"] = os.environ["AID"]
print(json.dumps(p))
'
}

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

echo "── researcher 子智能体: 只能新建文件 ──"
check allow "Write 新建报告（绝对路径）"     "$(tool_json Write "$TMP/repo/reports/audit.md")"
check allow "Write 新建报告（相对路径）"     "$(tool_json Write reports/audit.md)"
check deny  "Write 覆盖已有文件（绝对路径）" "$(tool_json Write "$TMP/repo/src/app.py")"
check deny  "Write 覆盖已有文件（相对路径按 cwd 解析）" "$(tool_json Write src/app.py)"
check deny  "Edit 已有文件"                  "$(tool_json Edit "$TMP/repo/src/app.py")"
check deny  "Edit 不存在的文件也拒绝"        "$(tool_json Edit "$TMP/repo/nope.py")"
check deny  "MultiEdit"                      "$(tool_json MultiEdit "$TMP/repo/src/app.py")"
check deny  "NotebookEdit"                   "$(tool_json NotebookEdit "$TMP/repo/nb.ipynb")"

# deny_cmd / allow_cmd <命令>：researcher 子智能体的 Bash 调用，描述即命令本身
deny_cmd()  { check deny  "$1" "$(bash_json "$1")"; }
allow_cmd() { check allow "$1" "$(bash_json "$1")"; }

# deny_reason <理由片段> <命令>：researcher 的 Bash 调用被拒，且理由含该片段
deny_reason() {
  local want="$1" cmd="$2" got
  got=$(bash_json "$cmd" | bash "$HOOK" 2>/dev/null | python3 -c '
import json,sys
try:
    print(json.load(sys.stdin)["hookSpecificOutput"]["permissionDecisionReason"])
except Exception:
    print("")
')
  if [[ "$got" == *"$want"* ]]; then
    PASS=$((PASS+1)); printf '  ✅ %-52s [理由含 %s]\n' "$cmd" "$want"
  else
    FAIL=$((FAIL+1)); printf '  ❌ %-52s 理由应含=%s 实际=%s\n' "$cmd" "$want" "$got"
  fi
}

echo "── researcher 的 Bash: 原地改写与覆盖已有文件拒绝 ──"
deny_cmd "sed -i 's/1/2/' src/app.py"
deny_cmd "sed -i.bak -e 's/1/2/' src/app.py"
deny_cmd "sed --in-place 's/1/2/' src/app.py"
deny_cmd "perl -pi -e 's/1/2/' src/app.py"
deny_cmd "perl -i.bak -pe 's/1/2/' src/app.py"
deny_cmd 'echo x > src/app.py'
deny_cmd 'echo x >> src/app.py'
deny_cmd 'echo x >src/app.py'
deny_cmd "printf x 1>> $TMP/repo/src/app.py"
deny_cmd 'ls | tee src/app.py'
deny_cmd 'ls | tee -a src/app.py'
deny_cmd 'rm src/app.py'
deny_cmd 'rm -f reports/not-yet.md'
deny_cmd 'mv src/app.py src/main.py'
deny_cmd 'cp other/app.py src/app.py'
deny_cmd 'cp other/app.py src/'
deny_cmd 'cp -t src other/app.py'
deny_cmd 'cp --target-directory=src other/app.py'
deny_cmd 'cp other/app.py src 2>/dev/null'
deny_cmd 'truncate -s 0 src/app.py'
deny_cmd 'chmod +x src/app.py'
deny_cmd 'ln -sf /etc/hosts src/app.py'
deny_cmd 'ln -s -f /etc/hosts reports/link'
deny_cmd 'ln -s --force /etc/hosts reports/link'

echo "── researcher 的 Bash: 改工作区或历史的 git 子命令拒绝 ──"
for sub in 'checkout -- src/app.py' 'switch main' 'reset --hard HEAD~1' 'restore src/app.py' \
           'commit -m wip' 'push origin main' 'stash' 'stash list' 'clean -fd' 'apply fix.patch' \
           'am fix.mbox' 'rebase main' 'merge dev' 'cherry-pick abc123' 'revert abc123' \
           'tag v1' 'branch -d old' 'branch -D old' 'branch --delete old'; do
  deny_cmd "git $sub"
done
deny_cmd 'git -C sub commit -m wip'
deny_cmd 'git --no-pager -c user.name=x commit -m wip'

echo "── researcher 的 Bash: 组合命令逐段判断 ──"
deny_cmd 'git log --oneline && git reset --hard HEAD~1'
deny_cmd 'git status; rm src/app.py'
deny_cmd 'false || echo x > src/app.py'
deny_cmd 'echo $(rm src/app.py)'
deny_cmd 'echo "$(git stash)"'

echo "── researcher 的 Bash: 只读命令与写到新路径放行 ──"
allow_cmd 'git log -p -- src/app.py'
allow_cmd 'git blame src/app.py'
allow_cmd 'git show HEAD:src/app.py'
allow_cmd 'git diff HEAD~1'
allow_cmd 'git status --short'
allow_cmd 'git grep -n print'
allow_cmd 'git branch -a'
allow_cmd 'cat src/app.py'
allow_cmd 'rg -n print src'
allow_cmd 'jq . package.json'
allow_cmd 'ls -la src'
allow_cmd 'python3 scripts/read_report.py src/app.py'
allow_cmd "sed -n '1,5p' src/app.py"
allow_cmd "sed 's/1/2/' src/app.py"
allow_cmd 'grep "a > b" src/app.py'
allow_cmd 'grep ">" src/app.py'
allow_cmd 'echo "> src/app.py"'
allow_cmd 'cp src/app.py reports/copy.py 2>/dev/null'
allow_cmd 'mkdir -p reports'
allow_cmd 'echo x > reports/new.md'
allow_cmd 'echo x >> reports/new.md'
allow_cmd 'ls src | tee reports/listing.txt'
allow_cmd 'cp src/app.py reports/app-copy.py'
allow_cmd 'cp other/notes.md src/'
allow_cmd 'cp --target-directory=src other/notes.md'
allow_cmd 'ln -s src/app.py reports/link'
allow_cmd 'python3 src/app.py > /dev/null'
allow_cmd 'python3 src/app.py 2>/dev/null'
allow_cmd 'python3 src/app.py 2>&1 | head -5'
allow_cmd 'echo done >&2'

echo "── researcher 的 Bash: bash -c / sh -c / zsh -c / eval 里的命令同样判断 ──"
deny_cmd  "bash -c 'rm src/app.py'"
deny_cmd  'sh -c "echo x > src/app.py"'
deny_cmd  "zsh -c 'git reset --hard'"
deny_cmd  "bash -lc 'sed -i s/1/2/ src/app.py'"
deny_cmd  'eval "echo x >> src/app.py"'
deny_cmd  'eval git stash'
deny_cmd  "bash -c \"sh -c 'rm src/app.py'\""
deny_cmd  "sudo bash -c 'echo x > src/app.py'"
allow_cmd "bash -c 'ls src && cat src/app.py'"
allow_cmd "sh -c 'echo x > reports/new.md'"
allow_cmd 'eval "$(ssh-agent -s)"'

echo "── researcher 的 Bash: 内联解释器代码里的写文件原语拒绝 ──"
deny_cmd  "python3 -c 'open(\"src/app.py\", \"w\").write(\"x\")'"
deny_cmd  "python -c 'open(\"reports/new.md\", mode=\"a\").write(\"x\")'"
deny_cmd  "python3 -c 'import pathlib; pathlib.Path(\"src/app.py\").write_text(\"x\")'"
deny_cmd  "python3 -c 'import os; os.remove(\"src/app.py\")'"
deny_cmd  "python3 -c 'import os; os.rename(\"src/app.py\", \"src/b.py\")'"
deny_cmd  "python3 -c 'import shutil; shutil.rmtree(\"src\")'"
deny_cmd  "python3 -c 'import shutil; shutil.copyfile(\"a\", \"src/app.py\")'"
deny_cmd  "python3 -c 'from pathlib import Path; Path(\"src/app.py\").unlink()'"
deny_cmd  "python3 -c 'from pathlib import Path; p = Path(\"src/app.py\"); p.rename(\"x\")'"
deny_cmd  "python3 -c 'from pathlib import Path; Path(\"src/app.py\").open(\"w\")'"
deny_cmd  $'python3 - <<\'EOF\'\nwith open("src/app.py", "a") as f:\n    f.write("x")\nEOF'
deny_cmd  $'python3 <<EOF\nimport os\nos.unlink("src/app.py")\nEOF'
deny_cmd  "node -e 'require(\"fs\").writeFileSync(\"src/app.py\", \"x\")'"
deny_cmd  "node -e 'fs.unlinkSync(\"src/app.py\")'"
deny_cmd  "node --eval 'require(\"fs\").appendFileSync(\"notes.md\", \"x\")'"
deny_cmd  "perl -e 'open(my \$f, \">\", \"src/app.py\")'"
deny_cmd  "perl -e 'open(F, \">>src/app.py\")'"
deny_cmd  "perl -e 'unlink \"src/app.py\"'"
deny_cmd  "ruby -e 'File.write(\"src/app.py\", \"x\")'"
deny_cmd  "ruby -e 'File.open(\"src/app.py\", \"w\") { |f| f.puts 1 }'"
deny_cmd  "ruby -e 'require \"fileutils\"; FileUtils.rm(\"src/app.py\")'"
deny_cmd  "bash -c \"python3 -c 'import os; os.remove(1)'\""
deny_reason Write "python3 -c 'open(\"reports/new.md\", \"w\").write(\"x\")'"
allow_cmd "python3 -c 'print(open(\"src/app.py\").read())'"
allow_cmd "python3 -c 'print(open(\"src/app.py\", \"r\").read())'"
allow_cmd "python3 -c 'import json; print(json.load(open(\"package.json\")))'"
allow_cmd "python3 -c 'print(\"a-b\".replace(\"-\", \"+\"))'"
allow_cmd "python3 -c 'from PIL import Image; Image.open(\"a.png\")'"
allow_cmd $'python3 - <<\'EOF\'\nprint(open("src/app.py").read())\nEOF'
allow_cmd "node -e 'console.log(require(\"fs\").readFileSync(\"src/app.py\", \"utf8\"))'"
allow_cmd "perl -ne 'print if /x/' src/app.py"
allow_cmd "ruby -e 'puts File.read(\"src/app.py\")'"

echo "── researcher 的 Bash: 相对路径跟随前面的 cd/pushd ──"
deny_cmd  'cd src && echo x > app.py'
deny_cmd  'cd src; echo x >> app.py'
deny_cmd  $'cd src\nls | tee app.py'
deny_cmd  'pushd src >/dev/null && cp ../notes.md app.py'
deny_cmd  'cd src || exit 1; echo x > app.py'
deny_cmd  '(cd src && echo x > app.py)'
deny_cmd  'cd "$SRC" && echo x > new.md'
deny_cmd  'cd - && echo x > new.md'
deny_cmd  'cd $(dirname src/app.py) && echo x > app.py'
deny_cmd  'cd `dirname src/app.py` && echo x > app.py'
deny_cmd  "cd src && bash -c 'echo x > app.py'"
allow_cmd 'cd src && echo x > notes.md'
allow_cmd '(cd src && ls); echo x > app.py'
allow_cmd 'cd src | cat; echo x > app.py'

echo "── retriever 子智能体: 与 researcher 同样只能新建文件 ──"
check allow "retriever Write 新建报告"       "$(tool_json Write "$TMP/repo/reports/lookup.md" retriever a_10)"
check deny  "retriever Write 覆盖已有文件"   "$(tool_json Write "$TMP/repo/src/app.py" retriever a_10)"
check deny  "retriever Edit 已有文件"        "$(tool_json Edit "$TMP/repo/src/app.py" retriever a_10)"
check deny  "retriever Bash 原地改写"        "$(bash_json 'sed -i s/1/2/ src/app.py' retriever a_10)"
check allow "--agent retriever 会话的主线程（无 agent_id）" "$(tool_json Edit "$TMP/repo/src/app.py" retriever '')"

echo "── 其他调用方一律放行 ──"
check allow "主线程 Edit（无 agent_id、无 agent_type）" "$(tool_json Edit "$TMP/repo/src/app.py" '' '')"
check allow "主线程 Write 覆盖"             "$(tool_json Write "$TMP/repo/src/app.py" '' '')"
check allow "--agent researcher 会话的主线程（无 agent_id）" "$(tool_json Edit "$TMP/repo/src/app.py" researcher '')"
check allow "其他子智能体 Edit"             "$(tool_json Edit "$TMP/repo/src/app.py" general-purpose a_02)"
check allow "其他子智能体 Write 覆盖"       "$(tool_json Write "$TMP/repo/src/app.py" claude a_03)"
check allow "implementer 子智能体 Edit"      "$(tool_json Edit "$TMP/repo/src/app.py" implementer a_11)"
check allow "implementer 子智能体 Bash 覆盖写" "$(bash_json 'echo x > src/app.py' implementer a_11)"
check allow "主线程 Bash 删文件"             "$(bash_json 'rm src/app.py' '' '')"
check allow "--agent researcher 会话主线程 Bash" "$(bash_json 'git reset --hard' researcher '')"
check allow "其他子智能体 Bash 覆盖写"      "$(bash_json 'echo x > src/app.py' general-purpose a_07)"
check allow "agent_type 大小写不同不算"     "$(tool_json Edit "$TMP/repo/src/app.py" Researcher a_04)"

echo "── 输入异常必须 fail-open ──"
check allow "非 JSON 输入" 'not json at all'
check allow "空输入" ''
check allow "researcher Write 缺 file_path" '{"tool_name":"Write","agent_type":"researcher","agent_id":"a_05","tool_input":{}}'
check allow "researcher Bash command 非字符串" '{"tool_name":"Bash","agent_type":"researcher","agent_id":"a_08","tool_input":{"command":["rm","x"]}}'
check allow "researcher Bash 缺 command" '{"tool_name":"Bash","agent_type":"researcher","agent_id":"a_09","tool_input":{}}'
check allow "researcher Write 缺 tool_input" '{"tool_name":"Write","agent_type":"researcher","agent_id":"a_06"}'

echo
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
