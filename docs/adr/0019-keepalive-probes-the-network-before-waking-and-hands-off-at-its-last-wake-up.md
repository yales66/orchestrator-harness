# ADR 0019: The keepalive probes the network before waking, and its last wake-up hands off when work is left

## Status

Accepted. In effect since 8 October 2026. Extends [ADR 0014](0014-idle-sessions-past-150k-keep-their-prompt-cache-warm-with-an-async-rewake.md) and [ADR 0015](0015-keepalive-keeps-timing-after-its-own-wake-up-and-skips-headless-sessions.md), whose conditions, 50-minute sleep and 8-hour limit stand. Adds one exception to [ADR 0011](0011-wrap-up-finishes-in-session-at-any-watermark.md) and to step 0 of the handoff skill from [ADR 0010](0010-handoffs-are-generated-whole-by-the-handoff-skill.md): when the keepalive's last wake-up judges a handoff needed, the handoff is generated at once, before any wrap-up.

## Context

A wake-up from `keepalive-gate.sh` starts a turn whose model request needs the network like any other. When the network has dropped, that request fails and the turn ends with the StopFailure event, not with Stop. Claude Code ignores the exit code and output of a StopFailure hook, so no hook can wake the model from there, and the Stop that would have started the next timer never fires. The keepalive chain therefore broke on every outage. On 7 October 2026 the wake-ups of three sessions ended with `ENOTFOUND`, and none of the three resumed.

A wake-up pays for itself only while the cache is still warm. The cache expires an hour after the request that last used it, and after that the next request rewrites the whole context at the cache-write price, so a wake-up that arrives too late costs more than no keepalive at all. `time.sleep` does not advance while a Mac sleeps, so after the lid has been closed a hook that has slept 50 minutes by its own count may wake well past that hour.

ADR 0014 stops the wake-ups 8 hours after the user's own last message. Until then the context can be read at the cache-read price; once the wake-ups stop and the cache expires, any turn that reads it, a handoff included, pays the rewrite.

## Decision

Before it wakes the model, the hook probes the API with a HEAD request to `ANTHROPIC_BASE_URL`, or to `https://api.anthropic.com` when that is unset. Any HTTP response counts as reachable, a 4xx or 5xx included, because it shows that a request gets through to the server. While the API is unreachable the hook probes again every 30 seconds, until 57 minutes after it started, which is the one-hour cache lifetime less a margin of 3 minutes. Past that deadline it exits 0 without waking. It checks the deadline against the wall clock, so a hook that wakes from a Mac's sleep past the deadline gives up in the same way. A new turn during the retries voids the timer just as it does during the sleep. The sleep before the first probe stays at 50 minutes by the author's choice, which leaves the last 7 minutes before the deadline for retries.

When the next wake-up would fall past the 8-hour limit, that is, when the hook's start plus two sleeps lies more than 8 hours after the user's own last message, this wake-up becomes the last one and its prompt changes. The prompt tells the model to use the handoff skill and finish all its steps when the session still has work for a new session to continue. That includes a session where only wrap-up such as a commit, a push, a pull request or a merge is left, and one that is waiting on the user's answer with work to follow, and in either case the model neither does the wrap-up nor asks the question again in this turn. When the task is done, when only things the user alone can do are left, or when an existing handoff or plan file already covers the remaining work and nothing has moved since, the model replies with only a full stop. Only the model can see from the session whether work is left, so the prompt leaves that judgement to it. After the last wake-up, however the model answered, the hook starts no timer until the user's own next message.

Three rules make room for that handoff, because each would otherwise steer the model away from it:

| Rule | What it says for the keepalive |
|---|---|
| Playbook §1 | A turn opened by a keepalive wake-up does only what its prompt asks, a full stop or every step of the handoff skill, and adds no reminder of pending questions |
| Playbook §3 | The rule that wrap-up is finished in the session without a handoff excepts the last keepalive wake-up that judges a handoff needed; that handoff is generated at once, before any wrap-up |
| Handoff skill, step 0 | The check is skipped when the last keepalive wake-up judges a handoff needed, and pending questions go into the brief's open items marked as awaiting the user instead of being asked again |

Two alternatives were rejected:

| Alternative | Why it was rejected |
|---|---|
| Recovering a failed wake-up from a StopFailure hook | Claude Code ignores a StopFailure hook's exit code and output, so such a hook cannot wake the model |
| Waiting for the network to return however long it takes, then waking | Past the deadline the cache has expired or cannot be renewed in time, and the wake-up would rewrite the whole context at the cache-write price, which costs more than no keepalive |

## Consequences

An idle session keeps its cache through an outage when the network returns before the deadline. When it does not, the hook gives up without a wake-up, and the session pays the rewrite at its next turn, as it would with no keepalive. One gap cannot be closed: when the probe succeeds and the wake-up's request fails right after it, the turn ends in StopFailure and the chain breaks.

A session the user leaves for 8 hours with work left gets a handoff written while its cache is warm, so the handoff skill reads the context at the cache-read price, and the user comes back to a handoff file a new session can start from. A session with nothing left to hand over gets only a full stop.

The hook tests cover an API that stays unreachable until the deadline, a network that returns before it, a user who comes back during the retries, a hook that wakes past the deadline as after a lid-close, a 404 that counts as reachable, a closed port that does not, and the last wake-up's handoff prompt.

## Sources

| Source | What it supports |
|---|---|
| `en/hooks/keepalive-gate.sh` and `en/hooks/tests/keepalive-gate.test.sh` | The probe, the 30-second retries, the 57-minute deadline on the wall clock, the last wake-up's condition and prompt, the stop after it, and the cases that check them |
| Claude Code hooks documentation, https://code.claude.com/docs/en/hooks.md | Claude Code ignores the exit code and output of a StopFailure hook |
| A check with `claude -p` on Claude Code 2.1.292, run by the author on 8 October 2026 | A turn whose request fails ends with StopFailure and is not woken |
| The author's session transcripts of 7 October 2026 | The wake-ups of three sessions ended with `ENOTFOUND`, and none resumed |
| `en/orchestrator-playbook.md` §1 and §3, and `en/skills/handoff/SKILL.md` step 0 | The three rules that make room for the last wake-up's handoff |
| [ADR 0014](0014-idle-sessions-past-150k-keep-their-prompt-cache-warm-with-an-async-rewake.md) | The one-hour cache, the 50-minute sleep and the 8-hour limit this ADR keeps |
