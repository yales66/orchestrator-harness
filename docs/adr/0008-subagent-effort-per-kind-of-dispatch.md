# ADR 0008: Subagent effort is set per kind of dispatch

## Status

Accepted. In effect since 1 October 2026. ADR 0006, in its row on a question about a fact, dispatched `researcher` to search session transcripts. Such a search now lands on `retriever` through the dispatch routing in section 2 of the playbook, and the rest of ADR 0006 stands.

## Context

Reasoning effort sets how much a subagent thinks before it acts, and with it the tokens and time a dispatch costs. The Agent tool takes no effort per call. Per subagent, effort can be set only in the `effort` field of its definition's frontmatter, and a definition without that field follows the session's effort, which for Opus 5.5 is `medium` when nothing sets it. The effort a dispatch runs at therefore depends on which definition it goes to. Before this decision `researcher` was the only subagent definition and set no `effort`, so subagents followed the session's effort, which the author's sessions set to `high` for Opus 5.5. That is why the sweep takes `high` as its baseline.

The effort sweep in `eval/effort-sweep` measured what `medium` costs against `high` on the same work. It replayed 20 real briefs from past sessions, 8 implementations with design decisions fixed by the brief, 6 read-only lookups and 6 read-only reviews or diagnoses that need judgement, each at both efforts on the commit it was written against. Each brief ran twice per effort on `claude-opus-5-5` between 30 September and 1 October 2026, 80 valid attempts in all.

