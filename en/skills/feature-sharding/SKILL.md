---
name: feature-sharding
description: |
  Unified execution planner for parallel multi-module work. Routes by budget first (phase 0): fits the main thread's remaining
  budget → just do it; otherwise strip phantom work that is already implemented, survey seams and unknowns → bin by
  workload (S/M/L) → all S bins → dispatch subagents in waves in this session; beyond the orchestration budget or needing
  a human ruling midway → produce a multi-session "session pack" and merge protocol; this session (first getting the user's
  approval of the launch checklist when the user must settle credentials or a paid allowance) launches each track as a
  claude --bg background session and acts as the parent session, coordinating until everything is merged.
  Triggers: multi-module change / new build from scratch / migration / cross-component refactor; the user says "split /
  parallelise / shard / scope this / this feature won't fit one session".
  Routing always goes by measured budget and seams (phase 0), never by module count or task count.
---

# Feature Sharding

**Role**: you are the execution planner and orchestrator, not the implementer. Wave mode produces PLAN.md and dispatches subagents in this session; shard mode produces up to "session pack + merge protocol + launch checklist", then launches each track as a background session per 3e (first asking the user to approve the launch checklist LAUNCH.md only when the user must settle credentials or a paid allowance); from then on this session is the parent session and, per `PARENT.md`, answers questions, relays, merges and moves to the next batch until wrap-up. Tracks run only as `claude --bg` sessions launched by `spawn_tracks.py`, never as `claude -p`: `-p` exits once it finishes, leaving no session to resume and no status hooks.

**Prerequisite**: run the phase 0 routing first. Routed to the main thread → no change brief. In every other case (including unsure, or needing phase 1/2 measurements first) → write the change brief `docs/changes/<change-id>/BRIEF.md` first, then enter phase 1. The change brief is the single source of decisions shared across tracks, and the baseline the main thread checks each track's delivery against item by item:

```markdown
# <change-id>

> Frozen once the last implementation PR merges; after that the code and docs/adr/ are authoritative.

## Goal
<one sentence + what is explicitly out of scope>

## Acceptance scenarios
<S1, S2…: precondition → action → expected result; mark non-negotiable behaviour MUST>

## Decisions
<D1, D2…: what was chosen, what was rejected, why. Decisions that constrain later changes are written as an ADR under docs/adr/; here, only that ADR's file path>
```

**Budget constants** (orchestration budget, bin thresholds, iteration multipliers) always come from `calibration.md` in this directory; never invent numbers by feel.

---

## Phase 0: routing — don't count modules, look at budget and rulings

Module count and task count do not measure workload (tracks with equally tidy task counts differed 3-9× in actual size). Pick the execution mode from the table below; when unsure, run phase 1/2 first to get the bins and come back, since phases 1/2 are themselves the measurement routing needs:

| Criterion (check in order, first match wins) | Mode |
|---|---|
| The read set of all the increments plus the briefs visibly fits the main thread's current remaining budget | **Main thread does it directly**: leave this skill and work per playbook §0/§2 |
| Any one of: ① orchestration budget overloaded (tracks × per-track orchestration overhead + merge margin > healthy budget; constants in calibration.md) ② ruling in the loop (some track needs a user decision midway; a subagent runs one-way and cannot carry it, and the orchestrator answering for the user dilutes its own context) ③ continuous working set (steps inside a track are strictly serial and share memory of "the files being changed"; a relay of subagents would pay the whole read set again) | **Shard mode**: all three phases, producing a multi-session session pack |
| None of the above, but there are several mutually independent changes | **Wave mode**: phases 1/2 run light (no spike if there are no unknowns), every track lands in an S bin, subagents are dispatched in waves in this session, no session pack |

Once routed to wave or shard mode, the main thread only orchestrates and does not implement: the moment it implements, orchestration breaks.

Tell the user plainly where the benefit ends: sharding buys context quality and wall-clock time; subagents and multiple sessions draw on the same account allowance, so **sharding saves no allowance**.

## Phase 1: seam survey — whether to split

### 1a. Strip phantom work first (already-implemented check)

For each requirement, decide whether the codebase already implements it: locate the corresponding files and read the key parts (function signatures / route definitions / component exports). Remove what is already implemented from scope and report it to the user; later surveys and budgets **count only the increment**.

### 1b. Dispatch a researcher subagent for the seam survey (read-only; take back only conclusions + file:line)

