# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

| Component | What it provides |
|---|---|
| `retriever` subagent | `agents/retriever.md`, read-only lookup and extraction of what can be read straight off the evidence, at effort `medium`, including searches of session transcripts. An answer that would take a judgement comes back as facts with the open judgement named, and a search whose answer could sit anywhere in a repository is not its work. It creates a new file only at a path the brief names or under the system temp directory and does not change existing ones |
| `implementer` subagent | `agents/implementer.md`, implementation whose design decisions the brief has fixed, at effort `medium` with every tool. It reports a decision the brief left open instead of settling it |
| ADR 0008 | Why subagent effort is set per kind of dispatch, with the effort sweep's results |
| ADR 0009 | Why read-only subagents create files only where the brief points and `retriever` leaves a judgement to the main thread; it supersedes the Limits of those two definitions in ADR 0008 |
| `scripts/ci-local.sh` | Runs the CI checks locally in one command: the hook tests of both copies, shellcheck and the en/zh parity check, exiting non-zero if any fails. It covers only the operating system and bash it runs on |
| `handoff` skill | `skills/handoff/SKILL.md` generates `HANDOFF.md` whole. `scripts/extract.py` writes every input the user gave in the session, including answers to choice questions in either wording, and the git state of each repository; `--transcript` is required. A `researcher` with none of the session's context writes the draft and checks before it writes; the review takes the first branch that holds and has the same `researcher` rewrite through SendMessage when the open items must change; `scripts/finalize.sh` moves the draft into place and archives the old handoff. Step 0 checks the entry: wrap-up gets no handoff, and a question that awaits the user gets a one-off wake-up 50 minutes out, which writes the handoff before a one-hour prompt cache expires. The scripts carry pytest tests |
| `handoff-guard.sh` | PreToolUse hook on `Edit\|Write\|NotebookEdit\|MultiEdit\|Bash` that denies direct writes to `HANDOFF.md` in every thread, while writing `HANDOFF.new.md` and running `finalize.sh` pass |
| `production-merge-gate.sh` | PreToolUse hook on `Bash` that has Claude Code ask the user before `gh pr merge` in a repository marked with `git config claude.production true`, and before a merge whose `-R` names another repository |
| `production-mode-hint.sh` | UserPromptSubmit hook that adds one line on setting and checking the production mark when the user's own message mentions production mode |
| ADR 0010 | Why handoffs are generated whole by the handoff skill and a hook denies hand edits; it supersedes the handoff format of ADR 0004 and the cross-session authorisation rule of ADR 0006 |
| ADR 0011 | Why wrap-up finishes in the current session at any watermark and a pending decision gets a wake-up before the cache expires; it extends ADR 0007 |
| ADR 0012 | Why merging a pull request the task opened is undoable outside production repositories and a hook asks first in production; it supersedes the classing of merging as external in ADR 0006 |
| CI job for skill scripts | Runs the pytest tests under `skills/*/scripts/` of both copies; `scripts/ci-local.sh` runs them too and fails when pytest is missing |
| `keepalive-gate.sh` | Stop hook that, once the main thread's context reaches 150,000 tokens with no live keepalive, has the model set a recurring CronCreate task every 30 minutes that keeps the one-hour prompt cache warm while the user is away. The keepalive deletes itself when the conversation holds no record of setting it, as after `/clear`, and the hook has it deleted 8 hours after the user's own last message. `keepalive-gate.test.sh` holds 28 cases, and ADR 0013 records why |

### Changed

