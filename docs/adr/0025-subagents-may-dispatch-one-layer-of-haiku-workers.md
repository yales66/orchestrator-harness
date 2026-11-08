# ADR 0025: Subagents may dispatch one layer of haiku workers

## Status

Accepted. In effect since 14 October 2026. It amends [ADR 0003](0003-subagents-cannot-spawn-subagents.md): a subagent may dispatch `Agent` or `Task` when the call sets the model to haiku, and those workers cannot dispatch further. Every other dispatch from inside a subagent, `Workflow` included, is still denied, and ADR 0003's `agent_id` criterion and allow-on-malformed-input stand. It also amends, for one kind of question, the rule restated in [ADR 0023](0023-implementer-runs-on-haiku-when-tests-decide-including-its-own.md) that work judged only by looking stays on opus: a yes-or-no question on a single-element crop in an end-to-end test goes to haiku.

## Context

Under ADR 0003 a subagent did every step itself. In end-to-end testing and similar work, many of its steps are short mechanical jobs, such as summarising a test run, checking copy against a source, or answering whether one cropped element is clipped, and each step a long-running subagent takes rereads its whole context. On 14 October 2026 the user chose to let subagents hand such jobs to haiku to cut their step count.

The same day the author measured haiku on these jobs: test-result summaries 8 of 8 correct, copy checks 8 of 8, and yes-or-no questions on single-element crops 12 of 13, where the one miss was an answer of "cannot judge". The longest worker context in that measurement was about 42,000 tokens.

Claude Code's `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` limits nesting; per the upstream commit, which cites the official documentation, a value of 2 lets a subagent dispatch one further layer whose members cannot dispatch again. Official pricing as of October 2026 bills a whole Haiku call at five times the rate once its prompt exceeds 100,000 tokens.

## Decision

`settings.example.json` in both copies sets `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` to `2`. `hooks/block-nested-subagent.sh` still runs on `PreToolUse` for `Agent`, `Task` and `Workflow` and still keys on `agent_id`. Inside a subagent it allows `Agent` or `Task` when `tool_input.model` is `haiku` or starts with `claude-haiku`, and denies everything else; the denial now says that only explicit haiku workers are allowed, for short jobs with context under 50,000 tokens, and that any other split goes back to the orchestrator in the return value.

Section 2 of the playbook sets the rule for the dispatching side:

| Item | Rule |
|---|---|
| Who may dispatch workers | Any subagent except `retriever`, whose definition no longer has the `Agent` tool |
| Which jobs | Only short mechanical ones: summarising test results, checking copy, yes-or-no questions on single-element crops, and fix suggestions for mechanical errors in a scene, after which the scene is rerun |
| Worker input | Only paths and the question; context kept under 50,000 tokens |
| Main thread's brief | States which jobs the subagent may hand out and the context cap |
| End-to-end crop questions | A yes-or-no question on a single-element crop, such as whether text is clipped, overlapping or illegible, goes to haiku; a problem haiku reports counts only after opus rechecks it |

The 50,000-token cap is the measured longest worker context, about 42,000, rounded up; the five-times billing above 100,000 tokens is the reason to stay well under that line.

The same playbook section also sorts messages to a running subagent into two branches, since each message makes it take more steps that each reread its long context. Branch A, sent at once and only to the affected subagents, covers what it would otherwise get wrong, waste work on or record as a wrong conclusion, and anything whose effect cannot be told. Branch B, everything else such as a wording correction that changes no output or conclusion, rides with the next continuation or dispatch if there is one and is otherwise dropped. Progress queries are never sent.

## Consequences

Dispatch can now be two levels deep, but only the second level's model is fixed, and that level cannot go further: the depth setting removes the `Agent` tool from workers. Fan-out the orchestrator did not plan is limited to haiku workers on jobs its brief named, while `Workflow` from inside a subagent stays denied.

The jobs measured are narrow and the samples small, 8, 8 and 13 cases. Haiku's one crop miss was an abstention rather than a wrong answer, and haiku's reported problems are rechecked by opus, so a false alarm costs a recheck; a problem haiku misses is not rechecked. Work judged by looking at a whole interface, rather than one cropped element, stays on opus.

The hook allows any explicit haiku call from inside a subagent, a worker's included, so the third level is stopped only by the depth setting; an installation whose `settings.json` lacks it relies on Claude Code's default depth, which this repository has not measured.

The hook's regression test pins the new branch with seven cases, which [ADR 0005](0005-deciding-hooks-ship-with-regression-tests.md) requires of a deciding hook: from inside a subagent, `Agent` and `Task` with the model `haiku` pass, as does the full name in any letter case; `opus`, a call that sets no model, a model name that only contains "haiku", and `Workflow` even with `haiku` are denied. Changing the condition to deny every haiku call, to allow every model, or to allow any name containing "haiku" turns at least one case red.

## Sources

| Source | What it supports |
|---|---|
| Commit 1f16ac2 in the author's live harness (`~/.claude`), body | The user's choice on 14 October 2026; depth 2 meaning one more layer that cannot dispatch, per the official documentation as the body cites it; only explicit haiku `Agent`/`Task` calls allowed, `Workflow` and other models still denied |
| Commit 07b3720 in the author's live harness, body | The measurement of 8 of 8, 8 of 8 and 12 of 13 with the one "cannot judge" miss; the 50,000 cap from the longest measured 42,000; the five-times threshold from official pricing |
| Commit 242c7ba in the author's live harness, body | The two branches for messages to a running subagent and why each message costs |
| Commit b29401e in the author's live harness, body | `retriever` loses the `Agent` tool and is excluded from the worker rule |
| `en/hooks/block-nested-subagent.sh`, header comment and code | The haiku allow branch, the `Workflow` denial and the denial text; the depth setting keeps the `Agent` tool from the worker layer |
| `en/hooks/tests/block-nested-subagent.test.sh` | 18 cases, 7 of them for the haiku worker branch |
| `en/settings.example.json`, `env` | `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` set to `2` |
| `en/agents/retriever.md`, frontmatter | `Agent` in `disallowedTools` |
| `en/orchestrator-playbook.md`, section 2, the "Who" item and the items on workers and on messages to a running subagent | The end-to-end crop exception, the worker rule and the two message branches |
| [ADR 0003](0003-subagents-cannot-spawn-subagents.md) and [ADR 0023](0023-implementer-runs-on-haiku-when-tests-decide-including-its-own.md) | The rules this ADR amends |
