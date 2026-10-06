# ADR 0016: feature-sharding ships with the harness

## Status

Accepted. In effect since 6 October 2026.

## Context

The playbook's §1 row on multi-module change, a new project or an intent to parallelise used to route that work to `feature-sharding`, a skill the repository did not ship. 563cfd9 changed the row in both playbooks to have the main thread plan the work and dispatch it in parallel per §2, splitting it into phases with a §3 handoff between them when it would not fit one session, and 9bbeb5b made the same change in both playbook arms of the rules-missed-asks eval.

A phase handoff carries one session's state to the next session, one after the other. It does not measure whether the work fits the main thread's budget, does not bin the work by size, and does not split it along seams into tracks that independent sessions can run side by side. Multi-module work beyond the main thread's budget therefore had no budget measurement or binning and no multi-session session pack.

## Decision

Both copies ship `skills/feature-sharding/`: `SKILL.md`, `calibration.md`, and `scripts/peak_context.py` with its pytest tests in `scripts/test_peak_context.py`.

The §1 row now reads: when the seams and the budget are visible at a glance and the work fits the main thread's remaining budget, the main thread plans it and dispatches in parallel per §2; otherwise the work goes to `feature-sharding`.

The skill routes in phase 0 by budget and by whether a user ruling is needed midway, never by module or task count. Work whose read set and briefs fit the main thread's remaining budget leaves the skill and is done directly. Work that overloads the orchestration budget, needs a user ruling inside a track, or has a strictly serial working set goes to shard mode. Several independent changes that hit none of those go to wave mode. Outside the direct route, the skill first writes a change brief, `docs/changes/<change-id>/BRIEF.md`, as the single source of shared decisions.

Phase 1 removes requirements the codebase already implements, has a read-only subagent list shared files, shared read sets, implicit contracts and tests that need both sides, runs spikes on known unknowns, and requires every unknown to be cleared, contained in one track or pinned at a seam by a golden fixture before phase 2. Phase 2 bins each module as S, M or L from (start-up cost + read-set cost) × an iteration multiplier. Phase 3 dispatches S-bin tracks as subagent waves in the current session, gives M-bin tracks and tracks needing a user ruling to independent sessions the user launches from a session pack (`HANDOFF-<track>.md`, `MERGE-PLAN.md` and a launch checklist), and keeps contract design, merge rulings and cross-track trade-offs on the main thread.

Every budget constant, bin threshold and multiplier lives in `calibration.md` with the date and model behind it. `peak_context.py` reports the peak context of each session transcript, the largest sum of input, cache-read and cache-creation tokens in one assistant message, so that the constants can be backfilled after each sharded feature.

## Consequences

Work that does not fit the main thread's remaining budget is measured and split by seams before anything is dispatched, instead of being run as a chain of phases in one line of sessions. Tracks that can run in parallel get frozen contracts, a walking skeleton and a merge order, and independent sessions start from a self-contained session pack.

The skill writes `docs/changes/<change-id>/` into the user's repository: the change brief, and in wave or shard mode `PLAN.md` or the session pack. Independent sessions are launched by the user by hand, and the skill tells the user that sharding buys context quality and wall-clock time but no account allowance.

The constants in `calibration.md` are initial estimates. Most come from one feature in one project on 16 July 2026 with the model not recorded, and the file marks such entries as due for remeasurement.

`HANDOFF-<track>.md` is not `HANDOFF.md`: `handoff-guard.sh` does not deny writing it, and the handoff skill and ADR 0010 do not govern it.

The CI pytest job and `scripts/ci-local.sh` already run every `skills/*/scripts/` directory that holds `test_*.py`, so they run the new tests with no change. `scripts/check-parity.sh` requires files under `skills/*/scripts/` to be byte-identical in the two copies, so the English copy carries the scripts with their Chinese comments, as it does for the handoff skill.

## Sources

| Source | What it supports |
|---|---|
| `en/skills/feature-sharding/SKILL.md` | Phase 0 routing, the change brief, phases 1 to 3, the session pack, the merge protocol, the launch checklist and calibration backfill |
| `en/skills/feature-sharding/calibration.md` | The budget constants, bin ceilings and multipliers, with their dates, and the rule that entries without a model are due for remeasurement |
| `en/skills/feature-sharding/scripts/peak_context.py` and `scripts/test_peak_context.py` | How the peak context is computed, and its tests |
| `en/orchestrator-playbook.md`, §1, the table row on multi-module change | When the main thread plans and dispatches itself and when the work goes to `feature-sharding` |
| Commit 563cfd9 | The routing that replaced `feature-sharding` with phases and a §3 handoff in both playbooks |
| Commit 9bbeb5b | The same change in both playbook arms of the rules-missed-asks eval |
| `en/hooks/handoff-guard.sh`, header comment | Only a file named exactly `HANDOFF.md` is denied; `HANDOFF-<track>.md` is not |
| `.github/workflows/ci.yml`, the `pytest` job, and `scripts/ci-local.sh` | Every `skills/*/scripts/` directory with `test_*.py` is tested in both copies |
| `scripts/check-parity.sh`, item 2 of the header comment | Skill scripts must be byte-identical in the two copies |
