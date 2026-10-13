# ADR 0023: `implementer` runs on Haiku when tests decide the change, including tests the subagent writes

## Status

Accepted. In effect since 14 October 2026. It amends the `implementer` rows of [ADR 0021](0021-implementer-runs-on-haiku-when-tests-decide-every-change.md): an implementation whose judgement the brief has settled runs on Haiku 5.5 when tests decide whether each changed behaviour is right, whether those tests already exist, are listed as acceptance cases in the brief or are written by the subagent itself, and the main thread checks that every file a haiku attempt changed lies within the brief's scope. Every other implementation stays on Opus 5.5, including one with any part judged only by looking or reading, such as a visual front-end change or an edit to documentation or prose, even when tests decide the rest of it. The `retriever` routing of [ADR 0022](0022-retriever-runs-on-haiku-when-the-brief-limits-it-to-local-files-or-one-named-page.md), the `researcher` routing and the effort settings of [ADR 0008](0008-subagent-effort-per-kind-of-dispatch.md) are unchanged.

## Context

ADR 0021 sent to opus any implementation in which a changed behaviour is judged only by tests the subagent writes, and says of that condition that it is "a safeguard reasoned from that, not something the sweep measured separately". In the October haiku sweep behind ADR 0021, 8 of its 9 implementation briefs told the subagent to write its own tests, and haiku `medium` passed 18 of 18 with a landed-test share within ±0.6 points of opus. In production from 8 to 13 October 2026, an opus classification of all 723 dispatch briefs found 76 `implementer` dispatches on opus whose briefs asked the subagent to write its own tests, $116 at list price over those six days. This follow-up measured that branch on its own.

The method was pre-registered before any haiku attempt ran. The population is those 76 dispatches, qualified under the rules in the section "Cases" of `eval/effort-sweep/README.md` and split into three bands by the tertile of the original subagent's tool calls in its first round, with cut points at 23 and 42. Ten cases were picked, 4 hard, 3 mid and 3 easy, across four private repositories. Haiku `implementer` subagents built all ten, and each passed `selftest.py`: the landed change passes, the unchanged base and a broken change fail, and the leak check is clean. Candidates were dropped when the brief pushes, opens or merges a real pull request, which a replay could carry out for real; when a script's own output order is nondeterministic; when the change was bundled with other briefs in one large commit that cannot be isolated; and when it depends on untracked data.

One arm ran: haiku at `medium`, two reps per case, 20 attempts. No new opus arm ran. The reference is the landed change, which passes every landed test by construction and includes fixes the main thread made after the original subagent, so the bar is stricter than an opus subagent would face.

The metric was changed before any attempt ran. The landed test files carry many old tests that pass on the unchanged base, 347 of 365 in one case, so the plain landed-test share gave an attempt that changed nothing up to 0.95. The metric used instead is the effective pass ratio: over the landed test commands, the sum of (tests the attempt passed minus tests the unchanged base passed) divided by the sum of (tests the landed change passed minus tests the unchanged base passed), clipped to the range 0 to 1.

The audit rule was fixed before dispatch. Opus `researcher` subagents classified every failed landed test against the brief's wording as `not_fixed`, meaning it asserts a detail the brief did not fix, such as a name, a module, wording or a format; `genuine`; or `environment`. A `not_fixed` test counts as passed, and an ambiguous one is classed `genuine`.

The decision rule is the 5-point bar of ADR 0008 and ADR 0021 with the reference fixed at 1.0: (1) the lower end of the 95% t interval of the per-case mean effective pass ratio is at least 0.95; (2) no hard case fails landed tests in both reps because the attempt misread the brief.

| Scoring | Mean effective pass ratio | Lower end of the 95% interval | Rule 1 |
|---|---|---|---|
| Pre-registered, audit applied | 0.986 | 0.963 | met |
| One disputed audit call reversed | 0.963 | 0.909 | not met |
| No audit (raw) | 0.729 | 0.509 | not met |

Rule 2 holds: no hard case showed a misreading, and every failure in the hard band was classed `not_fixed`. The genuine misses were 5 tests in one attempt and 1 test in another, both in the mid band and both marked ambiguous by the auditor. Typical `not_fixed` failures were a whole landed test file importing a module the brief never named, a parameter named differently from the landed one where the brief named only the command-line flag, exact message wording, and the English case of a label.

One audit call is disputed. In one mid case the brief fixed where to split text, after sentence-ending punctuation followed by whitespace or at a newline, but not which side of the cut keeps the whitespace. Both attempts dropped it, and the landed test asserts that the pieces join back into the original text. The auditor classed it `not_fixed`, noting that "split into pieces" can be read as lossless. Reversing this one call fails rule 1.

Self-verification passed in 18 of 20 attempts. Both failures belong to one hard case, in which both attempts edited existing test files outside the brief's scope, 3 files in all. ADR 0021 recorded 2 of 54 haiku attempts doing the same.

