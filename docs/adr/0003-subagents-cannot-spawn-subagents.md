# ADR 0003: Subagents cannot spawn subagents

## Status

Accepted. In effect since 13 September 2026.

## Context

The main thread is the orchestrator: it decides what to dispatch, to which model, with which brief (ADR 0002), and it keeps the conclusions. A subagent that dispatches its own subagents, or runs a workflow script, adds a layer of fan-out that the orchestrator neither planned nor sees.

Claude Code puts `agent_id` into hook input only when the hook fires inside a subagent. The main thread never carries it, and that includes a session started with `--agent`, whose main thread carries `agent_type` but no `agent_id`.

## Decision

`hooks/block-nested-subagent.sh` runs on `PreToolUse` for `Agent`, `Task` and `Workflow` and denies the call whenever `agent_id` is present and non-empty. The denial tells the subagent to finish the step itself and, if the work really needs splitting, to put its conclusions and a proposed split into its return value so that the orchestrator decides how to dispatch.

The hook keys on `agent_id` and not on `agent_type`, because `agent_type` is also present on the main thread of a `--agent` session and keying on it would block that main thread. `Workflow` is denied for the same reason as `Agent`: a workflow started inside a subagent is another uncontrolled fan-out. Malformed input is allowed, because a hook should never lock up a session.

## Consequences

Dispatch is one level deep. A subagent that finds its task too large reports back instead of splitting it, and every dispatch in a session passes through the main thread's routing and brief rules.

The main thread, including the main thread of a `--agent` session, can still dispatch subagents and run workflows. The regression test covers both sides: calls to `Agent`, `Task` and `Workflow` from inside a subagent that must be denied, and allowed cases for the main thread, a `--agent` main thread, an empty or null `agent_id`, and malformed input.

## Sources

| Source | What it supports |
|---|---|
| `en/hooks/block-nested-subagent.sh`, header comment | Scope of the hook, the `agent_id` criterion and why `agent_type` would block a `--agent` main thread, and `Workflow` as uncontrolled fan-out |
| `en/hooks/block-nested-subagent.sh`, the fallback when the input fails to parse | Allow on malformed input |
| `en/hooks/block-nested-subagent.sh`, `permissionDecisionReason` | Denial message pointing the split back to the orchestrator |
| `en/hooks/tests/block-nested-subagent.test.sh` | The deny and allow cases; their number is the `PASS=<n>` the test prints |
