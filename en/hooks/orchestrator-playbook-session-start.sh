#!/usr/bin/env bash
# SessionStart hook: 把编排者 playbook 注入主线程 context。
# 仅主线程 —— subagent 走独立的 SubagentStart，不继承此注入（这正是编排规则
# 要放这里、不放 CLAUDE.md 的原因：CLAUDE.md 会灌进每个 subagent）。
# playbook 是唯一真源，本脚本只读它、不复述 —— 无第二份，无漂移面。
# 用 python3 json.dumps 生成，绕开手搓 bash 转义的控制字符坑。
set -euo pipefail

# playbook 与 hooks/ 同级：按脚本自身位置解析，仓库放在哪里都能找到
PLAYBOOK="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/orchestrator-playbook.md"

exec python3 -c '
import json, sys
try:
    content = open(sys.argv[1], encoding="utf-8").read()
except Exception as e:
    content = "Error reading orchestrator-playbook.md: " + str(e)
sys.stdout.write(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": content,
    }
}))
' "$PLAYBOOK"
