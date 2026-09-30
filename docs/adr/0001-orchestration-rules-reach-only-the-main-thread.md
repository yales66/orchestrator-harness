# ADR 0001: Orchestration rules reach only the main thread

## Status

Accepted. In effect since 1 September 2026.

## Context

Claude Code loads `CLAUDE.md` into every session, and every subagent loads it as well. The orchestration rules (task routing, what to delegate, how to write a subagent brief, how to hand off a long task, the delivery gate) are written for the thread that dispatches work, which in this harness is always the main thread (ADR 0003). Kept in `CLAUDE.md`, these rules would travel in every subagent's context.

The `SessionStart` hook event reaches only the main thread. A subagent starts through its own `SubagentStart` event and does not inherit what a `SessionStart` hook injects.

## Decision

The orchestration rules live in `orchestrator-playbook.md`, and the model receives them only through `hooks/orchestrator-playbook-session-start.sh`, which injects the full playbook as `additionalContext` on `SessionStart` for the `startup`, `clear` and `compact` sources. `CLAUDE.md` keeps only the rules that every session, subagents included, needs; its admission rule is that it records only the deltas from Claude Code's default behaviour.

The hook reads the playbook and restates none of it, so the playbook is the only copy of these rules and no second copy can drift from it. The hook resolves the playbook relative to its own location, one directory above `hooks/`, so the rules load wherever the harness is installed.

## Consequences

A subagent starts with `CLAUDE.md` and its brief, without the rules for orchestrating other agents. Orchestration rules can change without touching the file every subagent loads.

`orchestrator-playbook.md` has to sit directly above `hooks/`. The install steps in `README.md` copy `hooks/*.sh` and the playbook to the same relative paths under `~/.claude/`, and `settings.example.json` registers the hook at that location. `orchestrator-playbook-session-start.test.sh` checks that the injected text equals the playbook byte for byte, including when `HOME` points at an empty directory.

## Sources

| Source | What it supports |
|---|---|
| `en/orchestrator-playbook.md` | The orchestration rules: what to delegate, task routing, subagent dispatch and the brief, long tasks and handoff, the delivery gate |
| `en/hooks/orchestrator-playbook-session-start.sh`, header comment | Main thread only; subagents use `SubagentStart` and do not inherit the injection; `CLAUDE.md` is loaded into every subagent, which is why the orchestration rules stay out of it; the playbook is the single source |
| `en/hooks/orchestrator-playbook-session-start.sh`, the `PLAYBOOK` assignment | Playbook resolved relative to the script's own location |
| `en/settings.example.json`, the `SessionStart` entry | `startup\|clear\|compact` matcher |
| `en/CLAUDE.md`, opening paragraph | Admission rule for `CLAUDE.md` |
| `README.md`, section Install, step 4 | The install copies `hooks/*.sh` and `orchestrator-playbook.md` to the same relative paths under `~/.claude/` |
| `en/settings.example.json`, the command of the `SessionStart` entry | The hook is registered at `$HOME/.claude/hooks/`, so it resolves the playbook as `$HOME/.claude/orchestrator-playbook.md` |
| `en/hooks/tests/orchestrator-playbook-session-start.test.sh` | Byte-equality test, including the empty `HOME` case |
