---
name: grilling
description: Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrases.
---

Interview the user relentlessly until you reach a shared understanding. Map this as a **design tree**: every decision branches into the decisions that hang off it.

Work the tree in **rounds**. The **frontier** is every decision whose prerequisites are already settled: the questions you can ask _now_ without guessing at answers you haven't heard yet.

The interview record is this task's progress source; if the task has none, create `PROGRESS.md` in the task's working directory and only ever append to it.

Before asking each round, sort every frontier decision into one of three types and handle each type as stated. A decision that involves something irreversible, an action visible outside the project, spend beyond what was pre-approved, overturning something the user personally decided, or narrowing a scope the user set is type B, whether or not it has a best answer.

- **A, has a best answer**: the answer follows from decisions the user already made, principles the user has stated, evidence about the real domain, or the field's established practice, the other options are filler, and the decision involves none of the actions listed above. Settle it yourself, record the decision and its basis in the interview record, and mention it in one line in the round.
- **B, a real preference at the level of principle or architecture**: after thinking it through a real trade-off remains, and it concerns business scope or target users, platform or market, or the naming and brand taste of products and features visible outside the project (naming code identifiers is type C). Put it to the user.
- **C, a real preference on an implementation detail**: a real trade-off remains, but it is an implementation detail and a wrong choice can be undone. Settle it on your recommendation, record it marked "pending user confirmation", and list it in one line in the round so the user can change it after seeing the result.

Settling A and C decisions pushes the frontier outward; recompute it and sort again until every frontier decision left is type B. Ask that whole set in one round: number each question and give your recommended answer. Then wait for the user's answers before the next round.

Format a round like so:

```
❓ **Q1** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

➡️ <your recommended answer>

---

❓ **Q2** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

➡️ <your recommended answer>
```

Each round the user answers reshapes the tree: settled decisions push the frontier outward and unblock questions that depended on them. Recompute the frontier and ask the next round. A question whose answer depends on another question still open in this round belongs to a _later_ round, not this one.

Finding _facts_ is your job, never the user's: don't ask the user for anything you could look up yourself. If a lookup is dispatched, only questions downstream of it wait; ask the rest of the frontier now. Type B decisions are the user's: put each to them and wait.

The session is done when the frontier is empty: every branch of the design tree visited, nothing left silently assumed.
