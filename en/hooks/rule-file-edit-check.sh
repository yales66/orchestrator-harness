#!/usr/bin/env bash
# PostToolUse / matcher "Edit|Write":路径命中 LLM 规则文件时,注入核查提醒
# (确定性触发,不依赖 rule-file-editing skill 的概率性自动加载)。
input=$(cat)
path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
[ -z "$path" ] && exit 0

case "$path" in
  */CLAUDE.md|*/CLAUDE.local.md|*/AGENTS.md|*/SKILL.md|*/.claude/commands/*.md|*/.claude/agents/*.md|*/.claude/output-styles/*)
    printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"已改动 LLM 规则文件:按 rule-file-editing skill 处理。"}}\n'
    ;;
esac
exit 0
