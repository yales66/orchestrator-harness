# ADR 0015: The keepalive keeps timing after its own wake-up, and headless sessions are not timed

## Status

Accepted. In effect since 6 October 2026. Supersedes the `stop_hook_active` condition of [ADR 0014](0014-idle-sessions-past-150k-keep-their-prompt-cache-warm-with-an-async-rewake.md), and extends its list of the user's own messages; the rest of ADR 0014 stands. [ADR 0019](0019-keepalive-probes-the-network-before-waking-and-hands-off-at-its-last-wake-up.md) extends it with the network probe and the handoff on the last wake-up.

## Context

ADR 0014 had `keepalive-gate.sh` do nothing when the Stop input carried `stop_hook_active` set. That condition came from ADR 0013, where the hook blocked the stop synchronously and a second block of the turn it had just resumed would have looped.

Claude Code 2.1.291 sets `stop_hook_active` to true at the end of the turn an `asyncRewake` wake-up started, and at the end of a turn that resumed after a synchronous Stop hook such as the context watermark gate blocked it. The keepalive's own turn therefore ended in a stop the hook skipped, so an idle session was woken once and never again, and a turn that another Stop hook had blocked started no timer either.

In a `-p` headless session, which Claude Code runs with `CLAUDE_CODE_ENTRYPOINT` set to `sdk-cli`, an `asyncRewake` hook does not move to the background. The hook runs synchronously and holds the whole run for its 50-minute sleep, while the run exits as soon as it finishes and leaves no cache to keep.

A user's answer to a choice question asked with AskUserQuestion enters the transcript as a tool result, a user-role message whose top-level `toolUseResult` carries `questions`. ADR 0014 counted no tool result as the user's own message, so a session the user answered only through choice questions was taken as one the user had left, and wake-ups stopped 8 hours after the last message they typed. When nobody answers, Claude Code submits the question on a timeout, and that tool result also carries `toolUseResult.afkTimeoutMs`.

## Decision

`keepalive-gate.sh` no longer looks at `stop_hook_active`. In an interactive session it only times in the background and never blocks the stop, so there is no blocking loop to prevent.

It does nothing when `CLAUDE_CODE_ENTRYPOINT` is `sdk-cli`, as it already does inside a subagent.

A user-role line whose `toolUseResult` carries `questions` counts as the user's own message, because the user was there to answer it. One whose `toolUseResult` also carries `afkTimeoutMs` does not, because nobody answered it.

## Consequences

An idle session past 150,000 tokens is woken every 50 minutes as ADR 0014 intended, until 8 hours have passed since the user's own last message, including after a turn the watermark gate or the reply gate blocked.

A `-p` run is never held up by the keepalive and is never woken.

A session the user answers through choice questions keeps its keepalive while they keep answering. A question submitted on timeout leaves the 8-hour limit counting from the user's last real answer or message, so a forgotten session still stops being woken.

The hook tests check that a stop with `stop_hook_active` set starts the timer, that the `sdk-cli` entrypoint does not and another entrypoint does, and the three cases of a recent answer, an answer 9 hours old and a timeout submission.

## Sources

| Source | What it supports |
|---|---|
| `en/hooks/keepalive-gate.sh` and `en/hooks/tests/keepalive-gate.test.sh` | The `sdk-cli` exit, the dropped `stop_hook_active` exit, the answers to choice questions counted as the user's own messages and the `afkTimeoutMs` exclusion, and the cases that check them |
| The bundled source of Claude Code 2.1.291, searchable by these fragments: `priority:"next",stopHookActive:!0,turnAttribution:"inherit"` (an `asyncRewake` exit 2 is queued with the flag set), `malformedToolUseRetried:!1,stopHookActive:!0` (the turn resumed after a synchronous Stop hook blocks), `hook_event_name:"Stop",stop_hook_active:` (the flag reaches the Stop input), `e.asyncRewake&&io` with `io` false in print mode (a `-p` session runs the hook synchronously), and `afkTimeoutMs` in the AskUserQuestion result built on a timeout | Claude Code marking the keepalive's own turn and a turn resumed after another Stop hook's block with `stop_hook_active`, `asyncRewake` running synchronously in a `-p` session, and the field that tells a timeout submission apart |
| A live interactive session on 6 October 2026, run with the threshold set to 0 and the sleep shortened to 100 seconds | The stop after the first wake-up arrived with `stop_hook_active` true, and the patched hook kept timing and woke the session a second time on schedule |
| A `-p` run on 6 October 2026 whose Stop hook printed `CLAUDE_CODE_ENTRYPOINT` | The entrypoint is `sdk-cli` in a `-p` session and `cli` in an interactive one |
| [ADR 0014](0014-idle-sessions-past-150k-keep-their-prompt-cache-warm-with-an-async-rewake.md) | The conditions, the 50-minute sleep and the 8-hour limit this ADR keeps |
