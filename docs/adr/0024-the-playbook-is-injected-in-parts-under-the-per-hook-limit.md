# ADR 0024: The playbook is injected in parts, each under the per-hook limit

## Status

Accepted. In effect since 7 November 2026. It amends the delivery detail of [ADR 0001](0001-orchestration-rules-reach-only-the-main-thread.md): `hooks/orchestrator-playbook-session-start.sh` no longer injects the whole playbook as one `additionalContext`, but is registered once per part and injects one part each time; the rest of ADR 0001 stands, including that the playbook is the only copy of the rules and reaches only the main thread. It supersedes the consequence in [ADR 0008](0008-subagent-effort-per-kind-of-dispatch.md) that `scripts/check-parity.sh` fails once a playbook reaches 10,000 characters, so that any routing text added to the English playbook has to displace something else.

## Context

Claude Code stores a single hook's `SessionStart` `additionalContext` that is longer than 10,000 characters in a file and gives the model only a 2KB preview. The character count is the JavaScript string length, that is UTF-16 code units. ADR 0008 recorded the English playbook at 9,993 characters, just under that limit, and `check-parity.sh` failed any playbook past it.

The rules synced in November 2026 bring the English playbook to 22,329 characters and the Chinese playbook to 7,815. Injected whole, the English playbook would reach the main thread only as a preview.

On 7 November 2026, on Claude Code 2.1.319, the author measured whether the limit applies to all `SessionStart` output or to each hook separately. Two hooks registered on the same event, each emitting 9,500 characters, both arrived whole; one hook emitting 12,000 characters arrived as a preview. The limit therefore applies per hook.

Hooks registered on one event run in parallel, and their outputs reach the model in the order the hooks finish. In one probe four parts arrived in the order 4, 1, 3, 2.

## Decision

The hook takes `--part N`. With it, the hook cuts the playbook into parts of at most 9,500 UTF-16 code units and emits only part N; a part number past the last part emits nothing. The cut is made at `## ` section headings first; a section that does not fit is cut at blank lines, then at line ends, and a single line that still does not fit is cut by character without splitting a surrogate pair. When the playbook fits in one part, the hook emits it unchanged. When it needs more than one, each part opens with the line `[orchestrator playbook, part i of n]`, and the parts with that line removed, joined in order, equal the playbook byte for byte. Without `--part` the hook still emits the whole file.

Part N waits (N-1) × 0.3 seconds before it writes, so that the parts finish in their own order. The delay is set by `PLAYBOOK_PART_DELAY` and defaults to 0.3. In two probes after this change the parts arrived as 1, 2, 3, 4.

`settings.example.json` in both copies registers the hook four times on `SessionStart`, with `--part 1` to `--part 4`. On this branch the English playbook cuts into four parts of 2,327, 9,260, 9,338 and 1,552 characters, labels included. The Chinese playbook fits in one part, so its hook entries for parts 2 to 4 emit nothing.

`scripts/check-parity.sh` no longer fails at a playbook length. For each copy it runs the hook for every registered part and fails when any part exceeds 9,500 characters, or when the playbook needs a part beyond the last one the settings register, since such a part would never reach the main thread.

## Consequences

The playbook can grow past 10,000 characters without being cut to a preview, and the parity check names the fix when it outgrows the registered parts: register another `--part` entry in the settings.

The 9,500 ceiling leaves 500 characters under the measured limit; the margin is the author's choice, not a measured need. The per-hook limit was measured on one Claude Code version on one day, and a later version could change how it counts.

Ordering rests on timing. The 0.3-second step was chosen by the author, and two probes in order are thin evidence that it always holds; on a heavily loaded machine the parts could still arrive out of order. Each part's label carries its number and the total, so the model can still tell the order when they do.

An installation that copies the hook but keeps a settings file with the single old entry, without `--part`, still receives the whole file as one injection and with it the preview problem for the English copy.

The hook's regression test checks that the injection without `--part` equals the playbook byte for byte, also with `HOME` pointing at an empty directory; that every part is within 9,500 code units, that the parts are numbered in sequence with a consistent total and join back to the playbook; and that the playbook does not need more parts than the settings register.

## Sources

| Source | What it supports |
|---|---|
| Commit b668337 in this repository, body | The 10,000-character limit and the 2KB preview; the measurement on Claude Code 2.1.319 on 7 November 2026 (two 9,500-character hooks whole, one 12,000-character hook a preview); the 22,329-character English playbook; the arrival order 4, 1, 3, 2 and the two probes reading 1, 2, 3, 4 after the delay |
| `en/hooks/orchestrator-playbook-session-start.sh`, header comment and code | `--part N`, the 9,500 cap in UTF-16 code units, the cut order, the label line, single-part output unchanged, the delay and `PLAYBOOK_PART_DELAY`, whole-file output without `--part` |
| `en/settings.example.json` and `zh/settings.example.json`, the `SessionStart` entries | Four registrations, `--part 1` to `--part 4` |
| `scripts/check-parity.sh`, the playbook part check and its comment | The per-part size check and the check that the settings register enough parts |
| `en/hooks/tests/orchestrator-playbook-session-start.test.sh` | The byte-equality, part-size, numbering and join checks; their number is the `PASS=<n>` the test prints |
| `wc -m` on `en/orchestrator-playbook.md` and `zh/orchestrator-playbook.md`, and the hook run with `--part 1` to `--part 5` on this branch | 22,329 and 7,815 characters; the four English parts and their sizes |
| [ADR 0001](0001-orchestration-rules-reach-only-the-main-thread.md) and [ADR 0008](0008-subagent-effort-per-kind-of-dispatch.md) | The delivery detail and the length consequence this ADR amends |
