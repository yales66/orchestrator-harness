# Effort sweep

This directory measures whether a subagent brief gets done as well at reasoning effort `medium` as at `high`, and how much each costs. The answer decides which kinds of dispatch can drop to `medium`. Every case is a real brief the main thread wrote between 16 and 29 September 2026, replayed on the commit it was written against, so the comparison holds the brief, the model (`claude-opus-5-5`), the workspace and the installed rule files fixed and changes only the effort.

Conversation text, briefs and results live in a private data directory outside the repository, passed to every script as `--data`. The repository keeps only the scripts and this README.

## Cases

The cases are split into three tiers, because the decision is expected to differ between them. The sweep runs 20 cases.

| Tier | What the brief asks for | How it is graded | Cases |
|---|---|---|---:|
| impl | an implementation whose design decisions the brief already fixes | end state of the workspace: the brief's own self-verification commands | 8 |
| lookup | read-only retrieval and extraction | the final report against conclusions the main thread later adopted | 6 |
| judgement | read-only review or diagnosis that needs judgement | the same, against the adopted verdicts | 6 |

`cases.jsonl` holds 25 cases; five of them are excluded because each repeats a retained case's repository, brief template and problem class, so it adds cost without adding a kind of dispatch. `EXCLUDE` in `common.py` maps each excluded id to its reason and `load_cases` drops those ids, so the runner, the self-test and `inputs.html` skip them even when a rebuilt `cases.jsonl` still holds them; `inputs.html` lists them with their reasons.

| Excluded case | Repeats |
|---|---|
| impl-aggregator-providers | impl-workday-paging: same repository, both change the code of one data source the project fetches from |
| lookup-obs-api | lookup-obs-external: same backend observability inventory, same brief template |
| lookup-obs-worker | lookup-obs-external, as above |
| judge-recheck-r4-r11 | one of five rechecks of root-cause fixes on `main` from one template in one repository; overlaps judge-recheck-r5 in problem class. The design document of that repository numbers its confirmed defects R1 to R12, and the suffix of each recheck id names the defects its brief rechecks, here R4 and R11 |
| judge-recheck-r5 | the same series; overlaps judge-recheck-r4-r11 |

A brief qualifies only if its repository still exists and the commit it was written against can be located from the dispatch timestamp. Briefs that contain credentials are excluded. For an impl case the self-verification commands must also run offline and the change that later landed must pass them; parts of a self-verification that need the network, a running server or a screenshot are listed per case as ungraded. For a read-only case the report must state its conclusions itself, and those conclusions must reappear in a later brief, commit or design document, which is recorded per case as `adopted_in`. Files a read-only brief read from a session scratch directory are carried inside `cases.jsonl` and restored at run time.

## Grading

An impl attempt passes when every graded self-verification command exits 0 in the workspace the subagent leaves behind, at least one file inside the brief's file scope has changed, and nothing outside that scope has changed. Where the change that landed came with tests whose interface the brief fixed, those tests are replayed on the end state as extra checks; they count towards `checks` but not towards `pass`, because the brief rarely pins every name a test might import.

A lookup or judgement attempt passes when every conclusion check matches the final report (plus any artifact file the brief asked for), no forbidden claim appears, and the workspace is untouched. A check is a set of regular expressions of which any may match; checks name a fact, a `file:line` with a tolerance of a few lines, or a verdict, and several are written to fail on the negated claim.

Every row carries `pass`, the headline, and `checks`, the share of atomic checks satisfied, which is continuous and therefore resolves smaller differences between the two efforts.

## How a case runs, and why this way

Each attempt gets its own clone of the case's repository in a new directory under the system temp directory (`tempfile.gettempdir()`, with symlinks resolved), removed afterwards. The clone is made with `git clone --no-local --no-hardlinks --mirror`, so a base commit reachable only from a remote-tracking ref is still found, and a base left on no ref at all by a squash merge is copied in as a pack of exactly its own history; then its remote is removed, every ref is deleted, a single branch `main` is pointed at the base commit and checked out, reflogs are expired and `git gc --prune=now` drops everything else. The subagent therefore cannot reach any commit made after the dispatch, and a brief's mention of `main` resolves to the base commit. Before the model is called, the runner checks the clone the same way the self-test does and fails the attempt as `workspace_leak` if anything later is left. Each attempt also gets a fresh `CLAUDE_CONFIG_DIR` holding `zh/` installed as the README's install steps describe: `CLAUDE.md`, the playbook, hooks, skills and agents. One more agent is added, `effort-sweep-high` or `effort-sweep-medium`, whose frontmatter pins `model: claude-opus-5-5` and the effort. `claude -p` then starts a main thread that makes exactly one Agent call to that agent. A `PreToolUse` hook replaces the placeholder prompt of that call with the case's brief, so the subagent receives it byte for byte, and the runner checks that the first message in the subagent's transcript equals the brief. Absolute paths into the original checkout are rewritten to the workspace, and artifact paths to the attempt's output directory.

Two setups were considered, and this one is closer to a real subagent.