| Component | What changed |
|---|---|
| `researcher` subagent | Runs at effort `high`, covers only read-only review, diagnosis, research and drafting that need judgement, and creates a new file only at a path the brief names or under the system temp directory |
| Playbook §1 and §2 | §2 routes each kind of dispatch to Explore, haiku, `retriever`, `researcher`, `implementer` or opus; §1 sends a search of session transcripts out through §2 instead of naming an agent; a read-only dispatch's output file must not be named `report*`, `summary*`, `findings*` or `analysis*`, which Claude Code 2.1.286 refuses to let a subagent write |
| Playbook §1 | The row routing domain-model work to `domain-modeling` is gone; with the skill installed its own description triggers it |
| `memory-audit` skill | The backup step no longer describes the author's own `~/.claude` layout |
| `subagent-readonly-guard.sh` | Restricts `retriever` the same way as `researcher` |
| Hook regression tests | Cases for the `retriever` restriction, for `implementer` passing the guard, for the three new hooks and for the watermark gate's block reasons naming the handoff skill. The hook tests hold 626 cases per copy, and the handoff scripts 36 pytest cases |
| Static context measurement | Rerun with the three agent definitions on Claude Code 2.1.286 and claude-opus-5-5. Each subagent's first-request input is 10,186 tokens in H against 13,529 in N for the English copy, 3,343 fewer or about 25%, and 10,108 against 13,739 for the Chinese copy, 3,631 fewer or about 26% |
| Fork replay runner | `--playbook FILE` replaces every playbook the recorded SessionStart hook injected into the session copy, including the rendered text a resume sends to the model, and the playbook in the config directory. A case's `cut_uuid` removes the earlier tasks before that prompt from the session copy. The reps of a case run back to back from a temp directory fixed per case and variant, so every rep after the first reads the request prefix from a prompt cache written at the 5-minute TTL. A dropped network connection is retried in place like an overload or a rate limit, five attempts within about three minutes. Replays run at effort `high` unless the eval config sets another, because the recorded sessions ran at `high` and claude-opus-5-5 falls back to `medium` when nothing sets it |
| Effort sweep | Ran 20 briefs twice at each effort on claude-opus-5-5, with the results in its README and in ADR 0008. The runner reads the effort each request carried from the captured request bodies and fails an attempt whose subagent requests carried another effort as `effort_mismatch`, and it fails an attempt that a usage limit or another API error cut short as `rate_limited` or `api_error` |
| Evaluation write-up | `docs/evaluation.md` and `docs/zh/evaluation.md` report the effort sweep's results, and note that the static context figures were measured before the handoff skill was added and playbook §3 was shortened |
| Rules on missed asks | Shelved, with the reason in its README. Neither playbook arm routes work to `feature-sharding`, a skill the repository does not ship |
| Gate follow-through | The stub hook's denial reads "PreToolUse hook：已记录，视同执行。" (recorded, treated as done) |
| Architecture diagrams | The read-only guard box in all four diagrams covers `retriever` as well as `researcher`. The diagrams add the UserPromptSubmit hook, the handoff guard and the production merge gate in PreToolUse, and a handoff file generated only by the handoff skill |
| Playbook §1 | Merging a pull request this task opened, with no reviewer, once CI or the delivery gate passes counts as undoable, and merging leaves the list of external steps; a pull request left as a draft over doubts about its content is not merged. An authorisation valid across tasks goes into project memory, and one binding only this task's remaining work travels in the handoff |
| Playbook §3 | Progress goes into the task's progress source or an append-only `PROGRESS.md`, which `HANDOFF.md` never counts as; `HANDOFF.md` is generated only by the handoff skill; wrap-up is finished at any watermark unless the gate blocks again. The handoff structure and evidence items moved into the handoff skill |
| `context-watermark-gate.sh` | Its block reasons point to the handoff skill and end with the transcript path |
| `settings.example.json` | Registers `production-mode-hint.sh` on UserPromptSubmit, `production-merge-gate.sh` on PreToolUse `Bash` and `handoff-guard.sh` on PreToolUse `Edit\|Write\|NotebookEdit\|MultiEdit\|Bash` |
| `scripts/check-parity.sh` | Files under `skills/*/scripts/` must be byte-identical in the two copies, as the hooks are |
| README | Describes the handoff skill, the three new hooks and the UserPromptSubmit path, gives the one-hour cache premise behind the 50-minute wake-up and how to adjust it, and notes that the static context figures were measured before this change |

