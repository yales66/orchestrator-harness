# ADR 0002: Every subagent brief carries six elements

## Status

Accepted. Under version control since 11 July 2026; the read-only return format took its current form on 19 September 2026.

## Context

A subagent has no conversation history. It knows its brief, `CLAUDE.md` and whatever it reads for itself, so every fact the main thread has already settled and leaves out of the brief is something the subagent has to rediscover or guess. The playbook therefore puts confirmed conclusions into the brief and gives each dispatch an objective test of "done", so that a subagent starts from conclusions and its work runs to a verifiable end.

Writing tasks and read-only tasks need different things. A task that changes files needs constraints on what it may touch and a command that proves it worked; a research or review task has neither.

## Decision

Every dispatch prompt is built from six elements:

| Element | What it holds |
|---|---|
| 1. Goal | A one-sentence task and an objective test of "done" |
| 2. File scope | The exact paths the subagent may modify, read-only references with line ranges, and an output file path when a read-only dispatch must write its full findings to disk |
| 3. Known context | Confirmed facts such as interface signatures, data structures, pitfalls and technical decisions; large decisions go to disk as a contract and are passed by path, and whole files are left for the subagent to read |
| 4. Constraints | Files and dependencies that must not be touched and existing patterns that must be reused |
| 5. Self-verification | The commands to run before delivery and their expected result |
| 6. Return format | For writing tasks, four fixed sections: changed files, verification, downstream interface facts, deviations and leftovers. For read-only tasks, either the conclusion with its evidence when the conclusion stands on its own, or the conclusion, the evidence coordinates and the path of the findings file when a judgement needs the material read through |

A writing dispatch is not sent while any of the six is missing. A read-only dispatch is not sent while element 1, 2, 3 or 6 is missing; elements 4 and 5 do not apply to it. The return format fixes the sections of what comes back and puts no cap on the length of the return as a whole, and element 2 carries the output path so that the pointer in element 6 always resolves.

## Consequences

Implementation is dispatched only once its judgement calls are fixed and the six elements can be written out; open decisions stay with the main thread. The main thread reads a bounded, predictable return and can check a writing task against the verification section without replaying the subagent's work.

A writing subagent in the main thread's working tree uses git read-only and does not commit; the main thread commits once per dispatch round. This is written into element 4 of each such brief.

Briefs take longer to write than a one-line instruction, and the main thread has to have settled the facts in element 3 before it can dispatch.

## Sources

| Source | What it supports |
|---|---|
| `en/hooks/orchestrator-playbook-session-start.sh`, header comment | A subagent loads `CLAUDE.md` but not what the main thread's `SessionStart` hook injects |
| `en/orchestrator-playbook.md`, §0 | Implementation is dispatched only when its judgement calls are fixed and the six elements can be written out; decisions stay with the main thread |
| `en/orchestrator-playbook.md`, §2, first bullet | The deliverable of a read-only dispatch is bounded to one judgement, command or yes-or-no with its evidence |
| `en/orchestrator-playbook.md`, §2, second bullet | Writing subagents use git read-only and the main thread commits once per dispatch round |
| `en/orchestrator-playbook.md`, §2, subsection "The six elements of a dispatch prompt" | Current text of the six elements |
| `en/orchestrator-playbook.md`, the opening line of that subsection | A writing dispatch needs elements 1 to 6, a read-only dispatch needs 1, 2, 3 and 6 |
| `en/orchestrator-playbook.md`, elements 1 and 3 of that subsection | An objective test of "done"; confirmed conclusions go into the brief |
| `en/orchestrator-playbook.md`, element 6 of that subsection | The two return shapes, the output path taken from element 2, and no cap on the return as a whole |