| | One dispatch from an isolated main thread (used) | `claude -p --effort X` with the brief as the prompt |
|---|---|---|
| System prompt and tools | the subagent's, including `SubagentHandback` | the main thread's, with the Agent tool available |
| Rule files in context | `CLAUDE.md` only, as ADR 0001 intends | `CLAUDE.md` plus the playbook the SessionStart hook injects |
| Hooks | see `agent_id`, so nested dispatch is denied as ADR 0003 requires | see no `agent_id`, so the brief could fan out |
| Effort mechanism | the agent frontmatter, the lever a downgrade would actually use | the CLI flag, a different path |
| Extra cost | one short main-thread turn, recorded apart as `dispatch_usage` | none |

The frontmatter `effort` overrides the session's effort, and `CLAUDE_CODE_EFFORT_LEVEL` would override the frontmatter, so the runner starts `claude` with a cleared environment and refuses to run when that variable is set in its own. The agent body is a two-sentence instruction shared by both efforts; it is not Claude Code's built-in general-purpose prompt, which is a constant difference between this setup and production and does not differ between the arms.

For every attempt the runner reads the subagent's own transcript and records the sum of `usage` over its API requests, the served model, tool calls, stop reason and latency. It fails the attempt into `errors.jsonl` when the served model is anything but `claude-opus-5-5`, when there is not exactly one subagent transcript, when the brief arrived altered, when the subagent's requests did not carry the effort under test, when an API error such as a usage limit ended the attempt early (`rate_limited` or `api_error`), on the wall-clock ceiling, or on any harness exception; such attempts never occupy a row in `results.jsonl`, so a rerun retries them. Each row of `results.jsonl` holds `prompt_id`, `tags`, `grade`, `usage`, `model`, `latency_s`, `tool_calls` and `status`, with the tier as the first tag, a trace per attempt under `traces/`, and the raw transcripts under `raw/`. The high arm writes to `baseline/` and the medium arm to `v1/`.

## Running

The graders and the workspace can be checked without any model call. For every case, `selftest.py` checks that the prepared clone is clean, meaning `git log --all` lists no commit newer than the dispatch commit or outside its history, only `main` is left, no remote is configured, and `git cat-file -e` fails for the landed commit and for every source branch tip that is not an ancestor of the base. It then grades three constructed end states: the change that landed (for read-only tiers, the adopted report), which must pass; the untouched workspace or an empty report, which must fail; and a state where something changed but the self-verification fails (only the landed tests, implementation left at base) or a plausible report with the key conclusion wrong, which must also fail.

```bash
DATA=<private data directory>
python3 eval/effort-sweep/selftest.py --data "$DATA"
python3 -m pytest eval/effort-sweep -q
python3 eval/effort-sweep/run.py run --data "$DATA" --effort high --dry-run
python3 eval/effort-sweep/render_inputs.py --data "$DATA"
```

A real run needs credentials in the environment, because a fresh `CLAUDE_CONFIG_DIR` cannot reach the keychain login, and a one-time approval of the harness, which records a hash of the runner, the grader, the cases and the installed rule files in `$DATA/_state.json`; any later change to those files stops the runner until it is approved again.

```bash
export CLAUDE_CODE_OAUTH_TOKEN=<token printed by claude setup-token>
python3 eval/effort-sweep/run.py run --data "$DATA" --effort high --approve-harness
python3 eval/effort-sweep/run.py run --data "$DATA" --effort high --reps 2
python3 eval/effort-sweep/run.py run --data "$DATA" --effort medium --reps 2
python3 eval/effort-sweep/run.py summarize --data "$DATA"
```

`summarize` prints, per tier and effort, the pass rate with a Wilson interval, the mean of `checks`, the median and range of tokens per attempt, the median output tokens and the median latency, then the paired difference in `checks` between the efforts with a 95% t interval on n − 1 degrees of freedom and the median over cases of the medium to high token ratio. For both paired figures each case's reps are averaged first, and tokens include cache reads and writes. `--cases`, `--concurrency`, `--timeout-s`, `--max-budget-usd` and `--keep` narrow a run, bound it or keep its workspaces. `--inline-brief` is a fallback for a Claude Code version whose hooks cannot rewrite tool input; the main thread then copies the brief itself and the verbatim check catches any drift. The scripts use the Python standard library only.

## Results

The sweep ran the 20 cases twice at each effort on `claude-opus-5-5` between 30 September and 1 October 2026, 80 valid attempts in all: 16 per effort for impl and 12 per effort for each read-only tier. Attempts cut short by the subscription's usage limit were written to `errors.jsonl` as `rate_limited` and run again, so none of them occupies a row. `python3 eval/effort-sweep/run.py summarize --data "$DATA"` prints the table below from the data directory.

