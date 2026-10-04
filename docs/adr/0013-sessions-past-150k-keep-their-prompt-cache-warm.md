# ADR 0013: Sessions past 150k keep their prompt cache warm with a 30-minute heartbeat

## Status

Accepted. In effect since 4 October 2026. Complements [ADR 0011](0011-wrap-up-finishes-in-session-at-any-watermark.md): ADR 0011's 50-minute wake-up writes a handoff when a question awaits the user's decision and a large block of work follows it, and this ADR covers the rest of the idle waiting.

## Context

A session's prompt cache expires after an hour without use, in the Claude Code setting of October 2026. The first request after that rewrites the cache from the full context at the cache write price. Over the three days before this decision, a session idle for more than an hour rewrote a cache of more than 100,000 tokens 38 times, for $64.37 in all and a median of $1.62 each. The user coming back triggered 20 of these rewrites, for $31.03, and a background notification or a scheduled wake-up triggered the other 18, for $33.34.

On claude-opus-5-5 a cache read costs $0.20 per million tokens and a one-hour cache write $8 per million. Rewriting a context of 300,000 tokens therefore costs about $2.40, while a request that only reads the same cache to keep it alive costs about $0.06. Below about 150,000 tokens a rewrite is cheap enough that a timer firing in an empty session is not worth it.

## Decision

The Stop hook `keepalive-gate.sh` blocks the stop when the main thread's context has reached 150,000 tokens and the transcript holds no live keepalive. Its reason has the model set one with CronCreate: a recurring task every 30 minutes whose prompt starts with `[保活]` and asks for nothing but a full stop as the reply. The hook works out the two minutes of the hour from the current time and keeps them off 0 and 30, so the task does not land with tasks set on the hour or the half hour. A keepalive counts as live when its CronCreate succeeded and no later CronDelete names the task's id.

The interval is 30 minutes rather than something close to an hour. A cron expression lists the minutes of the hour and cannot express an interval such as 55 minutes, and a recurring task may fire up to 10% of its period late; at 30 minutes the latest firing still falls within the hour the cache lasts.

The keepalive ends in three ways. Its own prompt has the model look for the record of setting it in the conversation, and when there is none, as after `/clear`, delete the task. Once 8 hours have passed since the user's own last message, the hook blocks the keepalive's turn and has the model delete it; messages from subagents, other sessions and background notifications do not count as the user's. Closing the terminal ends the task with the process, and `--resume` restores tasks that have not expired.

The setup lives only in the hook's block reason and not in the rule text, because the rule text sits in every session's context from the start, including those that never reach 150,000 tokens.

## Consequences

A session past 150,000 tokens that the user leaves for up to 8 hours pays about $0.06 every half hour instead of a rewrite of several dollars when the user, a notification or a wake-up next arrives. A session left longer than 8 hours stops its keepalive and pays the rewrite as before.

The heartbeat assumes a one-hour cache. Once usage moves into overage, the cache drops to 5 minutes and every keepalive fires after the cache has expired, so it saves nothing; it does no harm either, since each firing is a short request.

## Sources

| Source | What it supports |
|---|---|
| `en/hooks/keepalive-gate.sh` and `en/hooks/tests/keepalive-gate.test.sh` | The 150,000-token threshold, the live-keepalive check, the 30-minute cron with its minutes kept off 0 and 30, the keepalive prompt, the 8-hour limit and which messages count as the user's |
| The author's session transcripts, read on 4 October 2026 | The 38 rewrites of more than 100,000 tokens after more than an hour idle over three days, $64.37 in all with a median of $1.62, split into 20 for $31.03 on the user's return and 18 for $33.34 on a notification or wake-up |
| `docs/adr/0011-wrap-up-finishes-in-session-at-any-watermark.md` | The 50-minute handoff wake-up this ADR complements |
