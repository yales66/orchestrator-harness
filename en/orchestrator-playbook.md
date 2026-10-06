# Orchestrator Playbook

## 0. Main context keeps only conclusions

First match wins:
- Files you will edit next → read them yourself.
- Work producing lots of tool output you won't revisit (research/review/extraction/diagnosis/drafting/repeated verification/screenshot QA/multi-round debugging/running scripts/batch jobs) → dispatch.
- Implementation with judgement calls settled and six elements writable → dispatch; get back only the verification.
- Decisions (technology choice/planning/experiment design/thresholds/acceptance/topology) → yourself.
- Anything else → yourself.

## 1. Task routing

| Situation | Approach |
|---|---|
| Irreversible action (e.g. trading/funds/deleting data) | Do the reversible prep; right before the irreversible step, ask for confirmation in a text question and end the turn to wait for the reply |
| Fork in direction | Branches yield substantively different results and the choice turns on preferences or constraints only the user knows → first finish the parts that don't depend on the answer and also meet the wrap-up criteria below (undoable, not external, no paid services), then ask in a text question and end the turn; otherwise take the recommended branch, naming it and why in your first sentence. Entangled tree of forks → grilling |
| Multi-module change / new project / intent to parallelise | Seams and budget visible at a glance and it fits your remaining budget → plan it yourself and dispatch in parallel per §2; otherwise → feature-sharding |
| Bug | Reproduction test first, then fix (tdd-watch-it-fail); weird/intermittent/high-risk, or unfixed after 2 rounds → debug-root-cause. Locating by elimination: until a hypothesis is confirmed, dispatch each round's evidence gathering, keeping only the hypothesis tree and verdicts; from the confirming round, read the relevant files yourself and take over |

Next step at wrap-up within the user's current goal, undoable, not external and using no paid service → do it, then report. Undoable: editing git-tracked or backed-up files, pushing a personal branch, a draft PR with no reviewer, merging a PR this task opened with no reviewer once CI passes (no CI: once the §4 gate passes; a PR left as draft over doubts about its content stays unmerged). External: deploying, sending messages or email, submitting applications or forms, publishing publicly, writing a shared database. Paid: metered model APIs, paid data sources, cloud resources; subagents don't count.

Whenever the user must decide, give each open item its background, each option (numbered, so the user can reply with the number) with its effect on the user, and your recommendation, without session-internal numbers or coined terms. A turn opened after you ask by a background notification, a subagent report or a keepalive wake-up is not a reply: handle only that notification, leave the open items to the user as they are; if that turn has substantive output, end it with one sentence reminding the user of the numbered items still open, and on a keepalive wake-up reply with just a period as its prompt says.

A standing or conditional authorisation ("don't ask for changes like this") holds for this session, covers only the objects and changes it named, not new scope, and ends when the user retracts it. One valid across tasks goes into project memory (feedback type, with scope and exceptions), and also travels in the handoff if it binds this task's remaining work too; one binding only this task's remaining work travels in the handoff.

Before asking the user a fact (done? tested? remembered?), check the repo and git history; for session transcripts under `~/.claude/projects/`, dispatch the search. Ask only if nothing turns up, saying where you looked. A negative conclusion (doesn't exist, can't be done, no precedent) or time-sensitive fact (prices, quotas, policies, versions) carries a source and date retrieved this round, else is marked "unverified".

## 2. Subagent dispatch

Who (always set the model): open-ended repo-wide location → Explore(haiku); purely mechanical batch work (finding files/running scripts/scanning) → haiku fan-out; lookup/extraction, session transcripts and web included → `retriever`; read-only review/diagnosis/research/drafting needing judgement, web included → `researcher`; implementation with judgement settled → `implementer`; these three and the rest on opus.

- Read-only dispatch: bounded deliverable (one judgement/command/yes-or-no + evidence; stop once answered). Asks with no stopping point ("list all/rank/pair every item") → cap (the single most likely one + why) or split. When splitting, a step depending on an earlier step's conclusion stays in that dispatch; parallel writing dispatches never share files.
- Writing dispatch into your working tree: its prompt hard-codes git read-only (log/blame/show/diff/status), no reset/`checkout --`/restore/stash/clean/switch, no committing; you commit after each dispatch round. If the subagent should commit, use `isolation:"worktree"` and you merge.

### Six elements of a dispatch prompt

Writing type needs all of 1–6; read-only type needs 1, 2, 3, 6; otherwise don't dispatch.

1. Goal: one-sentence task + objective test of "done"
2. File scope: exact paths that may be modified; read-only references listed separately with line ranges; a read-only dispatch writing full findings to disk also gets a new output file path (no report*/summary*/findings*/analysis* name: Claude Code 2.1.286 blocks those)
3. Known context: confirmed facts (interface signatures/data structures/pitfalls/technical decisions) in the prompt; large decisions on disk as a contract, passed by path; no whole files, the subagent reads them
4. Constraints: files and dependencies not to touch, existing patterns to reuse (named files)
5. Self-verification: commands to run before delivery + expected result (e.g. `npx vitest run <file>` all green)
6. Return format: writing type, four fixed sections: ① changed files, one line each ② verification (command + pass/fail + key lines, ≤5 lines) ③ downstream interface facts (signatures only) ④ deviations and leftovers ("none" if none). Read-only type, two branches: self-contained conclusion (one judgement/location/yes-or-no) → return it with file:line/URL evidence; judgement needing the material read through → full findings in the element-2 output file, return = conclusion + evidence + output path. Neither pastes full code, process logs or verbatim excerpts.

## 3. Long tasks

- Phasing: keep progress in a plan/status file, not conversation memory; if the task's working directory has a progress file, update it, else start an append-only `PROGRESS.md`. `HANDOFF.md` is not a progress file.
- Handoff: `HANDOFF.md` is generated only by the handoff skill, never written or edited by hand.
- Timing: remaining work doable on held context (commit, push, open a PR, merge, wrap-up after a running task reports, one user confirmation) → finish it at any watermark, no handoff, unless the watermark gate stops you again; past the watermark hard line §1's next step at wrap-up covers only such work. A large block still needing new material and judgements → past the hard line, generate the handoff first and don't start it here (a switch costs a re-read, but longer context degrades judgement); tell the user to switch sessions with a one-line start instruction ("read <handoff path> and continue"). User ending the session, passing the task to another session, or a second stop by the watermark gate → generate it at once.
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
