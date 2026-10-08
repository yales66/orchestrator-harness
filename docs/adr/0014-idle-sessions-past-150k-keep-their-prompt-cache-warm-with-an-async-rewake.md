# ADR 0014: Idle sessions past 150k keep their prompt cache warm with an async rewake after 50 minutes

## Status

Accepted. In effect since 4 October 2026. Supersedes [ADR 0013](0013-sessions-past-150k-keep-their-prompt-cache-warm.md), whose context, 150,000-token threshold and 8-hour limit stand; the mechanism that fires the keepalive changes. Complements [ADR 0011](0011-wrap-up-finishes-in-session-at-any-watermark.md) as ADR 0013 did. Its `stop_hook_active` condition is superseded by [ADR 0015](0015-keepalive-keeps-timing-after-its-own-wake-up-and-skips-headless-sessions.md), under which the hook does nothing in a `-p` headless session instead, and its list of the user's own messages is extended there to answers to choice questions. [ADR 0019](0019-keepalive-probes-the-network-before-waking-and-hands-off-at-its-last-wake-up.md) extends it: the hook probes the network before each wake-up, gives up once a wake-up could no longer renew the cache before it expires, and its last wake-up hands off when work is left.

## Context

ADR 0013 had the Stop hook block the stop and have the model set a recurring CronCreate task every 30 minutes. Two things went wrong with it. A cron task fires on the clock, so it fires while the user is at the keyboard as well as while they are away, twice an hour, and every firing in a session the user is using is a request that saves nothing. The auto mode classifier also denies the CronCreate as Unauthorized Persistence, so in auto mode the keepalive is never set and the block only interrupts the turn. The 7-day expiry of recurring tasks played no part, since the 8-hour limit ends a keepalive long before it.

Claude Code lets a command hook set `"asyncRewake": true`: the hook runs in the background, and when it exits with code 2 its stderr wakes the idle session as a reminder. On 4 October 2026 a probe Stop hook with this setting slept 40 seconds in one run and 660 seconds in another, with `"timeout": 900`, and woke the session both times; the hook's timeout can therefore be set above 600 seconds. The wake-up enters the transcript as a user-role message that starts with `<task-notification>`.

After every stop Claude Code itself appends lines to the transcript, `stop_hook_summary` and `turn_duration` within milliseconds and `away_summary` a few minutes into an idle spell. These lines are not a new turn.

## Decision

`keepalive-gate.sh` runs on Stop with `"asyncRewake": true` and `"timeout": 3300`. After every turn of the main thread it checks the same conditions ADR 0013 did: it does nothing inside a subagent or with `stop_hook_active` set, when the main thread's context is under 150,000 tokens, when the main thread's last cache write used the five-minute TTL, and when more than 8 hours have passed since the user's own last message or there is none. Otherwise it records the end of the transcript and sleeps 50 minutes.

When it wakes, it exits 0 if the transcript is gone, has shrunk, or has a new `user` or `assistant` line after the recorded end, because the session had a new turn and that turn's own stop has started a new timer. Otherwise it writes `[保活] 只回复一个句点，不做别的。` to stderr and exits 2, which wakes the model to reply with only a full stop. Lines of any other type, such as the ones Claude Code appends after a stop, do not count as activity.

The keepalive's own turn ends in a stop that starts the next timer, so an idle session is woken every 50 minutes until 8 hours have passed since the user's own last message. The wake-up is a background notification, so like subagent reports, messages from other sessions and `isMeta` messages it does not count as the user's.

50 minutes leaves the wake-up inside the hour the cache lasts, with ten minutes of margin for the reminder to be queued and the request to run. The timeout of 3300 seconds leaves five minutes over the 3000-second sleep for reading the transcript before and after it.

## Consequences

A keepalive fires only while the user is away: a session the user keeps using never sleeps out a full 50 minutes, so it is never woken. An idle session past 150,000 tokens pays about $0.06 per wake-up, a little over once an hour, instead of a rewrite of several dollars when the user, a notification or a wake-up next arrives. A session idle longer than 8 hours stops being woken and pays the rewrite as before.

No task is created, so nothing persists beyond the hook's own background process, auto mode has nothing to deny, and there is nothing to delete after `/clear` or at the 8-hour limit.

The 50-minute sleep assumes a one-hour cache. Once the cache has dropped to five minutes the hook does not start the timer.

## Sources

| Source | What it supports |
|---|---|
| `en/hooks/keepalive-gate.sh` and `en/hooks/tests/keepalive-gate.test.sh` | The conditions checked before the timer, the 50-minute sleep, what counts as activity, the wake-up prompt and exit code 2, the 8-hour limit and which messages count as the user's |
| `en/settings.example.json` | `"asyncRewake": true` and `"timeout": 3300` on the keepalive entry |
| Claude Code hooks documentation, https://code.claude.com/docs/en/hooks | `asyncRewake`: "If true, runs in the background and wakes Claude on exit code 2" |
| A probe Stop hook run by the author on 4 October 2026 | Wake-ups after sleeping 40 and 660 seconds with `"timeout": 900`, and the wake-up entering the transcript as a `<task-notification>` user message |
| The author's session transcripts, read on 4 October 2026 | The `stop_hook_summary`, `turn_duration` and `away_summary` lines Claude Code appends after a stop, and the auto mode classifier denying the keepalive's CronCreate as Unauthorized Persistence |
| `docs/adr/0013-sessions-past-150k-keep-their-prompt-cache-warm.md` | The cost figures, the 150,000-token threshold and the 8-hour limit this ADR keeps |