| Tier | Pass rate at high [Wilson 95%] | Pass rate at medium [Wilson 95%] | Paired difference in the share of checks satisfied, high minus medium, percentage points (95% t interval) | Medium tokens ÷ high: median over cases of the per-case ratio (each case's two reps averaged first), tokens including cache reads and writes | Median seconds per attempt, high / medium |
|---|---|---|---|---:|---:|
| impl | 88% [64%, 97%] | 88% [64%, 97%] | -1.0 (-3.5 to +1.4) | 0.54 | 394 / 269 |
| lookup | 50% [25%, 75%] | 58% [32%, 81%] | -1.2 (-7.5 to +5.1) | 0.49 | 450 / 212 |
| judgement | 50% [25%, 75%] | 42% [19%, 68%] | +2.0 (-14.7 to +18.7) | 0.42 | 407 / 240 |
| all | 65% [50%, 78%] | 65% [50%, 78%] | -0.2 (-4.4 to +4.1) | 0.51 | 424 / 224 |

`checks` is the share of a brief's atomic checks an attempt satisfies, and a negative difference means medium satisfied slightly more. An attempt passes only when every check holds, and the per-tier pass rates rest on 12 to 16 attempts, so their intervals overlap almost entirely and the paired difference in `checks` carries the comparison. For implementation the interval's upper end puts any drop at medium at no more than about 1.4 points, and for lookup at no more than about 5.1, at about half the tokens. For judgement the upper end reaches 18.7 points, so six cases cannot rule out a drop of about 19 points.

Priced at API list rates, the subagents' usage comes to $68.3 at high against $41.4 at medium; the runs themselves drew on a subscription's usage allowance. The cost ratio of about 0.6 sits above the token ratio of about 0.5 because a cache read is priced at a hundredth of an output token, and most of the tokens medium saves are cache reads: summed over all attempts, medium used 55.9 million cache-read tokens against 111.0 million at high, but 2.8 million cache-write tokens against 4.1 million and 0.80 million output tokens against 1.27 million, and cache writes and output carry two thirds or more of the cost at either effort.

## Decision

Effort is fixed per kind of dispatch, in three subagent definitions:

| Definition | Effort | Takes | Limits |
|---|---|---|---|
| `researcher` | `high` | read-only review, diagnosis, research and drafting that need judgement, web included, whose deliverable is a verdict, an explanation or a draft | may create new files and must not change existing ones |
| `retriever` | `medium` | read-only lookup and extraction of facts, locations, values and records in code, documents, session transcripts or on the web, reported with evidence and without a verdict | the same as `researcher`; an answer that would take a judgement the brief did not ask for comes back as facts with the open judgement named |
| `implementer` | `medium` | implementation with design decisions fixed by the brief | every tool; a decision the brief did not settle and that would change the result goes into the report with its options and a recommendation, and the parts that do not depend on it are finished |

`researcher` is set to `high`, the session effort subagents followed before this change, because the judgement tier is the one the sweep could not clear. Every other dispatch on opus carries no effort of its own and runs at the session's effort. `subagent-readonly-guard.sh` restricts `retriever` the same way as `researcher`, since the `retriever` definition relies on the hook to deny edits.

Section 2 of the playbook routes by deliverable: open-ended location across a repository goes to Explore on haiku, purely mechanical batch work to a haiku fan-out, lookup and extraction to `retriever`, read-only review, diagnosis, research and drafting that need judgement to `researcher`, implementation with design decisions fixed by the brief to `implementer`, and the rest to opus.

## Consequences

Implementation and lookup dispatches run at about half the tokens and in less time with no loss the sweep could detect, and judgement-bound work runs at `high`. The main thread has to classify each dispatch: a judgement task sent to `retriever` runs at `medium`, and the definition's instruction to name an open judgement rather than settle it is the guard against that.

`researcher` and `retriever` differ only in effort and in the work they take. If the dispatch tool comes to accept effort per call, the two should merge into one read-only definition with the effort chosen at dispatch.

The judgement tier rests on six cases, and its interval is too wide to decide either way. It should be measured again with a larger sample, and moves to `medium` only once the upper end of the interval on its paired difference in checks, high minus medium, falls to the level the other two tiers reached, about 5 percentage points.

`CLAUDE_CODE_EFFORT_LEVEL`, once set in the environment, overrides the `effort` field of all three definitions, so a user who sets it runs every subagent at that one effort.

The English playbook carries the routing text too, and at 9,993 characters it is close to the 10,000 beyond which Claude Code hands a SessionStart injection to the model only as a preview; the Chinese playbook, at about 3,960 characters, is far from it, so the limit binds only the English one. `scripts/check-parity.sh` fails at that length, so any further routing text there has to displace something else.

## Sources

| Source | What it supports |
|---|---|
| `eval/effort-sweep/README.md`, the Results section | The cases, the runs, the table, latency, cost and its split by token kind, and the handling of attempts cut short by a usage limit |
| `eval/effort-sweep/run.py`, `cmd_summarize` | How the paired difference, its t interval and the per-case token ratio are computed |
| `git show 65524d0:en/agents/researcher.md` | Before this decision `researcher` was the only definition and set no `effort` |
| `eval/effort-sweep/README.md`, "How a case runs, and why this way" | The frontmatter `effort` overrides the session's effort, and `CLAUDE_CODE_EFFORT_LEVEL` overrides the frontmatter |
| The Agent tool's input parameters in Claude Code 2.1.286 | The Agent tool has no parameter that sets effort per call |
| `meta.effort_in_requests.main` in each attempt record of the effort sweep | A thread with no effort set sends `medium` in its requests |
| `en/agents/researcher.md`, `en/agents/retriever.md`, `en/agents/implementer.md` | Each definition's effort, the work it takes, and the instructions to name an open judgement or report an open decision |
| `en/orchestrator-playbook.md`, §2, the "Who" item | Routing by deliverable to Explore, haiku, `retriever`, `researcher`, `implementer` or opus |
| `en/orchestrator-playbook.md`, §1, the paragraph on asking the user a fact | The search of session transcripts dispatched through §2 |
| `en/hooks/subagent-readonly-guard.sh`, header comment and the `agent_type` check | The guard covers `retriever` as well as `researcher` |
| `en/hooks/tests/subagent-readonly-guard.test.sh`, the `retriever` section | `retriever` may create files and is denied changes to existing ones |
| `scripts/check-parity.sh`, the playbook length check | The 10,000-character limit on the playbook |
| `docs/adr/0006-ask-the-user-only-where-the-answer-is-theirs.md`, the row on a question about a fact | The detail this ADR supersedes |
