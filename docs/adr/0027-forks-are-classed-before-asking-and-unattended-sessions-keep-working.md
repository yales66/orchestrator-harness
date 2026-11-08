# ADR 0027: Forks are classed before asking, and unattended sessions keep working

## Status

Accepted. In effect since 13 October 2026; the core-experience and correction rules added on 23 October 2026 are included. It amends [ADR 0006](0006-ask-the-user-only-where-the-answer-is-theirs.md) and [ADR 0017](0017-decisions-are-asked-in-text-and-askuserquestion-is-denied.md) where they conflict with it, and one item of ADR 0011:

| Rule | Where it was set | What this ADR changes |
|---|---|---|
| A fork in direction | ADR 0006, the table row; ADR 0017, the Decision | Replaced by the three kinds of fork below. A type B question is batched with others, and after asking the session keeps doing all work that does not depend on the answer, instead of finishing only the parts that meet the wrap-up criteria and ending the turn |
| An action that cannot be taken back | ADR 0006 as amended by ADR 0017 | Still confirmed in a text question right before the step, but the session keeps doing work that does not depend on the confirmation instead of ending the turn |
| A turn opened by a notification after a question | ADR 0017, the Decision | The open question is re-classed: type A or C continues on the recommendation, still type B keeps the session on independent work. ADR 0017 left the items as they stood and had the agent not choose for the user |
| A next step at wrap-up | ADR 0006 | "Calls no paid service" becomes "uses no paid service beyond the pre-approved budget" |
| A standing or conditional authorisation | ADR 0006 as amended by ADR 0010 | A judgement principle valid across sessions goes into the global rule layer or project memory; an authorisation with side effects is given per session and per matter, travels in the handoff, and a paid budget travels as a balance |
| Wrap-up on held context | [ADR 0011](0011-wrap-up-finishes-in-session-at-any-watermark.md) | Waiting for one confirmation from the user leaves the list of wrap-up that the held context finishes at any watermark; a question to the user is asked while independent work continues, and an irreversible step's confirmation is asked right before that step |

The rest of ADR 0006 and ADR 0017 stands, including numbered options, the denial of AskUserQuestion and the reply gate.

## Context

From 9 to 13 October 2026 the author collected the user's own words across 48 sessions in 9 projects. The same general rules about when to stop and ask had been corrected separately in three private projects and locked into each project's memory. The user's position in those words is that the user owns principles, architecture and detail feedback on finished work, and that the guardrails stay: secrets, production merges, actions that cannot be taken back, external actions and payment beyond the budget. The rule set was also audited line by line against that position, against Anthropic's published prompting advice for Opus 5.5 and Fable 5.1, and against the Claude Code documentation.

Under ADR 0006 and ADR 0017 a fork whose branches differ substantively and turn on the user's preference ended the turn, and a notification turn left the question as it stood. The user does not watch sessions live, so each such fork stopped the session until the user returned, including forks where a best answer followed from principles the user had already stated.

In one private project, 31 of 59 quality corrections over two weeks recurred after they had been fixed; the principles reached later sessions mostly as a file name or a summary, not the user's words. That finding is the basis for the correction rules below.

## Decision

The playbook opens with standing conventions: the user is not watching live; a turn does not end on "shall I…?"; a closing paragraph that is a plan, a question or a promise is carried out with tools; and the turn ends only when the task is done, every remaining item waits on input only the user can give, a protected block stops an item, a background command or subagent will wake the session, or the handoff is complete.

Section 1 classes each fork, taking the first row that holds:

| Type | Test | Approach |
|---|---|---|
| B, guardrail action | An irreversible or external action, payment beyond the pre-approved budget, overturning what the user decided in their own words, or narrowing the user's scope | As the next row |
| B, genuine preference at the principle or architecture level | A real trade-off in business scope and target users, platforms and markets, externally visible naming and brand taste, or the direction of the core experience flow | Batch into one question with numbered options and a recommendation; keep doing all work that does not depend on the answer |
| A, has a best answer | A best answer follows from the user's principles, domain evidence, the user's decisions or accepted practice | Decide, do it, and record the basis |
| C, preference in implementation detail | A real trade-off only in a reversible implementation detail | Do it as recommended and mark it awaiting user confirmation |