One deviation came after the run and is recorded in the pre-registration. One mid case failed both attempts with `No module named pytest` at grading, from an error in building the case: its path rewrite mapped the wrong session scratchpad, so the brief still pointed at the original session's test script, which used `uv run`, and `uv run` synced the virtual environment back to the project's declared dependencies and removed the pytest that setup had installed. The replay shim also depended on pytest staying installed. The rewrite was corrected, the shim now reinstalls pytest when it is missing (with pytest removed from a kept workspace it ran 44 tests that passed and exited 0), the two original rows were moved to a quarantine file, and that case alone was run again. This was done after the other nine cases' results were known; the decision rule and the bar were not changed. The October sweep had likewise rerun one attempt after fixing a grader blind spot (ADR 0021, Context).

Haiku's subagent cost per case averaged 0.22 of what the original opus dispatch cost on the same briefs, $3.06 against $14.13 summed over the ten cases. The opus figure prices each request at list rates, with its 5-minute and 1-hour cache writes priced separately. The haiku subagents of the 20 attempts cost $6.11 at list price, and the dispatching main thread added $2.45.

## Decision

| Dispatch | Model | Effort | Condition |
|---|---|---|---|
| `implementer` | haiku | `medium`, from the definition | tests decide whether each changed behaviour is right, whether they are existing tests, acceptance cases listed in the brief or tests the subagent writes; the main thread checks that every file a haiku attempt changed lies within the brief's scope |
| `implementer` | opus | `medium`, from the definition | every other implementation, including any with a part judged only by looking or reading, such as how a user interface looks or an edit to documentation, even when tests decide the rest |
| `retriever` | haiku or opus, by [ADR 0022](0022-retriever-runs-on-haiku-when-the-brief-limits-it-to-local-files-or-one-named-page.md) | `medium`, from the definition | unchanged |
| `researcher` | opus | `high`, from the definition | unchanged |

The "Who" item of section 2 in the `en/` and `zh/` playbooks states the `implementer` routing. The agent definitions are unchanged.

## Consequences

The result depends on the audit. Without it the mean effective pass ratio is 0.729 with a lower end of 0.509, and the bar is cleared only because the auditor classed the failed tests that assert unfixed details as passed. The margin is one call: reversing the disputed call on where whitespace goes when text is split fails rule 1 at a lower end of 0.909. The one-case rerun came after the other nine cases' results were known, which weakens the result even though the rule and the bar stayed fixed.

The evidence covers only implementations in which tests decide correctness: every case was drawn from briefs that asked the subagent to write its own tests, and every score comes from landed tests. Nothing here measured an implementation judged by looking at a user interface or reading prose, so those stay on opus.

ADR 0021's safeguard rested on the reasoning that code and tests written from the same reading of a brief let a misreading pass both. This follow-up found no misreading in the hard band, and its two genuine misses were in the mid band on wording the auditor called ambiguous. The reference is the landed change rather than an opus subagent, so the run shows how close haiku comes to the change that was merged, not a paired difference against opus on these ten briefs.

Haiku sometimes edits files outside the brief's scope: 2 of 20 attempts here, both on one case, and 2 of 54 in the sweep behind ADR 0021, against none of 18 for opus there. The main thread therefore checks the file scope of every haiku attempt when it reviews the hand-back.

At list price the haiku subagent costs about 0.22 of the opus subagent on these briefs. Ten cases from four repositories leave the interval wide enough that one audit call decides the verdict; more cases, rather than more reps, would narrow it.

## Sources

| Source | What it supports |
|---|---|
| `eval/effort-sweep/README.md`, the section "Self-written tests follow-up (October 2026)" | The population, method, metric change, audit, results, deviation and cost |
| `eval/effort-sweep/README.md`, the section "Cases" | The qualification rules |
| `eval/effort-sweep/selftest.py` | The leak, oracle, null and broken checks every case passed |
| A private data directory | The cases, the pre-registration with its deviation log, the audit packets and verdicts, the raw transcripts and the scoring script; the figures recompute only from it |
| [ADR 0021](0021-implementer-runs-on-haiku-when-tests-decide-every-change.md) | The condition this decision amends, the October sweep's figures, and the 2 of 54 haiku attempts outside scope |
| [ADR 0008](0008-subagent-effort-per-kind-of-dispatch.md) | The 5-point bar and the effort per definition |
| `en/orchestrator-playbook.md`, section 2 | The routing of `implementer` to haiku and the main thread's file-scope check |
| `en/agents/implementer.md`, frontmatter | `implementer` sets effort `medium` and no model |
| platform.claude.com/docs/en/about-claude/pricing, retrieved 8 October 2026 | Opus 5.5 and Haiku 5.5 list prices, with Haiku billing a whole request at the higher row once its prompt exceeds 100,000 tokens |
