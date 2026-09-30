# orchestrator-harness

[![CI](https://github.com/yales66/orchestrator-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/yales66/orchestrator-harness/actions/workflows/ci.yml)

The hooks, skills and orchestration rules for Claude Code that every one of my coding sessions runs inside.

The harness comes as two complete copies that each install on their own: `en/` in English and `zh/` in Chinese, the language I work in with Claude. Both hold the same rules, translated as closely as possible. The hook scripts are identical in the two copies; their comments and messages are in Chinese, which Claude reads either way. A Chinese version of this README is [zh/README.md](zh/README.md).

## Design goals

This harness is built for long-horizon agentic coding with as little human intervention as possible.

1. **Lean subagent context.** Orchestration rules reach only the main thread, through a SessionStart hook; `CLAUDE.md`, which every subagent loads, carries only rules every session needs. Each delegation is a goal-driven brief: an objective with verifiable acceptance criteria, file scope, known context, constraints, a self-check command and a bounded return format. Subagents start from conclusions rather than rediscovering them, and cannot spawn subagents of their own.
2. **Long-horizon sessions.** The main thread keeps decisions and conclusions and delegates exploration, review and implementation, so its context budget lasts. As the window fills, a context watermark gate blocks the main thread's attempt to end its turn and has it weigh a switch to a fresh session: it finishes the wrap-up that its context already covers, and before a new large block of work it writes a handoff and asks the user to switch to a fresh session, which resumes from that handoff.
3. **Human in the loop only at decision points.** The orchestrator playbook is built to send the user only the questions whose answer is theirs. An action that cannot be taken back, such as trading, moving funds or deleting data, is confirmed right before that step, after the reversible preparation is done. A fork goes to the user only when its branches produce substantively different results and the choice depends on something only the user knows; otherwise the agent takes the recommended branch and names it in its opening sentence. A next step at wrap-up that lies within the user's goal, can be undone, is not external and calls no paid service is done and then reported. A standing authorisation covers only the objects and changes it named, lasts for the session and ends when the user takes it back. A question that does go to the user sets out the background, the consequences of each option and a recommendation. When a reply ends by offering a next step, the `reply-gate` Stop hook blocks the stop once and restates these criteria. Before the user sees a visible output, the agent compares screenshots of the affected states and hands over a preview link or launch command, and prose meant for other readers first goes to a reviewer subagent that carries none of the session's context.

## Architecture

The diagram follows one turn. At session start, after `/clear` and after compaction, the SessionStart hook injects the orchestrator playbook into the main thread only, so a subagent works from `CLAUDE.md` and the brief it was given and hands back a bounded report. Every tool call from either thread passes PreToolUse first. A call is denied when it is nested dispatch inside a subagent, `git commit --no-verify`, a call that would print a secret value, or a researcher subagent changing, moving or deleting an existing file; its reason goes back to the thread that made it, and that thread tries another way. A researcher subagent may still read files, run commands and create new files. An allowed call runs the tool; PostToolUse then returns a rule-file reminder to the calling thread when a rule file was edited, and when a new worktree is entered it symlinks `CLAUDE.md`, `node_modules` and `.env*` from the main checkout into that worktree without replying. When the main thread tries to end its turn, the two Stop hooks decide whether the turn ends. The reply gate blocks once when the reply's last sentence offers a next step, and the main thread then either takes that step or, when the decision really is the user's, asks again with the background, the consequences of each option and a recommendation. In the `zh/` copy's install, which sets `REPLY_LANG=zh`, it also blocks once when a longer reply is mostly not in Chinese. The context watermark gate adds a reminder once per session past 35% of the context window, or on every turn when the session has no scratchpad, and blocks once past 40%. The main thread then finishes any wrap-up that the context it holds can complete, and when a new large block of work comes next it writes a handoff file and tells the user to switch sessions. After that, the gate blocks again at every further rise of 5 percentage points over the usage at its last block, and the main thread writes the handoff at once. A new session reads that file to carry on. Neither gate blocks the turn it has just resumed, so that turn's next attempt to stop passes, and the orange arrows in the diagram mark every path on which control returns to a thread.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/architecture.en.dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="docs/architecture.en.light.svg">
  <img src="docs/architecture.en.light.svg" alt="Architecture of one turn. At session start, after /clear and after compaction, the SessionStart hook injects the orchestrator playbook into the main thread only; subagents do not receive it. The main thread sends a brief to a subagent, which returns a bounded report. Every tool call from either thread passes PreToolUse before the tool runs: it denies nested dispatch inside subagents, git commit --no-verify, calls that would print a secret value, and a researcher subagent changing, moving or deleting an existing file, while a researcher subagent may still read files, run commands and create new files. A denial sends its reason back to the calling thread, which tries another way; an allowed call runs the tool. After the tool runs, PostToolUse returns a rule-file reminder as added context to the calling thread when a rule file was edited, and when a new worktree is entered it symlinks CLAUDE.md, node_modules and .env* from the main checkout into that worktree without replying. When the main thread tries to end the turn, the Stop hooks run, and if both pass the turn ends. The context watermark gate adds a reminder once per session over 35%, or on every turn when the session has no scratchpad, and lets the stop pass, blocks once over 40%, and after that blocks again at every further rise of 5 points over the usage at its last block; the reply gate blocks once when the reply&#x27;s last sentence offers a next step. A block returns control to the main thread. After the reply gate it either takes the offered step or, when the decision really is the user&#x27;s, asks again with the background, the consequences of each option and a recommendation. After the watermark gate&#x27;s first block it finishes any wrap-up that the context it already holds can complete, and when a new large block of work comes next it writes the handoff file and tells the user to switch to a new session; after each further block it writes the handoff at once. A new session reads that file to carry on. Neither gate blocks the turn it has just resumed, so that turn&#x27;s next attempt to stop passes.">
</picture>

## What is measured

Every result below comes from a measurement that a command in this repository reruns from the repository root. The static context measurement calls Claude Code with your own credentials, and the others make no model calls. [docs/evaluation.md](docs/evaluation.md) gives the method and limits of each, and describes three further experiments that pay for model calls as designs, with no results until they have run.

| Measurement | Result | Rerun |
|---|---|---|
| Hook regression tests | 494 cases per copy pass | `for t in en/hooks/tests/*.test.sh; do bash "$t"; done` |
| Hook mutation testing, [eval/hook-mutations](eval/hook-mutations/README.md) | the tests killed 42 of 54 injected defects on the first run and 54 of 54 once boundary cases were added for the survivors; on a held-out set of 35, written from the hook header comments without reading the tests, they kill 30, which is the unbiased estimate | `HM_MANIFEST=eval/hook-mutations/holdout.tsv HM_OUT=eval/hook-mutations/holdout-results.md bash eval/hook-mutations/run.sh` |
| Static context, [eval/static-context](eval/static-context/README.md) | each subagent's first-request input is 10,186 tokens with the playbook injected by the hook against 13,489 with it in `CLAUDE.md` (en/ copy, Claude Code 2.1.285) | `bash eval/static-context/run.sh` |
| Reply gate replay, [eval/reply-gate-replay](eval/reply-gate-replay/README.md) | over 2,734 final replies written before the gate existed, its closing-offer rule blocks with 68.5% precision and 31.7% recall | `python3 eval/reply-gate-replay/score.py --data "$DATA"`, where `DATA` is the private directory holding the transcripts and labels |

The static measurement compares two isolated configurations: H installs this harness, and N installs the harness but writes the orchestrator playbook into `CLAUDE.md` rather than injecting it through the SessionStart hook. First-request input is the sum of the uncached input tokens, cache write tokens and cache read tokens of a thread's first API request, which hold only fixed content: Claude Code's own system prompt and tool definitions, CLAUDE.md, the skill list, any text injected by hooks, and for a subagent the brief it was given; nothing the thread reads or produces later is included.

| Group | Main thread first-request input (tokens) | Subagent first-request input (tokens) |
|---|---|---|
| H | 20,318 | 10,186 |
| N | 20,307 | 13,489 |

Keeping the playbook out of `CLAUDE.md` cuts each subagent's first-request input from 13,489 to 10,186 tokens, 3,303 fewer or about 24%, while the main thread receives the playbook either way and its first-request input differs by 11 tokens between the groups. The script reruns any run whose subagent model or deferred tool set makes it not comparable, and both runs of each group gave identical totals. The Chinese copy, measured with `SC_COPY=zh`, cuts the subagent's first-request input from 13,666 to 10,108 tokens, 3,558 fewer or about 26%, and both repeats of each group gave identical totals ([results.zh.md](eval/static-context/results.zh.md)). The playbook stays under 10,000 characters because Claude Code hands a longer SessionStart context to the model only as a 2KB preview; `scripts/check-parity.sh` fails once either copy passes that length, and the load checks in the results confirm that the full playbook reaches the main thread in both groups. The measurement installed the `en/` copy and used Claude Code 2.1.285, with claude-opus-5-5 for both the main thread and the subagent. Claude Code's own system prompt and tool definitions change from version to version, so the absolute numbers hold only for 2.1.285, and another version needs a rerun of the script. [eval/static-context/results.md](eval/static-context/results.md) lists the per-run numbers, the load checks and the limitations.

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
| `context-watermark-gate.sh` | Stop | Reads the context usage of the last assistant message from the session transcript. Past 35% of the context window it adds a reminder once per session, or on every turn when there is no session scratchpad, and allows the stop. At 40% it blocks once, or on every turn when the session has no scratchpad, and the main thread finishes the wrap-up its context covers or, with a new large block of work next, writes a handoff and suggests a new session. After that it blocks again at every further rise of 5 percentage points over the usage at its last block and asks for the handoff at once. Its marks live in the session scratchpad and are cleared when usage falls back below 35%, as after compaction. Inside a subagent and on malformed input it allows the stop | `context-watermark-gate.test.sh` |
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

**The orchestrator playbook reaches only the main thread, and reaches it whole.** The SessionStart hook injects the playbook at session start, after `/clear` and after compaction, instead of leaving it in `CLAUDE.md`, which every subagent also loads. In the static measurement this cuts each subagent's first-request input by about 24% in the English copy, from 13,489 to 10,186 tokens, and by about 26% in the Chinese copy, from 13,666 to 10,108 tokens. Claude Code hands the model only a 2KB preview of a SessionStart injection longer than 10,000 characters, so `scripts/check-parity.sh` fails once either playbook passes that length. The measurement's load check looks for the playbook's last heading in the attachments that reach the model, which a truncated preview would lack, and it found the full playbook in the main thread of every run.

**Stop gates hand control back to the main thread.** The reply gate blocks a reply that ends by offering a next step, and its reason restates when to act directly and how to put a decision to the user, so the main thread either takes that step or, when the decision really is the user's, asks again with the background, the consequences of each option and a recommendation. Replayed offline over 2,734 final replies written before the gate existed and scored against labels of which offered steps should simply have been done, assigned by a single agent that knew the gate's phrase list but not its output, its closing-offer rule blocks with 68.5% precision (Wilson 95% interval 59.3% to 76.4%) and 31.7% recall (14.5% to 55.8%). The context watermark gate reads the real usage from the session transcript, because the Stop hook input carries no token fields. Past 40% of the context window it blocks once and leaves the main thread to weigh a new session against a longer context: wrap-up that the context it holds can finish gets finished, and only a new large block of work next calls for a handoff, whose format includes a note to the user on where the work stopped and what they need to do next. Both gates give a reason when they block, and neither blocks the turn it has just resumed, because both allow the stop while `stop_hook_active` is set, so neither can loop. The window size is 1,000,000 tokens by default and is not detected from the model in use; it and the gate's three thresholds, 35%, 40% and the 5-point rise before each further block, can be overridden with `CONTEXT_WINDOW_TOKENS`, `CONTEXT_WARN_PCT`, `CONTEXT_HARD_PCT` and `CONTEXT_REBLOCK_DELTA_PCT`.

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

Each hook test prints `PASS=<n> FAIL=<n>` and exits non-zero on any failure. The nine tests hold 494 cases in each copy. From the repository root, the check that `en/` and `zh/` hold matching copies runs with:

```bash
bash scripts/check-parity.sh
```

CI runs on every push and pull request. It runs the hook tests of both copies, 494 cases each, on Ubuntu and macOS, runs shellcheck over the hooks, their tests and the repository scripts, and runs the en/zh parity check.

## Documentation

| Document | Topic |
|---|---|
| [ADR 0001: Orchestration rules reach only the main thread](docs/adr/0001-orchestration-rules-reach-only-the-main-thread.md) | Where the playbook is loaded |
| [ADR 0002: Every subagent brief carries six elements](docs/adr/0002-every-subagent-brief-carries-six-elements.md) | What a delegation must contain |
| [ADR 0003: Subagents cannot spawn subagents](docs/adr/0003-subagents-cannot-spawn-subagents.md) | Who may dispatch work |
| [ADR 0004: The context watermark is read from transcript usage and gates the stop on a handoff](docs/adr/0004-context-watermark-read-from-transcript-usage.md) | How the context watermark is measured |
| [ADR 0005: Hooks that deny, block or inject rules ship with regression tests](docs/adr/0005-deciding-hooks-ship-with-regression-tests.md) | Which hooks carry tests |
| [ADR 0006: Ask the user only where the answer is theirs](docs/adr/0006-ask-the-user-only-where-the-answer-is-theirs.md) | When the agent asks and when it acts |
| [ADR 0007: Handoff timing weighs a session switch against a longer context](docs/adr/0007-handoff-timing-weighs-switch-against-long-context.md) | When a long session hands off |
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
