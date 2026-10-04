# ADR 0006: Ask the user only where the answer is theirs

## Status

Accepted. In effect since 29 September 2026. Its choice of subagent for a search of session transcripts is superseded by [ADR 0008](0008-subagent-effort-per-kind-of-dispatch.md). In the row on a standing or conditional authorisation, the rule that one meant to carry across sessions goes into project memory and into the handoff file is superseded by [ADR 0010](0010-handoffs-are-generated-whole-by-the-handoff-skill.md): one valid across tasks goes into project memory, and one binding only this task's remaining work travels in the handoff. In the row on a next step at wrap-up, the classing of merging as external is superseded by [ADR 0012](0012-merging-own-pr-is-undoable-outside-production.md).

## Context

Every time the agent stops to ask the user something, work waits until the user sends another message. Many such questions concern a next step that lies within the user's current goal and can be undone if it turns out wrong, such as updating a related file or pushing a personal branch, and the user almost always agrees to it. A reply that ends by offering such a step ("Shall I also update the README?") has the same effect: a step the agent could have finished becomes a round of waiting, and the user has to come back only to say "go ahead".

Some questions do belong to the user. An action that cannot be taken back, such as a trade, a transfer of funds or the deletion of data, cannot be repaired after the fact, so it needs the user's confirmation. A fork whose branches produce substantively different results, where the choice depends on a preference or constraint only the user knows, cannot be settled from the repository. Other questions look like decisions but are facts, such as whether something was done or tested, and the repository and its git history can often answer them without the user.

## Decision

The orchestrator playbook decides when the agent asks, by situation:

| Situation | What the agent does |
|---|---|
| An action that cannot be taken back | Does the reversible preparation, and confirms with AskUserQuestion right before the step that cannot be taken back |
| A fork in direction | Asks only when the branches produce substantively different results and the choice depends on preferences or constraints only the user knows; otherwise takes the recommended branch and states in one opening sentence which branch it chose and why |
| A next step at wrap-up | Does it and then reports when it lies within the user's current goal, is undoable if done wrong, is not external and calls no paid service. Undoable covers changing files tracked by git or already backed up, pushing a personal branch and opening a draft PR with no reviewer; external covers merging, deploying, sending messages or email, submitting applications or forms, publishing and writing to a shared database; paid covers metered model APIs, paid data sources and cloud resources, and dispatching a subagent does not count |
| A standing or conditional authorisation | Treats it as in effect for the rest of the session, covering only the objects and changes it referred to when given; new scope does not inherit it, and it ends as soon as the user takes it back. An authorisation meant to carry across sessions goes into project memory and into the handoff file |
| A question about a fact | Checks the repository and the git history first, dispatches a researcher when the session transcripts must be searched, and asks only when nothing is found, saying where it looked |

When a decision does go to the user, each pending item states the background, how each option affects the user and the agent's recommendation, without session-internal numbers or self-coined terms.

`hooks/reply-gate.sh` runs on `Stop` and checks how the reply ends. When the last sentence of the last paragraph is an offer such as "Shall I …?", "Would you like me to …?" or 「要我…吗」, it blocks the stop once, and its reason restates the wrap-up criteria and the way to put a decision to the user. Fenced code, inline code and URLs are stripped first, and a question in an earlier paragraph or followed by a statement does not count, because the action has then already been decided. A stop that is already continuing because of a `Stop` hook is allowed, so the gate never blocks twice in a row.

## Consequences

A next step that is undoable, within the goal, internal and free is taken and reported rather than offered, so the user sees it already done and can undo it. Steps that cannot be taken back, external steps and paid steps still wait for the user, as do forks that turn on the user's own preferences. The cost is that the agent sometimes takes a step the user would not have chosen, and the conditions on the wrap-up rule confine that to steps that can be reverted.

The reply gate recognises offers by a fixed set of phrases in Chinese and English, so an offer worded another way passes. A question that the user really does need to answer, if it ends with one of those phrases, costs one extra turn: the gate blocks once, and the agent keeps the question with its background, consequences and recommendation, and the next stop is allowed. The gate carries a regression test under ADR 0005.

## Sources

| Source | What it supports |
|---|---|
| `en/hooks/reply-gate.sh`, item A1 of the header comment | An offer at the end of a reply turns a reversible action into a round of waiting, and only the last sentence of the last paragraph counts |
| `en/hooks/reply-gate.sh`, header comment | Code and URLs are stripped, and a stop already continuing because of a `Stop` hook is allowed |
| `en/hooks/reply-gate.sh`, `ZH_OFFER`, `EN_OFFER` and `ends_with_offer` | The Chinese and English offer phrases and how the last sentence is found |
| `en/hooks/reply-gate.sh`, the reason added when `ends_with_offer` matches | The block reason restates the wrap-up criteria and how to put a decision to the user |
| `en/settings.example.json`, the `Stop` entry | The reply gate is registered on `Stop` |
| `en/hooks/tests/reply-gate.test.sh`, the A1 sections and the loop-guard and malformed-input section | The cases for offers that must be blocked, questions and statements that must pass, the loop guard and malformed input |
| `en/orchestrator-playbook.md`, §1, the table row on actions that cannot be taken back | Actions that cannot be taken back are confirmed right before that step |
| `en/orchestrator-playbook.md`, §1, the table row on a fork in direction | When a fork goes to the user |
| `en/orchestrator-playbook.md`, §1, the paragraph on next steps at wrap-up | Next steps at wrap-up, what counts as undoable, external and paid, and how a pending decision is written |
| `en/orchestrator-playbook.md`, §1, the paragraph on standing or conditional authorisation | Scope and end of a standing authorisation |
| `en/orchestrator-playbook.md`, §1, the paragraph on asking the user about a fact | Facts are checked before the user is asked about them |
