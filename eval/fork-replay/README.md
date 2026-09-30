# Fork replay

This directory holds a generic runner that continues past Claude Code sessions from a chosen decision point under a configuration of your choice, and records what the model does next. It measures behaviour that an offline replay of finished replies cannot see: what the agent does after a hook blocks it, or which decision it takes when the same moment is regenerated under different rules. Evals built on it keep their own grader, config and README in a sibling directory; the first one is `eval/gate-followthrough/`.

Session transcripts and anything derived from them live in a private data directory outside the repository. The repository keeps only code and aggregate results.

## How one replay runs

For each case and each rep, `run.py`:

1. checks out the case's repository at the recorded commit with `git worktree add --detach` into a fresh directory under the system temp directory (`tempfile.gettempdir()`, with symlinks resolved); a recorded path under `<repo>/.claude/worktrees/<name>` that no longer exists is checked out from `<repo>`, with whatever followed `<name>` as the subdirectory; or it uses an empty directory when the case has no restorable repository (`--unrestorable-cwd origin` uses the session's original directory instead, read-only);
2. builds a fresh `CLAUDE_CONFIG_DIR` from the configuration under test, removes the hook events the eval config lists under `drop_hook_events`, and registers `stub_hook.py` as the first `PreToolUse` hook for every tool;
3. copies the private session transcript to `$CLAUDE_CONFIG_DIR/projects/<slug of cwd>/<session id>.jsonl`, which is where Claude Code looks for a session to resume; with `--playbook FILE`, every playbook the recorded `SessionStart` hook injected into that copy is replaced by the file's text, and the file also replaces `orchestrator-playbook.md` in the config directory;
4. resumes the session through the Agent SDK with `resume`, `resume_session_at` and `fork_session=True`, so the original transcript is never edited and the replay gets a new session id;
5. grades the continuation with the eval's `grade(case, trajectory, cfg)` and appends the result, then removes the worktree and the temp directory. The trajectory is `{calls, tool_calls, texts, final_text}`: `calls` and `tool_calls` are the same ordered list of `{tool, input, decision}` from the stub's log, where `decision` is `allow` for a call that ran as read-only and `deny` otherwise, `texts` are the assistant's text blocks and `final_text` is the last of them.

The two fork modes differ only in step 4:

| fork_mode | kept history | next input |
|---|---|---|
| after | up to and including `fork_uuid` | `resume_input`, sent as one user message |
| before | up to the record before the user prompt that opened the `fork_uuid` turn | that prompt, re-sent, so the whole turn is generated afresh |

In before mode, a decision that came after tool calls in the same turn is regenerated together with those calls; the result row records how many assistant records were rewound.

The SDK rebuilds the system prompt on every request only when asked to; the runner passes `system_prompt={"type": "preset", "preset": "claude_code", "snapshot": False}` by default so the configuration under test, not the snapshot recorded in the transcript, supplies it. `verbatim_prompts` is on by default, so the resume input is delivered as written, without `@path` expansion, slash-command dispatch or the attachments Claude Code adds to a typed prompt. Replays run at effort `high` (`sdk.effort`), the level the recorded sessions ran at; neither installed configuration sets it, and `claude-opus-5-5` would otherwise run at its default, `medium`.

## Side effects

Nothing a replay does may reach the outside world. `stub_hook.py` appends every tool call to a JSON-lines log and returns `allow` only for Read, Grep and Glob, for tools the eval config lists under `stub.extra_readonly`, and for Bash commands that pass a conservative whitelist: plain readers such as `ls`, `cat`, `grep`, `rg`, `find` without `-exec` or `-delete`, `sed -n` without `-i` or a `w` command, read-only `git` subcommands (`status`, `log`, `show`, `diff`, `blame` and similar, `branch` only for listing) and read-only `gh` subcommands (`pr view`, `issue list` and similar). A command with output redirection to a file, command substitution, a heredoc, or any program outside the whitelist is denied. Everything else is denied with the eval's `deny_reason` and still logged, and the grader reads the log.

Three layers keep a failure from turning into a side effect. The stub fails closed: if it cannot read its config or crashes, it exits with code 2, which blocks the call. A `can_use_tool` callback denies anything that still reaches a permission prompt. The replay runs with `HOME` pointed at an empty temp directory, as `eval/static-context/run.sh` does, so tools that read credentials from the home directory find none. One residual risk remains: if the stub hook were bypassed entirely and the checked-out project's own settings allowed a command, that command would run in the worktree copy.

## Case contract

`cases.jsonl` holds one JSON object per line. Every eval built on this runner uses the same fields; `casekit.validate_case` is the definition and `casekit.load_cases` refuses a file with any violation.

| field | type | meaning |
|---|---|---|
| id | string | unique case id |
| source_session | path | the session transcript to resume, normally a private redacted copy; its file name is the session id |
| fork_mode | "after" or "before" | see the table above |
| fork_uuid | string | uuid of the transcript record at the decision point |
| resume_input | string or null | next user message in after mode; ignored in before mode |
| cwd_repo | object or null | `{path, commit, subdir?}`: the repository to run `git worktree add` from, the commit, and the cwd relative to the checkout root; null when the working directory cannot be restored |
| label | string | the case's ground-truth label from whatever labeling produced it |
| forbidden | list of rules | a denied call matching any rule is an overstep |
| expected | list or "ask" | rules for calls that count as correct, and/or `{"final": "ask"}` for ending the turn by asking the user; the bare string `"ask"` means `[{"final": "ask"}]` |
| tags | list of strings | `tags[0]` is the primary grouping key in reports |
| meta | object, optional | carried through, never read by the runner |

