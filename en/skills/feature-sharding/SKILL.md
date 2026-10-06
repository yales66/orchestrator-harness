---
name: feature-sharding
description: |
  Unified execution planner for parallel multi-module work. Routes by budget first (phase 0): fits the main thread's remaining
  budget → just do it; otherwise strip phantom work that is already implemented, survey seams and unknowns → bin by
  workload (S/M/L) → all S bins → dispatch subagents in waves in this session; beyond the orchestration budget or needing
  a human ruling midway → produce a multi-session "session pack" that the human launches, plus a merge protocol.
  Triggers: multi-module change / new build from scratch / migration / cross-component refactor; the user says "split /
  parallelise / shard / scope this / this feature won't fit one session".
  Routing always goes by measured budget and seams (phase 0), never by module count or task count.
---

# Feature Sharding

**Role**: you are the execution planner and orchestrator, not the implementer. Wave mode produces PLAN.md and dispatches subagents in this session; shard mode stops at "session pack + merge protocol + launch checklist", because independent sessions can only be launched by the user personally. Do not stand in with background `claude -p` processes: those are pricier subagents with nobody correcting them, not sessions.

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

Module count and task count do not measure workload (tracks with equally tidy task counts differed 3-9× in actual size; data in calibration.md). Pick the execution mode from the table below; when unsure, run phase 1/2 first to get the bins and come back, since phases 1/2 are themselves the measurement routing needs:

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

### 1b. Dispatch a seam-hunter (read-only subagent; take back only conclusions + file:line)

Scan along the candidate module boundaries, category by category:

- Shared files (files both candidate modules must change)
- Shared read set (the same code both candidate modules must read through)
- Implicit contracts: conventions for paths / prefixes / task names / event names, and representation conventions for coordinate systems / units / encodings / time zones
- Tests that can only be written knowing both sides

### 1c. Dispatch spikes to clear known unknowns (30-60 minutes each, one-off verification of one concrete question)

Enumerate unknowns by where they hide, asking for each category "is there an unverified assumption here":

1. Real behaviour of third-party libraries: check their issue tracker and real call sites first, don't read only the official docs
2. The repo's first file of its kind (first component test, first pipeline of some kind): hidden infrastructure cost
3. Conversion points across coordinate systems / formats / encodings / units
4. Differences between two environments (several Python environments, dependency differences between a worktree and the main checkout, and the like)
5. Outbound network traffic (default CDN / font / telemetry requests)

### 1d. Handling unknowns — pick one of three before continuing

Every unknown must land in one of:

- **Cleared**: a spike produced a definite answer
- **Contained**: the unknown is sealed entirely within one track's boundary (e.g. "the frontend library may appear only inside a single wrapper component"); **no unknown may span two parallel tracks**: a spanning unknown that blows up means cross-track rework, and the parallel gain drops to zero
- **Seam pinned**: the unknown naturally sits on a seam (e.g. a coordinate convention) → use a golden fixture: build known data that both sides assert against (known input → known output, edge cases included), turning "a shared unknown" into "certainty each side can verify on its own", and write a guard test so the fixture itself cannot decay

### 1e. Four criteria for split / don't split (rule on each pair of adjacent modules)

1. **Compressible brief**: all the context the module needs to start fits into a six-element brief far smaller than its workload (six elements defined in the orchestrator playbook §2). Can't write it compactly = too much implicit context → don't split
2. **Read-set overlap**: two modules' read sets overlap by more than about 30% → merge them, or move the shared reading to wave 0 and push its conclusions down as "downstream notes"
3. **Zero in-flight coordination**: every seam is either frozen or stubbable (stub the not-yet-existing interface on the other side with something like `patch(..., create=True)`, and both sides start from the frozen signature)
4. **Independently verifiable**: every track has its own test gate that does not depend on a sibling track merging

**Output**: seam list (coupling point / how it is frozen / guard test) + unknowns list (each marked with how it is handled) + file ownership table (each track has an exclusive write set, no overlaps; a file both tracks must change is either owned by one track or eliminated up front in wave 0, e.g. by turning a shared registration point into a shell that each track fills only through its own file). **Gate**: any unhandled unknown → no entry to phase 2.

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
- **L bin** → must be split further; if it truly cannot be split → build in a phase gate: on reaching the overflow-valve trigger (constants in calibration.md), force a CHECKPOINT to disk and have a new session take over (the valve instruction goes into the HANDOFF, see phase 3)

Binning recognises only the three measurements above; task count is not workload (phase 0 already gave the data).

## Phase 3: topology routing and session packing — where it runs

### 3a. Topology decision table

| Track characteristics | Topology |
|---|---|
| S bin, with judgement settled (contract frozen, a template to copy, verifiable in one delivery) | subagent, dispatched in waves in this session: one wave = no shared files, no dependencies, sent in parallel in one message; with dependencies → next wave, its prompt pointing to the predecessor track's deliverables. Write the dispatch prompt with all six elements (see orchestrator playbook §2), carrying all the planning the execution needs, so the subagent runs no separate planning workflow |
| M bin; or needs live measurement / a human ruling midway; or continuous working set | **Independent session** (launched by the human, given a session pack) |
| Contract design, merge rulings, cross-track trade-offs | Main thread, never outsourced |