| Tier | Pass rate at high [Wilson 95%] | Pass rate at medium [Wilson 95%] | Paired difference in the share of `checks` satisfied, high minus medium, percentage points (95% t interval) | Medium tokens ÷ high: median over cases of the per-case ratio (each case's two reps averaged first), tokens including cache reads and writes | Median seconds per attempt, high / medium |
|---|---|---|---|---:|---:|
| impl | 88% [64%, 97%] | 88% [64%, 97%] | -1.0 (-3.5 to +1.4) | 0.54 | 394 / 269 |
| lookup | 50% [25%, 75%] | 58% [32%, 81%] | -1.2 (-7.5 to +5.1) | 0.49 | 450 / 212 |
| judgement | 50% [25%, 75%] | 42% [19%, 68%] | +2.0 (-14.7 to +18.7) | 0.42 | 407 / 240 |
| all | 65% [50%, 78%] | 65% [50%, 78%] | -0.2 (-4.4 to +4.1) | 0.51 | 424 / 224 |

`summarize` prints the paired difference as a share; the table gives it in percentage points. A negative paired difference means medium satisfied slightly more checks. An attempt passes only when every check holds, and the per-tier pass rates rest on 12 to 16 attempts, so their intervals overlap almost entirely and the paired difference in `checks` carries the comparison. For impl the interval's upper end puts any drop at medium at no more than about 1.4 points of checks, and for lookup at no more than about 5.1, at about half the tokens. For judgement the upper end reaches 18.7 points, so six cases cannot rule out a drop of about 19 points.

Priced at API list rates from the recorded `usage`, the subagents' usage comes to $68.3 at high and $41.4 at medium: impl $21.5 against $14.0, lookup $27.0 against $16.7 and judgement $19.8 against $10.7. The runs themselves drew on a subscription's usage allowance. The cost ratio of about 0.6 sits above the token ratio of about 0.5 because a cache read is priced at a hundredth of an output token, and most of the tokens medium saves are cache reads. Summed over all attempts:

| Effort | Cache reads | Cache writes | Output | Input |
|---|---:|---:|---:|---:|
| high | 110,969,304 | 4,133,727 | 1,269,603 | 2,626 |
| medium | 55,865,893 | 2,841,555 | 801,064 | 1,746 |

Medium halves the cache reads but keeps about two thirds of the cache writes and of the output, and those two carry two thirds or more of the cost at either effort.

ADR 0008 (`docs/adr/0008-subagent-effort-per-kind-of-dispatch.md`) records the decision these results support: implementation with settled decisions and read-only lookup run at `medium`, and judgement-bound review and diagnosis stay at `high`. Judgement moves to `medium` only once a larger sample brings the upper end of its interval on the paired difference in checks, high minus medium, down to the level the other two tiers reached, about 5 percentage points.

## Files

| File | Role |
|---|---|
| run.py | builds the workspace and config dir, dispatches the brief, reads the subagent transcript, grades, writes rows, traces and errors, and summarizes |
| grade.py | the end-state grader for impl cases and the report grader for read-only cases |
| common.py | case loading and the exclusions, the pruned clones and their leak check, overlays, path globbing, prompt rewriting |
| selftest.py | the offline leak, oracle, null and broken checks of every case |
| render_inputs.py | renders `cases.jsonl` as `inputs.html` for review, with the excluded cases and their reasons |
| test_grade.py | unit tests for the grader's pure functions |
| test_exclude.py | unit tests for the case-set exclusions |
| test_common.py | unit tests for the workspace location |
| test_summarize.py | unit tests for the t interval on the paired difference |
| test_api_failure.py | unit tests for failing an attempt that an API error or usage limit cut short |
| test_bodies.py | unit tests for reading the effort each request carried from the captured request bodies |

The data directory holds `cases.jsonl`, `inputs.html`, and after a run `_state.json`, `baseline/` and `v1/`.

## Limits

Claude Code ends a turn it cannot complete, such as one refused by the subscription's usage limit, with a synthetic assistant message that a check on the served model alone does not catch. The runner's check for such attempts, which fails them as `rate_limited` or `api_error`, is in commit `3a066e4`.

A clone holds one branch, so a brief that names another branch, such as the unmerged branch that the five rechecks of numbered defects in one repository compare against, or `origin/main`, finds nothing under that name, whereas the original subagent could read it. The runner still records in `meta.leak_signals` any tool call that touches the original checkout, lists history across all refs or names the landed commit, as a second line of defence.

The read-only checks were written from reports that a model produced, most of them `claude-opus-5-5`, and kept only where the main thread later acted on the conclusion. They test the conclusion and its evidence, not the wording, but a report that reaches the same conclusion through different evidence can still miss a `file:line` check. Graded self-verification drops the parts that need the network or a running service, and one case runs `docker compose config` with placeholder secrets because the workspace has no `.env`.

The transcripts Claude Code writes do not show which effort a request ran at, so the runner has Claude Code write every request body of an attempt to a temporary directory (`OTEL_LOG_RAW_API_BODIES=file:<dir>`) and reads `output_config.effort` back from them. A request whose first user message holds the brief is the subagent's, every other one the dispatching main thread's; both sets go into `meta.effort_in_requests`, and an attempt whose subagent requests carried anything but the effort under test fails as `effort_mismatch`. The bodies themselves are removed with the attempt's temp directory. The historical token figures in `inputs.html` are the original runs' usage, not a pilot of this setup. With 20 cases a pass rate carries a noise floor of about `1/sqrt(20 × reps)`, roughly ±16 points at two reps, so a per-tier difference is visible only when it is large; `checks` and the paired design narrow this, and more reps narrow it further.
