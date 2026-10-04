# ADR 0010: Handoffs are generated whole by the handoff skill, and a hook denies hand edits

## Status

Accepted. In effect since 4 October 2026. Supersedes the handoff format that ADR 0004 placed in section 3 of the playbook; the format now lives in the handoff skill, and the way ADR 0004 reads the watermark stands. Supersedes, in the row of ADR 0006 on a standing or conditional authorisation, the rule that an authorisation meant to carry across sessions goes into both project memory and the handoff file; the rest of ADR 0006 stands.

## Context

A handoff file that the main thread writes by hand drifts from the session it describes. When a later session patches the same file in place, its decisions section only ever grows: entries stay after the work they constrained is done, and nothing removes them. The rule that the user's own words go into the handoff takes effect only at the moment of writing, and a patch does not rescan the whole conversation, so a decision the user made earlier in the session can be left out without anyone noticing.

The user's input can be read mechanically from the session transcript, but only if every form it takes is recognised. Claude Code records the answer to a multiple-choice question with one of two opening phrases. An extraction that knew only one of them missed every answer opening with "The user answered:": over the seven days before this decision, it dropped 40 answers across 31 sessions, and each dropped answer could carry an authorisation or a rejection.

The handoff format and its rules for evidence sat in section 3 of the playbook, which reaches only the main thread (ADR 0001). A subagent asked to write the handoff could not read them unless the main thread copied them into the brief.

## Decision

`HANDOFF.md` is produced only through the handoff skill, and each time it is generated whole; an existing handoff and the task's progress source are material for the new one, not a file to patch. Progress goes into the task's own progress source, or into an append-only `PROGRESS.md` when it has none, and `HANDOFF.md` does not count as a progress source. The skill runs these steps:

| Step | What it does |
|---|---|
| Extract | `scripts/extract.py` reads the session transcript and writes every input the user gave, typed messages, slash commands, answers to choice questions in either wording and rejected tool calls, numbered in time order, with the git state of each repository the task touches. `--transcript` is required, because a parallel session in the same project can own the newest transcript file |
| Brief | The main thread writes only what the extraction and the repositories cannot supply: the goal in the user's words, the open items with how to check them, key commands run and their results, the choices that still bind remaining items, running tasks and pitfalls found |
| Generate | A `researcher` that carries none of the main thread's context writes `HANDOFF.new.md` and a routing file from the brief, the extraction and the old handoff, following the structure and evidence rules in the skill, which it can read. The read-only guard lets it create these files but not change them afterwards, so it checks before it writes and reports any error it finds later instead of editing |
| Review | The main thread takes the first branch that holds. New input or a repository change since the extraction that bears on the open items: extract again and revise the brief. A brief that must change what the open items are, or a draft whose open items do not match the brief: delete the draft and send the corrections with SendMessage to the same `researcher` to rewrite. Other errors: the main thread fixes the draft directly. No errors: go on. A fresh dispatch is used only when the message cannot be delivered |
| Finalize | `scripts/finalize.sh` moves `HANDOFF.new.md` into place and archives the previous version under `.handoff-archive/` |
| Route | Entries in the routing file that hold across tasks go into project memory through the admission check of `memory-audit`; an authorisation that binds only this task's remaining work travels in the handoff |

Having the original `researcher` revise its draft costs $0.16 to $0.31 for that one dispatch, against $0.61 to $1.26 for the one dispatch of a fresh `researcher` on the same handoff, because the original has already read the material. Both figures count that single dispatch only, not the whole handoff. It still holds none of the main thread's context, so the reason for handing generation to a fresh context is unaffected.

`hooks/handoff-guard.sh` runs on PreToolUse for `Edit|Write|MultiEdit|NotebookEdit|Bash`, in the main thread and in subagents alike. It denies an edit or write whose target is named exactly `HANDOFF.md`, and a shell command that writes it in place: redirection, `tee`, in-place `sed`, `perl` or `awk`, `ed` or `ex`, `truncate`, `cp`, `mv`, `rm` or `ln` with it as source or target, `git checkout`, `restore`, `rm` or `mv` on it, and inline interpreter code that names it. Reading it, writing `HANDOFF.new.md` and running `finalize.sh` pass. The context watermark gate's block reasons point to the handoff skill and carry the transcript path, which the extraction step needs.

## Consequences

Every handoff is rebuilt from the full record of what the user said, so a decision made early in the session reaches the next one, and entries about finished work fall away with that work. A handoff costs a `researcher` dispatch; in the author's sessions a whole handoff, counting the main thread's extraction, writing the brief and the review, cost a median of $1.88 over 27 handoffs, which is why section 3 of the playbook keeps wrap-up out of handoffs (ADR 0011).

The guard stops the incidental patch, the edit a model makes in passing; it does not stop a deliberate bypass, such as a script file that writes the handoff, because a script run from a file is not inspected. The playbook's takeover item refers to section ⑤ of the handoff, which the skill defines, so the playbook and the skill ship together. The guard carries a regression test under ADR 0005, and the extraction and finalize scripts carry pytest tests, including both openings of a choice answer.

## Sources

| Source | What it supports |
|---|---|
| `en/skills/handoff/SKILL.md`, steps 1 to 8 | The extraction, brief, generation, review branches, finalize and routing steps; the `researcher` checks before writing and reports later errors; the rewrite by the original `researcher` through SendMessage |
| `en/skills/handoff/SKILL.md`, "Handoff structure" | The structure and evidence rules the generating `researcher` follows, and where an authorisation goes |
| `en/skills/handoff/scripts/extract.py`, module docstring and the answer prefixes | What counts as the user's input, both openings of a choice answer, and why `--transcript` is required |
| `en/skills/handoff/scripts/test_extract.py` | The tests that pin which transcript records count as the user's input |
| `en/skills/handoff/scripts/finalize.sh` | Moving the new handoff into place and archiving the old one |
| `en/hooks/handoff-guard.sh`, header comment | What the guard denies and allows, and that it applies to every thread |
| `en/hooks/tests/handoff-guard.test.sh` | The guard's cases; their number is the `PASS=<n>` the test prints |
| `en/hooks/context-watermark-gate.sh`, the two `block` reasons | The reasons name the handoff skill and carry the transcript path |
| `en/orchestrator-playbook.md`, §1, the paragraph on standing or conditional authorisation | An authorisation valid across tasks goes into project memory; one binding this task's remaining work travels in the handoff |
| `en/orchestrator-playbook.md`, §3, the Phasing, Handoff and Taking over items | Progress goes to a progress source; `HANDOFF.md` only through the skill; the takeover restates ⑤ |
| The author's session transcripts, read on 4 October 2026 | The 40 answers in 31 sessions missed by the single-wording extraction; the cost of a rewrite against a fresh dispatch; the median cost of a handoff |
| `docs/adr/0004-context-watermark-read-from-transcript-usage.md` and `docs/adr/0006-ask-the-user-only-where-the-answer-is-theirs.md` | The details this ADR supersedes |
