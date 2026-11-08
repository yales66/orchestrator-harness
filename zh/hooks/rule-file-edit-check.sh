#!/usr/bin/env bash
# PostToolUse / matcher "Edit|Write":路径命中 LLM 规则文件时,注入核查提醒
# (确定性触发,不依赖 rule-file-editing skill 的概率性自动加载)。
# 同一上下文同一文件只提醒一次:技能在第一次改动前就该加载,之后的提醒不带新信息。
# 子智能体与主线程共用 scratchpad_dir 却不共享已加载的技能,所以标记按 agent_id 加路径哈希命名;
# 拿不到该目录时每次都提醒。
input=$(cat)
path=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
[ -z "$path" ] && exit 0

case "$path" in
  */CLAUDE.md|*/CLAUDE.local.md|*/AGENTS.md|*/SKILL.md|*/.claude/commands/*.md|*/.claude/agents/*.md|*/.claude/output-styles/*|*/.claude/orchestrator-playbook.md|*/.claude/skills/*.md)
    sp=$(printf '%s' "$input" | jq -r '.scratchpad_dir // empty' 2>/dev/null)
    if [ -n "$sp" ] && [ -d "$sp" ]; then
      agent=$(printf '%s' "$input" | jq -r '.agent_id // empty' 2>/dev/null)
      mark="$sp/.rule-file-edit-check-$(printf '%s|%s' "$agent" "$path" | cksum | cut -d' ' -f1)"
      [ -e "$mark" ] && exit 0
      : > "$mark" 2>/dev/null
    fi
    msg="改动了 LLM 规则文件 ${path}：还没加载 rule-file-editing 技能就先加载，按它复核这处改动。"
    printf '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":%s}}\n' "$(printf '%s' "$msg" | jq -Rs .)"
    ;;
esac
exit 0
