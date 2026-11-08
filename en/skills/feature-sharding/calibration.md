# feature-sharding calibration data

## Budget constants

| Constant | Current value |
|---|---|
| Healthy session orchestration budget | 250-300k tokens |
| Per-track orchestration overhead (contract frozen, judgement settled) | 50-60k / track |
| Ruling-heavy track weighting | ≥2× |
| Overflow-valve trigger | Track budget ×0.6 (computed into a concrete token count from the bin ceiling when packing, and filled into the 「预算」 (budget) column of LAUNCH.md) |
| S bin ceiling (single subagent run) | 80k |
| M bin ceiling (one independent session finishes it) | 250k |
| Spike duration | 30-60 minutes |
| Read-set overlap merge line | About 30% |
| Frozen tracks one session runs directly | 3-4 |

## Iteration multiplier table

Expected total consumption ≈ (start-up cost + read-set cost) × multiplier.

| Risk category | Multiplier |
|---|---|
| Copying an existing template (CRUD / similar router / similar component) | ×1.5-2 |
| New infrastructure (the repo's first file of its kind, first pipeline of its kind) | ×3-5 |
| Contains uncleared unknowns | Not allowed into a bin: spike first, or move the whole track to a human-supervised independent session |

## Data-point log

| Date | Model | Feature (project) | Session role | Estimated bin | Measured peak context | Notes |
|---|---|---|---|---|---|---|
| 2026-07-16 | Not recorded | Orchestration budget statistics (project X, 39 session transcripts) | Several sessions | None | Single-session peak up to 789k | 52% of cache reads happened above 300k; past 300k hallucination and rework rose noticeably |
| 2026-07-16 | Not recorded | Feature X (project X) | Planning / wave 0 implementation / wave 1 orchestration / wave 2 integration | None (retroactive baseline) | 260k / 323k / 238k / 294k | First baseline. In wave 1 all four subagent tracks delivered in about 40 minutes; track A (new infrastructure) reworked heavily in wave 2 |
| 2026-11-03 | Opus 5.5 | batch1-format, draft format and first batch (project Y) | Parent session / FMT first session and 9 relays / IDX | 150k per track | Parent 183k; FMT 257k, 173k, 167k, 160k, 172k, 205k, 173k, 428k, 170k, 296k; IDX 99k | IDX (following an existing export pattern) finished in one session; FMT was estimated at one session and took 10: the small-batch gate failed six rounds (each review round found new problems), and every round's fix, paid batch run and review was a fresh judgement, so it was an iterating track with uncleared unknowns and should have been estimated as a human-supervised independent session. FMTR7 peaked at 428k because keepalive and a network outage stacked before it handed off. Also: the keepalive hook's reply 「完」 overwrote the handoff status line; track_hook has been fixed |
| 2026-11-03 | Opus 5.5 | batch1-r7, seventh small batch (project Y) | Single track R7 (parent session carried over from R1) | 150k | 360k | One session did the rule change, the paid small batch, the review and the report, with no handoff; 2.4× over budget, and the watermark hook did not stop it for a handoff (cause not investigated). Iterating tracks of this kind should be estimated at the top of the M bin |
| 2026-11-03 | Opus 5.5 | batch1-r8, eighth small batch (project Y) | Single track R8, first session and 1 relay | 150k | 382k, 208k | The first session handed off only after finishing the rule change and committing the generated output; again the watermark hook did not stop it near 150k (same as R7, cause not investigated) |
