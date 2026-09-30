# ADR 0001：编排规则只送达主线程

## 状态

已采纳，自 2026 年 9 月 1 日起生效。

## 背景

Claude Code 会把 `CLAUDE.md` 加载进每个会话，每个子智能体也会加载它。编排规则（任务路由、哪些活派出去、派发说明怎么写、长任务怎么交接、交付闸门）是写给派活的那条线程的，而在本框架里派活的只有主线程（见 ADR 0003）。这些规则若放在 `CLAUDE.md` 里，每个子智能体的上下文都要背着它们。

`SessionStart` 钩子事件只在主线程触发。子智能体经由自己的 `SubagentStart` 事件启动，不继承 `SessionStart` 钩子注入的内容。

## 决策

编排规则放在编排手册 `orchestrator-playbook.md` 里，模型只通过 `hooks/orchestrator-playbook-session-start.sh` 拿到它：该钩子在 `startup`、`clear`、`compact` 三种来源的 `SessionStart` 上，把编排手册全文作为 `additionalContext` 注入。`CLAUDE.md` 只保留包括子智能体在内每个会话都需要的规则，它的准入判据是只记录与 Claude Code 默认行为的差分。

钩子只读取编排手册、不复述其中任何内容，所以编排手册是这些规则唯一的一份，不存在会与它漂移的第二份。钩子按脚本自身位置解析编排手册，取 `hooks/` 的上一级目录，因此框架装在哪里规则都能加载。

## 后果

子智能体启动时只带 `CLAUDE.md` 和自己的派发说明，不带编排其他智能体的规则。改编排规则不必动每个子智能体都会加载的那个文件。

`orchestrator-playbook.md` 必须紧挨在 `hooks/` 的上一级。`zh/README.md` 的安装步骤把 `hooks/*.sh` 与编排手册按相同的相对路径复制到 `~/.claude/` 下，`settings.example.json` 也按这个位置注册该钩子。`orchestrator-playbook-session-start.test.sh` 检查注入的文本与编排手册逐字节相同，`HOME` 指向空目录时也一样。

## 出处

| 出处 | 支撑的内容 |
|---|---|
| `zh/orchestrator-playbook.md` | 编排规则本身：哪些活派出去、任务路由、子智能体派发与派发说明、长任务与交接、交付闸门 |
| `zh/hooks/orchestrator-playbook-session-start.sh` 文件头注释 | 仅主线程；子智能体走 `SubagentStart`、不继承注入；`CLAUDE.md` 会进入每个子智能体，所以编排规则不放在里面；编排手册是唯一真源 |
| `zh/hooks/orchestrator-playbook-session-start.sh` 中 `PLAYBOOK` 的赋值 | 按脚本自身位置解析编排手册 |
| `zh/settings.example.json` 的 `SessionStart` 条目 | `startup\|clear\|compact` 匹配条件 |
| `zh/CLAUDE.md` 开头一段 | `CLAUDE.md` 的准入判据 |
| `zh/README.md`「安装」一节第 4 步 | 安装把 `hooks/*.sh` 与 `orchestrator-playbook.md` 按相同的相对路径复制到 `~/.claude/` 下 |
| `zh/settings.example.json` 中 `SessionStart` 条目的命令 | 钩子注册在 `$HOME/.claude/hooks/` 下，因此它把编排手册解析为 `$HOME/.claude/orchestrator-playbook.md` |
| `zh/hooks/tests/orchestrator-playbook-session-start.test.sh` | 逐字节相等的测试，含 `HOME` 为空目录的情形 |