Scan along the candidate module boundaries, category by category:

- Shared files (files both candidate modules must change)
- Shared read set (the same code both candidate modules must read through)
- Implicit contracts: conventions for paths / prefixes / task names / event names, and representation conventions for coordinate systems / units / encodings / time zones
- Tests that can only be written knowing both sides

### 1c. Dispatch spikes to clear known unknowns (duration of each in calibration.md, one-off verification of one concrete question)

Enumerate unknowns by where they hide, asking for each category "is there an unverified assumption here":

1. Real behaviour of third-party libraries: check their issue tracker and real call sites first, don't read only the official docs
2. The repo's first file of its kind (first component test, first pipeline of some kind): hidden infrastructure cost
3. Conversion points across coordinate systems / formats / encodings / units
4. Differences between two environments (several Python environments, dependency differences between a worktree and the main checkout, and the like); when a track must write to a shared directory in the main checkout that is not in git (data, caches), writing out of the worktree through a symlink is blocked by isolation, so the HANDOFF places the track's output in a git-ignored directory inside the worktree, and per 3d MERGE-PLAN.md carries the copy-back command
5. Outbound network traffic (default CDN / font / telemetry requests)
6. Shared resources on the same machine: disk, memory and swap, ports, and single-instance locks (databases, emulators, GPU) that parallel tracks contend for when they run builds, tests, containers or models at the same time; measure one track's peak usage, multiply it by the number of tracks and compare it with the machine's headroom; if it exceeds it, put the heavy work in different waves, or write the lock for serial use into the HANDOFF's downstream notes

### 1d. Handling unknowns — pick one of three before continuing

Every unknown must land in one of:

- **Cleared**: a spike produced a definite answer
- **Contained**: the unknown is sealed entirely within one track's boundary (e.g. "the frontend library may appear only inside a single wrapper component"); **no unknown may span two parallel tracks**: a spanning unknown that blows up means cross-track rework, and the parallel gain drops to zero
- **Seam pinned**: the unknown naturally sits on a seam (e.g. a coordinate convention) → use a golden fixture: build known data that both sides assert against (known input → known output, edge cases included), turning "a shared unknown" into "certainty each side can verify on its own", and write a guard test so the fixture itself cannot decay

### 1e. Four criteria for split / don't split (rule on each pair of adjacent modules)

1. **Compressible brief**: all the context the module needs to start fits into a six-element brief far smaller than its workload (six elements defined in the orchestrator playbook §2). Can't write it compactly = too much implicit context → don't split
2. **Read-set overlap**: two modules' read sets overlap beyond the merge line (see calibration.md) → merge them, or move the shared reading to wave 0 and push its conclusions down as "downstream notes"
3. **Zero in-flight coordination**: every seam is either frozen or stubbable (stub the not-yet-existing interface on the other side with something like `patch(..., create=True)`, and both sides start from the frozen signature)
4. **Independently verifiable**: every track has its own test gate that does not depend on a sibling track merging

**Output**: seam list (coupling point / how it is frozen / guard test) + unknowns list (each marked with how it is handled) + file ownership table (each track has an exclusive write set, counted in whole files, with no overlaps; a file split between two tracks by line ranges or functions still counts as overlap and still conflicts at merge. A file both tracks must change is either owned by one track or eliminated up front in wave 0, e.g. by turning a shared registration point into a shell that each track fills only through its own file). **Gate**: any unhandled unknown → no entry to phase 2.

## Phase 2: workload budget — how big to split

Measure three quantities for each candidate module; only bin them, don't pretend to precise prediction:

| Quantity | How to measure |
|---|---|
| Start-up cost | Actually write the brief + contract + notes and count the tokens |
| Read-set cost | Total size of the module's must-read files: `wc -c` divided by ~4 to estimate tokens |
| Iteration multiplier | Look up the multiplier table in calibration.md (by risk category) |

Expected total consumption ≈ (start-up + read set) × iteration multiplier, then bin it (thresholds in calibration.md):

- **S bin** → a single subagent run can handle it. The ceiling is set by the "trustworthy unsupervised range": a single subagent run has nobody correcting it, and the longer it runs the later a drift is discovered and the only fix is a full re-dispatch; **it is not set by the context window**
- **M bin** → one independent session can finish it in one go
- **L bin** → must be split further; if it truly cannot be split → launch it as an independent session anyway, with the trigger in the launch checklist's 「预算」 (budget) column computed from the M bin ceiling: when the track's watermark hook reaches the line it makes the track hand off, and the parent session launches a relay session to continue (see 3e and PARENT.md)