## [0.4.0] - 2026-09-30

### Added

| Component | What it provides |
|---|---|
| ADR 0007 | `docs/adr/0007-handoff-timing-weighs-switch-against-long-context.md` and its Chinese copy record how the handoff timing weighs a session switch against a longer context. It supersedes the handoff timing of ADR 0004, whose way of reading the watermark from transcript usage stands |

### Changed

| Component | What changed |
|---|---|
| Playbook §3, the Timing item | Past the watermark hard line the main thread weighs the cost of a switch, a re-read in the new session and an interruption for the user, against the worse judgement of a longer context. It finishes remaining work that its context already covers, such as a commit, push or pull request, and writes the handoff and asks the user to switch sessions before a new large block of work. It writes the handoff at once when the user ends the session or the gate blocks a second time |
| `context-watermark-gate.sh` | Past 35% the gate reminds once per session, and its reminder no longer asks for a handoff. Its first block past 40% restates the weighing, and a second block after another 5-point rise asks for the handoff at once. Both scratchpad marks are cleared when usage falls back below 35%, as after compaction |
| Hook regression tests | Cases for the single reminder, the reset below the reminder line and the wording of each block reason. The hook tests hold 494 cases per copy |
| README and architecture diagrams | The design goals, the architecture section, the four diagrams and the hook table describe the new handoff timing, and "Two mechanisms worth a closer look" covers the playbook reaching only the main thread and the Stop gates handing control back to it |
| Static context measurement | Rerun on the current playbooks with Claude Code 2.1.285 and claude-opus-5-5. Each subagent's first-request input is 10,186 tokens in H against 13,489 in N for the English copy, 3,303 fewer or about 24%, and 10,108 against 13,666 for the Chinese copy, 3,558 fewer or about 26% |
| English playbook | Reworded to 9,882 characters, below the 10,000 at which Claude Code passes only a preview of a SessionStart injection |

### Fixed

| Component | What changed |
|---|---|
| Static context measurement | The prompt passes the requested model's alias to the Agent call, since the installed playbook tells the main thread to pick a subagent model and some runs had dispatched it on haiku. `parse_usage.py check` marks a run whose subagent model or deferred tool set is not comparable, `run.sh` reruns it for up to `SC_RETRIES` rounds, and `results.md` reports each run's validity and discarded attempts |

## [0.3.0] - 2026-09-30

### Added

| Component | What it provides |
|---|---|
| Hook mutation testing | `eval/hook-mutations/`, which injects one defect at a time into a copy of a hook and runs that hook's tests against it. `mutations.tsv` holds 54 mutants and `holdout.tsv` 35 more, written from the hook header comments without reading the tests. The tests kill 54 of 54 and 30 of 35, and `bash eval/hook-mutations/run.sh` reruns the first set |
| Reply gate replay | `eval/reply-gate-replay/`, which replays `reply-gate.sh` offline over past session transcripts kept in a private data directory and scores it against blind labels. Over 2,734 replies the closing-offer rule has 68.5% precision and 31.7% recall, and `python3 eval/reply-gate-replay/score.py --data "$DATA"` recomputes them from that directory |

### Changed

| Component | What changed |
|---|---|
| `secret-guard.sh` | The guard judges the command strings of `bash -c`, `sh -c`, `zsh -c` and `eval` like any other command, denies more commands that print a `.env` file, and denies a recursive `grep`, or an `rg` that searches dot files, over a tree holding a `.env` file that its options do not exclude. Relative search roots follow an earlier `cd` or `pushd`, and a `cd` target that is not literal counts as holding `.env` |
| `subagent-readonly-guard.sh` | The guard denies file-writing calls in inline interpreter code for Python, Node, Perl and Ruby, resolves relative paths after an earlier `cd` or `pushd`, and counts every relative write target as existing after a `cd` whose target is not literal |
| Hook regression tests | Cases for the new guard rules and boundary cases for the rules the first mutation run found untested. The hook tests hold 486 cases per copy, among them `reply-gate.test.sh` (37), `secret-guard.test.sh` (155) and `subagent-readonly-guard.test.sh` (160) |
| Evaluation write-up | `docs/evaluation.md` and `docs/zh/evaluation.md` pair every claim with the command that reruns it, report the static measurement, the mutation testing and the reply gate replay, and describe the gate follow-through, missed-ask and effort experiments as designed and not yet run |

