---
name: memory-audit
description: "Audits and cleans up project memory (the MEMORY.md index and memory/*.md), decides for each entry whether to keep, delete or merge it, and carries out the deletions and the index rebuild; also used for the admission check before writing a single new memory. Triggers: the user saying there are too many memories / clean up memory / are the memories still useful, the index being visibly bloated, finding two memories that say the same thing, or being about to write a new memory."
---

# Memory audit

## Admission criterion

A memory deserves to exist if and only if it can answer: **which specific future action exists that will differ because it was read, compared with not having read it?** If you cannot write down that action, delete it; when writing a new memory, put it through this same question first.

Five cases that condemn a memory; check each one in turn:

1. The fact can be looked up in the repository on the spot (code, git log, docs/adr, CI configuration, package.json).
2. The rule is already in CLAUDE.md or in some skill.
3. The state it describes no longer holds (shipped, retired, superseded, to-do completed), and deleting it loses nothing that still constrains future actions.
4. The **whole entry** is a log of "what was done" (process narrative, what was done on some day); a session reference appearing in a single sentence does not condemn it.
5. It says the same thing as another entry. **The merge criterion is "will be read at the same moment"**, not topical similarity; if four entries have to be read at the same moment, they should be one.

For entries that are kept but verbose (over about 3000 characters), give a separate compression target: cut process narrative, comparison figures from closed cases, and rulings already recorded in an ADR (architecture decision record); keep pitfalls and constraints.

The `description` field is for judging relevance, not a summary of the content; the body must not explain why the memory exists.

## Two layers of size, counted separately

The index `MEMORY.md` is paid for by every session and by **every subagent** (measured in 2026-09: a subagent loads both CLAUDE.md files and MEMORY.md, contrary to what the official documentation says; to re-test, dispatch a haiku and ask it only whether a distinctive string from the index is in its context), while memory bodies are paid for only when read. The gain from compressing the index is multiplied by the number of dispatches; the gain from compressing bodies is realised only on a hit. Compress the index first.

## Procedure

1. **Locate and back up**. The memory directory is `~/.claude/projects/<the project's absolute path with / replaced by ->/memory`. It is usually not under any version control (`~/.claude` is a git repository, but the `/*` in its `.gitignore` keeps `projects/` out entirely), so deletions cannot be rolled back:
   ```
   D=~/.claude/projects/<slug>        # parent directory of memory
   tar -czf "$D/memory-backup-$(date +%Y%m%d-%H%M%S).tar.gz" -C "$D" memory
   ```
   The backup archive goes next to memory as its sibling; do not put it inside memory.
2. **Read everything and rule**. Finding duplicates across entries requires seeing everything at once and cannot be split up; when this is dispatched, the prompt must hard-code that the agent only rules and does not execute, must not touch the memory directory, and writes a ruling table to an output file.
3. **Spot-check the rulings**. For any ruling whose reason is "already in the repository / already in the always-loaded layer", pick the few whose deletion would lose the most and verify them with grep on the ground; do not execute the list as given.
4. **Read back the runtime**. A dispatched agent can only compare against the repository and cannot verify live state; for any claim involving timers, services or data freshness, read it back once via ssh or a database query before deciding.
5. **The main thread executes** deletions, writes and renames; do not hand these to a subagent.
6. **Rebuild the index**: generate it from the `name` and `description` in each file's frontmatter, and check four things: every file the index points to exists, there are no orphan files left unindexed, `name` matches the file name, and every inbound `[[link]]` in the surviving memories has a target (deletions and renames both create dangling links, and so does `name` using hyphens while the file name uses underscores).

## Pitfalls

An identifier recorded in a memory may be wrong, so looking it up may find nothing and lead to a false verdict of "does not exist"; when a lookup finds nothing, first use pattern matching (prefix, keywords) to confirm whether it is real, then conclude.

An entry whose content no longer matches its file name after a rewrite must be renamed; before renaming, grep all memories to confirm there is no inbound `[[link]]`.

If the audit agent's reason for "should be deleted" is an inference rather than evidence (e.g. "mechanism X already guarantees this structurally"), overrule it and keep the entry, unless you can point out that the mechanism covers every scenario.
