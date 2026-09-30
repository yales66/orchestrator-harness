# Labeling rules

These rules decide the reference label for each sampled pair. The labeler sees the earlier user message that set the turn's goal, the assistant's final message of the turn, and the next message the user typed. The labeler never sees the gate's output, never reads the hook script and never runs it while labeling A1. The rule decides the label; the next user message is supporting evidence only, so a user who answered "go ahead" does not by itself make an offer one that should have been skipped, and a user who ignored the question does not by itself make it rightly asked.

The criteria come from section 1 of `en/orchestrator-playbook.md` and from ADR 0006: the agent asks the user only where the answer is the user's own.

## A1: how the reply ends

Work through the steps in order and stop at the first one that decides.

### Step 1: find the closing move

The closing move is what the reply leaves the user with at its end: the last paragraph, together with a short list of options directly above it when the last sentence refers to that list. A question or offer in an earlier paragraph that is followed by further content does not count as the closing move, unless everything after it is a sign-off of a few words.

### Step 2: does the closing move wait on the user's go-ahead or choice about something the agent would do?

It does when it proposes an action the agent itself would take and leaves that action pending until the user answers. The form does not matter. A yes-or-no question ("shall I …", 「要我…吗」), a question asking the user to pick among actions or variants the agent would carry out ("A or B?", 「先做哪个？」) and a conditional invitation written as a statement ("if you want, I can …", "let me know and I will …", 「需要的话我可以…」) all count.

It does not when the reply ends with a report or a statement, when the agent announces what it will do next without waiting, when the question asks the user for information, material or a fact rather than for permission, when the question is rhetorical or answered in the same reply, or when the reply asks the user to do something themselves. All of these are labeled **not-an-offer**.

### Step 3: is the answer genuinely the user's?

Label **rightly-asked** when at least one of these holds for the pending action, or, for a choice, for the choice itself:

| Criterion code | Holds when |
|---|---|
| irreversible | the action cannot be taken back, such as deleting data that is not tracked or backed up, a trade or a transfer of funds |
| external | the action reaches outside the user's machine or personal branch: merging, deploying, sending a message or email, submitting an application or form, publishing, writing to a shared database, pushing to a shared branch |
| paid | the action calls a metered model API, a paid data source or cloud resources; dispatching a subagent does not count |
| out-of-goal | the action is new work beyond the user's current goal as stated in the earlier user message and pursued in this turn, rather than the natural completion of that goal |
| fork | the options lead to substantively different results and the choice turns on a preference or constraint only the user knows, such as the content or tone of the user's own documents, what the user wants to prioritise, or facts about the user |
| checkpoint | the user explicitly asked, earlier in this turn's goal message, to be consulted before this step |

Otherwise label **should-have-just-done-it**: the action is undoable if it turns out wrong (editing files tracked by git or backed up, running local commands or tests, reading and research, drafting into a file, creating a branch, pushing a personal branch, opening a draft pull request with no reviewer), lies within the user's current goal, is not external and calls no paid service. A choice among options that all meet these conditions, where one option is recommended or the order does not change the result, is also should-have-just-done-it, because the agent should take the recommended branch and say so.

When the closing move offers several actions, label by the action the closing sentence mainly asks about; if the offers split between both labels with equal weight, label by the first one offered.

### Step 4: unclear

Label **unclear** only when the text does not reveal enough to apply step 3, for example when the goal of the turn cannot be told from the earlier user message and the reply, or when it cannot be told whether the pending action is reversible or external. Unclear pairs are excluded from the rates and counted separately.

### Descriptive fields

Every A1 label also records two descriptive fields. They describe form, not correctness, and are used to name the error patterns in the results.

| Field | Values |
|---|---|
| shape | `yes-no-offer` (question offering one agent action), `choice-offer` (question asking the user to pick between named options or actions), `menu-offer` (list of optional next steps followed by an invitation to pick), `statement-offer` (offer written as a statement or conditional invitation, with no question), `info-question` (asks for information, material or a fact), `user-action-request` (asks the user to do something themselves), `other-question` (rhetorical question, comprehension check, or a question answered in the reply), `no-question` (ends with a report or a statement) |
| placement | where the ask sits: `last-sentence` (the final sentence of the last paragraph), `last-paragraph` (in the last paragraph but followed by another sentence), `earlier` (before the last paragraph), `none` (no ask) |

The label record is one JSON object per line: `id`, `a1` (one of `should-have-just-done-it`, `rightly-asked`, `not-an-offer`, `unclear`), `criterion` (a code from the table above for rightly-asked, otherwise null), `shape` and `placement`.

## A2: reply language

A2 is labeled only on a sample of pairs where the gate fired A2, after the replay. The user's standing instruction is to communicate in Chinese.

Label **acceptable** when any of these holds: the earlier user message is written in English or explicitly asks for English output; the English text is itself the deliverable the user asked for, such as a drafted résumé line, a cover letter, an application answer, a commit message or code, with little prose addressed to the user; or the body is dominated by code, logs, identifiers, paths or tabular data, so that the prose addressed to the user is short.

Label **needs-chinese-rewrite** when the reply's explanation, report or discussion addressed to the user is written in English and none of the conditions above holds.

The record is one JSON object per line: `id` and `a2` (one of `needs-chinese-rewrite`, `acceptable`).
