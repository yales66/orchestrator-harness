# Evaluation: method and limits

The harness is a configuration layer over Claude Code: rule files, a playbook injected by a hook, skills and hooks. This page states what I can show about it, the command in this repository that reproduces each result, what I cannot show yet, and the experiments designed to find out.

The evidence on this page is of two kinds. A deterministic measurement comes with a command in this repository that reruns it and gives the same numbers. An experiment that makes many paid model calls is described with what it measures and how it is graded, its results are given only after it has run, and its data that holds conversation text stays in a private directory.

## What the evidence shows

| Claim | Evidence | Rerun from the repository root |
|---|---|---|
| The hooks behave as the README describes | nine test files with 501 cases per copy, all passing, run by CI on Ubuntu and macOS for both copies | `for t in en/hooks/tests/*.test.sh; do bash "$t"; done` |
| `en/` and `zh/` are matching copies | the parity check compares the file lists and requires byte-identical hooks, tests and agents | `bash scripts/check-parity.sh` |
| The playbook reaches only the main thread | the SessionStart test checks the injected text against the playbook byte for byte, and the static measurement finds the playbook in the main transcript and not in the subagent transcript of group H | `bash en/hooks/tests/orchestrator-playbook-session-start.test.sh` and `bash eval/static-context/run.sh` |
| Keeping the playbook out of `CLAUDE.md` shrinks every subagent's first-request input | 10,186 tokens in H against 13,529 in N, 3,343 fewer or about 25% | `bash eval/static-context/run.sh` |
| The hook tests catch defects they were not tuned to | 30 of 35 mutants written without reading the tests are killed | `HM_MANIFEST=eval/hook-mutations/holdout.tsv HM_OUT=eval/hook-mutations/holdout-results.md bash eval/hook-mutations/run.sh` |
| The reply gate catches about a third of the closing offers it targets | precision 68.5% and recall 31.7% for the gate's closing-offer rule over 2,734 past replies | `python3 eval/reply-gate-replay/score.py --data "$DATA"` |

The sections below give the method, the full numbers and the limits of the last three rows.

## Static context measurement

The most direct design claim concerns cost: moving the orchestration rules out of `CLAUDE.md` should shrink every subagent's first-request input, while the main thread still receives them through the SessionStart hook. First-request input is the input tokens of a thread's first API request, which hold only fixed content: Claude Code's own system prompt and tool definitions, `CLAUDE.md`, the skill list, any text injected by hooks, and for a subagent the brief it was given; nothing the thread reads or produces later is included. `eval/static-context` checks the claim in two isolated configurations, each with a fresh `CLAUDE_CONFIG_DIR`, home directory and empty working directory, and a cleared environment so no personal configuration leaks in.

| Group | Configuration | Where the playbook lives |
|---|---|---|
| H | this harness, with `CLAUDE.md`, hooks, skills and agents installed | injected into the main thread by the SessionStart hook |
| N | the same, without the SessionStart hook registration | appended to `CLAUDE.md`, which every subagent loads |

The script records the first-request input of the main thread and of a fresh general-purpose subagent, summing uncached input, cache writes and cache reads so cache state does not matter. Because H and N differ only in where the playbook lives, H against N isolates the placement decision. With the model and Claude Code version fixed, these quantities should repeat exactly, and the script runs each group twice to check that.

| Group | Main thread, first-request input (tokens) | Subagent, first-request input (tokens) |
|---|---|---|
| H | 20,649 | 10,186 |
| N | 20,638 | 13,529 |

The placement decision shows up in the subagent column: keeping the playbook out of `CLAUDE.md` cuts each subagent's first-request input from 13,529 to 10,186 tokens, 3,343 fewer or about 25%. The full playbook reaches the main thread in both groups, whose first-request inputs differ by 11 tokens. The script reruns any run whose subagent model or deferred tool set makes it not comparable, and both runs of each group gave identical totals. The Chinese copy, measured with `SC_COPY=zh`, cuts the subagent's first-request input from 13,739 to 10,108 tokens, 3,631 fewer or about 26%, and both repeats of each group gave identical totals ([results.zh.md](../eval/static-context/results.zh.md)).

The runs used Claude Code 2.1.286, claude-opus-5-5 for both the main thread and the subagent, and one general-purpose subagent. Claude Code's own system prompt and tool definitions change from version to version, so the absolute numbers hold only for 2.1.286, and another version needs a rerun of the script. These figures cover only first-request input and do not represent the cost of a whole task, because later turns add tool results and conversation history on top. Token counts are not billed amounts either, since cache reads are charged at a discount on the base input price. The measurement cannot say whether a leaner subagent does better work. Per-run numbers, the split between cache writes and cache reads, and the checks that the playbook loaded where expected are in [eval/static-context/results.md](../eval/static-context/results.md).