Binning recognises only the three measurements above; task count is not workload (phase 0 already gave the data).

## Phase 3: topology routing and session packing — where it runs

### 3a. Topology decision table

| Track characteristics | Topology |
|---|---|
| S bin, with judgement settled (contract frozen, a template to copy, verifiable in one delivery) | subagent, dispatched in waves in this session: one wave = no shared files, no dependencies, sent in parallel in one message; with dependencies → next wave, its prompt pointing to the predecessor track's deliverables. Write the dispatch prompt with all six elements (see orchestrator playbook §2), carrying all the planning the execution needs, so the subagent runs no separate planning workflow |
| M bin; or needs live measurement / a human ruling midway; or continuous working set | **Independent session** (launched per 3e, given a session pack) |
| Contract design, merge rulings, cross-track trade-offs | Main thread, never outsourced |

Orchestration capacity limit (constants in calibration.md): this session directly runs no more than the per-session limit of frozen subagent tracks (see calibration.md), ruling-heavy tracks count ≥2×, and a merge margin is kept. An independent session that dispatches subagents of its own is under the same limit: human → one independent session per track (orchestration + rulings) → its own subagents (execution).

**Wave mode** (routed from phase 0, or every track landed in an S bin in phase 2 with no human-ruling track): no session pack. Write the file ownership table + wave split into `docs/changes/<change-id>/sharding/PLAN.md`, then dispatch per the table above, telling the user the PLAN.md path when dispatching; when done, run "calibration backfill" too.

### 3b. Wave 0 always contains three pieces (done and merged before any parallel track starts: in wave mode a wave of implementation subagents dispatched on its own, in shard mode one independent session; the contract's design stays with the main thread per 3a, and wave 0 implements the frozen design)

