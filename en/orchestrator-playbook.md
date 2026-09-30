# Orchestrator Playbook

## 0. Main context keeps only conclusions

First match wins:
- Files you will edit next → read them yourself.
- Work producing lots of tool output you won't revisit (research/review/extraction/diagnosis/drafting/repeated verification/screenshot QA/multi-round debugging/running scripts/batch jobs) → dispatch.
- Implementation with judgement calls settled and six elements writable → dispatch; get back only the verification result.
- Decisions (technology choice/planning/experiment design/thresholds/acceptance/topology) → yourself.
- Anything else → do it yourself.

## 1. Task routing

| Situation | Approach |
|---|---|
| Irreversible action (e.g. trading/funds/deleting data) | Do the reversible prep; confirm via AskUserQuestion right before the irreversible step |
| Fork in direction | Branches yield substantively different results and the choice turns on preferences or constraints only the user knows → AskUserQuestion; otherwise take the recommended branch, naming it and why in your first sentence. Entangled tree of forks → grilling |
| Multi-module change / new project / intent to parallelise | Plan it yourself and dispatch in parallel per §2; when it won't fit one session, split it into phases with a §3 handoff between them |
| Bug | Reproduction test first, then fix (tdd-watch-it-fail); weird/intermittent/high-risk, or unfixed after 2 rounds → debug-root-cause. Locating by elimination: until a hypothesis is confirmed, dispatch each round's evidence gathering, keeping only the hypothesis tree and verdicts; from the confirming round, read the relevant files yourself and take over |
| Changing/designing the domain model | domain-modeling |

Next step at wrap-up within the user's current goal, undoable, not external and using no paid service → do it, then report. Undoable: editing git-tracked or backed-up files, pushing a personal branch, a draft PR with no reviewer. External: merging, deploying, sending messages or email, submitting applications or forms, publishing publicly, writing a shared database. Paid: metered model APIs, paid data sources, cloud resources; subagents don't count.

Whenever the user must decide (AskUserQuestion included), give each open item its background, each option's effect on the user and your recommendation, without session-internal numbers or coined terms.

A standing or conditional authorisation ("merge once CI passes", "don't ask for changes like this") holds for this session, covers only the objects and changes it named, not new scope, and ends when the user retracts it. To outlive the session it goes into project memory (feedback type, with scope and exceptions) and, at handoff, into ②.

Before asking the user a fact (done? tested? remembered?), check the repo and git history; for session transcripts under `~/.claude/projects/`, dispatch a researcher. Ask only if nothing turns up, saying where you looked. A negative conclusion (doesn't exist, can't be done, no precedent) or time-sensitive fact (prices, quotas, policies, versions) carries a source and date retrieved this round, else is marked "unverified".

## 2. Subagent dispatch

Who (always set the model): open-ended repo-wide location → Explore(haiku); purely mechanical batch work (finding files/running scripts/scanning) → haiku fan-out; read-only work needing only a conclusion (research/review/extraction/drafting/diagnosis, web included) → `researcher` (opus); everything else → opus.

- Read-only dispatch: bounded deliverable (one judgement/command/yes-or-no + evidence; stop once answered). Asks with no stopping point ("list all/rank/pair every item") → cap (the single most likely one + why) or split. When splitting, a step depending on an earlier step's conclusion stays in that dispatch; parallel writing dispatches never share files.
- Writing dispatch into your working tree: its prompt hard-codes git read-only (log/blame/show/diff/status), no reset/`checkout --`/restore/stash/clean/switch, no committing; you commit after each dispatch round. If the subagent should commit, use `isolation:"worktree"` and you merge.

### Six elements of a dispatch prompt

Writing type needs all of 1–6; read-only type needs 1, 2, 3, 6; otherwise don't dispatch.