### Fixed

| Component | What changed |
|---|---|
| Static context measurement | `eval/static-context/run.sh` installs `agents/` in both groups, since the `researcher` description is part of the Agent tool definition that every thread receives. On Claude Code 2.1.285 with claude-opus-5-5, each subagent's first-request input is 10,190 tokens in H against 13,513 in N, 3,323 fewer or about 25%, and the main thread's is 20,341 against 20,330 |

## [0.2.0] - 2026-09-29

### Added

| Component | What it provides |
|---|---|
| `reply-gate.sh` | A `Stop` hook that blocks the stop once when the reply ends by offering a next step, as in "Shall I …?" or 「要我…吗」, and restates in its reason when to act directly and how to put a decision to the user. With `REPLY_LANG=zh`, which `zh/settings.example.json` sets on its command, it also blocks once when a long reply is not in Chinese. It ignores code and URLs and allows a stop that is already continuing because of a `Stop` hook, so it never loops |
| `secret-guard.sh` | A `PreToolUse` hook on `Bash` and `Read` that keeps secret values out of the model's context. It denies reading `.env` files other than the `.example`, `.sample` and `.template` samples, and shell commands that would print such a file or a variable whose name marks it as a secret, while commands that only use the value pass |
| `subagent-readonly-guard.sh` | A `PreToolUse` hook on `Edit`, `Write`, `NotebookEdit`, `MultiEdit` and `Bash` that lets the `researcher` subagent create report files but denies every edit, overwrite, move or deletion of an existing file, including through shell commands and git subcommands that change the working tree, index, refs or remotes |
| `researcher` subagent | `agents/researcher.md`, the subagent the playbook routes read-only research, review, extraction, drafting and diagnosis to. It returns the file, location and exact text of any change it recommends, and the main thread makes the change |
| Hook regression tests | `reply-gate.test.sh` (35 cases), `secret-guard.test.sh` (91) and `subagent-readonly-guard.test.sh` (100). The hook tests hold 351 cases per copy across nine hooks |
| Playbook criteria for asking the user | The routing table confirms an action that cannot be taken back only right before that step, and asks at a fork only when the branches differ substantively and the choice depends on something only the user knows. A next step at wrap-up that lies within the user's goal, can be undone, is not external and calls no paid service is done and then reported, and the playbook lists which actions count as undoable, external and paid. A standing authorisation lasts for the session, covers only the objects and changes it named and ends when the user takes it back. A fact is checked in the repository and the git history before the user is asked about it, and a negative or time-sensitive claim carries a source and date retrieved in the same round |
| Playbook verification of visible outputs and prose for others | A change to something the user can see is compared against screenshots of the affected states and handed over with a preview link or launch command. Prose meant for other readers is reviewed by a `researcher` that carries none of the session's context, for at most two rounds |
| ADR 0006 | `docs/adr/0006-ask-the-user-only-where-the-answer-is-theirs.md`, with a Chinese version in `docs/zh/adr/`, records the criteria for asking the user and the reply gate |

### Changed

