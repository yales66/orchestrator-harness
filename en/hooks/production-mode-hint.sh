#!/bin/bash
# UserPromptSubmit hook: 用户本人输入的消息提到「生产模式」或 production mode（不分大小写）时，注入切换方法说明。
# 生产标记的实际作用方是 production-merge-gate.sh；本钩子只让会话知道怎么设置与取消这个标记。
python3 -c '
import json, re, sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
prompt = data.get("prompt", "") or ""
# 子智能体回报与后台通知也走 UserPromptSubmit，不是用户本人输入
if re.match(r"\s*(Another Claude session sent a message|<agent-message|<task-notification)", prompt):
    sys.exit(0)
if not re.search(r"生产模式|production\s+mode", prompt, re.IGNORECASE):
    sys.exit(0)

hint = "生产模式＝仓库 git config claude.production true（--unset 退回）；生产仓库合并会弹确认。先确认是哪个仓库。"
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": hint
}}, ensure_ascii=False))
sys.exit(0)
' 2>/dev/null
exit 0