A rule is `{tool, pattern}`. `tool` is a regular expression matched against the whole tool name, so `Edit|Write` matches `Write` but not `NotebookWrite`. `pattern` is a regular expression searched in the tool input serialized as JSON with sorted keys and unescaped Unicode. A rule may carry `example`, a tool input the rule must match, and `example_tool`, the tool name for that example when `tool` is not a plain name; `validate_case` checks the match, and evals use the examples to build known-bad trajectories for their self-checks.

`cwd_repo.subdir`, `example`, `example_tool`, the `{"final": "ask"}` form of `expected` and `meta` are extensions of the original field list; all are optional except that `expected` must say what counts as correct.

## Outputs

Results are written under `<flow>/<variant>/`, with these files and row fields:

| file | content |
|---|---|
| results.jsonl | one row per (case, rep): `prompt_id`, `rep`, `prompt`, `tags`, `stop_reason`, `status` (`ok`, or `truncated` when the run hit max tokens, max turns or the budget), `grade`, `explanation`, `model` as served, `usage`, `latency_s`, `tool_calls`, `trace` and `meta` (grader outcome, first non-read-only call, attempts, turns, cost reported by the SDK, forked session id) |
| traces/<id>_rep<k>.json | the continuation as `{role, content}` turns: the resume input, assistant text, tool calls and tool results |
| errors.jsonl | one row per failed attempt with a failure class: `timeout`, `harness-or-serving`, `served-model-mismatch` or `grader-error` |

Resume is idempotent at the (case, rep) key: rerunning the same command skips rows already in `results.jsonl`. Each attempt has a hard wall-clock ceiling (`--timeout-s`); errors whose message looks like an overload or rate limit are retried with jittered exponential backoff, and every attempt is recorded. A response served by a model other than the requested one fails the attempt.

A real run refuses to start until the harness has been approved: the runner hashes itself, the stub, `casekit.py`, the grader, the eval config, the cases file, the configuration under test and any `harness_paths` listed in `<flow>/_state.json`, plus the `--playbook` file when one is given, and exits with code 2 when the hash differs from the one the last `--approve-harness` run recorded for the same `--variant`. Each variant is approved on its own, because arms of one flow may run under different playbooks. Approving is the user's decision.

## Running

The runner needs the Python Agent SDK, which is not part of the standard library. Install it into a virtual environment rather than the system Python:

```bash
python3 -m venv ~/.venvs/fork-replay
~/.venvs/fork-replay/bin/pip install claude-agent-sdk   # 0.2.161 bundles Claude Code 2.1.284
```

A fresh `CLAUDE_CONFIG_DIR` cannot see the keychain login, so export `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) or `ANTHROPIC_API_KEY` first. Then, from the repository root:

```bash
PY=~/.venvs/fork-replay/bin/python
$PY eval/fork-replay/run.py --cases "$DATA/cases.jsonl" --flow "$DATA" --config en \
    --grader eval/<eval>/grade.py --eval-config eval/<eval>/config.json --dry-run
$PY eval/fork-replay/run.py ... --approve-harness --only <one id>     # first real run, after review
$PY eval/fork-replay/run.py ... --reps 2 --concurrency 3
```

`--dry-run` needs neither the SDK nor credentials: it creates each worktree, config directory and session copy, prints the plan (cwd, where the session was placed, the resume point, the settings the replay would load) and removes everything again. `--config` takes either a harness tree shaped like `en/`, installed the way `eval/static-context/run.sh` installs it, or a ready configuration directory with its own `settings.json`. `--variant` names the output directory, `baseline` or `v<N>`. `--keep` leaves each attempt's temp directory in place for inspection. The CLI also accepts an undocumented `--resume-session-at` flag, a fallback if the SDK option ever changes.

Tests: `python3 -m pytest eval/fork-replay -q` (add `-p no:pytest_ethereum` on a machine whose global site-packages carries a broken web3 pytest plugin).

## Files

| file | role |
|---|---|
| run.py | the runner |
| stub_hook.py | the PreToolUse hook: logs every call, allows read-only ones, denies the rest |
| casekit.py | the case contract, rule matching, session lookup and redacted copies, repository and commit resolution |
| test_*.py | unit tests for the three modules |

## Limits

Resuming replays the transcript as recorded, including every piece of context hooks injected at the time. A `SessionStart` hook whose matcher does not include `resume` does not fire on the fork, so the replay sees the injection recorded in the original session, not the one the configuration under test would produce. An eval whose arms differ only in the injected playbook passes `--playbook`; the runner then rewrites both records the hook left, the `hook_additional_context` attachment together with its `rendered` text, which is what a resume actually sends to the model, and the `hook_success` output it came from, and fails the attempt if the copy holds no playbook to replace. `--raw-bodies DIR` has Claude Code write every request body of an attempt under `DIR/<id>_rep<k>/` (through `OTEL_LOG_RAW_API_BODIES=file:<dir>`), which is how a pilot run checks the prefix the model actually saw.

The worktree restores the committed state only; uncommitted edits present at the decision point are missing. Reads of absolute paths outside the worktree see those files as they are today. The rebuilt system prompt carries today's date. MCP servers and connectors that the original session had are absent unless the configuration under test provides them, so a case whose forbidden step is an MCP call can only overstep if the tool exists in the replay.
