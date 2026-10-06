# ADR 0018: The watermark reminder does not hold back new work

## Status

Accepted. In effect since 7 October 2026. Supersedes the reminder text in the 35% to 40% row of [ADR 0007](0007-handoff-timing-weighs-switch-against-long-context.md); the rest of ADR 0007 stands.

## Context

Between the reminder line (35%) and the hard line (40%), the context watermark gate's reminder told the main thread not to write a handoff yet and not to open a new block of work expected to cross the hard line. When the next block was expected to cross it, the reminder forbade starting it and did not call for a handoff either, and the playbook's timing rule applies only past the hard line, so the main thread had to guess between stopping to ask the user and handing off on its own.

## Decision

The reminder now says that no handoff is needed yet, that work in hand and new blocks of work go ahead as usual, and that past the hard line the playbook's §3 timing rule applies. A block that crosses the hard line is then weighed by the gate's first block like any other: wrap-up the held context can finish is finished, and a new large block of work that remains calls for a handoff.

## Consequences

A switch costs a re-read of the material, so starting the block and weighing it at the hard line spends no handoff on work that turns out to fit. A block that does cross the hard line runs past 40% before the weighing happens.

## Sources

| Source | What it supports |
|---|---|
| `en/hooks/context-watermark-gate.sh`, the reminder's `additionalContext` | The reminder text |
| `en/orchestrator-playbook.md`, §3, the timing bullet | The timing rule that applies past the hard line |
| The prompt audit of the harness, 7 October 2026 | The reminder left the case of a block expected to cross the hard line undecided |
