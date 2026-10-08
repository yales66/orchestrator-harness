# ADR 0021: `implementer` runs on Haiku when tests decide every change

## Status

Accepted. In effect since 8 October 2026. It changes only the model the main thread sets when it dispatches `implementer`. The effort each definition carries under [ADR 0008](0008-subagent-effort-per-kind-of-dispatch.md) stands, so `implementer` runs at `medium` on either model, and the routing of every other kind of dispatch in ADR 0008 is unchanged.

## Context

Since ADR 0008 took effect on 1 October 2026, `implementer` and `retriever` dispatches have run on Opus 5.5 at effort `medium`, and `researcher` dispatches on Opus 5.5 at `high`. The definitions set effort but no model; section 2 of the playbook has the main thread set the model on every dispatch, and it sent all three to opus. The question this ADR answers is whether Claude Haiku 5.5 (`claude-haiku-5-5`) can take over the dispatches that ran on Opus 5.5 at `medium`, and at which effort.

The effort sweep in `eval/effort-sweep` answered it with the same replay ADR 0008 rests on, with the subagent's model as a variable and the dispatching main thread kept on Opus. The cases are 15 real briefs dispatched between 1 and 8 October 2026 to `implementer` or `retriever` and served by `claude-opus-5-5`: 9 implementations and 6 lookups, drawn from a qualifying pool of 173 implementations and 35 lookups under the qualification rules of the September sweep. Each kind is split into three difficulty bands by the tertile of the original subagent's first-round tool calls, and the sweep took three implementations and two lookups per band. Five of the six lookups verify official facts on the web and one extracts facts from local design documents. Each case ran twice in each of four arms, opus `medium` as the reference and haiku at `xhigh`, `high` and `medium`, which gave 120 valid attempts and no errors, all on 8 October 2026 with Claude Code 2.1.293. Haiku at `max` was piloted on two cases and dropped, because on the mid-band implementation it cost $0.97 against $0.19 at `high` and scored lower; haiku at `low` was not run, since the descent stopped once `medium` cleared.

The competence rule was fixed before the runs. Per kind, paired by case, the upper end of the 95% t interval on opus `medium` checks minus haiku checks must be at most 5 percentage points, the bar ADR 0008 used, and no hard-band case may have opus passing both reps while haiku fails both. Among the competent efforts the cheapest at list price is chosen, and it must cost less than opus `medium`. Haiku 5.5 bills a whole request at its higher rates once the prompt exceeds 100,000 tokens, $0.50 instead of $0.10 per million input tokens and $2.50 instead of $0.50 per million output tokens, so each request is priced on its own prompt length.

Before the results were unblinded, a blind audit reviewed every check that half or more of all attempts missed, every landed-test command that failed in half or more, and every implementation attempt failed on scope or on an unmatched self-check placeholder. It deleted four lookup checks for facts the brief never asked for, widened two that were too literal and excluded 18 landed tests that asserted details no brief fixed. After the audit:

| Kind | Arm | Pass | Paired checks difference, opus minus haiku, pp (95% CI) | Landed-test share difference, pp (95% CI) | Haiku cost ÷ opus | Verdict |
|---|---|---|---|---|---|---|
| impl | opus medium | 18/18 | | | ($20.47 total) | reference |
| impl | haiku medium | 18/18 | −2.8 (−9.2 to +3.6) | −0.2 (−0.6 to +0.3) | 0.16 ($3.28) | competent |
| impl | haiku high | 17/18 | +0.3 (−4.2 to +4.8) | +0.1 (−0.4 to +0.5) | 0.28 ($5.72) | competent |
| impl | haiku xhigh | 17/18 | −1.1 (−8.4 to +6.3) | −0.1 (−0.7 to +0.5) | 0.43 ($8.88) | interval too wide |
| lookup | opus medium | 7/12 | | | ($4.07) | reference |
| lookup | haiku xhigh | 6/12 | +1.4 (−13.7 to +16.4) | | 0.24 ($0.98) | not cleared |
| lookup | haiku high | 5/12 | +3.9 (−5.0 to +12.8) | | 0.16 ($0.66) | not cleared |
| lookup | haiku medium | 4/12 | +8.2 (−4.2 to +20.6) | | 0.10 ($0.40) | not cleared |

