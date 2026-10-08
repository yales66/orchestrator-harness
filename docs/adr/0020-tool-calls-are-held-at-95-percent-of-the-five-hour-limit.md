# ADR 0020: Tool calls are held at 95% of the five-hour limit, with a keepalive every 50 minutes

## Status

Accepted. In effect since 8 October 2026. Its 50-minute rounds rest on the one-hour prompt cache of [ADR 0014](0014-idle-sessions-past-150k-keep-their-prompt-cache-warm-with-an-async-rewake.md), and it lets the last keepalive wake-up of [ADR 0019](0019-keepalive-probes-the-network-before-waking-and-hands-off-at-its-last-wake-up.md) through.

## Context

A Claude.ai Pro or Max subscription allows a set amount of usage in each five-hour window. When usage runs into that limit, a session and its subagents that are still working stop with an error partway through their task.

The input of a hook carries no usage data. Claude Code passes `rate_limits.five_hour.used_percentage`, from 0 to 100, and `resets_at`, in Unix seconds, to the status line command on a Pro or Max subscription after the session's first API response, and each session's value comes from its own latest response. The claude-hud status line plugin, when it is installed, keeps a usage cache that it refreshes at most every 5 minutes, because the usage API it queries is rate-limited.

A PreToolUse hook that times out is cancelled and the tool call proceeds; the default timeout is 600 seconds. While the main thread's tool call waits in a hook, a message the user types is queued by Claude Code and delivered only when the call returns, and one such message waited 36 minutes.

## Decision

`statusline-tee.sh` wraps the status line command: it writes `rate_limits` to `~/.claude/state/rate-limits.json` through a temp file and a rename, then hands its stdin unchanged to the status line command given as its arguments. Within one window, which it takes as two reset times less than 10 minutes apart, it never overwrites a higher value with a lower one, because an idle session that re-renders its status line carries a stale lower value while usage within a window only rises. It records `pause_since`, the time the window first reached 95%, and keeps it for that window. Input without a `five_hour` field leaves the file untouched.

`limit-pause-gate.sh` runs on PreToolUse for every tool, with matcher `*` and `"timeout": 3300`, in the main thread and in subagents alike, since hooks from settings run inside subagents. It reads two local files, the one `statusline-tee.sh` writes and claude-hud's `~/.claude/plugins/claude-hud/.usage-cache.json`, and takes the highest reading whose reset time is still in the future, because within a window a lower reading is a stale one. Reading files sends no request and spends no allowance. Below 95%, or with no reading, it allows the call with no output, so the normal permission flow applies.

At or above 95% before the reset, the hook holds the call. It sleeps until the reset, at most 50 minutes per round, checking every 3 seconds. When the reset passes within the round it allows the call, and no extra request is needed because the cache outlives the wait. Otherwise, after 50 minutes, it denies the call with a reason telling the model to make only the pause call (`: 限额暂停`) through Bash. That request is the keepalive, a cache read with a few output tokens, and the new call is held in turn. Once the reset passes, the hook allows the pause call with `permissionDecision` set to `allow`, so that no permission prompt stops an unattended interactive session, and the model re-issues the call it was paused on. The pause call stands in for the original call because re-sending that call every round would regenerate its whole input, such as the full content of a Write.

Three cases are not held:

| Case | Why it passes |
|---|---|
| `~/.claude/state/limit-pause-off` exists | It is the manual global off switch: `! touch ~/.claude/state/limit-pause-off` turns the pause off and deleting the file turns it back on |
| In the main thread, the most recent input in the transcript is the user's own (`origin.kind` of `human`), a prompt that opens a turn or a message typed mid-turn, sent after `pause_since` | A user who acts at 95% will not start large work, so the call is theirs to make. When `pause_since` is unknown, the input is not exempt |
| The most recent input is the keepalive's last wake-up | That turn writes a handoff, and holding it past an hour would lose the cache the handoff reads. A subagent passes too when the main transcript did not record its id before that wake-up, which makes it one that turn dispatched, such as the researcher that drafts the handoff; a background subagent dispatched earlier had its id recorded at dispatch and stays held, and a synchronous one cannot outlive the turn that dispatched it |

