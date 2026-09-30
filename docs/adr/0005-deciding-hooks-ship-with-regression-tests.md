# ADR 0005: Hooks that deny, block or inject rules ship with regression tests

## Status

Accepted. In effect since 16 July 2026.

## Context

A hook that denies a tool call or blocks a stop runs on every matching event, and its mistakes are silent in both directions: a missed denial lets through the behaviour the hook exists to stop, and a false denial blocks legitimate work. An earlier version of `block-no-verify-commit.sh` matched the whole command with a regular expression and failed both ways. The expression required at least one character between `git` and the subcommand, so the most common form of the bypass, with the two words adjacent, was never blocked. Commands that contained both `git` and `commit` together with a standalone `-n`, such as a `git log` followed by the shell test `[ -n "$C" ]`, were denied in real use, and the test keeps them as regression cases dated 15 July 2026.

A test that has never failed does not show that it would catch a broken hook.

## Decision

Every hook that can deny a tool call, block a stop or inject rules into the context ships with `hooks/tests/<hook>.test.sh`. The test feeds the hook the JSON that Claude Code would send and asserts the decision. It covers the calls that must be denied or blocked, the calls that must be allowed, and malformed input, on which every such hook allows so that a broken payload never locks up a session. Each test prints `PASS=<n> FAIL=<n>` and exits non-zero on any failure.

A test counts once it has been seen to fail against a broken hook: either the unfixed version, or a deliberately injected bug that is reverted after the test turns red.

## Consequences

Every hook this rule covers carries its test in each language copy, and the Hooks table in `README.md` names the test of each hook. The number of cases in a test is the `PASS=<n>` that test prints.

`rule-file-edit-check.sh` only adds a reminder and never denies or blocks, and `worktree-symlink-claudemd.sh` creates symlinks in a new worktree, so neither falls under this rule as written. They carry characterisation tests all the same, which pin their current behaviour. The worktree hook replaces the worktree's tracked `CLAUDE.md` with `rm -f`, so its test pins when that file is replaced, which is only when it matches `HEAD` and the link target exists, that the new link resolves to the main worktree's `CLAUDE.md` even when the worktree path passes through a symlinked directory, and that malformed input changes nothing. The cases for a symlinked path and for uncommitted changes are regression cases for defects the tests exposed.

CI runs every hook test in both copies on every push and pull request.

## Sources

| Source | What it supports |
|---|---|
| `en/hooks/block-no-verify-commit.sh`, header comment | Why the hook tokenises the command: matching all of it missed the adjacent form of the bypass and denied commands containing `[ -n "$C" ]` |
| `en/hooks/tests/block-no-verify-commit.test.sh`, the regression section dated 2026-07-15 | The commands denied in real use, kept as regression cases dated 15 July 2026 |
| `en/CLAUDE.md`, section Testing | A test that cannot turn red when the code is wrong is not written |
| `en/hooks/block-nested-subagent.sh` and `en/hooks/context-watermark-gate.sh`, their handling of malformed input | Allow on malformed input so that a hook never locks up a session |
| `en/hooks/worktree-symlink-claudemd.sh`, `link_target` | The worktree hook removes the tracked `CLAUDE.md` before linking it |
| `en/hooks/tests/rule-file-edit-check.test.sh` | The characterisation cases of the rule-file reminder |
| `en/hooks/tests/worktree-symlink-claudemd.test.sh` | The cases of the worktree hook |
| `en/hooks/tests/reply-gate.test.sh` | The cases of the reply gate |
| `en/hooks/tests/secret-guard.test.sh` | The cases of the secret guard |
| `en/hooks/tests/subagent-readonly-guard.test.sh` | The cases of the read-only subagent guard |
| `.github/workflows/ci.yml`, the `on` triggers and the `Hook tests (en and zh)` step | CI runs every hook test in both copies on every push and pull request |