1. **Contract freeze**: source of truth + each mirror + **mechanical alignment tests** (tests that parse each mirror and compare it field by field against the source of truth; the freeze discipline is enforced by them, not by prose)
2. **Walking skeleton**: a minimal hello-world-level end-to-end vertical slice that surfaces integration risk before parallel work starts
3. **Conclusions pushed down**: environment pitfalls, dependency pitfalls and template file:line found during the survey and wave 0's implementation are written into each track HANDOFF's "downstream notes" (in wave mode, into each dispatch prompt's known context); the end of every later wave likewise backfills the next wave (rolling planning, not planning everything at once)

### 3c. Session pack (one per independent-session track)

Session pack artefacts (`HANDOFF-*.md`, `MERGE-PLAN.md`, `LAUNCH.md`, `PARENT.md`) go into `docs/changes/<change-id>/sharding/` and are committed to the baseline branch together with BRIEF.md and the ADRs it references, and pushed to the remote; a track session's worktree is cut from the main checkout's current commit and fast-forwards to the baseline branch at the start, and so carries its own copy; a track's PR targets the remote baseline branch. REPORT files go in the same directory, landing on each track's own branch, so they never conflict.

A HANDOFF holds only pointers and track-specific facts: it copies neither the change brief (it would drift) nor the general pipeline discipline of CLAUDE.md / the playbook (test-first, the rule "must pass the delivery gate" itself, git rules), since the harness injects the global and project rule stack into every new session automatically and copying it again makes two sources. This track's **concrete** acceptance commands and expected output are track-specific facts and still go under "Acceptance + self-check". How a track reports back and when it hands off are set by the wrap-up contract the launch script appends to the opening line; the HANDOFF does not restate them. Template (the new session reads only this to start, so it must be self-contained; every placeholder is filled in when packing):

```markdown
# HANDOFF-<track>

## Goal
<one-sentence task + objective test of "done"; this track covers acceptance scenarios S… of BRIEF.md>

## File scope
Exclusive: <exact paths>
Read-only reference: <paths> (frozen, do not change)
Off-limits: <paths> (including files owned by other tracks)

## Shared decisions / interfaces
Read "Decisions" in docs/changes/<change-id>/BRIEF.md for shared decisions; frozen signatures / stubbing this track touches: <list>

## Downstream notes
<conclusions pushed down from wave 0: environment pitfalls, dependency entry points, template file:line, same-machine resources and locks to use serially>

## Acceptance + self-check
<delivery gate commands + expected output>

## Report
Once the delivery gate passes, write REPORT-<track>.md: changed files / verification evidence (≤5 lines) /
downstream interface facts (signatures only) / deviations and leftovers ("none" if none); then open a PR (targeting the remote <baseline branch>)
```

### 3d. Merge protocol `MERGE-PLAN.md`

- Merge order (dependencies first); each track's merge gate = its delivery gate + the contract's mechanical alignment tests all green. The parent session merges track by track in this order; track sessions only open PRs
- The parent session works in the main checkout directory and does not enter track worktrees, so for each track write copyable commands that confirm the merge gate from the main checkout directory (such as `gh pr checks <PR>`, plus the verification evidence of REPORT-<track>.md in `gh pr diff <PR>`; REPORT exists only on the track branch) and the merge command; also write the merge check commands, run in the main checkout directory after `git pull --ff-only`. For a track whose output sits in an ignored directory inside its worktree, write the copy-back command before that track's merge command: the source path is the worktree containing the cwd in `<state dir>/<track>.status.json` plus that directory, the target is the main checkout's shared directory, merged file by file rather than replacing the whole directory (that directory in the main checkout may hold raw inputs the track lacks); the parent session runs it with absolute paths from the main checkout directory, then merges, since the claude rm after the merge deletes the worktree along with the session
- **The integration wave is taken over by a brand-new session**, reusing no track's spent context: it goes into the launch checklist's pending table as one row, and the parent session launches it
- Contract problems found in integration → back to wave 0 to refreeze and sync every track; no unilateral changes

### 3e. Launch checklist and launching

The launch checklist is written to `docs/changes/<change-id>/sharding/LAUNCH.md`. In every table the first column is the track name, whose first word is the track code, matching `HANDOFF-<track>` and different on every row; another column is named exactly 「预算」 (budget) and holds the track's overflow trigger (the budget bin's ceiling × the overflow-valve factor in calibration.md, computed into a concrete number such as `15万`, i.e. 150k), from which the launch script sets the track session's watermark: a reminder at 20% before the line, and at the line the watermark hook stops it and makes it hand off. Tracks that can launch right now go in a table with a column named exactly 「开工第一句」 (opening line); tracks that must wait for a predecessor track to merge go in another table, with the launch condition in a column of its own and the opening line in a column named exactly 「待拉起的开工第一句」 (pending opening line). Cells hold only the sentence itself, without code formatting. How to write the opening line: `First run git merge --ff-only <baseline branch> (if git refuses, the worktree holds no work yet, so run git reset --hard <baseline branch> instead), then read docs/changes/<change-id>/sharding/HANDOFF-<track>.md and follow it`. When there is a wave 0, it is the only row in the 「开工第一句」 table and every other track goes into the pending table, with the launch condition naming which track it waits to merge; that session's last step writes the pitfalls found during implementation into the downstream notes of every HANDOFF-*.md and commits them with its own PR.

List the credentials (keys, accounts) and paid allowances each track needs from the user. When there are such items, have the user settle them together with how they are provided; write what is settled into the relevant HANDOFF and PARENT.md, recommit and push them with the session pack, then ask the user to approve the launch checklist. When there are none, don't ask for approval: launch directly, and give the path of LAUNCH.md in your report so the user can call a halt at any time. The user fills credentials into an env file themselves; sessions only run commands after loading it with `set -a; source <file>; set +a`, and never read or print it. Launch every track in this session's current permission mode: cross-session messages are held for approval when the two ends' permission modes are of different kinds; a background session has nobody watching, and in any mode other than auto/bypassPermissions it stops at permission prompts (the waiting script reports 「卡住」 (stuck), and the user must `claude attach <id>` to approve), so state this to the user when asking for approval or in your report.

When packing, write `docs/changes/<change-id>/sharding/PARENT.md` from the template below. It is the parent session's working protocol, and when this session relays out, the new parent session reads only it and the handoff file, so the commands must run when copied. Placeholders filled in when packing: S (absolute path of this skill's directory), R (absolute path of the main checkout directory), the baseline branch, the change-id, the permission mode and every file's absolute path; commands always carry expanded absolute paths. `<this session's name>` and `<this session's id>` are not filled in and stay as they are: whichever session is acting as parent fills in its own. The session id is the path segment just above `scratchpad` in its scratchpad path, and the session name is the name on the row of `claude agents --json` whose sessionId equals it.