No hard-band case had opus at 2/2 and haiku at 0/2 at any effort. For implementation, `medium` and `high` both clear the bar and `medium` is the cheaper, at 0.16 of the opus cost. For lookup no effort clears it. Haiku at `high` made more tool and web calls than opus and still scored lower, and its misses lie in judging sources and claims: an archive declared missing, a required official source absent, a wrong oldest device. Nothing in a lookup pushes back on such a miss, whereas an implementation brief carries self-verification commands that do.

## Decision

| Dispatch | Model | Effort | Condition |
|---|---|---|---|
| `implementer` | haiku | `medium`, from the definition | existing tests or acceptance cases listed in the brief (inputs and expected outputs, edge cases included) decide every changed behaviour |
| `implementer` | opus | `medium`, from the definition | any changed behaviour is judged only by tests the subagent writes |
| `retriever` | opus | `medium`, from the definition | unchanged |
| `researcher` | opus | `high`, from the definition | unchanged |

The main thread sets the model on each dispatch, as section 2 of the playbook already requires, and line 31 of both playbooks states the condition. The agent definitions are unchanged, because `implementer` already sets effort `medium` and none of them sets a model.

## Consequences

Implementation dispatches whose correctness an independent check decides cost 0.16 of what they cost on opus at list price, with no loss the sweep could detect. Haiku uses more tokens than opus on the same brief, a median ratio of 1.8 at `medium`, but its list price is far lower. A case whose requests mostly exceed 100,000 prompt tokens costs haiku the most, and the largest implementation case cost $1.7 to $2.0 per attempt at `high`.

The condition exists because of how a first implementation is checked. When the only check is tests the subagent writes itself, code and tests come from the same reading of the brief, so a misreading passes both. The two from-scratch cases in this sweep had contracts that pinned acceptance cases, and on those haiku matched opus on the landed tests, which is the situation the sweep supports. A first implementation without such a fixed check stays on opus. The main thread has to judge the condition at dispatch, and a brief that only says "write tests" does not meet it.

Three follow-ups remain open. A lookup brief that carries a checklist of required sources may let haiku clear the bar, and should be tried on haiku. A larger lookup sample at `xhigh` would narrow an interval that six cases leave wide. The Agent tool now accepts effort per call, which ADR 0008 said should lead to merging `researcher` and `retriever` into one read-only definition; that merge has not been made.

## Sources

| Source | What it supports |
|---|---|
| `eval/effort-sweep/README.md`, the section "Haiku sweep (October 2026)" | The question, cases, bands, arms, competence rule, blind audit, results table, lookup behaviour, token ratios and spend |
| `eval/effort-sweep/run.py`, `build_parser` | Arms by `--model` and five efforts, `summarize --ref/--arms`, `reprice` and `regrade` |
| `eval/effort-sweep/run.py`, `request_costs` and `PRICES` | Each request priced on its own prompt length, with the Haiku rates above 100,000 prompt tokens |
| `eval/effort-sweep/run.py`, `print_paired` | The paired difference in checks and in the landed-test share, their t intervals, and the cost ratio |
| `eval/effort-sweep/run.py`, `hidden_tests` and `apply_hidden_exclude` | The landed-test share, the excluded landed tests and the run stopped at collection counted as indeterminate |
| `eval/effort-sweep/run.py`, `grading_root` and `soft_reset_to_base` | Grading an attempt that worked in a nested worktree and committed its changes |
| `eval/effort-sweep/run.py`, `save_answer_files` and `cmd_regrade` | The offline regrade after the audit, which reproduced every grade exactly with unchanged checks |
| `en/orchestrator-playbook.md`, line 31 | The routing of `implementer` to haiku or opus by the condition above |
| `en/agents/implementer.md`, frontmatter | `implementer` sets effort `medium` and no model |
| platform.claude.com/docs/en/about-claude/pricing, retrieved 8 October 2026 | Opus 5.5 and Haiku 5.5 list prices, and the Haiku rates for a prompt above 100,000 tokens |
| [ADR 0008](0008-subagent-effort-per-kind-of-dispatch.md), Decision and Consequences | Effort per definition, the 5-point bar, and the merge of `researcher` and `retriever` once effort can be set per call |