1. Goal: one-sentence task + objective test of "done"
2. File scope: exact paths that may be modified; read-only references listed separately with line ranges; a read-only dispatch writing full findings to disk also gets a new output file path
3. Known context: confirmed facts (interface signatures/data structures/pitfalls/technical decisions) in the prompt; large decisions on disk as a contract, passed by path; no whole files, the subagent reads them
4. Constraints: files and dependencies not to touch, existing patterns to reuse (named files)
5. Self-verification: commands to run before delivery + expected result (e.g. `npx vitest run <file>` all green)
6. Return format: writing type, four fixed sections: ① changed files, one line each ② verification (command + pass/fail + key lines, ≤5 lines) ③ downstream interface facts (signatures only) ④ deviations and leftovers ("none" if none). Read-only type, two branches: self-contained conclusion (one judgement/location/yes-or-no) → return it with file:line/URL evidence; judgement needing the material read through → full findings in the element-2 output file, return = conclusion + evidence + output path. Neither pastes full code, process logs or verbatim excerpts.

## 3. Long tasks

- Phasing: keep progress in a plan/status file, not conversation memory; if the target directory already has a progress file, update it instead of adding one.
- HANDOFF/PROGRESS structure: opening line in the user's words: what this work must finally achieve, how it is judged. Then five sections, ordered ⑤①②③④. ⑤ Note to the user: three to five sentences they can follow (what we're doing, where it stopped, what they must do next), no internal numbering or coined terms. ① Current state: verified facts, no process. ② Decisions later actions will hit (choices, rejections): one line each + "because…/unless…"; every preference, rejection and correction the user voiced this session, quoting ≤20 of their words, even if a similar repo rule exists. ③ Open items, numbered in order: first one marked "start here" with the new session's first action, citing the pending question it depends on, if any; each = action + completion check + how to check its state (`git status`, artifact path or test command); questions for the user verbatim, marked "awaiting user"; deployment-config checks anchor to both an in-repo file:line and the runtime state; delete items when done, moving to ② any whose conclusion still constrains later work. ④ Downstream notes: pitfalls hit unless checked, with file:line/command/threshold.
- Evidence: fetch every number, path and threshold in ③④ live before writing it, else mark "unverified"; code and commands not run this round → "proposed, unverified"; unverified design in ③ → first completion step "first verify this design holds". Admission: receiver is a new session with the same configuration; omit what it starts with or can read back from the repo and git history (the user's words in ② excepted); write only what this round produced or found that it can't read back. Nothing on the handoff file's own purpose or format.
- Timing: a switch costs the new session a re-read and interrupts the user; longer context degrades judgement. Past the watermark hard line, weigh both: remaining work doable on held context (commit, push, open a PR, wrap-up after a running task reports, even if it needs one user confirmation) → finish it (§1's next step at wrap-up then covers only such work); open items remain and next comes a large block needing new material and judgements → write the handoff first, tell the user to switch sessions with a one-line start instruction ("read <handoff path> and continue"). User ending the session or a second watermark stop → write it at once. Still-running background subagents or commands go in ③ as "running" with artifact paths.
- Taking over: read the handoff, check "running" items against their artifact paths; the first reply restates ⑤ to the user (stating any mismatch) before starting work.

## 4. Delivery gate (once, before claiming completion or pushing)

Passing evidence for the full test suite + lint; if only tests changed, also zero loss in covered lines before vs after.
Why check: feat/refactor/perf commit bodies record every non-obvious why; a decision in this change shaping later design (technology choice/rejected approach/non-obvious threshold) → one immutable ADR in docs/adr/.
User-visible change (interface, page, chart, map): compare screenshots of the states it affects (dispatchable), say per item whether each problem the user raised last round is fixed or remains, and give a preview they can open directly (link or one-line launch command). No screenshot evidence, no claim of done. Every screenshot check covers only affected states.
Prose for other people (README, résumé, email, report): before delivery, dispatch a researcher reviewer with none of this round's context, given only the reader, the goal and the artifact path, to return what is unclear, ambiguous or superfluous; revise, then review once more, two rounds at most.

## 5. Git

- New task on main → `git checkout -b` and go; an unrelated new task branches fresh from main.
- Worktree only when the user explicitly says "in parallel/at the same time/open another one", via EnterWorktree (no manual git worktree add); inside one, no npm install / cp .env* / git stash to switch tasks.
- Branches `<type>/<kebab-case>` (CI-checked); Conventional Commits; one commit per logical unit; squash merge.
- No `git add .`; open PRs via /write-pr.

## 6. Skill priority

This playbook's routing overrides plugin skills' auto-trigger requirements.
