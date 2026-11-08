# ADR 0029: The keepalive stops for finished or handed-off sessions and stays on for sharding parents

## Status

Accepted. In effect since 24 October 2026; its parts reached the author's live harness between 8 and 24 October 2026. It extends [ADR 0014](0014-idle-sessions-past-150k-keep-their-prompt-cache-warm-with-an-async-rewake.md), [ADR 0015](0015-keepalive-keeps-timing-after-its-own-wake-up-and-skips-headless-sessions.md) and [ADR 0019](0019-keepalive-probes-the-network-before-waking-and-hands-off-at-its-last-wake-up.md): their 50-minute sleep, 5-minute-TTL check, headless skip, network probe and 57-minute deadline stand. Four things change. The hook also runs on `SessionEnd`. It reads only `user` and `assistant` transcript lines. A wake-up may be answered with a stop word, `Done` in an en install or 「完」 in a zh install, which stops the keepalive. A sharding parent with running tracks is kept warm below 150,000 tokens, with its 8-hour limit counted from later activity. In ADR 0019's last wake-up, a session with only wrap-up left records a wrap-up checklist instead of writing a handoff.

## Context

An `asyncRewake` wake-up enters whichever session the Claude Code process holds at that moment, while the timer watches the transcript of the session it started in. After `/clear` or `/resume` the old transcript stops changing, so the old timer runs out and wakes the new session, which then initialises for nothing.

From Claude Code 2.1.300 the transcript also carries lines of type `api-request-blob` with a user-role message and no timestamp. The hook took them for the user's own messages, the time of the user's last message became empty, and sessions past 150,000 tokens stopped being timed at all; in the author's transcripts the last wake-up that took effect was at 14:28 UTC on 20 October 2026.

Under ADR 0014 a finished session was still woken every 50 minutes until the 8-hour limit, since only the model can tell whether the task is done. A session that has handed off is in the same position: its remaining work and the user's answers go to the relay session. From 21 to 24 October 2026, 3 sessions received 7 wake-ups after handing off and answered every one with a full stop: the prompt then allowed 「完」 only when no question awaited the user, and a handed-off session almost always ends with questions the handoff carries over.

When `feature-sharding` runs tracks as background sessions (ADR 0028), the planning session waits idle as their parent, and a track's stop always wakes it. With a small context it falls under ADR 0013's 150,000-token threshold and is not timed, and its 8-hour limit runs from the user's last message even while the tracks are still working. The upstream commit prices the rewrite at the waking: for Opus 5.5, a one-hour cache write at $8 per million tokens against a cache read at $0.20, 40 times as much.

ADR 0019's last wake-up wrote a handoff whenever work was left, wrap-up included. Of 42 handoffs put in place from 6 to 13 October 2026, 13 were triggered by the last keepalive wake-up, at about $2.9 each at the API-equivalent price. When only commit, push, pull request or merge is left, a new session can see what remains from the git state.

## Decision

| Change | What `keepalive-gate.sh` does |
|---|---|
| Ended sessions | It is also registered on `SessionEnd`, where it leaves an empty marker named by the session id under `~/.claude/state/keepalive-ended` and removes markers older than a day. While timing and before waking, it exits 0 when its own session's marker exists |
| Transcript lines | Messages and activity are read only from lines of type `user` or `assistant` |
| `Done` or 「完」 | The full-stop prompt has two branches in which the model replies with only a stop word: 「完」 when `REPLY_LANG=zh` is set, as in a zh install, and `Done` otherwise. A: the task is done, no question awaits the user, and no background task or subagent is running. B: this session has written a handoff with the handoff skill and passed the remaining work to another session, the handoff records the remaining work, open questions and running tasks, and nothing has happened since apart from completion notices of tasks the handoff lists. The hook accepts either word whatever the install language, and after such a reply starts no timer until the user's own next message, an answer to a choice question included. It reads the transcript again before waking, since the stop-word line is often written after the hook started, and compares with quotes and closing punctuation removed and `Done` matched case-insensitively |
| Sharding parents | When `~/.claude/state/sharding/parents/<session id>.json` exists and its state directory has a track that has not ended and has not declared 完成 (done), or a registered track with no status file yet, the 150,000-token threshold does not apply, the stop word does not stop the timer, and the 8-hour limit and the last wake-up count from the later of the user's own last message and the latest track status. Any read failure counts as no running track |
| Last wake-up | The prompt takes the first branch that holds. A: substantive work for a new session, or a question awaiting the user; go through every step of the handoff skill. B: only wrap-up is left (commit, push, pull request, merge, wrap-up after a running task reports), possibly with things the user must do; append to the progress source a section listing each action with its check command and the output paths of running tasks, then reply with a full stop. C: the task is done, only things the user alone can do are left, or an existing handoff or plan already covers the rest; reply with a full stop. The turn does no wrap-up and asks no question again |