```markdown
# PARENT

## Identity and location
You are the parent session of <change-id>, working in the main checkout directory <R>; you do not enter track worktrees and do not switch <R>'s branch (it stays on the baseline branch <baseline branch>).
Launch checklist <absolute path of LAUNCH.md>; merge protocol <absolute path of MERGE-PLAN.md>; change brief <absolute path of BRIEF.md>;
state directory <R>/.claude/stages/<change-id> (tracks.json records each track's session name, background id, budget and relays); permission mode <mode>.
<this session's name> and <this session's id> mean your own: the session id is the path segment just above scratchpad in your scratchpad path, and the session name is the name on the row of claude agents --json whose sessionId equals it.
A track's "current background id" is the bg_id of the last entry of its relays in tracks.json, or its own bg_id when it has no relays.

## Waiting
Before ending each turn, first run python3 <S>/scripts/wait_tracks.py <state dir> --once and look at the summary on its first line:
- 「在跑」 (running) above 0: run python3 <S>/scripts/wait_tracks.py <state dir> with Bash's background run (run_in_background) (don't start another if one is already running).
  It exits when a track stops, gets stuck or its process is gone, and its exit wakes you.
- 「在跑」 (running) at 0: start no wait, since it would exit at once and wake you for nothing. When everything left needs the user's decision, report it to the user in this session in one go and stop, and carry on once the user replies;
  when a track is stuck and needs the user to handle it with claude attach, ask the user in the report to come back to this session and say so when done, and you resume waiting.
Don't poll ListAgents, and don't send tracks "are you done yet".

## After waking, handle the tracks in the detail lines one by one
A detail line has the format "[<bucket>] <track> <session name> state=<agents state> status=<first-line declaration> ctx=<context>｜<last message>"; handle it by the bucket at the start of the line;
leave tracks in the bucket 「在跑」 (running) alone. A track with state=missing in the bucket 「完成」 (done) has already been merged and rm'd; skip it.
1. 「完成」 (done): confirm the merge gate in the merge protocol's order, then merge its PR; if one earlier in the order is not merged yet, this one waits. After merging one, use --once to find the other tracks
   whose status is 「完成」 and that are not merged yet, and merge them in order. For each merged track, run claude stop on its current background id, then run claude rm on its own bg_id and on every bg_id in its relays,
   one by one (this deletes the session and the worktree; the transcript is kept); if rm reports unpushed commits, confirm the PR is merged and rerun it with the --discard-unpushed argument it gives.
2. 「待答」 (awaiting answer): what can be settled from "Decisions" in the change brief and the ADRs it references, answer directly with SendMessage to that track by session name; collect what only the user can settle
   and ask the user in this session in one go, each item with its background, its numbered options with their effects, and a recommendation; once answered, send the answers back to each track. When a track proposes changing a frozen contract: if the change follows from the change brief's
   "Decisions" and the ADRs it references, settle it yourself, go back to wave 0 to refreeze per the merge protocol, and notify every track with SendMessage; if it touches the change brief's "Goal",
   an acceptance scenario marked MUST or an ADR-level decision, handle it as something the user must settle, and notify the affected tracks to stop the related parts first.
   When SendMessage reports the session cannot be found (nobody replied for about 1 hour after it asked, and its process has been stopped), continue that session with the answer as a new message:
   claude --resume <session_id in status.json> --bg "<answer>"
   Pass only these two arguments: without other arguments it keeps the session's saved name, permission mode and settings, and the background id stays the same; with other arguments it starts a separate copy and tracks.json no longer matches.
3. 「交接」 (handoff): run claude stop on its current background id, confirm with claude agents --json --all that the id no longer has a pid (the worktree is released only when the process exits), then run
   python3 <S>/scripts/spawn_tracks.py --relay <track> --sentence "Read <absolute path of the handoff file> and continue" --state <state dir>
4. 「卡住」 (stuck; usually at a permission prompt): tell the user in this session to run claude attach <current background id> to handle it, and meanwhile go on handling the other tracks.
5. 「未声明」 (undeclared; it stopped but its first line has no status): read the detail line and judge. If it is stuck on something you can answer directly, SendMessage it to continue; if you can't tell why, SendMessage
   it to add a status line per the wrap-up contract.
6. 「进程不在」 (process gone): if there is a handoff file, launch a relay per 3; if not, launch a relay with the command from 3 using --sentence "Read docs/changes/<change-id>/sharding/HANDOFF-<track>.md,
   first check with git log and git status how far this worktree has got, then carry on".
When done, go back to "Waiting". If two relays in a row of the same track stop again soon after starting, handle it as something the user must settle, and don't launch another.

## Next batch
Once every track of the current batch is merged, run the merge checks per the merge protocol, run git -C <R> pull --ff-only, then launch the pending tracks whose launch conditions are now met (the integration wave included):
python3 <S>/scripts/spawn_tracks.py <absolute path of LAUNCH.md> --repo <R> --change-id <change-id> --state <state dir> --parent <this session's name> --parent-session <this session's id> --permission-mode <mode> --only <track,…>
Codes already in tracks.json are always skipped. To test the launch mechanism, do it in a separate session without touching running tracks.

## Wrap-up
Once everything is merged: per "Calibration backfill" in <S>/SKILL.md, measure each track session's peak context, taking the transcript paths from transcript_path in each <state dir>/<track>.status.json;
backfill <S>/calibration.md and commit it; delete ~/.claude/state/sharding/parents/<this session's id>.json; report to the user in this session.

## Relaying yourself
When the watermark hook asks for a handoff: first stop the wait_tracks you are running in the background with TaskStop; then write the handoff with the handoff skill and launch the relay session per its step 4 D.
The start-here item of ③ says "read <absolute path of this file>, run python3 <S>/scripts/spawn_tracks.py --adopt --state <state dir> --parent <this session's name> --parent-session <this session's id>
(filled in with this relay session's own name and id), then run wait_tracks.py --once to see the whole picture, first handle the tracks that have stopped and not yet been handled (awaiting answer and not replied, done and not merged), then do as the 'Waiting' section says".
```

