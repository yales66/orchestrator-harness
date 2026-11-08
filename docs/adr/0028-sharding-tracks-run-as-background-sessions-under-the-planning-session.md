# ADR 0028: Sharding tracks run as background sessions under the planning session

## Status

Accepted. In effect since 20 October 2026; the fixes of 3 November 2026 to track status and worktree output are included. It amends [ADR 0016](0016-feature-sharding-ships-with-the-harness.md) in three places. Independent track sessions are launched by the planning session as `claude --bg` background sessions, not by the user by hand. The planning session stays on as the parent that answers, relays and merges the tracks. The playbook's section 1 row on multi-module work routes by the shape of the work rather than by whether it fits the main thread's remaining budget. ADR 0016's phases, binning, change brief, session pack and calibration file stand.

## Context

ADR 0016 left launching the independent sessions of a session pack to the user. The harness then let a session launch tracks itself, by driving Ghostty through AppleScript to open a window per track, and the author's runs of it hit three kinds of failure. A launch failed without any report 5 times, the worst of them delaying the work by 7 hours. A relay ran into the worktree lock of an old session that had not yet exited 2 times. Sessions were addressed by name, and names clashed.

Each track session was also asked to watch its own context and hand off at an overflow line written in its handoff file. Of 12 track sessions, 9 crossed that line without handing off. Planning or merge sessions ran into trouble of their own: 6 of them reached the 400,000-token hard line in the middle of a sharded change.

Claude Code 2.1.304 ships background sessions, `claude --bg`, with a supervisor that starts, lists, stops and removes them and gives each a worktree with `-w`. All the steps below were rehearsed on real background sessions before the change: launch, a track awaiting an answer, the answer, completion, a relay refused while the old process lived, and the relay.

## Decision

| Piece | What it does |
|---|---|
| `scripts/spawn_tracks.py` | Launches each track in `LAUNCH.md` as `claude --bg -w` with its own `--settings`: the state directory and track code as environment variables, the watermark gate's warning and hard lines set from the track's budget column (80% of the budget and the budget itself), and `track_hook.py` on `SessionStart`, `Stop` and `SessionEnd`. A launch counts only when `claude agents` lists the session and its `SessionStart` record has been written; otherwise the script prints each reason and exits 1. `--relay` launches a relay in the same worktree only once the old process has exited; `--adopt` hands the state directory to a new parent session. Paths are expanded to absolute |
| `scripts/track_hook.py` | Writes `<track>.status.json` and appends to `events.jsonl` on each of those events. The status is read from the first line of the track's last message, `状态：完成` (done), `待答` (awaiting answer) or `交接` (handoff), as the wrap-up contract in the track's opening instruction requires. A later turn that replies only with a keepalive's full stop, `Done` or 「完」 keeps the status declared before |
| `scripts/wait_tracks.py` | Runs in the background in the parent session and exits when a track stops, gets stuck or its process is gone, which wakes the parent. A single failed `claude agents` query reuses the previous result; three in a row count as the session missing |
| `PARENT.md` | Written into the session pack. It is the parent's working protocol: how to wait, how to handle each status (merge in order and remove the session, answer from the change brief or ask the user in one batch, stop and relay, ask the user to attach to a stuck track), how to launch the next batch, how to wrap up, and how the parent relays itself with `--adopt` |

The planning session is the parent. When its own context is already past 250,000 tokens, the lower bound of the healthy orchestration budget in `calibration.md`, it hands off first and a relay session with a clean context becomes the parent. The user is asked to approve the launch checklist only when credentials or a paid allowance must be settled; otherwise the tracks launch directly and the report gives the path of `LAUNCH.md`.

The watermark line moves from the track's handoff file to the launch settings, so the watermark gate enforces it. Phase 1 lists shared resources on the same machine as a place unknowns hide, since parallel tracks contended for disk 5 times and once waited 80 minutes on a lock. A write set is a whole file, since splitting one file by line ranges between two tracks caused conflicts at merge. A track whose output must land in a directory the main checkout ignores writes it inside its own worktree, and the merge protocol carries the command that copies it back before the parent merges and removes the session.

