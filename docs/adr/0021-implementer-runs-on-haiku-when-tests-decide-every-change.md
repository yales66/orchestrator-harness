# ADR 0021: `implementer` runs on Haiku when existing tests or listed acceptance cases decide every change

## Status

Accepted. In effect since 8 October 2026. It changes only the model the main thread sets when it dispatches `implementer`; the effort settings of [ADR 0008](0008-subagent-effort-per-kind-of-dispatch.md) stand, and the playbook's routing of every other kind of dispatch is unchanged.

## Context

Since ADR 0008 took effect on 1 October 2026, `implementer` and `retriever` dispatches have run on Opus 5.5 at effort `medium`, and `researcher` dispatches on Opus 5.5 at `high`. The definitions set effort but no model; section 2 of the playbook has the main thread set the model on every dispatch, and it sent all three to opus. The question this ADR answers is whether Claude Haiku 5.5 (`claude-haiku-5-5`) can take over the dispatches that ran on Opus 5.5 at `medium`, and at which effort.

The effort sweep in `eval/effort-sweep` answered it with the same replay ADR 0008 rests on, with the subagent's model as a variable and the dispatching main thread kept on Opus. The cases are 15 real briefs dispatched between 1 and 8 October 2026 and served by `claude-opus-5-5`: 9 implementations dispatched to `implementer` (kind `impl`) and 6 lookups dispatched to `retriever` (kind `lookup`), drawn from a qualifying pool of 173 implementations and 35 lookups under the qualification rules of the September sweep. Each kind is split into three difficulty bands by the tertile of the original subagent's tool calls in its first round, from receiving the brief to its first hand-back, and three implementations and two lookups per band were picked by hand, from different repositories within a band and from each kind's most common problem class, except for one local extraction lookup added on purpose. Five of the six lookups verify facts on the web, four of them against official pages, and one extracts facts from local design documents. Each case ran twice in each of four arms, opus `medium` as the reference and haiku at `xhigh`, `high` and `medium`, which gave 120 valid attempts and no errors, all on 8 October 2026 with Claude Code 2.1.293. Haiku at `max` was piloted once each on a mid-band implementation and a mid-band lookup and dropped: the implementation passed but cost $0.97 against $0.19 for the same rep at `high` and scored 0.80 of checks against 1.00 for every haiku `high` and opus attempt on that case, and the lookup failed under the checks as they stood before the audit. Haiku at `low` was not run, since the descent stopped once `medium` cleared for implementation, and lookup had already failed at every effort from `xhigh` down.

The competence rule was fixed before the runs. Per kind, paired by case, the upper end of the 95% t interval on opus `medium` checks minus haiku checks must be at most 5 percentage points, the bar ADR 0008 used, and no hard-band case may have opus passing both reps while haiku fails both. Among the competent efforts the cheapest at list price is chosen, and it must cost less than opus `medium`. Haiku 5.5 bills a whole request at its higher rates once the prompt exceeds 100,000 tokens, $0.50 instead of $0.10 per million input tokens and $2.50 instead of $0.50 per million output tokens, so each request is priced on its own prompt length.

An attempt passes when the brief's own self-verification commands succeed and it changed files inside the brief's file scope and nothing outside it. `checks` is the share of all atomic checks an attempt satisfies, and for an implementation it also counts the replay of the landed tests, the tests that came with the original change and were later merged, which do not count towards a pass. Two implementation arms can therefore both pass 18 of 18 and still differ in `checks`. The landed-test share is the share of individual landed tests that pass, a finer measure than the all-or-nothing landed-test check.

