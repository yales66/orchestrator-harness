# ADR 0017: Decisions are asked in text, and AskUserQuestion is denied

## Status

Accepted. In effect since 6 October 2026. Supersedes the confirmation with AskUserQuestion before a step that cannot be taken back in [ADR 0006](0006-ask-the-user-only-where-the-answer-is-theirs.md); the rest of ADR 0006 stands.

## Context

The playbook had the agent confirm a step that cannot be taken back, and settle a fork whose choice turns on the user's own preferences, with AskUserQuestion. While an AskUserQuestion dialog is open, the turn is stopped in the middle of a tool call. An `asyncRewake` wake-up, such as the keepalive's, can then only queue behind it, so the keepalive cannot keep the prompt cache warm while the question waits, and once the wait passes one hour the cache expires.

The author's session transcripts show the cost. Of the choice questions answered after more than 60 minutes, 4 of 5 were followed by a request that rewrote the whole prompt cache; of those answered after 5 to 55 minutes, 95 of 96 read it from the cache.

Claude Code 2.1.291 has a timeout for choice questions, `askUserQuestionTimeout` or `CLAUDE_AFK_TIMEOUT_MS`, but its countdown keeps returning to zero while the terminal has focus, so it cannot submit the question before the cache expires for a user who left the terminal in front.

When AskUserQuestion is listed under `permissions.deny`, the tool disappears from the list of tools the model is given, as tested in a session.

## Decision

`settings.example.json` in both copies lists `"AskUserQuestion"` under `permissions.deny`.

The playbook asks every decision in text. Before a step that cannot be taken back, the agent asks for confirmation in a text question and ends the turn to wait for the reply. At a fork whose choice turns on preferences or constraints only the user knows, it first finishes the parts that do not depend on the answer and can be undone, then asks in a text question and ends the turn. Each option of a pending item is numbered, so the user can reply with the number.

A turn that a background notification, a subagent's report or a keepalive wake-up opens after the question is asked is not a reply. The agent handles only that notification, leaves the pending items to the user as they stand, and does not choose for the user.

## Consequences

While a decision waits, the session has ended its turn, so the keepalive of [ADR 0014](0014-idle-sessions-past-150k-keep-their-prompt-cache-warm-with-an-async-rewake.md) and [ADR 0015](0015-keepalive-keeps-timing-after-its-own-wake-up-and-skips-headless-sessions.md) covers the wait as it covers any idle session past 150,000 tokens.

The user loses the dialog in which an option is picked by clicking, and replies by typing the option's number instead.

Asking in text does not add a round trip per decision. After the user answers a choice question, Claude Code sends another request too, carrying the answer as a tool result, just as it sends the user's typed reply.

Because the keepalive's turns and other notifications are not replies, a decision stays open until the user answers it, even when the session is woken many times in between.

The handoff skill's extraction of choice answers and the keepalive's counting of them as the user's own messages stay, for installations that do not deny the tool and for transcripts written before it.

## Sources

| Source | What it supports |
|---|---|
| `en/settings.example.json`, `permissions.deny` | AskUserQuestion is denied |
| `en/orchestrator-playbook.md`, §1, the table rows on actions that cannot be taken back and on a fork in direction | Confirmation and forks are asked in text, after the parts that do not depend on the answer, and the turn ends |
| `en/orchestrator-playbook.md`, §1, the paragraph on decisions that go to the user | Numbered options, and turns opened by notifications, subagent reports or keepalive wake-ups are not replies |
| The author's Claude Code session transcripts | Choice questions answered after more than 60 minutes: 4 of 5 followed by a full cache rewrite; after 5 to 55 minutes: 95 of 96 read from the cache |
| Claude Code 2.1.291, the choice-question timeout `askUserQuestionTimeout` / `CLAUDE_AFK_TIMEOUT_MS` | The countdown keeps returning to zero while the terminal has focus |
| A session run with AskUserQuestion under `permissions.deny` | The tool is removed from the model's tool list |
| [ADR 0011](0011-wrap-up-finishes-in-session-at-any-watermark.md) | The handoff skill already asks its pending question in plain text, because a scheduled wake-up does not fire while AskUserQuestion waits |
| [ADR 0014](0014-idle-sessions-past-150k-keep-their-prompt-cache-warm-with-an-async-rewake.md) and [ADR 0015](0015-keepalive-keeps-timing-after-its-own-wake-up-and-skips-headless-sessions.md) | The keepalive that covers a session after its turn ends, and its counting of choice answers |
| [ADR 0006](0006-ask-the-user-only-where-the-answer-is-theirs.md) | The detail this ADR supersedes |