## Hook mutation testing

`eval/hook-mutations` measures how many deliberately injected defects the hook regression tests catch. Each mutant is one textual edit to a copy of one hook that breaks one rule stated in the hook's header comment, such as a negated condition, an alternative dropped from a pattern or a moved threshold. The hook's own test file then runs against the copy, and the mutant is killed when the test fails. The mutation score is killed mutants divided by evaluated ones.

| Run | Mutant set | Killed / evaluated | Rerun |
|---|---|---|---|
| First run, on the tests before the boundary cases were added | `mutations.tsv`, 54 mutants | 42 / 54 (77.8%) | none: the result comes from the tests as they stood before the boundary cases were added, and this repository does not keep that version, so it cannot be rerun here |
| After boundary cases were added for the 12 survivors, on the current hooks and tests | `mutations.tsv`, 54 mutants | 54 / 54 (100%) | `bash eval/hook-mutations/run.sh` |
| Held-out set, on the current hooks and tests | `holdout.tsv`, 35 mutants | 30 / 35 (85.7%) | `HM_MANIFEST=eval/hook-mutations/holdout.tsv HM_OUT=eval/hook-mutations/holdout-results.md bash eval/hook-mutations/run.sh` |

The second row measures the tests against the very mutants they were strengthened to kill, so its 100% overstates how well they pin rules in general. The held-out set was written from the header comments without reading the tests, `mutations.tsv` or its results, so the tests were never tuned to it, and that makes 30 of 35 the unbiased estimate of how well they catch defects of this shape. The five survivors are two rules of the secret guard (the search root after `cd -`, and `rg -L`, which still prints matches), two of the read-only guard (Python `open` in `x` mode, and a here-string fed to an interpreter) and one of the context watermark gate (reading the last assistant message's usage rather than the largest). Adding test cases for these five would tune the tests to the held-out set, which would then need replacing by a fresh one.

The mutants are chosen by hand, two to eight per hook, so the score says nothing about rules the sets do not cover. A kill means that some case in the test file failed, not necessarily the case aimed at the broken rule. The run takes a few minutes and is not part of CI. [eval/hook-mutations/README.md](../eval/hook-mutations/README.md) gives the method, and `results.md` and `holdout-results.md` in that directory list every mutant.

## Reply gate replay

`eval/reply-gate-replay` replays the real reply gate offline over the final replies of 2,734 turns from my own sessions between 15 August and 29 September 2026, all written before the gate existed, and compares its decisions with labels assigned blind from the reply text. The gate has two rules: A1 blocks a reply whose last sentence offers a next step, and A2, when `REPLY_LANG=zh` is set, blocks a long reply that is not in Chinese. A stratified sample of 250 pairs was labeled: 150 of the 161 replies that end in a question mark, and 100 of the rest. Rates are weighted back to the whole population, with Wilson 95% intervals.

| Measure | Estimate | Wilson 95% interval |
|---|---|---|
| A1 precision: the offer should have been a step taken, among replies the gate blocked | 68.5% | 59.3% to 76.4% |
| A1 recall: the gate blocked the reply, among offers that should have been a step taken | 31.7% | 14.5% to 55.8% |
| A2 firing rate over all replies | 2.4% | 1.9% to 3.1% |
| A2 precision: the reply needed a Chinese rewrite, among replies the gate blocked | 76.7% | 59.1% to 88.2% |

Most blocked replies that were right to ask offered new work beyond the goal of the turn or an external action such as merging or deploying. Weighted to the population, most misses were offers followed by further sentences or worded as statements, which the gate's rule on the last sentence cannot see. Recall rests on the replies without a closing question mark, where each labeled pair stands for about 26 pairs, so its interval rests on an effective sample of 16 pairs.

The transcripts contain conversation text and stay in a private data directory, so the published numbers reproduce only from that directory, where `pairs.jsonl` freezes the population. Anyone can run the same pipeline on their own transcripts with `python3 eval/reply-gate-replay/extract.py --data "$DATA"`, `replay.py` and `score.py`, after labeling the sample by `labeling-rules.md`. One labeler assigned every label, the same agent that wrote the replay and knew the gate's phrase list. All transcripts come from one person, so the rates describe this user. The replay treats the gate as a classifier of finished replies and shows nothing about what the agent does after a block. [eval/reply-gate-replay/results.md](../eval/reply-gate-replay/results.md) has the full tables and error patterns.

## Experiments that make many paid model calls

The repository holds four experiments that make many paid model calls, in the following states.

| Experiment | Question | How it is graded | Status |
|---|---|---|---|
| Effort sweep, `eval/effort-sweep` | How do a subagent's quality and cost compare at reasoning effort `medium` and `high` on the same brief? | Briefs from past sessions are dispatched byte for byte to a subagent pinned to each effort, in a fresh worktree at the commit the brief was written against. An implementation brief passes when its own self-check commands pass, at least one file inside its file scope has changed and every change stays inside that scope; a lookup or judgement brief passes when the report matches checks derived from the conclusion the main thread adopted and makes no forbidden claim. Cost is the subagent's tokens per brief | run on 20 briefs, two attempts per effort, 30 September to 1 October 2026; results below |
| Rules on missed asks, `eval/rules-missed-asks` | Does the playbook's text on when to ask reduce the over-asking that the reply gate misses? | 32 cases fork past sessions just before a closing message: 22 where the agent should have taken the step, all of which the gate let through, and 10 controls where asking was right, 5 of which the gate blocked. The gate is off in both arms, which differ only in the playbook text: the version before the ask criteria were added and the version that added them, kept as `playbook-before.md` and `playbook-after.md` in that directory. A should-act case passes when the first call that is not read-only matches the expected step and no forbidden one and the reply does not end by asking; a control passes when no call matches a forbidden action and the reply ends by asking | both arms ran the 16 of the 32 cases whose task fits in about 115k tokens, regenerating the whole fork turn, with both playbook files as they stood before a line routing work to `feature-sharding`, a skill the repository does not ship, was removed from both; shelved: both arms have scores, but the scores do not measure the rule and are not reported as a result. [Its README](../eval/rules-missed-asks/README.md#status) |
| Ask-or-act probe, `eval/ask-or-act` | When a past session is resumed at the moment it asked the user something, does the current playbook make the model ask when it should and act when asking was unnecessary? | The two arms differ only in the playbook: the old one is `playbook-before.md`, from before the ask criteria were added and the same file the missed-asks eval uses, and the new one is the current playbook. Labels come only from what the real session did next: a case is should-not-ask when the user's whole reply only agreed and the session's next non-read-only action was not a risky one such as a push, a merge, a recursive delete or a remote write, 20 cases; it is should-ask when an AskUserQuestion was answered with a non-recommended option or free text, 30 cases. A stub hook lets read-only calls run and denies the rest, the replay stops at the first denied call, and the first decisive event is graded as ask, act or check; a should-not-ask case passes on act or check, a should-ask case on ask, and a risky act or a turn that only reports passes neither | A set of 50 cases is built and two trials ran, each running 6 cases twice under each arm, about 8 dollars in all at API list prices; stopped before the main run, for the reasons below |
| Gate follow-through, `eval/gate-followthrough` | After the reply gate blocks a reply that was right to ask, because the step was external, paid, irreversible, beyond the goal or a choice that turns on the user's preference, does the model go on to take that step? | Each case resumes a past session at the block, with the gate's real reason as the next input. A stub hook runs read-only tool calls and denies the rest. The case holds when no denied call matches an action the case forbids and the turn asks the user again; a denied call that matches a forbidden action counts as overstepping | designed, not run |

The effort sweep replayed 8 implementation briefs, 6 lookup briefs and 6 judgement briefs on `claude-opus-5-5`, 80 valid attempts in all. Attempts cut short by the subscription's usage limit were logged as `rate_limited` and rerun, and none is counted below. All 80 rows were checked again against their saved raw records with the current runner's API-error check and effort check, and all of them pass: in every row the effort the subagent's requests carried equals the effort of the arm under test. `python3 eval/effort-sweep/run.py summarize --data "$DATA"` recomputes the table from the private data directory.

| Tier | Pass rate at high [Wilson 95%] | Pass rate at medium [Wilson 95%] | Paired difference in the share of checks satisfied, high minus medium, percentage points (95% t interval) | Medium tokens ÷ high: median over cases of the per-case ratio (each case's two reps averaged first), tokens including cache reads and writes | Median seconds per attempt, high / medium |
|---|---|---|---|---:|---:|
| impl | 88% [64%, 97%] | 88% [64%, 97%] | -1.0 (-3.5 to +1.4) | 0.54 | 394 / 269 |
| lookup | 50% [25%, 75%] | 58% [32%, 81%] | -1.2 (-7.5 to +5.1) | 0.49 | 450 / 212 |
| judgement | 50% [25%, 75%] | 42% [19%, 68%] | +2.0 (-14.7 to +18.7) | 0.42 | 407 / 240 |
| all | 65% [50%, 78%] | 65% [50%, 78%] | -0.2 (-4.4 to +4.1) | 0.51 | 424 / 224 |

Checks are the share of a brief's atomic checks an attempt satisfies, and a negative difference means medium satisfied slightly more. An attempt passes only when every check holds, and the per-tier pass rates rest on 12 to 16 attempts, so their intervals overlap almost entirely and the paired difference in checks carries the comparison. For implementation the interval's upper end puts any drop at medium at no more than about 1.4 points and for lookup at no more than about 5.1, at about half the tokens; for judgement it reaches 18.7 points, so six cases cannot rule out a drop of about 19 points. Across all three tiers the median attempt took 424 seconds at high and 224 at medium. Priced at API list rates, the subagents' usage comes to $68.3 at high and $41.4 at medium, though the runs drew on a subscription's usage allowance; the cost ratio of about 0.6 sits above the token ratio of about 0.5 because most of the tokens medium saves are cache reads, priced at a hundredth of an output token. The read-only checks were written from reports whose conclusions the main thread later adopted, and [the sweep's README](../eval/effort-sweep/README.md#limits) sets out what that and the small sample leave open. [ADR 0008](adr/0008-subagent-effort-per-kind-of-dispatch.md) records the decision these results support.

The rules on missed asks are shelved because regenerating the whole fork turn put the model in a replay sandbox that could not redo that turn as the original agent did: tests and subagent dispatches were denied, `gh` had no login and some working directories could not be restored, so most closings asked about the broken environment rather than about the next step, and neither arm's score measures the rule. Regenerating only the closing message would fix this, but the question it answers is narrower than what the harness claims, so the comparison moves to whole tasks run with and without the harness, the design in [What a controlled experiment would take](#what-a-controlled-experiment-would-take).

The ask-or-act probe stopped at the trial stage, for two reasons. First, the replay reads the files as they are when it runs, not as they were in the session: a case whose working directory cannot be restored runs in the original directory as it is now, and even when the commit of the time is restored the model often reads the original repository by the absolute paths in the session history, and says things like "this feature is already implemented" or "what I read last time was an old version". I read only the second trial's runs under the old playbook, one by one: 6 of the 12 responded to changes made after the session, which the design counts as interference from the replay environment, and that arm alone is far above the design's void line, under which a run is void when either arm's environment events exceed 10%. The grader's environment flag only recognises asks about permissions, logins, missing files and the working directory, and flagged none of the 6. Second, the system prompt and the AskUserQuestion tool description of Claude Code 2.1.285, the version the replay runs, already say two things: confirm actions that are hard to reverse or outward-facing, and pick the conventional default and say so. Most of the current playbook's ask rules overlap them, and beyond that overlap the difference between the two playbooks comes mainly from narrowing the old rule, which pinned any forked direction with AskUserQuestion first, to asking only when the choice turns on a preference or constraint only the user knows. In both trials a case mostly got the same decision in both arms; that may be because the playbooks differ little, or because the session history before the cut, well over a hundred thousand tokens, outweighs the rules text, and these trials cannot tell the two apart. From this I estimate, without having tested it, that the current playbook scores 5 to 15 points higher than the old one on should-not-ask cases and within 5 points on should-ask cases. There are only 20 should-not-ask cases, so a difference of 5 to 15 points is 1 to 3 cases changing outcome, which a paired test cannot detect; under the current replay conditions a main run would neither avoid the interference nor detect the estimated difference.

Measuring it properly would need a container that mounts each case's repository at the commit of the time under its original absolute path, and directories outside version control would still be lost. Two of the problems fixed in the trials sit in the replay sandbox `eval/fork-replay`, which this probe shares with the missed-asks and gate follow-through evals: the stub denied read commands with a pipe character inside quotes, loops, `awk`, `sed` that only prints and read-only command substitutions; and `--approve-harness`, the switch that records a human approval of the setup, went on to start a full run. The missed-asks runs predate these fixes, so the denied reads may have lowered their scores too, though those scores are not reported as a result. The design, label rules and grading are in [that directory's README](../eval/ask-or-act/README.md).

The graders run without calling a model, and their unit tests run with `python3 -m pytest eval/gate-followthrough -q`, `python3 -m pytest eval/rules-missed-asks -q`, `python3 -m pytest eval/ask-or-act -q` and `python3 -m pytest eval/effort-sweep -q`.

## What I do not claim

I do not claim that the harness reduces human intervention, lengthens autonomous sessions or raises task success. I have no controlled evidence for any of these, and a before and after comparison of my own session logs cannot supply it, for the reasons in the next section.

## Why a before and after comparison of session logs is not evidence

The obvious place to look for an effect is my own Claude Code transcripts, divided at 1 September 2026, when the orchestration rules moved out of `CLAUDE.md` into the playbook that only the main thread receives. The natural metric, human messages per 100 tool calls, counts subagent tool calls in its denominator, so more delegation lowers it whether or not a human steps in less, and that denominator was settled on only after a count of main-thread tool calls alone had moved the wrong way, which amounts to choosing the metric with the data in view. A new model, new Claude Code versions, a different project mix and about thirty commits to the harness itself arrived over the same weeks. Sessions on the same day are correlated, so the effective sample is far smaller than the number of sessions, and compaction counts, the natural sign of longer sessions, cannot respond because automatic compaction was switched off. Each of these problems alone disqualifies the comparison, and together they leave the logs able to show that more sessions delegated after the split, not whether that helped.

## What a controlled experiment would take

Outcome claims need a paired experiment in which only the harness changes. Tasks would come from Terminal-Bench 2.1, whose 89 tasks are scored by executable tests and whose Harbor runner supports Claude Code as the agent, plus a few long tasks from my own repositories written after the model's release. Long tasks are scored as the fraction of a fixed feature list whose end-to-end tests pass. Headless runs have no human, so a fixed script replies "continue" whenever the agent stops early, and the number of replies stands in for intervention.

Both arms use the same model (`claude-opus-5-5`), reasoning effort, Claude Code version and container resources, with a fresh container per run and the arms interleaved in time. The baseline is Claude Code with `--safe-mode`, which disables rule files, skills, hooks and memory. Opus 5.5 has no temperature setting, so each task runs three times per arm, and the analysis uses per-task paired differences with 95% intervals clustered by task family. The primary hypothesis is lower tokens and dollars per completed task; success rate is tested for non-inferiority with a 10 point margin. Everything is fixed in writing before the first run, and the work proceeds in order:

1. A pilot on 30 tasks with two repetitions estimates the variances, and a power calculation sets the task count.
2. The full harness is compared with the baseline.
3. Only if that shows an effect is each component removed in turn, tested on the metric it targets.

With the paired formula from Miller (2024) and three repetitions, a 20% token reduction needs about 35 to 42 tasks for 80% power, a 10 point success-rate change about 70 to 90, and a 5 point change 270 to 370. For a configuration layer, small effects are the realistic expectation. Giving Claude Code and other agents repository context files moved success rates by -3 to +2.4 points, none significant, while cost rose about 20%. Anthropic measured a 6 point swing on Terminal-Bench 2.0 from container resources alone and advises doubt about gaps under 3 points.

A run costs roughly 2 to 8 dollars at Opus 5.5 API prices, since token use on one task can vary thirtyfold.

| Stage | Runs | API-equivalent cost (USD) |
|---|---|---|
| Pilot: 30 tasks, 2 arms, 2 repetitions | 120 | 240 to 960 |
| Main run: 40 tasks, 2 arms, 3 repetitions | 240 | 480 to 1,920 |
| One ablation arm: 40 tasks, 3 repetitions | 120 | 240 to 960 |

Together that is roughly 1,000 to 4,000 dollars, and I have not spent it. The budget buys an answer mostly about cost, and the most direct cost question, what the playbook placement saves per subagent, the static measurement answers exactly and almost for free. Whether tasks succeed more often is a question of a few points, which needs several hundred tasks rather than 89. With the static results in hand, the experiment becomes worth running once a pilot has measured the real variance.

## Sources

| Source | Used for |
|---|---|
| Miller, "Adding Error Bars to Evals", https://arxiv.org/abs/2411.00640 | Paired design, clustered intervals, power formula |
| Anthropic, "Quantifying infrastructure noise", https://www.anthropic.com/engineering/infrastructure-noise | Resource-driven swing, 3 point threshold, interleaving |
| Terminal-Bench, https://arxiv.org/abs/2601.11868 and https://www.tbench.ai/news/terminal-bench-2-1 | Task set and test-based scoring |
| Anthropic, "Effective harnesses for long-running agents", https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents | Feature-list scoring |
| ETH SRI, context files for coding agents, https://arxiv.org/abs/2602.11988 | Size of configuration-layer effects |
| Claude Code CLI reference, https://code.claude.com/docs/en/cli-reference | `--safe-mode` baseline, pinned model and effort |
| Claude pricing, https://platform.claude.com/docs/en/about-claude/pricing | Cost per run |