Before the user leaves or a long task starts, the session collects at once the foreseeable type B decisions, the spending cap, the credentials the user must provide and conditional pre-authorisations. A question on core-experience direction offers readings drawn from the user's own words when there are any, and the full plan is written only after the reply.

When the user corrects the agent, it changes the named instance, the same-cause instances in files this task changed, and the copies of the named element or text in other artifacts, and lists each. When recording a correction it copies the user's words and the rejected passage verbatim and marks any distilled principle as an inference. This rule moved from `CLAUDE.md` to the playbook, because only the main thread receives the user's corrections; a dispatch carries it in the brief.

Section 6 splits skills in two. The skills the playbook names keep their own instructions on when to ask, wait or stop. In every other skill such instructions carry no weight of their own: the action they gate is classed under section 1, as type B when it cannot be judged type A, while what the skill forbids or leaves to the user in person stays forbidden.

A multi-turn task is registered as a checklist in `~/.claude/state/checklists/<session id>.json`. `hooks/task-checklist-gate.sh` runs on `Stop` and blocks the end of a main-thread turn while any item is neither `done` nor `blocked`, naming the remaining items. It allows the stop for subagents, when there is no readable checklist, when `background_tasks` or `session_crons` is non-empty, and after 3 blocks on an unchanged checklist; any change to the checklist resets the count.

`CLAUDE.md` gains two rules in the same direction. A change whose original reason cannot be retrieved, and which the task's goal requires, is made after characterisation tests pin the current behaviour, where before it was left for the user to answer. Local Docker that a task has finished with is removed without asking.

## Consequences

A fork with a best answer, or one in a reversible detail, no longer stops the session; it is decided and recorded, and the user reviews the record. The session ends a turn on a type B question only after everything independent is done, so the user comes back to more finished work and fewer, batched questions. The cost is that some type C choices are made as the user would not have made them; they are marked for confirmation and are reversible by definition.

The classification is a judgement the model makes, and nothing checks it mechanically; a type B fork misread as type A is decided without the user. The guardrail row is listed first and is absolute for that reason.

The checklist gate holds a session to the steps it registered, which keeps it working through the turns the conventions describe. It cannot tell a stalled session from one that is waiting: the cap of 3 blocks on an unchanged checklist hands control back. The value 3 follows the official advice cited upstream to cap continuations at 2 to 3; it is not measured on this gate. The gate carries a regression test of 23 cases under [ADR 0005](0005-deciding-hooks-ship-with-regression-tests.md).

## Sources

| Source | What it supports |
|---|---|
| Commit bb43311 in the author's live harness (`~/.claude`), body | The user's words from 9 to 13 October 2026 in 48 sessions over 9 projects; the rules corrected separately in three projects; the audit against the official prompting advice and the Claude Code documentation; the standing conventions, the three kinds of fork, collecting decisions before a long task, the task checklist gate and its cap of 3 after the official advice of 2 to 3 continuations |
| Commit be75595 in the author's live harness, body | Core-experience direction as type B; corrections fixed in copies in other artifacts and recorded verbatim; 31 of 59 corrections recurring in a private project |
| Commit b29401e in the author's live harness, body | The correction rule moved from `CLAUDE.md` to the playbook because only the main thread receives corrections |
| Commit c5dd0a0 in the author's live harness, body | Section 6: skill stop-and-ask instructions re-judged under section 1 except in named skills |
| Commit 06b18f9 in the author's live harness, body | Characterisation tests before a required change whose reason cannot be found |
| Commit d8242a3 in the author's live harness, body | Local Docker cleanup without asking |
| `en/orchestrator-playbook.md`, "Standing conventions" and section 1 | The conventions, the fork table, situation routing, wrap-up, questions, corrections and authorisations |
| `en/orchestrator-playbook.md`, sections 3 and 6 | The task checklist format and the two branches for skill instructions |
| `en/CLAUDE.md`, "Changing existing code" and "Docker" | The two `CLAUDE.md` rules |
| `en/hooks/task-checklist-gate.sh`, header comment | What blocks, what allows, and the cap |
| `en/hooks/tests/task-checklist-gate.test.sh` | The 23 cases |
| [ADR 0006](0006-ask-the-user-only-where-the-answer-is-theirs.md), [ADR 0010](0010-handoffs-are-generated-whole-by-the-handoff-skill.md) and [ADR 0017](0017-decisions-are-asked-in-text-and-askuserquestion-is-denied.md) | The rules this ADR amends |