Orchestration capacity limit (constants in calibration.md): this session directly runs ≤3-4 frozen subagent tracks, ruling-heavy tracks count ≥2×, and a merge margin is kept. An independent session that dispatches subagents of its own is under the same limit: human → one independent session per track (orchestration + rulings) → its own subagents (execution).

**Wave mode** (routed from phase 0, or every track landed in an S bin in phase 2 with no human-ruling track): no session pack. Write the file ownership table + wave split into `docs/changes/<change-id>/sharding/PLAN.md`, then dispatch per the table above, telling the user the PLAN.md path when dispatching; when done, run "calibration backfill" too.

### 3b. Wave 0 always contains three pieces (done and merged before any parallel track starts: in wave mode a wave of implementation subagents dispatched on its own, in shard mode one independent session; the contract's design stays with the main thread per 3a, and wave 0 implements the frozen design)

1. **Contract freeze**: source of truth + each mirror + **mechanical alignment tests** (tests that parse each mirror and compare it field by field against the source of truth; the freeze discipline is enforced by them, not by prose)
2. **Walking skeleton**: a minimal hello-world-level end-to-end vertical slice that surfaces integration risk before parallel work starts
3. **Conclusions pushed down**: environment pitfalls, dependency pitfalls and template file:line found during the survey and wave 0's implementation are written into each track HANDOFF's "downstream notes" (in wave mode, into each dispatch prompt's known context); the end of every later wave likewise backfills the next wave (rolling planning, not planning everything at once)

### 3c. Session pack (one per independent-session track)

Session pack artefacts (`HANDOFF-*.md`, `MERGE-PLAN.md`) go into `docs/changes/<change-id>/sharding/` and are committed to the baseline branch together with BRIEF.md and the ADRs it references; each track session fast-forwards its new worktree to the baseline branch and so carries its own copy. CHECKPOINT / REPORT files go in the same directory, landing on each track's own branch, so they never conflict.

A HANDOFF holds only pointers and track-specific facts: it copies neither the change brief (it would drift) nor the general pipeline discipline of CLAUDE.md / the playbook (test-first, the rule "must pass the delivery gate" itself, git rules), since the harness injects the global and project rule stack into every new session automatically and copying it again makes two sources. This track's **concrete** acceptance commands and expected output are track-specific facts and still go under "Acceptance + self-check". Template (the new session reads only this to start, so it must be self-contained; every placeholder is filled in when packing, except the worktree path in the overflow valve, which the track session fills in itself):

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
<conclusions pushed down from wave 0: environment pitfalls, dependency entry points, template file:line>

## Acceptance + self-check
<delivery gate commands + expected output>

## Overflow valve
This track's budget is <N×10k tokens>, trigger at <N×0.6×10k tokens> (computed into concrete numbers when packing, no formulas left).
When context use nears the trigger: stop opening new ground, write the state to CHECKPOINT-<track>.md in this directory
(done / in progress / next step / pitfalls hit), then prompt the user to open a new session to take over;
the takeover session's first line, with this session's worktree path filled in: "Use EnterWorktree with path <this worktree's path>, read
HANDOFF-<track>.md and CHECKPOINT-<track>.md under sharding/, and continue from 'next step'."

## Report
Once the delivery gate passes, write REPORT-<track>.md: changed files / verification evidence (≤5 lines) /
downstream interface facts (signatures only) / deviations and leftovers ("none" if none)
```

### 3d. Merge protocol `MERGE-PLAN.md`

- Merge order (dependencies first); each track's merge gate = its delivery gate + the contract's mechanical alignment tests all green
- **The integration wave is taken over by a brand-new session**, reusing no track's spent context
- Contract problems found in integration → back to wave 0 to refreeze and sync every track; no unilateral changes

### 3e. Launch checklist (for the user; this skill's final product)

One line per independent-session track: budget bin and overflow trigger, where to launch (run `claude` in the main checkout directory), and the opening line (`Use EnterWorktree to open this track's worktree, run git merge --ff-only <baseline branch> in it (if git refuses, the new worktree holds no work yet, so run git reset --hard <baseline branch> instead), then read docs/changes/<change-id>/sharding/HANDOFF-<track>.md, follow it, and stop once the delivery gate passes`). Each track session creates its own worktree with the native EnterWorktree tool; the packer does not pre-create them and does not run `git worktree add` by hand. List wave 0's session first and state that the other tracks launch only after it merges; that session's last step writes its pitfalls into the downstream notes of every HANDOFF-*.md and commits them to the baseline branch. In shard mode, handing over the launch checklist finishes the job; the user launches each track.

## Calibration backfill (after each sharded feature is finished)

For each participating session, measure the peak context, compare it with the estimated bin, and backfill the data-point log and constants in calibration.md:

```bash
python3 "$HOME/.claude/skills/feature-sharding/scripts/peak_context.py" "$HOME/.claude/projects/<project directory>/"*.jsonl
```

To count only the sessions that took part in this feature, replace the whole `"$HOME/.claude/projects/<project directory>/"*.jsonl` with a space-separated list of full paths (each file with its own directory prefix).

Also sort the "pitfalls not foreseen when planning" back into the phase 1c list of where unknowns hide (as a new category or a new instance).
