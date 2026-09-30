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

`ANTHROPIC_API_KEY` works in place of the OAuth token. The token is handed to the child process through its environment and is never written to disk. The script runs each group twice with `claude-opus-5-5` for both the main thread and the subagent, rewrites `results.json` and `results.md`, and prints the temp directory that keeps the raw stream and transcript logs. It stops early if a thread's first-request input exceeds 100000 tokens or if a thread made no API request.

`SC_SETUP_ONLY=1 bash eval/static-context/run.sh` builds the two config directories without calling the API, which is useful for inspecting exactly what each group installs. `SC_COPY=zh` installs the Chinese copy instead of `en/` and writes `results.zh.json` and `results.zh.md`. `SC_MODEL`, `SC_REPEATS`, `SC_WORK` and `SC_MAX_INPUT` override the model, the repeat count, the log directory and the abort threshold.

The numbers in `results.md` were measured on Claude Code 2.1.285 with `claude-opus-5-5` for both the main thread and the subagent. Claude Code's own system prompt and tool definitions change from version to version, so the absolute numbers hold only for 2.1.285, and another version needs a rerun of this script.

## Results

| Group | Main thread first-request input (tokens) | Subagent first-request input (tokens) |
|---|---|---|
| H | 20,341 | 10,190 |
| N | 20,330 | 13,513 |

The subagent's first-request input is 3,323 tokens lower in H, about 25%, because N's subagent loads the playbook with CLAUDE.md. The load checks in `results.md` find the full playbook in the context the main thread receives in both groups, and the two main threads differ by 11 tokens. Both repeats of each group gave identical totals. The Chinese copy, measured with `SC_COPY=zh`, cuts the subagent's first-request input from 13,641 to 10,108 tokens, 3,533 fewer or about 26%; in the first H run of that measurement Claude Code sent six extra deferred tools and the subagent took 11,371 tokens, so the comparison uses the second run, whose tool set matches the other three ([results.zh.md](results.zh.md)). The table reports the first repeat, and `bash eval/static-context/run.sh` reruns the whole measurement.

## Files

| File | Role |
|---|---|
| run.sh | builds the two configurations, runs `claude -p --output-format stream-json --verbose --include-hook-events`, and calls the parser |
| parse_usage.py | extracts the token usage of each thread's first API request from stream-json (main thread has a null `parent_tool_use_id`, the subagent a non-null one) and from the session transcripts, then aggregates and renders the results |
| test_parse_usage.py | unit tests for the parser, the aggregation and the rendering on synthetic stream-json and run-summary fixtures |
| results.json | numbers from the latest run, including per-run hook events, playbook load checks and init metadata |
| results.md | tables rendered from results.json, with configuration notes and limitations |

Run the tests with `python3 -m pytest eval/static-context/test_parse_usage.py -q`.