| Component | What changed |
|---|---|
| `CLAUDE.md`, changing existing code | The reason retrieved from git history and ADRs decides the next move. A reason that agrees with the change is followed and cited in the report. A reason showing that the current state is intentional and conflicts with the change leads to a question that cites it. A spot whose reason cannot be retrieved, where the change would alter behaviour, and a business threshold with no source in the repository, are left untouched while the rest of the task is done, and the report lists each one with the question the user needs to answer. A spot the user names for change in the current turn is changed directly |
| `CLAUDE.md`, corrections | A correction about an objective defect also fixes the same-cause instances in the files the task has already changed and lists them. A correction about style or wording lists similar instances without changing them. A correction that states a general rule is followed within the task and written into a feedback memory |
| Orchestrator playbook, dispatch | Read-only work whose deliverable is a conclusion goes to the `researcher` subagent. A read-only dispatch that writes its findings to disk is given the path of a new file, and any change the researcher wants comes back in its return |
| `scripts/check-parity.sh` | The parity check requires `agents/` to be byte-identical in both copies, and accepts the `REPLY_LANG=zh` prefix on the `zh/` reply gate command as the one difference between the two `settings.example.json` files |

## [0.1.1] - 2026-09-29

### Fixed

| Component | What changed |
|---|---|
| `worktree-symlink-claudemd.sh` | The hook resolves both the worktree path and the main worktree path to physical paths before computing the link, so a worktree path through a symlinked directory no longer leaves a dangling `CLAUDE.md` link. It replaces the worktree's `CLAUDE.md` only when the file matches `HEAD`, and keeps a file with uncommitted changes. The hook tests now hold 125 cases per copy |

## [0.1.0] - 2026-09-29

First public release of the harness. It ships as two complete copies, `en/` in English and `zh/` in Chinese, each of which installs on its own and mirrors the layout of `~/.claude/`.

### Added

| Component | What it provides |
|---|---|
| Global rules | `CLAUDE.md`, the rules loaded into every session, subagents included: how to write prose, how to change existing code and how to test |
| Orchestrator playbook | `orchestrator-playbook.md`, the rules for the main thread as orchestrator: task routing, the six-element subagent brief, long-task handoffs, the delivery gate and git conventions |
| Hooks | Six shell hooks, registered through `settings.example.json`: playbook injection on `SessionStart`, denial of nested subagents, denial of commits that skip the commit-msg hook, the context watermark gate on `Stop`, the rule-file edit reminder and worktree symlinking |
| Hook regression tests | `hooks/tests/`, 109 cases per copy covering all six hooks: regression tests for the four that deny, block or inject the playbook, and characterization tests that pin the behaviour of the rule-file edit reminder and worktree symlinking |
| Skills | `rule-file-editing` and `memory-audit` |
| Installation instructions | The Install section of each README, written for Claude Code: the user asks Claude to install the chosen copy, and the section gives Claude the steps to follow, which check the dependencies, back up every file the install overwrites, copy the files into `~/.claude` and merge the hooks block into an existing `settings.json` without dropping or duplicating entries |
| Continuous integration | `.github/workflows/ci.yml`, which on every push and pull request runs the hook tests of both copies on Linux and macOS, runs shellcheck on the hooks, their tests and the repository scripts, and runs `scripts/check-parity.sh` to confirm that `en/` and `zh/` hold the same files and byte-identical hooks |
| Architecture decision records | Five records in `docs/adr/`, with Chinese versions in `docs/zh/adr/`, covering playbook injection into the main thread only, the six-element brief, the ban on nested subagents, the context watermark gate and hook regression tests |
| Static context measurement | `eval/static-context/`, which measures the first-request input of the main thread and of a subagent. First-request input is the input tokens of a thread's first API request, which hold only fixed content: Claude Code's own system prompt and tool definitions, CLAUDE.md, the skill list, any text injected by hooks, and for a subagent the brief it was given; nothing the thread reads or produces later is included. `bash eval/static-context/run.sh` reruns it and rewrites the results |
| Evaluation write-up | `docs/evaluation.md`, with a Chinese version in `docs/zh/evaluation.md`, which states what the harness claims and what it does not, why a before and after comparison of session logs is not evidence, and what a controlled experiment would take and cost |
| Documentation | The MIT `LICENSE`, an English `README.md` and a Chinese `zh/README.md`. Each README carries a CI badge, an architecture diagram of what the main thread and subagents receive and where each hook acts, a section on what is measured, installation instructions for Claude Code, the test and CI commands, and links to the ADRs and the evaluation write-up |
