# ADR 0004: The context watermark is read from transcript usage and gates the stop on a handoff

## Status

Accepted. In effect since 19 September 2026. Its handoff timing is superseded by [ADR 0007](0007-handoff-timing-weighs-switch-against-long-context.md), and its handoff format, which section 3 of the playbook defined, by [ADR 0010](0010-handoffs-are-generated-whole-by-the-handoff-skill.md), under which the handoff skill defines it.

## Context

A long session loses quality as its context fills. Long-context studies point the same way: RULER finds the effective context length of most models well short of the nominal length, and BABILong finds 10% to 20% of the context used effectively. The playbook's answer to a filling context is a handoff file, written in the handoff format of the playbook's §3, that a fresh session resumes from.

The input that Claude Code passes to a `Stop` hook carries no token fields. The session transcript does: the last assistant message's usage block records `input_tokens`, `cache_read_input_tokens` and `cache_creation_input_tokens`, and their sum is what that turn actually sent to the model.

`stop_hook_active` is true only in the turn that continues because a `Stop` hook blocked, and it resets with the next user message. A gate that relies on it alone blocks again at the end of every turn above its threshold.

## Decision

`hooks/context-watermark-gate.sh` runs on `Stop`, reads the last usage block from the transcript and compares the sum with the window size.

| Usage | Behaviour |
|---|---|
| Below 35% | Allow the stop |
| From 35% to below 40% | Allow, and add a reminder to write the handoff at the next natural break and then carry on |
| 40% and above | Block the stop once and ask for a handoff in the handoff format of the playbook's §3, placed in the task's working directory, after which the agent tells the user to switch to a new session |

After a block the gate writes the blocked level to the session's scratchpad and does not block again until usage has risen another 5 percentage points, so the session keeps working after it writes the handoff. Without a scratchpad directory it blocks on every turn above the hard line, because staying silent would lose the safeguard. It always allows the stop in three cases: when `stop_hook_active` is true, when it runs inside a subagent, and on any malformed input. A subagent is exempt because it has its own lifetime and the watermark is the main thread's concern. `CONTEXT_WINDOW_TOKENS`, `CONTEXT_WARN_PCT`, `CONTEXT_HARD_PCT` and `CONTEXT_REBLOCK_DELTA_PCT` override the 1,000,000-token window and the three thresholds.

The messages name only the action, carry no percentages, and point at section 3 of the playbook for the handoff format, so the format is defined in one place only.

## Consequences

The gate blocks the stop and asks for a handoff; it does not check that a handoff was written. Its thresholds assume the default 1,000,000-token window, and a session on a smaller window needs `CONTEXT_WINDOW_TOKENS` set to get meaningful percentages.

The usage figure depends on the transcript format. If the fields of the usage block changed, the gate would find no usage and allow every stop, which disables it silently but never blocks work. The regression test pins the three levels, the loop guard, subagent scope, threshold overrides, re-block suppression and malformed input.

## Sources

| Source | What it supports |
|---|---|
| `en/hooks/context-watermark-gate.sh`, header comment | `Stop` input has no token fields; usage is the sum of the three fields of the last assistant message in the transcript; the two lines, why `stop_hook_active` alone would block every turn above the hard line, the re-block rule, subagent scope and allow on error |
| `en/hooks/context-watermark-gate.sh`, the `WINDOW`, `WARN`, `HARD` and `REDELTA` defaults | Default window and thresholds and their environment overrides |
| `en/hooks/context-watermark-gate.sh`, the check on `used` after the transcript is read | No usage found means the stop is allowed |
| `en/hooks/context-watermark-gate.sh`, the `additionalContext` message below the hard line | The reminder between the two lines: write the handoff at the next natural break, then carry on |
| `en/hooks/context-watermark-gate.sh`, the scratchpad mark and the `block` reason | The blocked level is recorded only when a scratchpad directory exists; the block asks for a handoff in the task's working directory and, once it is written, for the user to be told to switch to a new session; nothing checks that it was written |
| `en/orchestrator-playbook.md`, §3 | The handoff format; when stopped at the hard line, the handoff is written at once and the user is then told to switch to a new session |
| `en/hooks/tests/context-watermark-gate.test.sh`, the re-block suppression section | Without a scratchpad directory the gate blocks on every turn instead of allowing silently |
| `en/hooks/tests/context-watermark-gate.test.sh` | The test cases; their number is the `PASS=<n>` the test prints |
| Hsieh et al., "RULER: What's the Real Context Size of Your Long-Context Language Models?", 2024, https://arxiv.org/abs/2404.06654 | Effective context length falls short of the nominal length |
| Kuratov et al., "BABILong: Testing the Limits of LLMs with Long Context Reasoning-in-a-Haystack", 2024, https://arxiv.org/abs/2406.10149 | Popular models use only 10% to 20% of the context effectively |
