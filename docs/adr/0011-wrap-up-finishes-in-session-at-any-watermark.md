# ADR 0011: Wrap-up finishes in the current session at any watermark, and a pending decision gets a wake-up before the cache expires

## Status

Accepted. In effect since 4 October 2026. Extends [ADR 0007](0007-handoff-timing-weighs-switch-against-long-context.md): the wrap-up that ADR 0007 finishes in the current session past the hard line is now finished there at any watermark. ADR 0007's weighing before a new large block of work, and its immediate handoff when the user ends the session or the gate blocks a second time, stand. The 50-minute wake-up now runs as a background `sleep 3000` instead of a CronCreate one-off, because the auto mode classifier denies CronCreate as unauthorized persistence (see [ADR 0014](0014-idle-sessions-past-150k-keep-their-prompt-cache-warm-with-an-async-rewake.md)).

## Context

ADR 0007 has a session past the watermark's hard line finish the wrap-up its context already covers, such as a commit, a push or a pull request, instead of handing off. It said nothing about the same wrap-up below the hard line, and there the main thread sometimes handed off on its own judgement. In 28 pairs of a handoff and the session that took it over, 5 handoffs should not have been written, because what remained was wrap-up, and all 5 were the main thread's own decision: none followed a block by the gate or a request from the user. The new session read the material again and then finished in a step or two, or came back to ask the user.

Such a handoff costs more than the work it hands over. Generating a handoff costs a median of $1.88 in all, counting the main thread's extraction, writing the brief and the review, over 27 handoffs, and the new session's rebuild of its context from the handoff a median of $0.20, while the wrap-up itself needs no new reading in the session that already holds the context.

A handoff can also be needed while the session waits for the user. When a question needs the user's decision and a large block of work follows it, the session stops and waits. If the user comes back after the prompt cache has expired, an hour in the Claude Code setting of October 2026, the first request rewrites the cache from the full context: a median of $1.62 after more than an hour idle, and about $3.04 for a context of 380,000 tokens, before any work is done. A handoff written while the cache is still warm lets the user resume in a new session at the rebuild cost instead.

## Decision

Section 3 of the playbook, in its Timing item, has remaining work that the held context can finish, committing, pushing, opening or merging a pull request, wrap-up after a running task reports and waiting for one confirmation from the user, finished in the current session at any watermark and without a handoff, unless the gate blocks again. A large block of work that needs new material and new judgements still follows ADR 0007: past the hard line the handoff comes first.

Step 0 of the handoff skill checks the entry before anything is generated:

| Situation | What the main thread does |
|---|---|
| The user asked for a handoff, ends the session or passes the task to another session, or the watermark gate has blocked again | Goes on to generate the handoff |
| Every remaining open item is wrap-up | Generates no handoff and goes back to finish the work |
| A question needs the user's decision and a large block of work follows it | Asks in plain text and ends the turn, and sets a one-off wake-up 50 minutes out with CronCreate. If the user has not answered by then, the wake-up generates the handoff with the question written into its open items as awaiting the user. If the user answers first, the wake-up is deleted with CronDelete and step 0 runs again with the answer. Without CronCreate the main thread does not ask and generates that handoff at once |
| Anything else | Goes on to generate the handoff |

The question is asked in plain text rather than with AskUserQuestion, because a scheduled wake-up does not fire while AskUserQuestion is waiting. The 50 minutes are the cache lifetime of one hour less 10 minutes, so the handoff is written before the cache expires; the skill states this, and a different cache lifetime calls for that lifetime less 10 minutes, and with a cache of 10 minutes or less the session sets no wake-up and generates the handoff at once.

## Consequences

A session finishes its commit, push, pull request or merge where it stands, and the user switches sessions only before work that needs fresh reading. The judgement that remaining work is wrap-up is still the main thread's, and the gate does not check it; the gate's further blocks at every rise of 5 percentage points remain the bound on a session that keeps going.

While the user is away from a pending decision, the session writes its handoff once, at about 50 minutes, and a user who answers sooner continues in the same session. The 50 minutes assume a one-hour cache. With a shorter cache the wake-up fires after the cache has already expired, so the handoff it writes pays for a cache rewrite and saves nothing; the README gives the premise and how to adjust the wake-up, and a cache of 10 minutes or less gets no wake-up, the handoff being generated at once.

## Sources

| Source | What it supports |
|---|---|
| `en/orchestrator-playbook.md`, §3, the Timing item | Wrap-up finished at any watermark; the exception when the gate blocks again; a large block of work handed off past the hard line; an immediate handoff when the user ends the session or passes the task on |
| `en/skills/handoff/SKILL.md`, step 0 | The entry check, the plain-text question, the 50-minute wake-up and its instruction, CronDelete on an early answer, the fallback without CronCreate, and the source of the 50 minutes |
| The author's session transcripts, read on 4 October 2026 | The 28 pairs and the 5 unneeded handoffs, all of them the main thread's own decision; the medians of $1.88 per handoff, $0.20 per rebuild and $1.62 per cache rewrite after an hour idle, and about $3.04 at 380,000 tokens |
| `docs/adr/0007-handoff-timing-weighs-switch-against-long-context.md` | The weighing this ADR extends |
