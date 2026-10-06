---
name: rule-file-editing
description: Use when creating or editing any LLM instruction artifact (CLAUDE.md, AGENTS.md, SKILL.md, slash command .md, agent prompt, hook reminder text, output style). Load BEFORE writing the edit. Enforces behavior-delta review, branch-structured rules, and independent diff verification for deletions.
---

# Rule file editing discipline

There is only one standard for rulings: **the runtime behaviour delta**, not "does it look like filler", not "can it be derived". The delta is measured from the side of **a future reader without this round's context**: whether reading it would change their behaviour, not "I, the author, think it is useful".

## Before editing

- List the 3-5 typical runtime scenarios the file covers (who, carrying what task, at what moment they read this passage).
- If the directory is already under git (e.g. ~/.claude), first `git log -p` / `git blame` the relevant lines and get the load-bearing notes before changing anything.

## Rule on each change against the scenario table

For every addition or deletion, answer per scenario "does the behaviour in this scenario change after the edit?":

**Additions**: six kinds do not go into the always-loaded layer:
① Historical rationale (which incident, how it was done before, who made the call → belongs in the commit message / the Why of a memory)
② Repeated emphasis of the same correction (one clean rule, not three in a row)
③ Procedural content (how to invoke, how to pass parameters → belongs in an on-demand skill)
④ Environment/model snapshots (they go stale; if one must be kept, mark the date and the re-test condition)
⑤ Author-coordinate residue: a rejected alternative that was considered only during this round of editing and that the reader never had ("don't use X again / don't X"). Tempting-default test: in a new session with zero context, would the reader reach for X **on its own**? Yes → it is the reader's tempting default, and naming it negatively is load-bearing (e.g. "don't WebSearch yourself, hand it straight to the researcher subagent"); no, X lives only in your own recent line of thought → residue, cut it. Write positively, in the present tense, self-contained; when the positive branches already exhaust the decision axis, a negation is redundant.
⑥ Self-referential description: the file talking about its own scope / loading mechanism / whether it is the "single source of truth" / why it is organised this way. Zero behaviour delta for the runtime reader; it serves only "an editor thinking about architecture" → residue, cut it.
Runtime facts (configuration state, the existence of external checks) do not count as argument, and stay only if they change some decision of the reader: `researcher has web_search attached → route web research to it` stays (the fact changes the routing); one that only serves as a reason for "a rule that is already directly commanded" → cut (e.g. `autoCompact is off` for "write to disk", since writing to disk is already directly commanded; the same goes for `this file is loaded only by the main thread` / `single source of truth`).

**Self-contained references**: a cross-file pointer must resolve in **every load scope** of that file. The global layer (global skills / global CLAUDE) must not point to a narrow scope (project memory / project files / another project); if you need a reference, reference something **always present in the same scope** (its own references/, the global CLAUDE), or a **live source of truth** (`--help`, the configuration file itself); referencing a live source also avoids the staleness of ④ snapshots.

**Procedural rules are example-driven**: for the "how to use" of ③ that lands in a skill, write copyable invocations (command + placeholders + where the output goes), not a pile of the tool's internal properties/maintenance information (how the configuration is wired, which path the I/O takes, where the source is, how to change it); those force the reader to reverse-engineer usage from properties. Test: can a new session copy the command and run it successfully? If not, it is property soup.

**Deletions**: exemptions, branches and guardrail clauses look like filler but are load-bearing: they pre-resolve conflicts with absolute rules. "Derivable" ≠ deletable: derivation is a tax re-paid on every run.

**When an absolute rule needs an exception**: rewrite it as branches (Type A: … / Type B: …), each branch absolute on its own; the "general rule + exceptions" structure is forbidden.

## Wrap-up

Branch by type of change, each branch absolute on its own:
Type A, deleting or restructuring existing rule entries: dispatch a read-only subagent reviewer that does not carry this round's context, with the before/after diff, asking only for a verdict.
Type B, creating a new rule file: dispatch the same reviewer, with the full AFTER text.
Type C, wording, formatting and typo fixes for which question ① of the three questions is answered "no scenario behaviour change": do not dispatch; run the three questions below yourself. Any change to modal strength, conditions or branches is Type A; when one change mixes several types, take the strictest one.

Three questions: ① In which runtime scenarios does behaviour change (for a new file, ask instead: which sentences are load-bearing, such that without them an action would be missed) ② Check for author residue by behaviour delta: is there any sentence that cannot change any runtime reader's behaviour, especially self-referential sentences describing the file's own scope / mechanism / origin (if it cannot, cut it) ③ Does every cross-file pointer resolve in this file's load scope?

When committing, the commit message states the behaviour-delta basis for each addition and deletion, so future editors can recover the load-bearing notes with git blame.