Before the results were unblinded, a blind audit split 15 items among three Opus `researcher` subagents, one auditor per item, with the main thread making the final call on each item before it opened the unblinding key. It reviewed every lookup check that half or more of all attempts missed, every landed-test command that failed in half or more, and every implementation attempt failed on scope or on an unmatched self-check placeholder, meaning the brief asked the subagent to run tests it wrote and the attempt added no file matching that command. It deleted four lookup checks for facts the brief never asked for, widened two that were too literal and excluded 18 landed tests that asserted details no brief fixed. The one verdict changed after unblinding concerns an opus implementation attempt that had worked in a nested worktree, as its brief told it to, and that the auditor had judged a scope violation; it was a blind spot of the grader. The grader now grades such a worktree for every arm, no other attempt worked in one, and the attempt was run again and passed; its workspace had been deleted, so it could not be regraded offline, and the rerun replaced the original row. The change raises opus's score, so it can only make it harder for haiku to clear the bar. As a check on `regrade` itself, regrading with the pre-audit checks reproduced every grade exactly; the audited checks were then applied offline, to the saved reports and answer files for lookup and to the recorded test replays for implementation. After the audit, with differences as opus minus haiku so that a negative value means haiku satisfied more:

| Kind | Arm | Pass | Paired checks difference, pp (95% CI) | Landed-test share difference, pp (95% CI) | Haiku cost ÷ opus (list-price total of the arm's attempts) | Verdict |
|---|---|---|---|---|---|---|
| impl | opus medium | 18/18 | | | ($20.47) | reference |
| impl | haiku medium | 18/18 | −2.8 (−9.2 to +3.6) | −0.2 (−0.6 to +0.3) | 0.16 ($3.28) | competent |
| impl | haiku high | 17/18 | +0.3 (−4.2 to +4.8) | +0.1 (−0.4 to +0.5) | 0.28 ($5.72) | competent |
| impl | haiku xhigh | 17/18 | −1.1 (−8.4 to +6.3) | −0.1 (−0.7 to +0.5) | 0.43 ($8.88) | interval too wide |
| lookup | opus medium | 7/12 | | | ($4.07) | reference |
| lookup | haiku xhigh | 6/12 | +1.4 (−13.7 to +16.4) | | 0.24 ($0.98) | not cleared |
| lookup | haiku high | 5/12 | +3.9 (−5.0 to +12.8) | | 0.16 ($0.66) | not cleared |
| lookup | haiku medium | 4/12 | +8.2 (−4.2 to +20.6) | | 0.10 ($0.40) | not cleared |

No hard-band case had opus at 2/2 and haiku at 0/2 at any effort. For implementation, `medium` and `high` both clear the bar and `medium` is the cheaper, at 0.16 of the opus cost. For lookup no effort shows that haiku stays within 5 points of opus. Haiku at `high` made more tool and web calls than opus and passed fewer attempts, and its misses lie in judging sources and claims: an archive that is still online declared missing, a required official source absent, a wrong lower bound of support. Our reading, which the sweep did not test, is that nothing in a lookup pushes back on such a miss, whereas an implementation brief carries self-verification commands that do.

## Decision

| Dispatch | Model | Effort | Condition |
|---|---|---|---|
| `implementer` | haiku | `medium`, from the definition | existing tests or acceptance cases listed in the brief (inputs and expected outputs, edge cases included) decide every changed behaviour |
| `implementer` | opus | `medium`, from the definition | every other case, including any changed behaviour judged only by tests the subagent writes |
| `retriever` | opus | `medium`, from the definition | unchanged |
| `researcher` | opus | `high`, from the definition | unchanged |

The main thread sets the model on each dispatch, as section 2 of the playbook already requires, and the "Who" item of section 2 in the `en/` and `zh/` playbooks states the condition: haiku when it holds, opus otherwise. The agent definitions are unchanged, because `implementer` already sets effort `medium` and none of them sets a model.

## Consequences

Implementation dispatches whose correctness an independent check decides cost the subagent 0.16 of what they cost on opus at list price, and the sweep found no loss beyond 5 percentage points of checks on its 9 cases. The sweep did not sort those 9 cases by the condition, so its figures cover settled implementation in general, and the condition narrows haiku to the part of it where the check is independent. The dispatching main thread adds about $0.14 per dispatch on either model. Haiku uses more tokens than opus on the same brief, an implementation median ratio of 1.8 at `medium`, but its list price is far lower. At `high` the most expensive haiku case was an implementation whose requests mostly exceeded 100,000 prompt tokens, at $1.7 to $2.0 per attempt. Haiku also edited a file outside the brief's scope in 2 of its 54 implementation attempts, against none of 18 for opus, so the main thread checks the file scope when it reviews a haiku attempt.

The condition exists because of how a first implementation is checked. When the only check is tests the subagent writes itself, code and tests come from the same reading of the brief, so a misreading passes both. The two from-scratch cases in this sweep had contracts that pinned acceptance cases, and on those haiku matched opus on the landed tests, which is the situation the sweep supports. The condition is a safeguard reasoned from that, not something the sweep measured separately, and a first implementation without such a fixed check stays on opus. The main thread has to judge the condition at dispatch, and a brief that only says "write tests" does not meet it.

The grading baseline leans towards the reference arm. Lookup checks come from the reports the main thread adopted, mostly written by opus, and landed tests come from changes opus made; the audit removed checks for facts no brief asked for, but the lookup verdict in particular should be read with that lean in mind.

A checklist at the end of each lookup brief, asking for an official source and a quoted sentence per conclusion for the routes tried before "not found", and for another route after a 403, a 404 or an unreadable PDF, was tried on haiku at `high`. It cleared the bar once under checks revised after the original four arms were unblinded and failed a confirmation run with those checks frozen, so `retriever` stays on opus; the section "Lookup follow-up" of `eval/effort-sweep/README.md` has the figures, and shows that part of the lookup gap above came from how the checks were written. Two follow-ups remain open. More lookup cases at `xhigh`, not more reps, would narrow an interval that six cases leave wide. Since Claude Code 2.1.292 the Agent tool accepts effort per call, which ADR 0008 said should lead to merging `researcher` and `retriever` into one read-only definition; that merge has not been made.

## Sources

| Source | What it supports |
|---|---|
| `eval/effort-sweep/README.md`, the section "Haiku sweep (October 2026)" | The question, cases, bands, arms, competence rule, blind audit, results table, lookup behaviour, token ratios and spend |
| `eval/effort-sweep/README.md`, the section "Grading" | What a pass, `checks` and the landed-test share count |
| `eval/effort-sweep/run.py`, `build_parser` | Arms by `--model` and five efforts, `summarize --ref/--arms`, `reprice` and `regrade` |
| `eval/effort-sweep/run.py`, `request_costs` and `PRICES` | Each request priced on its own prompt length, with the Haiku rates above 100,000 prompt tokens |
| `eval/effort-sweep/run.py`, `print_paired` | The paired difference in checks and in the landed-test share, their t intervals, and the cost ratio |
| `eval/effort-sweep/run.py`, `hidden_tests` and `apply_hidden_exclude` | The landed-test share and the excluded landed tests |
| `eval/effort-sweep/run.py`, `grading_root` and `soft_reset_to_base` | Grading an attempt that worked in a nested worktree and committed its changes |
| `eval/effort-sweep/run.py`, `save_answer_files` and `cmd_regrade` | The offline regrade after the audit, which reproduced every grade exactly with unchanged checks |
| `eval/effort-sweep/grade.py`, `expand_command` | The self-check placeholder that fails when the attempt added no matching file |
| `en/orchestrator-playbook.md`, section 2 | The routing of `implementer` to haiku or opus by the condition above |
| `en/agents/implementer.md`, frontmatter | `implementer` sets effort `medium` and no model |
| platform.claude.com/docs/en/about-claude/pricing, retrieved 8 October 2026 | Opus 5.5 and Haiku 5.5 list prices, and the Haiku rates for a prompt above 100,000 tokens |
| Claude Code changelog, version 2.1.292 | The Agent tool's `effort` parameter |
| [ADR 0008](0008-subagent-effort-per-kind-of-dispatch.md), Decision and Consequences | Effort per definition, the 5-point bar, and the merge of `researcher` and `retriever` once effort can be set per call |
