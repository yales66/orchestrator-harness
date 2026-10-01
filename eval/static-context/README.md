# Static context measurement

This directory measures the first-request input of the main thread and of a freshly spawned general-purpose subagent under two configurations that differ only in where the orchestrator playbook lives. First-request input is the input tokens of a thread's first API request, which hold only fixed content: Claude Code's own system prompt and tool definitions, CLAUDE.md, the skill list, any text injected by hooks, and for a subagent the brief it was given; nothing the thread reads or produces later is included. The harness injects the playbook into the main thread through a SessionStart hook, while group N appends it to CLAUDE.md, which every subagent also loads.

| Group | Installed into a fresh CLAUDE_CONFIG_DIR | Playbook location |
|---|---|---|
| H | en/CLAUDE.md, en/hooks, en/skills, en/agents, orchestrator-playbook.md, and the hooks block of en/settings.example.json | injected into the main thread by the SessionStart hook |
| N | the same as H, but without the SessionStart hook registration | appended to the end of CLAUDE.md |

Every run gets its own temporary CLAUDE_CONFIG_DIR, HOME and empty working directory, and the claude process is started with a cleared environment, so the real `~/.claude` (its skills, plugins, MCP servers and CLAUDE.md) is never read.

## Running

A fresh config directory cannot reach the keychain login, so credentials are passed through the environment. Create a long-lived token once with `claude setup-token`, then run from the repository root:

```bash
export CLAUDE_CODE_OAUTH_TOKEN=<token printed by claude setup-token>
bash eval/static-context/run.sh
```

`ANTHROPIC_API_KEY` works in place of the OAuth token. The token is handed to the child process through its environment and is never written to disk. The script runs each group twice with `claude-opus-5-5` for both the main thread and the subagent, rewrites `results.json` and `results.md`, and prints the temp directory that keeps the raw stream and transcript logs. It stops early if a thread's first-request input exceeds 100000 tokens or if a thread made no API request. The prompt asks the main thread to pass the requested model's alias (opus, sonnet, haiku or fable, read from `SC_MODEL`) as the Agent tool's model parameter, because the installed playbook tells the main thread to choose a subagent model itself and `CLAUDE_CODE_SUBAGENT_MODEL` does not override an explicit choice.

Only comparable runs enter the comparison. After the planned runs finish, `python3 parse_usage.py check <work_dir> <model>` prints the run directories to discard: a run whose subagent ran on a model other than `<model>`, and among the remaining runs one whose main thread or subagent was announced a different set of deferred tools than the reference set for that thread, which is the set most of those runs received, or the smaller set on a tie. The deferred tool sets come from the `deferred_tools_delta` attachments in the session transcripts, because Claude Code occasionally announces extra deferred tools to a session and they add to the first-request input. `run.sh` reruns the listed runs in place and checks again, for up to `SC_RETRIES` rounds (default 3), and counts each discarded attempt in the run directory's `discarded_attempts` file. A run still invalid after the last round keeps its row in `results.md` with Valid set to no; the repeat consistency and group difference tables use only valid runs, take the first valid run of each group, and show n/a when a group has none.

`SC_SETUP_ONLY=1 bash eval/static-context/run.sh` builds the two config directories without calling the API, which is useful for inspecting exactly what each group installs. `SC_COPY=zh` installs the Chinese copy instead of `en/` and writes `results.zh.json` and `results.zh.md`. `SC_MODEL`, `SC_REPEATS`, `SC_WORK`, `SC_MAX_INPUT` and `SC_RETRIES` override the model (a full model id naming opus, sonnet, haiku or fable), the repeat count, the log directory, the abort threshold and the number of rerun rounds.

The numbers in `results.md` were measured on Claude Code 2.1.286 with `claude-opus-5-5` for both the main thread and the subagent. Claude Code's own system prompt and tool definitions change from version to version, so the absolute numbers hold only for 2.1.286, and another version needs a rerun of this script.

## Results

| Group | Main thread first-request input (tokens) | Subagent first-request input (tokens) |
|---|---|---|
| H | 20,527 | 10,190 |
| N | 20,516 | 13,533 |

The subagent's first-request input is 3,343 tokens lower in H, about 25%, because N's subagent loads the playbook with CLAUDE.md. The load checks in `results.md` find the full playbook in the context the main thread receives in both groups, and the two main threads differ by 11 tokens. The script reruns any run whose subagent model or deferred tool set makes it not comparable, and both runs of each group gave identical totals. The Chinese copy, measured with `SC_COPY=zh`, cuts the subagent's first-request input from 13,741 to 10,110 tokens, 3,631 fewer or about 26%, and both repeats of each group gave identical totals ([results.zh.md](results.zh.md)). The table reports the first repeat, and `bash eval/static-context/run.sh` reruns the whole measurement.

## Files

| File | Role |
|---|---|
| run.sh | builds the two configurations, runs `claude -p --output-format stream-json --verbose --include-hook-events`, and calls the parser |
| parse_usage.py | extracts the token usage of each thread's first API request from stream-json (main thread has a null `parent_tool_use_id`, the subagent a non-null one) and from the session transcripts, flags runs that are not comparable, then aggregates and renders the results |
| test_parse_usage.py | unit tests for the parser, the aggregation and the rendering on synthetic stream-json and run-summary fixtures |
| results.json | numbers from the latest run, including per-run hook events, playbook load checks, deferred tool sets, validity, discarded attempts and init metadata |
| results.md | tables rendered from results.json, with configuration notes and limitations |

Run the tests with `python3 -m pytest eval/static-context/test_parse_usage.py -q`.
