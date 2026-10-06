# feature-sharding calibration data

All constants and multipliers are empirical: after each sharded feature is finished, measure and backfill them per "Calibration backfill" in SKILL.md.
Each value carries its source date and the main model at the time; after the main model changes generation, entries not backfilled on the new model, and entries with no model recorded, count as due for remeasurement.

## Budget constants

| Constant | Current value | Basis (date, model) |
|---|---|---|
| Healthy session orchestration budget | 250-300k tokens | Project transcript statistics: long sessions peaked at up to 789k, 52% of cache reads happened above 300k, and past 300k hallucination and rework rose noticeably (2026-07-16, 39 transcripts of project X) |
| Per-track orchestration overhead (contract frozen, judgement settled) | 50-60k / track | Feature X wave 1: 4 tracks of pure orchestration (dispatch + report back + gates) peaked at 238k (2026-07-16) |
| Ruling-heavy track weighting | ≥2× | Initial estimate, to be backfilled |
| Overflow-valve trigger | Track budget ×0.6 | Initial estimate, to be backfilled (computed into a concrete token count from the bin ceiling when packing, and filled into the HANDOFF) |
| S bin ceiling (single subagent run) | 80k | Initial estimate set by the trustworthy unsupervised range, to be backfilled |
| M bin ceiling (one independent session finishes it) | 250k | Initial estimate aligned with the healthy orchestration budget, to be backfilled |

## Iteration multiplier table

Expected total consumption ≈ (start-up cost + read-set cost) × multiplier.

| Risk category | Multiplier | Basis (date, model) |
|---|---|---|
| Copying an existing template (CRUD / similar router / similar component) | ×1.5-2 | Feature X tracks B/D delivered in one go with no rework (2026-07-16) |
| New infrastructure (the repo's first file of its kind, first pipeline of its kind) | ×3-5 | Feature X track A: task count level with track B (9 vs 8), actual size 19 files / 3002 lines vs 2 files / 936 lines, and still reworking in wave 2 (2026-07-16) |
| Contains uncleared unknowns | Not allowed into a bin | Spike first, or move the whole track to a human-supervised independent session |

## Data-point log

| Date | Model | Feature (project) | Session role | Estimated bin | Measured peak context | Notes |
|---|---|---|---|---|---|---|
| 2026-07-16 | Not recorded | Feature X (project X) | Planning / wave 0 implementation / wave 1 orchestration / wave 2 integration | None (retroactive baseline) | 260k / 323k / 238k / 294k | First baseline. In wave 1 all four subagent tracks delivered in about 40 minutes; track A (new infrastructure) reworked heavily in wave 2 |