The playbook's section 3 says the last keepalive wake-up does no wrap-up and records the wrap-up checklist per its prompt, and section 1 lists the three replies a keepalive turn may give.

## Consequences

A cleared or resumed session is no longer woken by an older session's timer. The fix for `api-request-blob` lines restored timing; it also shows that the hook depends on the transcript format, which can change between Claude Code versions.

A finished or handed-off session stops after one more wake-up instead of running to the 8-hour limit; that one wake-up is the price of leaving the judgement to the model. A session the model wrongly judges finished loses its warm cache until the user's next message.

A sharding parent stays warm while its tracks run, at the cost of a wake-up every 50 minutes for a context that may be small. The 40-times comparison is the upstream commit's price arithmetic, not a measurement on these sessions.

A session left with only wrap-up gets a checklist in its progress source rather than a full handoff, and the wrap-up itself still waits for the user, so nothing is pushed or merged while nobody is present.

The prompts are Chinese strings inside the hook in both copies. The stop word in the full-stop prompt follows `REPLY_LANG`: `zh/settings.example.json` sets `REPLY_LANG=zh` on the keepalive command, so a zh install asks for 「完」, and an en install, without the prefix, asks for `Done`. The hook accepts either reply in both installs.

## Sources

| Source | What it supports |
|---|---|
| Commit e1853f0 in the author's live harness (`~/.claude`), body | A wake-up entering the session the process currently holds; the `SessionEnd` marker and its one-day cleanup |
| Commit f8cbee7 in the author's live harness, body | `api-request-blob` lines from Claude Code 2.1.300; the last effective wake-up at 14:28 UTC on 20 October 2026; branch A of 「完」 and the stop until the user's next message; 「完」 not applying to a sharding parent with running tracks; the reread before waking and the comparison without quotes or punctuation |
| Commit bb18ad1 in the author's live harness, body | Branch B of 「完」; 3 sessions with 7 wake-ups after handing off from 21 to 24 October 2026, all answered with a full stop; the reply as the single character 「完」 |
| Commit b7d76f2 in the author's live harness, body | The sharding parent marker; the threshold waived; $8 against $0.20 per million tokens, 40 times; the 8-hour limit from the later of the user's message and the track status; read failures counting as no running track |
| Commit af126b8 in the author's live harness, body | The last wake-up's three branches; 13 of 42 handoffs from 6 to 13 October 2026 triggered by it at about $2.9 each; wrap-up still not done while the user is away |
| `en/hooks/keepalive-gate.sh`, header comment and prompts | The ordered conditions, the marker directory, the line types, both prompts and their branches |
| `en/hooks/tests/keepalive-gate.test.sh` | The hook's cases; their number is the `PASS=<n>` the test prints |
| `en/settings.example.json`, the `SessionEnd` entry | The keepalive registered on `SessionEnd` |
| `en/orchestrator-playbook.md`, sections 1 and 3 | The keepalive turn's three replies and the wrap-up checklist |
| [ADR 0013](0013-sessions-past-150k-keep-their-prompt-cache-warm.md), [ADR 0014](0014-idle-sessions-past-150k-keep-their-prompt-cache-warm-with-an-async-rewake.md), [ADR 0015](0015-keepalive-keeps-timing-after-its-own-wake-up-and-skips-headless-sessions.md), [ADR 0019](0019-keepalive-probes-the-network-before-waking-and-hands-off-at-its-last-wake-up.md) and [ADR 0028](0028-sharding-tracks-run-as-background-sessions-under-the-planning-session.md) | The mechanism this ADR extends and the background tracks whose parent it covers |