Launching (L is the absolute path of LAUNCH.md, R the main checkout directory, S this skill's directory, and commands carry expanded absolute paths; this session's id is the path segment just above `scratchpad` in the scratchpad path, and this session's name is the name on the row of `claude agents --json` whose sessionId equals it):
1. If this session's main-thread context is already past 250k tokens (the lower bound of the healthy orchestration budget in calibration.md), don't launch yet: hand off with the handoff skill, with the start-here item of ③ saying "read <absolute path of PARENT.md>, run python3 S/scripts/spawn_tracks.py L --repo R --change-id <change-id> --state R/.claude/stages/<change-id> --parent <this session's name> --parent-session <this session's id> --permission-mode <mode> (name and id filled in with the relay session's own), then follow PARENT.md", so the relay session acts as parent with a clean context.
2. `python3 S/scripts/spawn_tracks.py L --repo R --change-id <change-id> --state R/.claude/stages/<change-id> --parent <this session's name> --parent-session <this session's id> --permission-mode <mode>`. For each track the script checks that the background session really started; on any failure it exits non-zero and prints each reason (for example, an untrusted directory needs the user to run claude in R once and accept trust); handle each reason, then launch the failed tracks again with `--only`.
3. Once the launch succeeds, do as "Waiting" in PARENT.md says, report each track's session name to the user, and tell the user they can view them with `claude agents` and enter any track with `claude attach <id>`. From then on, follow PARENT.md through to wrap-up.

## Calibration backfill (after each sharded feature is finished)

For each participating session, measure the peak context, compare it with the estimated bin, and backfill the data-point log and constants in calibration.md. Recompute a constant from the log's data points of the same kind rather than overwriting it with a single data point; a constant that no data point in the log supports is replaced by the first measured value; recompute only from data points of the current main model.

```bash
python3 <absolute path of this skill's directory>/scripts/peak_context.py <absolute transcript path> [<absolute transcript path> …]
```

Take the parent session's own transcript, plus `transcript_path` from each `<state dir>/<track>.status.json` (for a track that relayed, find the predecessor sessions' transcripts at `~/.claude/projects/*/<session_id>.jsonl` by the session_id in `events.jsonl`); in wave mode, take this session's and each subagent's. Write paths expanded to absolute: worktree isolation blocks commands carrying `$HOME`.

Also sort the "pitfalls not foreseen when planning" back into the phase 1c list of where unknowns hide (as a new category or a new instance).
