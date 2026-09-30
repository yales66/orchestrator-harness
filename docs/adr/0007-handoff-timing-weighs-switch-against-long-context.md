# ADR 0007: Handoff timing weighs a session switch against a longer context

## Status

Accepted. In effect since 30 September 2026. Supersedes the handoff timing of ADR 0004; the way ADR 0004 reads the watermark from transcript usage stands.

## Context

Under ADR 0004, a session stopped at the watermark's hard line wrote its handoff at once, without waiting for background tasks, and told the user to switch to a new session. Between the reminder line and the hard line, the gate reminded the session on every turn to write the handoff at the next natural break.

Both rules showed their cost in use. When all that remained was a few commit and push steps that were already settled, the hard line still made the user switch sessions midway, and the new session had to read the material again to take those steps. The reminder fired at the end of every turn above 35%, so the handoff file was rewritten again and again.

Continuing has a cost as well. Judgement worsens as the context grows, which is why ADR 0004 put a hard line on it, so a session past that line should not open work that needs new reading and new decisions.

## Decision

The timing item in section 3 of the playbook names both costs: a switch makes the new session read the material again and interrupts the user, and a longer context degrades judgement. Past the hard line the main thread weighs the two. Remaining work that the context it already holds can finish, such as committing, pushing, opening a pull request or wrapping up after a running task reports, is finished in the current session, even when it waits for one confirmation from the user; past the hard line, the next step at wrap-up in section 1 of the playbook covers only this kind of work. When open items remain and the next piece is a large block of work that reads new material and makes new judgements, the main thread writes the handoff first and tells the user to switch sessions, with a one-line start instruction. When the user ends the session, or the gate blocks a second time, the handoff is written at once. Background subagents or commands still running when a handoff is written go into its open items, marked as running, with their artifact paths.

`hooks/context-watermark-gate.sh` follows the same rule:

| Usage | Behaviour |
|---|---|
| Below 35% | Allow the stop and clear both scratchpad marks |
| From 35% to below 40% | Allow, and remind once per session that no handoff is needed yet, that no new block of work expected to cross the hard line should start, and that the playbook's timing rule applies past the hard line |
| 40% and above, first block | Block once; the reason restates the weighing: finish what the held context can finish, and write the handoff and ask the user to switch sessions before a new large block of work |
| 5 percentage points or more above the last block | Block again and ask for the handoff at once, with the unfinished steps in its open items, and for the user to be told to switch sessions |

The reminder's mark lives in the session's scratchpad, next to the mark of the last block. Without a scratchpad directory the reminder fires on every turn between the two lines, just as the block fires on every turn above the hard line. When usage falls back below 35%, as it does after compaction, the gate removes both marks, so the next crossing of either line reminds and blocks as the first one did.

## Consequences

A session past the hard line can finish a commit, push or pull request it has already settled, including one that waits for a single confirmation from the user, and the user switches sessions only before work that needs fresh reading. The handoff file is written when the weighing calls for it, and the turns above the reminder line do not rewrite it.

The weighing is the main thread's judgement, and the gate does not check it. What the gate does enforce is a block that demands the handoff at once each time usage rises another 5 percentage points, so a session that keeps going past the hard line is stopped again at regular steps. The regression test pins the single reminder, the reset after usage falls below the reminder line, and whether each block reason asks for the handoff at once.

## Sources

| Source | What it supports |
|---|---|
| `en/orchestrator-playbook.md`, §3, the Timing item | The two costs; the weighing past the hard line; the next step at wrap-up covering only work the held context can finish; the immediate handoff when the user ends the session or the gate blocks again; running tasks listed as running |
| `en/hooks/context-watermark-gate.sh`, header comment | The reminder once per session through a scratchpad mark; the first block following the playbook's timing rule; the second block asking for the handoff at once |
| `en/hooks/context-watermark-gate.sh`, the branch below the reminder line | Both marks are removed when usage falls below 35% |
| `en/hooks/context-watermark-gate.sh`, the `additionalContext` message and the two `block` reasons | What the reminder, the first block and the second block ask of the main thread |
| `en/hooks/tests/context-watermark-gate.test.sh`, the re-block suppression section | The reminder fires once per session; after usage falls below 35% the gate reminds and blocks again; the first block reason does not ask for the handoff at once and the second does |