Everything else stays held. A turn that started before the crossing is held, including a fully autonomous run the user launched earlier, because the user did not start it in view of the limit. When a background notification, a subagent report or a keepalive wake-up other than the last arrives after the user's input, later calls are held again, so an autonomous task cannot ride on a turn the user started. Other subagents are always held, including those dispatched in a turn the user started past 95%, because the exemption covers only the user's own input to the main thread, and a user who has reached 95% is not starting large work.

While it holds a call in the main thread, the hook checks the transcript every 3 seconds for a new `queue-operation` line of `enqueue` whose content is not a notification. When it finds one, it denies the held call at once with a reason asking the model to handle the user's message first and to stop after it, leaving the paused work for after the reset.

On any error the hook allows the call, because it sits in front of every tool and must not lock a session up. Its timeout of 3300 seconds lies above the 3000-second round, so Claude Code does not cancel the hook and let the call through.

Two alternatives were rejected:

| Alternative | Why it was rejected |
|---|---|
| Refreshing claude-hud's usage cache every minute | It hits the rate limit of the usage API the plugin queries |
| Taking the reading from whichever file is newer | An idle session that re-renders its status line writes a stale lower value as the newest one, and claude-hud's cache lags and is rounded, so the reading jumped around 95% and let calls through that should have been held. The first real trigger exposed this, which is why the hook takes the maximum |

## Consequences

A session or subagent that reaches 95% of the five-hour limit waits for the reset instead of failing partway through its work, and a request every 50 minutes keeps its prompt cache warm until then. The user can still act after the crossing, and the queue check lets a message they type during a hold through within seconds.

The status line wrapper and the pause need a Claude.ai Pro or Max subscription, since Claude Code passes `rate_limits` to the status line only there. A change to the `statusLine` setting takes effect in running sessions without a restart, as checked live on 8 October 2026.

The design has three known limits. Usage data updates only when some session receives a model response, so several busy sessions can still cross 100% within the step between two readings. Concurrent status line writes can briefly store a lower value, which the next render corrects. The fix that takes the maximum of the two files has not yet run through a real 95% window.

The pause was checked by unit tests, by an end-to-end run with `claude -p` and haiku against a fake usage file, and by a real overnight trigger, which ran the earlier version that took the newer file. In the end-to-end run the main thread was held, made the pause call, was released at the reset and re-issued its original call; a subagent went through the same cycle, and once re-issued its original call instead of the pause call, which the hook held again. In the overnight trigger on 8 October 2026 the hook held calls for 50 minutes per round across four rounds, so Claude Code honours the 3300-second timeout, for which its documentation states no upper limit.

## Sources

| Source | What it supports |
|---|---|
| `en/hooks/limit-pause-gate.sh` and `en/hooks/tests/limit-pause-gate.test.sh` | The two usage files and the highest reading, the 95% threshold, the 50-minute rounds and 3-second checks, the pause call and its `allow`, the three exemptions, the queue check, and the cases that check them |
| `en/hooks/statusline-tee.sh` and `en/hooks/tests/statusline-tee.test.sh` | The wrapper's write through a temp file, the rule against lowering a value within a window, `pause_since`, and the cases that check them |
| `en/settings.example.json` | The PreToolUse entry with matcher `*` and `"timeout": 3300`, and the `statusLine` command |
| Claude Code status line documentation, https://code.claude.com/docs/en/statusline.md | `rate_limits.five_hour.used_percentage` and `resets_at` reach the status line on Pro and Max subscriptions after the first API response |
| Claude Code hooks documentation, https://code.claude.com/docs/en/hooks.md | A PreToolUse hook that times out is cancelled and the call proceeds, the default timeout of 600 seconds, and settings hooks running inside subagents |
| The author's end-to-end runs with `claude -p` and haiku, and the real trigger overnight to 8 October 2026 | The hold, keepalive and release cycle in the main thread and in subagents, the approval prompt that the `allow` avoids, the 36-minute wait of a queued message, the four 50-minute rounds, and the stale lower readings that picking the newer file let through |