`launch_tracks.py` stays only for the handoff skill's interactive relay session; it now times out its AppleScript after 60 seconds and fails when the new session does not appear in `claude agents` within 45 seconds.

Section 1 of the playbook routes multi-module work by its shape: independent parts with judgement settled are dispatched in parallel under section 2, strongly serial and judgement-dense parts stay with the main thread, and work that needs several sessions or a human ruling midway goes to `feature-sharding`.

## Consequences

Track sessions no longer need the user to launch them or a terminal window to run in, and their status comes from hooks, not from the model remembering to report. A launch that fails says why. A relay cannot collide with a live worktree lock, because the parent stops the old session and confirms its process is gone first.

Each track's background session runs in the parent's permission mode. A background session has nobody watching, so in a mode other than auto or bypassPermissions it stops at the first permission prompt, and the user has to attach to it.

The design depends on `claude --bg`, `claude agents`, `claude attach`, `claude stop` and `claude rm` as Claude Code 2.1.304 provides them, and on two details of that version: measured there, a turn that ends with a question is listed as blocked, so a first line declaring `待答` is read as awaiting an answer rather than stuck; and Claude Code flushes the transcript every 100 milliseconds, so the `Stop` hook prefers `last_assistant_message` and otherwise waits a second before reading the transcript. A later Claude Code version could change any of these.

The keepalive's reply rule matters here. Before the 3 November fix, a track that had handed off and then answered a keepalive wake-up with a full stop or 「完」 was read as running again, and in a private project the parent waited about 7 hours on such a track.

The status line, the bucket names and the scripts' comments are in Chinese in both copies, as `scripts/check-parity.sh` requires skill scripts to be byte-identical.

## Sources

| Source | What it supports |
|---|---|
| Commit b3d62cb in the author's live harness (`~/.claude`), body | The AppleScript failures (5 silent launch failures, up to 7 hours; 2 worktree lock clashes; name clashes); Claude Code 2.1.304 background sessions; the rehearsal; `spawn_tracks.py`, `track_hook.py`, `wait_tracks.py`; 9 of 12 track sessions crossing their own overflow line; the 2.1.304 blocked-state measurement; the 100-millisecond flush; `launch_tracks.py` kept for relays with its 60- and 45-second checks; absolute paths |
| Commit a19a794 in the author's live harness, body | The planning session as parent; the 250,000-token handoff before launch and the 6 sessions that reached 400,000; `PARENT.md`; the watermark line moved to the launch settings; shared resources (disk contention 5 times, one 80-minute lock wait); whole-file write sets |
| Commit d23f8e2 in the author's live harness, body | Keepalive replies keep the declared status, and the 7-hour wait in a private project; worktree output copied back per the merge protocol |
| Commit bb43311 in the author's live harness, body | Multi-module work routed by its shape; approval asked only for credentials or a paid allowance |
| `en/skills/feature-sharding/SKILL.md`, the launch checklist, the `PARENT.md` template and "Launching" | Background sessions stopping at permission prompts outside auto or bypassPermissions; the parent's protocol, the 250,000-token rule and the launch steps |
| `en/skills/feature-sharding/scripts/spawn_tracks.py`, `track_hook.py` and `wait_tracks.py`, module docstrings and constants | The per-track settings and watermark lines, the status line, the keepalive-reply rule, the waiting and failure tolerance |
| `en/skills/feature-sharding/scripts/test_spawn_tracks.py`, `test_track_hook.py`, `test_wait_tracks.py` | The scripts' tests |
| `en/orchestrator-playbook.md`, section 1, the row on multi-module change, and section 5 | The routing by shape of work, and tracks created by `spawn_tracks.py` with `claude --bg -w` |
| `scripts/check-parity.sh`, item 2 of the header comment | Skill scripts byte-identical in both copies |
| [ADR 0016](0016-feature-sharding-ships-with-the-harness.md) | The parts this ADR amends |
