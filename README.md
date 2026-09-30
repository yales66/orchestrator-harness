# orchestrator-harness

[![CI](https://github.com/yales66/orchestrator-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/yales66/orchestrator-harness/actions/workflows/ci.yml)

The hooks, skills and orchestration rules for Claude Code that every one of my coding sessions runs inside.

The harness comes as two complete copies that each install on their own: `en/` in English and `zh/` in Chinese, the language I work in with Claude. Both hold the same rules, translated as closely as possible. The hook scripts are identical in the two copies; their comments and messages are in Chinese, which Claude reads either way. A Chinese version of this README is [zh/README.md](zh/README.md).

## Design goals

This harness is built for long-horizon agentic coding with as little human intervention as possible.

1. **Lean subagent context.** Orchestration rules reach only the main thread, through a SessionStart hook; `CLAUDE.md`, which every subagent loads, carries only rules every session needs. Each delegation is a goal-driven brief: an objective with verifiable acceptance criteria, file scope, known context, constraints, a self-check command and a bounded return format. Subagents start from conclusions rather than rediscovering them, and cannot spawn subagents of their own.
2. **Long-horizon sessions.** The main thread keeps decisions and conclusions and delegates exploration, review and implementation, so its context budget lasts. Before the window fills, a context watermark gate makes the session write a handoff and tell the user to switch to a fresh session, which resumes from that handoff.
3. **Human in the loop only at decision points.** The orchestrator playbook is built to send the user only the questions whose answer is theirs. An action that cannot be taken back, such as trading, moving funds or deleting data, is confirmed right before that step, after the reversible preparation is done. A fork goes to the user only when its branches produce substantively different results and the choice depends on something only the user knows; otherwise the agent takes the recommended branch and names it in its opening sentence. A next step at wrap-up that lies within the user's goal, can be undone, is not external and calls no paid service is done and then reported. A standing authorisation covers only the objects and changes it named, lasts for the session and ends when the user takes it back. A question that does go to the user sets out the background, the consequences of each option and a recommendation. When a reply ends by offering a next step, the `reply-gate` Stop hook blocks the stop once and restates these criteria. Before the user sees a visible output, the agent compares screenshots of the affected states and hands over a preview link or launch command, and prose meant for other readers first goes to a reviewer subagent that carries none of the session's context.

## Architecture

The diagram follows one turn. At session start, after `/clear` and after compaction, the SessionStart hook injects the orchestrator playbook into the main thread only, so a subagent works from `CLAUDE.md` and the brief it was given and hands back a bounded report. Every tool call from either thread passes PreToolUse first. A denied call, which is nested dispatch inside a subagent, `git commit --no-verify`, a call that would print a secret value, or a researcher subagent doing anything but create a new file, sends its reason back to the thread that made it, and that thread tries another way. An allowed call runs the tool; PostToolUse then returns a rule-file reminder to the calling thread when a rule file was edited, and links a newly entered worktree on disk without replying. When the main thread tries to end its turn, the two Stop hooks decide whether the reply reaches the user. The reply gate blocks once when the reply's last sentence offers a next step, and the main thread goes on to do that step. The context watermark gate adds a reminder past 35% of the context window and blocks once past 40%, and the main thread then writes a handoff file before it stops; a new session reads that file to carry on. Each gate blocks only once, so the resumed turn's next attempt to stop passes, and the orange arrows in the diagram mark every path on which control returns to a thread.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/architecture.en.dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="docs/architecture.en.light.svg">
  <img src="docs/architecture.en.light.svg" alt="Architecture of one turn. At session start, after /clear and after compaction, the SessionStart hook injects the orchestrator playbook into the main thread only; subagents do not receive it. The main thread sends a brief to a subagent, which returns a bounded report. Every tool call from either thread passes PreToolUse before the tool runs: it denies nested dispatch inside subagents, git commit --no-verify, calls that would print a secret value, and anything but creating new files for researcher subagents. A denial sends its reason back to the calling thread, which tries another way; an allowed call runs the tool. After the tool runs, PostToolUse returns a rule-file reminder as added context to the calling thread when a rule file was edited, and links a newly entered worktree on disk without replying. When the main thread tries to end the turn, the Stop hooks run, and if both pass the reply reaches the user. The context watermark gate adds a reminder over 35% and blocks once over 40%; the reply gate blocks once when the reply&#x27;s last sentence offers a next step. A block returns control to the main thread: after the reply gate it does the offered step, and after the watermark gate it writes the handoff file and then stops, and a new session reads that file to carry on. Each gate blocks once, so the resumed turn&#x27;s next attempt to stop passes.">
</picture>

## What is measured

Every result below comes from a deterministic measurement that a command in this repository reruns from the repository root. [docs/evaluation.md](docs/evaluation.md) gives the method and limits of each, and describes three experiments that pay for model calls as designs, with no results until they have run.

| Measurement | Result | Rerun |
|---|---|---|
| Hook regression tests | 486 cases per copy pass | `for t in en/hooks/tests/*.test.sh; do bash "$t"; done` |
| Hook mutation testing, [eval/hook-mutations](eval/hook-mutations/README.md) | the tests killed 42 of 54 injected defects on the first run and 54 of 54 once boundary cases were added for the survivors; on a held-out set of 35, written from the hook header comments without reading the tests, they kill 30, which is the unbiased estimate | `HM_MANIFEST=eval/hook-mutations/holdout.tsv HM_OUT=eval/hook-mutations/holdout-results.md bash eval/hook-mutations/run.sh` |
| Static context, [eval/static-context](eval/static-context/README.md) | each subagent's first-request input is 10,190 tokens with the playbook injected by the hook against 13,513 with it in `CLAUDE.md` | `bash eval/static-context/run.sh` |
| Reply gate replay, [eval/reply-gate-replay](eval/reply-gate-replay/README.md) | over 2,734 final replies written before the gate existed, its closing-offer rule blocks with 68.5% precision and 31.7% recall | `python3 eval/reply-gate-replay/score.py --data "$DATA"`, where `DATA` is the private directory holding the transcripts and labels |

The static measurement compares two isolated configurations: H installs this harness, and N installs the harness but writes the orchestrator playbook into `CLAUDE.md` rather than injecting it through the SessionStart hook. First-request input is the input tokens of a thread's first API request, which hold only fixed content: Claude Code's own system prompt and tool definitions, CLAUDE.md, the skill list, any text injected by hooks, and for a subagent the brief it was given; nothing the thread reads or produces later is included.

| Group | Main thread first-request input (tokens) | Subagent first-request input (tokens) |
|---|---|---|
| H | 20,341 | 10,190 |
| N | 20,330 | 13,513 |

Keeping the playbook out of `CLAUDE.md` cuts each subagent's first-request input from 13,513 to 10,190 tokens, 3,323 fewer or about 25%, while the main thread receives the playbook either way and its first-request input differs by 11 tokens between the groups. Both repeats of each group gave identical totals. The Chinese copy, measured with `SC_COPY=zh`, cuts the subagent's first-request input from 13,641 to 10,108 tokens, 3,533 fewer or about 26%; in the first H run of that measurement Claude Code sent six extra deferred tools and the subagent took 11,371 tokens, so the comparison uses the second run, whose tool set matches the other three ([results.zh.md](eval/static-context/results.zh.md)). The playbook stays under 10,000 characters because Claude Code hands a longer SessionStart context to the model only as a 2KB preview; `scripts/check-parity.sh` fails once either copy passes that length, and the load checks in the results confirm that the full playbook reaches the main thread in both groups. The measurement used Claude Code 2.1.285, with claude-opus-5-5 for both the main thread and the subagent. Claude Code's own system prompt and tool definitions change from version to version, so the absolute numbers hold only for 2.1.285, and another version needs a rerun of the script. [eval/static-context/results.md](eval/static-context/results.md) lists the per-run numbers, the load checks and the limitations.

The section [Why a before and after comparison of session logs is not evidence](docs/evaluation.md#why-a-before-and-after-comparison-of-session-logs-is-not-evidence) in [docs/evaluation.md](docs/evaluation.md) explains why my own session logs cannot show whether the harness helps, and the same document sets out what a full controlled experiment would take.

## Layout

Each language folder has the same layout, mirroring `~/.claude/`:

| Path | What it is |
|---|---|
| `CLAUDE.md` | Global rules loaded into every session: how to write prose, how to change existing code, how to test |
| `orchestrator-playbook.md` | Rules for the main thread as an orchestrator: what to delegate, how to write a subagent brief, how to hand off a long task, the delivery gate, git conventions |
| `hooks/` | Shell hooks registered in `settings.json`; each one reads the hook JSON on stdin |
| `hooks/tests/` | Regression tests covering all nine hooks |
| `agents/` | The `researcher` subagent definition, for read-only research, review and diagnosis that may create report files but does not change existing ones |
| `skills/` | Skills written for this harness, loaded on demand by Claude Code |
| `settings.example.json` | The `hooks` block that registers every hook, with paths under `$HOME/.claude` |

## Hooks

| Hook | Event | Behaviour | Tests |
|---|---|---|---|
| `orchestrator-playbook-session-start.sh` | SessionStart | Injects `orchestrator-playbook.md` into the main thread. The playbook lives here rather than in `CLAUDE.md` because `CLAUDE.md` is also loaded into every subagent, and the orchestration rules are for the main thread only | `orchestrator-playbook-session-start.test.sh` |
| `block-nested-subagent.sh` | PreToolUse on `Agent\|Task\|Workflow` | Denies a subagent from spawning further subagents or workflows. It keys on `agent_id`, which is present only inside a subagent, so a session started with `--agent` is not blocked | `block-nested-subagent.test.sh` |
| `block-no-verify-commit.sh` | PreToolUse on `Bash` | Denies `git commit --no-verify` and `git commit -n` so the commit-msg hook always runs. It tokenises the command and only looks at the options of the `commit` subcommand, so `[ -n "$C" ]` or `-n` inside a commit message pass | `block-no-verify-commit.test.sh` |
| `context-watermark-gate.sh` | Stop | Context watermark gate, described below | `context-watermark-gate.test.sh` |
| `rule-file-edit-check.sh` | PostToolUse on `Edit\|Write` | When the edited path is an LLM rule file, injects a reminder to follow the `rule-file-editing` skill. The trigger is deterministic instead of depending on the skill being auto-loaded | `rule-file-edit-check.test.sh` |
| `worktree-symlink-claudemd.sh` | PostToolUse on `EnterWorktree` | Symlinks `CLAUDE.md`, `node_modules` and `.env*` from the main checkout into a new git worktree without overwriting real files | `worktree-symlink-claudemd.test.sh` |
| `reply-gate.sh` | Stop | Blocks the stop once when the last sentence of the reply offers a next step, as in "Shall I …?" or 「要我…吗」, and its reason restates when to act directly and how to put a decision to the user. Fenced code, inline code and URLs are ignored, and a stop with `stop_hook_active` set is allowed, so the gate never loops | `reply-gate.test.sh` |
| `secret-guard.sh` | PreToolUse on `Bash\|Read` | Denies calls that would print a secret into the model's context. A Read of a file named `.env` or `.env.*` is denied, with the name compared in lower case, while the `.example`, `.sample` and `.template` samples pass. A shell command is split at `&&`, `\|\|`, `;`, `\|` and newlines, command substitutions are split out, and the strings given to `bash -c`, `sh -c`, `zsh -c` or `eval` are judged the same way up to three levels deep. A segment is denied when it prints a `.env` file through `cat`, `head`, `tail`, `less`, `awk`, a `sed` that is not in place, `sort`, `diff`, `base64`, `xxd` or a similar reader; when `grep` or `rg` reads such a file without a count, quiet or file-name option; when a recursive `grep`, or an `rg` that searches dot files, runs over a tree holding a `.env` file that its include, exclude or glob options do not rule out; when `echo` or `printf` expands a variable whose name contains KEY, SECRET, TOKEN, PASSWORD, PASSWD or CREDENTIAL, where `${#VAR}` gives only the length and passes; when `printenv` runs bare or names such a variable; and when `env`, `export -p` or `set` runs alone. A relative search root follows an earlier `cd` or `pushd` in the same command, and a `cd` target that is not literal counts as holding `.env`. The tree walk skips `.git` and `node_modules` and allows a tree of more than 20,000 entries. Commands that use a value without printing it, such as `source .env` followed by a command, pass, and the denial names such alternatives | `secret-guard.test.sh` |
| `subagent-readonly-guard.sh` | PreToolUse on `Edit\|Write\|NotebookEdit\|MultiEdit\|Bash` | Inside the `researcher` subagent, allows creating new files and denies changing existing ones. Every Edit, MultiEdit and NotebookEdit is denied, and a Write only when its target exists. A shell command is split and unwrapped the same way as in the secret guard, and a segment is denied when it runs `sed -i` or `perl -i`, redirects or `tee`s into an existing file (`/dev/null` and new paths pass), runs `rm`, `mv`, `truncate`, `chmod` or `ln -f`, runs `cp` onto an existing target, runs a git subcommand that changes the working tree, index, refs or remotes, or `git branch -d` or `-D`, or carries inline interpreter code that writes, renames or deletes files, whether or not the target exists. Inline code means the argument of `python -c`, `node -e` or `-p`, `perl -e` and `ruby -e`, a `<<<` string, and a heredoc body fed to one of these interpreters; a script run from a file, such as `python3 script.py`, is not inspected. Relative paths follow an earlier `cd` or `pushd` in the same command, and after a `cd` whose target is not literal every relative write target counts as existing. It keys on `agent_id` together with `agent_type`, so a session started with `--agent researcher` is not restricted | `subagent-readonly-guard.test.sh` |

## Skills

| Skill | Purpose |
|---|---|
| `rule-file-editing` | Discipline for editing `CLAUDE.md`, `SKILL.md` and other instruction files: judge each change by how it alters runtime behaviour, write exceptions as branches, and send deletions and new rule files to an independent reviewer |
| `memory-audit` | Decides which Claude Code memory entries to keep, merge or delete, and rebuilds the index |

## Two mechanisms worth a closer look

**Independent review of rule-file changes.** The `rule-file-editing` skill ends every deletion or restructuring of a rule, and every new rule file, by dispatching a read-only reviewer subagent that has no conversation history. The reviewer gets only the before/after diff (or the full new file) and returns a verdict, so it judges the change the way a future session with no context would read it.

**Context watermark gate.** The Stop hook input carries no token fields, so `context-watermark-gate.sh` reads the real usage from the session transcript: the last assistant message's `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`. At 35% of the context window it adds a reminder. At 40% it blocks the stop once and asks the session to write a handoff file in the handoff format of the playbook's §3 before it ends, and then to tell the user to switch to a new session. After a block it records the level in the session scratchpad and does not block again until usage has risen another 5 percentage points, so the session can keep working after writing the handoff instead of being stopped on every turn. Inside a subagent, and on any malformed input, it allows the stop. The window size and all three thresholds can be overridden with `CONTEXT_WINDOW_TOKENS`, `CONTEXT_WARN_PCT`, `CONTEXT_HARD_PCT` and `CONTEXT_REBLOCK_DELTA_PCT`.

## Install

Clone this repository, start Claude Code in it and ask Claude to do the install, for example:

```text
Install the en/ copy of this repository into ~/.claude, following the Install section of README.md.
```

Ask for `zh/` instead to get the Chinese copy. The steps below are written for the Claude session that carries out the install, and it follows them in order:

1. Check that `bash`, `python3`, `jq` and `git` are on `PATH`, and tell the user about any missing one before copying anything. The hooks parse their input with `python3` and `jq`, and a hook that denies, blocks or injects exits without a decision when `python3` is missing, so every call then goes through unchecked and nothing reports it.
2. Take the source files from the copy the user named, `en/` or `zh/`, and ask when the request names neither.
3. Before overwriting any file that already exists under `~/.claude/`, `settings.json` included, copy it to a backup location and tell the user where the backups are.
4. Copy `hooks/*.sh` into `~/.claude/hooks/` without `hooks/tests/`, copy each directory under `skills/` into `~/.claude/skills/`, copy `agents/*.md` into `~/.claude/agents/`, and copy `orchestrator-playbook.md` into `~/.claude/`. The playbook has to sit in the directory directly above `hooks/`, because the SessionStart hook resolves it relative to its own location.
5. Merge the `hooks` block of `settings.example.json` into `~/.claude/settings.json`, creating the file when it does not exist. Keep every other key and every existing hook entry, and skip any hook whose command is already registered under the same event.
6. Install `CLAUDE.md` only when the user explicitly asks for it. When `~/.claude/CLAUDE.md` already exists, ask the user whether to overwrite it or merge the two before changing it.
7. Tell the user to start a new Claude Code session, since the hooks and skills take effect only in sessions started after the install.

The playbook and `CLAUDE.md` also route to `grilling`, `domain-modeling`, `write-pr`, `prose-discipline`, `tdd-watch-it-fail`, and `debug-root-cause`. Those skills are not included here, either because they are third-party or built mainly on third-party material, or because they only fit my own setup; install your own equivalents or remove those routes.

## Tests

Run the hook tests from `en/` or `zh/`:

```bash
for t in hooks/tests/*.test.sh; do bash "$t"; done
```

Each hook test prints `PASS=<n> FAIL=<n>` and exits non-zero on any failure. The nine tests hold 486 cases in each copy. From the repository root, the check that `en/` and `zh/` hold matching copies runs with:

```bash
bash scripts/check-parity.sh
```

CI runs on every push and pull request. It runs the hook tests of both copies, 486 cases each, on Ubuntu and macOS, runs shellcheck over the hooks, their tests and the repository scripts, and runs the en/zh parity check.

## Documentation

| Document | Topic |
|---|---|
| [ADR 0001: Orchestration rules reach only the main thread](docs/adr/0001-orchestration-rules-reach-only-the-main-thread.md) | Where the playbook is loaded |
| [ADR 0002: Every subagent brief carries six elements](docs/adr/0002-every-subagent-brief-carries-six-elements.md) | What a delegation must contain |
| [ADR 0003: Subagents cannot spawn subagents](docs/adr/0003-subagents-cannot-spawn-subagents.md) | Who may dispatch work |
| [ADR 0004: The context watermark is read from transcript usage and gates the stop on a handoff](docs/adr/0004-context-watermark-read-from-transcript-usage.md) | When a long session must hand off |
| [ADR 0005: Hooks that deny, block or inject rules ship with regression tests](docs/adr/0005-deciding-hooks-ship-with-regression-tests.md) | Which hooks carry tests |
| [ADR 0006: Ask the user only where the answer is theirs](docs/adr/0006-ask-the-user-only-where-the-answer-is-theirs.md) | When the agent asks and when it acts |
| [Evaluation: method and limits](docs/evaluation.md) | What the harness claims, what it does not, and what a controlled experiment would cost |
| [Static context measurement](eval/static-context/README.md) | How to run the measurement and what each configuration installs |
| [Hook mutation testing](eval/hook-mutations/README.md) | How injected defects measure the hook tests, and the held-out set |
| [Reply gate replay](eval/reply-gate-replay/README.md) | How the reply gate was replayed over past sessions and scored against blind labels |

## License

MIT. See `LICENSE`.

## Data sources

| Figures | Source |
|---|---|
| Prompt token accounting (input plus cache creation plus cache read) | Anthropic prompt caching documentation, https://platform.claude.com/docs/en/build-with-claude/prompt-caching |
