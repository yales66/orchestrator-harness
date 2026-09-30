# Reply gate replay

This directory measures how well the `Stop` hook `en/hooks/reply-gate.sh` separates replies it should block from replies it should let through, by replaying the real script offline over one user's past Claude Code sessions. The hook has two rules. A1 blocks a reply whose last sentence offers a next step ("Shall I …?", 「要我…吗」), because an offer of a step the agent could simply take turns into a round of waiting. A2 blocks a long reply written mostly in Latin script when the user has asked for Chinese. The reference for A1 is section 1 of `en/orchestrator-playbook.md` and ADR 0006: asking is right for irreversible, external or paid actions and for forks whose choice depends on the user's own preferences, and wrong for a reversible, free, internal step within the user's current goal.

Every file that contains conversation text lives in a private data directory outside the repository, passed to each script as `--data`. The repository keeps only the scripts, the labeling rules, this README and `results.md`, which holds aggregate numbers only.

## Method

1. **Extraction** (`extract.py`). The script reads the main-thread transcripts `~/.claude/projects/*/*.jsonl`, skipping subagent transcripts and sessions started non-interactively with `claude -p`. A pair is the assistant's final text message of a turn together with the next message the user typed. A turn ends where the model stops: an assistant text message followed by a user record that is not a tool result. Stops that another `Stop` hook blocked are not turn ends, interrupted turns are dropped, and tool results, hook and system injections, task notifications, subagent hand-backs and slash-command output never count as the user's message. Records copied into resumed sessions are counted once. The window ends at the first time the reply gate itself appears in a transcript, because later replies were already shaped by it. Each pair keeps its session id and timestamp; no project name is written anywhere.
2. **Sample.** Stratum Q holds every pair whose reply ends with `?` or `？`; stratum R holds the rest. The sample is all of Q capped at 150 by a seeded random draw, plus 100 random pairs from R, with seed 20260929.
3. **Blind labeling.** Before the gate was run, every sampled pair was labeled from its text alone following `labeling-rules.md`, as should-have-just-done-it, rightly-asked, not-an-offer or unclear, together with the form of the ending. The labeler read the excerpt that `extract.py` writes to `label-view/a1.md`: the first 260 characters of the user message that set the turn's goal, the last 500 characters of the reply, and the first 160 characters of the next user message.
4. **Replay** (`replay.py`). The real hook script runs once per pair with `REPLY_LANG=zh`, because this user always requires Chinese, on the same JSON a `Stop` event carries, with `stop_hook_active` false. A1 and A2 share one reason string, so each is recognised by its own marker sentence, the same markers the hook's regression test uses. The script records the first 12 hex digits of the SHA-256 of the hook file, and draws up to 30 pairs where A2 fired for A2 labeling.
5. **Scoring** (`score.py`). A1 precision is the share of should-have-just-done-it among fired, labeled pairs; A1 recall is the share fired among labeled should-have-just-done-it pairs. Each labeled pair is weighted by its stratum's size divided by its sample size, so both rates estimate the whole population. Intervals are Wilson 95% intervals, with Kish's effective sample size standing in for n on weighted rates. A2 is reported as its firing rate over all pairs and its precision on the labeled A2 sample. The error patterns come from the descriptive fields of the labels, never from conversation text.

## Running

From the repository root, with `DATA` set to the private directory:

```bash
python3 eval/reply-gate-replay/extract.py --data "$DATA"
python3 eval/reply-gate-replay/replay.py --data "$DATA"
python3 eval/reply-gate-replay/score.py --data "$DATA"
```

The scripts use the Python standard library only. `extract.py` accepts `--projects` to read transcripts from somewhere other than `~/.claude/projects`, `replay.py` accepts `--repo` to replay a hook from another checkout, and `score.py` accepts `--out` to write the results elsewhere. The labels are not produced by any script: `score.py` reads `labels.jsonl` and `labels-a2.jsonl` from the data directory and stops if a sampled pair has no label.

Rerunning the three commands reproduces `results.md` byte for byte as long as the transcripts in the window are unchanged and the hook file still has the SHA-256 prefix recorded in `results.md`. Claude Code deletes transcripts older than its `cleanupPeriodDays` setting, so once files from the window age out, a rerun of `extract.py` yields a different population and sample, and `score.py` refuses to score pairs that were never labeled. The `pairs.jsonl` saved in the data directory is the frozen population for the published numbers. The hash line in `results.md` identifies the hook that produced the numbers, and it changes only if the hook does.

## Files

| File | Role |
|---|---|
| extract.py | builds the pairs, the strata, the seeded sample and the blind labeling view |
| replay.py | runs the hook on every pair, records A1 and A2 firings and the hook file hash, draws the A2 labeling sample |
| score.py | computes the weighted rates, intervals and error patterns and writes `results.md` |
| labeling-rules.md | the rules that decide every A1 and A2 label |
| results.md | aggregate results of the latest run |

The data directory holds `pairs.jsonl`, `extract-meta.json`, `sample.jsonl`, `label-view/a1.md`, `labels.jsonl`, `replay.jsonl`, `replay-meta.json`, `a2-sample.jsonl`, `label-view/a2.md` and `labels-a2.jsonl`.

## Limits

One labeler assigned every label, and it was the same agent that wrote the replay and knew the gate's phrase list, so the labels are blind to the gate's output but not to its design, and there is no second labeler or agreement figure. Whether an offered step lies beyond the turn's goal is the least mechanical judgement in the rules, which is why `results.md` repeats both A1 rates with those offers counted the other way.

A1 recall rests on stratum R: A1 can only fire on a reply that ends with a question mark or 吗, so every should-have-just-done-it pair in R is a miss, and each labeled pair in R stands for about 26 pairs. The recall interval is correspondingly wide.

The replay measures the gate as a classifier of finished replies. The replies were written before the gate existed, so they show nothing about how the agent rewrites a reply after a block, and the replay never exercises the rule that lets the second consecutive stop through. All transcripts come from one person over about six weeks, most of them in Chinese and heavy on delegated multi-agent work, so the rates describe this user rather than Claude Code users in general. Turns are read in file order, so conversation branches created by rewinding are not told apart. A2 recall was not measured.
