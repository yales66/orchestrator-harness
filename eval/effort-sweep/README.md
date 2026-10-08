# Effort sweep

This directory measures whether a subagent brief gets done as well at reasoning effort `medium` as at `high`, and how much each costs. The answer decides which kinds of dispatch can drop to `medium`. In the September sweep every case is a real brief the main thread wrote between 16 and 29 September 2026, replayed on the commit it was written against, so the comparison holds the brief, the model (`claude-opus-5-5`), the workspace and the installed rule files fixed and changes only the effort. The October sweep, described under "Haiku sweep (October 2026)", replays briefs the same way with the subagent's model as a second variable, to decide which dispatches can move from Opus 5.5 to Haiku 5.5.

Conversation text, briefs and results live in a private data directory outside the repository, passed to every script as `--data`. The repository keeps only the scripts and this README.

## Cases

The cases are split into three tiers, because the decision is expected to differ between them. The sweep runs 20 cases.

| Tier | What the brief asks for | How it is graded | Cases |
|---|---|---|---:|
| impl | an implementation whose design decisions the brief already fixes | end state of the workspace: the brief's own self-verification commands | 8 |
| lookup | read-only retrieval and extraction | the final report against conclusions the main thread later adopted | 6 |
| judgement | read-only review or diagnosis that needs judgement | the same, against the adopted verdicts | 6 |

`cases.jsonl` holds 25 cases; five of them are excluded because each repeats a retained case's repository, brief template and problem class, so it adds cost without adding a kind of dispatch. An excluded case carries its reason in an `exclude` field of its row, and `load_cases` drops every row that has one, so the runner, the self-test and `inputs.html` skip them; `inputs.html` lists them with their reasons. Case ids name private projects, so the table below describes each exclusion without its id.

| Excluded | Repeats |
|---|---|
| one impl case | a retained impl case in the same repository; both change the code of one data source the project fetches from |
| two lookup cases | a retained lookup case: the same backend observability inventory, from the same brief template |
| two judgement cases | each other: two of five rechecks of root-cause fixes on `main`, from one template in one repository, overlapping in problem class |

A brief qualifies only if its repository still exists and the commit it was written against can be located from the dispatch timestamp. Briefs that contain credentials are excluded. For an impl case the self-verification commands must also run offline and the change that later landed must pass them; parts of a self-verification that need the network, a running server or a screenshot are listed per case as ungraded. For a read-only case the report must state its conclusions itself, and those conclusions must reappear in a later brief, commit or design document, which is recorded per case as `adopted_in`. Files a read-only brief read from a session scratch directory are carried inside `cases.jsonl` and restored at run time.

## Grading

An impl attempt passes when every graded self-verification command exits 0 in the workspace the subagent leaves behind, at least one file inside the brief's file scope has changed, and nothing outside that scope has changed. Where the change that landed came with tests whose interface the brief fixed, those tests are replayed on the end state as extra checks; they count towards `checks` but not towards `pass`, because the brief rarely pins every name a test might import. A case lists in `hidden.exclude` the landed tests that assert details no brief fixed, and their failures count neither against that check nor in the landed-test share below. A replay that stops while collecting tests, with no test passed and an error raised, cannot say how the landed tests fare, so it is marked indeterminate and left out of `checks`.

The landed-test share of an impl attempt is the share of landed tests that pass, summed over the replayed commands whose pytest or vitest summary line the grader kept. The brief's own self-verification mostly runs tests the subagent wrote itself, so the landed tests are the independent signal, and this share resolves them more finely than the all-or-nothing check does.

An impl attempt is graded in the workspace, unless the workspace has no change inside the brief's scope and exactly one linked worktree inside it differs from the base commit, as when a brief tells the subagent to make a worktree of its own; that worktree is then graded. When the graded directory's HEAD is not the base commit, it is first soft-reset onto the base, so committed changes are graded like uncommitted ones.

A lookup or judgement attempt passes when every conclusion check matches the final report (plus any artifact file the brief asked for), no forbidden claim appears, and the workspace is untouched. A check is a set of regular expressions of which any may match; checks name a fact, a `file:line` with a tolerance of a few lines, or a verdict, and several are written to fail on the negated claim. Every answer file the grader read is copied into the attempt's raw directory, so `regrade` can grade the attempt again after the checks change without calling a model.

Every row carries `pass`, the headline, and `checks`, the share of atomic checks satisfied, which is continuous and therefore resolves smaller differences between the two efforts.

## How a case runs, and why this way

Each attempt gets its own clone of the case's repository in a new directory under the system temp directory (`tempfile.gettempdir()`, with symlinks resolved), removed afterwards. The clone is made with `git clone --no-local --no-hardlinks --mirror`, so a base commit reachable only from a remote-tracking ref is still found, and a base left on no ref at all by a squash merge is copied in as a pack of exactly its own history; then its remote is removed, every ref is deleted, a single branch `main` is pointed at the base commit and checked out, reflogs are expired and `git gc --prune=now` drops everything else. The subagent therefore cannot reach any commit made after the dispatch, and a brief's mention of `main` resolves to the base commit. Before the model is called, the runner checks the clone the same way the self-test does and fails the attempt as `workspace_leak` if anything later is left. Each attempt also gets a fresh `CLAUDE_CONFIG_DIR` holding `zh/` installed as the README's install steps describe: `CLAUDE.md`, the playbook, hooks, skills and agents. One more agent is added, `effort-sweep-<effort>` for an Opus arm or `effort-sweep-<model>-<effort>` otherwise, whose frontmatter pins the arm's model, `claude-opus-5-5` or `claude-haiku-5-5`, and its effort. The dispatching main thread runs on `claude-opus-5-5` in every arm, so only the subagent differs between arms. `claude -p` then starts a main thread that makes exactly one Agent call to that agent. A `PreToolUse` hook replaces the placeholder prompt of that call with the case's brief, so the subagent receives it byte for byte, and the runner checks that the first message in the subagent's transcript equals the brief. Absolute paths into the original checkout are rewritten to the workspace, and artifact paths to the attempt's output directory.

Two setups were considered, and this one is closer to a real subagent.

| | One dispatch from an isolated main thread (used) | `claude -p --effort X` with the brief as the prompt |
|---|---|---|
| System prompt and tools | the subagent's, including `SubagentHandback` | the main thread's, with the Agent tool available |
| Rule files in context | `CLAUDE.md` only, as ADR 0001 intends | `CLAUDE.md` plus the playbook the SessionStart hook injects |
| Hooks | see `agent_id`, so nested dispatch is denied as ADR 0003 requires | see no `agent_id`, so the brief could fan out |
| Effort mechanism | the agent frontmatter, the lever a downgrade would actually use | the CLI flag, a different path |
| Extra cost | one short main-thread turn, recorded apart as `dispatch_usage` | none |

The frontmatter `effort` overrides the session's effort, and `CLAUDE_CODE_EFFORT_LEVEL` would override the frontmatter, so the runner starts `claude` with a cleared environment and refuses to run when that variable is set in its own. The agent body is a two-sentence instruction shared by both efforts; it is not Claude Code's built-in general-purpose prompt, which is a constant difference between this setup and production and does not differ between the arms.

For every attempt the runner reads the subagent's own transcript and records the sum of `usage` over its API requests, the served model, tool calls, stop reason and latency. It fails the attempt into `errors.jsonl` when the served model is anything but the arm's model, when there is not exactly one subagent transcript, when the brief arrived altered, when the subagent's requests did not carry the effort under test, when an API error such as a usage limit ended the attempt early (`rate_limited` or `api_error`), which Claude Code closes with a synthetic assistant message that a check on the served model alone misses, on the wall-clock ceiling, or on any harness exception; such attempts never occupy a row in `results.jsonl`, so a rerun retries them. Each row of `results.jsonl` holds `prompt_id`, `tags`, `grade`, `usage`, `cost_usd`, `model`, `latency_s`, `tool_calls` and `status`, with the tier as the first tag, a trace per attempt under `traces/`, and the raw transcripts and copies of the answer files under `raw/`. `cost_usd` is the subagent's cost at list prices, with each request priced on its own prompt length and 5-minute and 1-hour cache writes kept apart, because Haiku 5.5 bills a whole request at higher rates once its prompt exceeds 100,000 tokens; the main thread's cost is kept apart as `meta.dispatch_cost_usd`. `meta.changed` lists every file the attempt changed, `meta.band` the case's difficulty band, and for an impl attempt `meta.grading_root` and `meta.soft_reset_from` record a graded worktree and the HEAD a soft reset moved from. Each (model, effort) arm writes to its own directory: the Opus `high` and `medium` arms to `baseline/` and `v1/`, the names their September data was collected under, and every other arm to `<model>-<effort>/`, such as `haiku-medium/`.

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
python3 eval/effort-sweep/run.py run --data "$DATA" --model haiku --effort medium --reps 2
python3 eval/effort-sweep/run.py summarize --data "$DATA" --ref v1 --arms haiku-xhigh,haiku-high,haiku-medium
python3 eval/effort-sweep/run.py reprice --data "$DATA" --arms baseline,v1
python3 eval/effort-sweep/run.py regrade --data "$DATA" --arms v1,haiku-medium --dry-run
```

`--model` takes `opus`, the default, or `haiku`, and `--effort` takes `low`, `medium`, `high`, `xhigh` or `max`. A dry run builds one case per tier that the case set holds. `summarize` prints, per arm and per tier, overall and per difficulty band where the cases carry one, the pass rate with a Wilson interval, the mean of `checks`, the median and range of tokens per attempt, the median output tokens, the median latency, the total and median cost once rows carry `cost_usd`, and for impl the mean landed-test share. Then, for each arm named in `--arms`, it prints the paired difference in `checks` between `--ref` and that arm with a 95% t interval on n − 1 degrees of freedom, the median over cases of the arm's token ratio to the reference, the arm's cost as a share of the reference's, and the paired difference in the landed-test share with its own t interval. For every paired figure each case's reps are averaged first, and tokens include cache reads and writes. Without `--ref` and `--arms` it pairs `baseline/` against `v1/`, the September comparison of high against medium.

`reprice` recomputes `cost_usd` of existing rows from their raw subagent transcripts and rewrites `results.jsonl` in place. `regrade` grades the ok rows of the named arms again against the current `cases.jsonl` without calling a model: a read-only row from the report and the answer files kept in `raw/`, rebuilt from the transcript's Write and Edit calls for rows that predate the copies, and an impl row by applying the case's `hidden.exclude` to the replays it recorded. It keeps the first grade in `meta.grade_original`, and `--dry-run` prints each row's old and new grade and writes nothing. `--cases`, `--concurrency`, `--timeout-s`, `--max-budget-usd` and `--keep` narrow a run, bound it or keep its workspaces. `--inline-brief` is a fallback for a Claude Code version whose hooks cannot rewrite tool input; the main thread then copies the brief itself and the verbatim check catches any drift. The scripts use the Python standard library only.

## Results

The sweep ran the 20 cases twice at each effort on `claude-opus-5-5` between 30 September and 1 October 2026, 80 valid attempts in all: 16 per effort for impl and 12 per effort for each read-only tier. Attempts cut short by the subscription's usage limit were written to `errors.jsonl` as `rate_limited` and run again, so none of them occupies a row. All 80 rows were checked again against their saved raw records with the current runner's API-error check and effort check, and all of them pass: in every row the effort the subagent's requests carried equals the effort of the arm under test. `python3 eval/effort-sweep/run.py summarize --data "$DATA"` prints the table below from the data directory.

| Tier | Pass rate at high [Wilson 95%] | Pass rate at medium [Wilson 95%] | Paired difference in the share of `checks` satisfied, high minus medium, percentage points (95% t interval) | Medium tokens ÷ high: median over cases of the per-case ratio (each case's two reps averaged first), tokens including cache reads and writes | Median seconds per attempt, high / medium |
|---|---|---|---|---:|---:|
| impl | 88% [64%, 97%] | 88% [64%, 97%] | -1.0 (-3.5 to +1.4) | 0.54 | 394 / 269 |
| lookup | 50% [25%, 75%] | 58% [32%, 81%] | -1.2 (-7.5 to +5.1) | 0.49 | 450 / 212 |
| judgement | 50% [25%, 75%] | 42% [19%, 68%] | +2.0 (-14.7 to +18.7) | 0.42 | 407 / 240 |
| all | 65% [50%, 78%] | 65% [50%, 78%] | -0.2 (-4.4 to +4.1) | 0.51 | 424 / 224 |

`summarize` prints the paired difference as a share; the table gives it in percentage points. A negative paired difference means medium satisfied slightly more checks. An attempt passes only when every check holds, and the per-tier pass rates rest on 12 to 16 attempts, so their intervals overlap almost entirely and the paired difference in `checks` carries the comparison. For impl the interval's upper end puts any drop at medium at no more than about 1.4 points of checks, and for lookup at no more than about 5.1, at about half the tokens. For judgement the upper end reaches 18.7 points, so six cases cannot rule out a drop of about 19 points.

Priced at the API list rates for `claude-opus-5-5`, $4 per million input tokens, $5 per million 5-minute cache-write tokens, $0.20 per million cache-read tokens and $20 per million output tokens, multiplied by the summed `usage` the attempts recorded, the subagents' usage comes to $68.3 at high and $41.4 at medium: impl $21.5 against $14.0, lookup $27.0 against $16.7 and judgement $19.8 against $10.7. The runs themselves drew on a subscription's usage allowance. The cost ratio of about 0.6 sits above the token ratio of about 0.5 because a cache read is priced at a hundredth of an output token, and most of the tokens medium saves are cache reads. These dollar figures and the sums below come from summing `usage` over the rows of `baseline/results.jsonl` and `v1/results.jsonl` and, for the dollars, multiplying by the rates above; `summarize` does not print the sums. `reprice`, which prices each request from the saved transcripts, reproduces the $41.4 of the medium arm. Summed over all attempts:

| Effort | Cache reads | Cache writes | Output | Input |
|---|---:|---:|---:|---:|
| high | 110,969,304 | 4,133,727 | 1,269,603 | 2,626 |
| medium | 55,865,893 | 2,841,555 | 801,064 | 1,746 |

Medium halves the cache reads but keeps about two thirds of the cache writes and of the output, and those two carry two thirds or more of the cost at either effort.

ADR 0008 (`docs/adr/0008-subagent-effort-per-kind-of-dispatch.md`) records the decision these results support: implementation with settled decisions and read-only lookup run at `medium`, and judgement-bound review and diagnosis stay at `high`. Judgement moves to `medium` only once a larger sample brings the upper end of its interval on the paired difference in checks, high minus medium, down to the level the other two tiers reached, about 5 percentage points.

## Haiku sweep (October 2026)

Since ADR 0008 took effect on 1 October 2026, `implementer` and `retriever` dispatches have run on Opus 5.5 at effort `medium`. This sweep asks whether Claude Haiku 5.5 (`claude-haiku-5-5`) can take those dispatches over, and at which effort. The briefs, results and the audit's working notes live in a private data directory passed as `--data`; this section gives only the summaries.

### Cases

The cases are real briefs dispatched between 1 and 8 October 2026 to `implementer` or `retriever` and served by `claude-opus-5-5`, chosen under the qualification rules in "Cases" above. A kind here is what the September sweep calls a tier: `impl` cases were dispatched to `implementer` and `lookup` cases to `retriever`. The qualifying pool held 173 implementations and 35 lookups. Each kind is split into three difficulty bands by the tertile, within that kind, of the original subagent's tool calls in its first round, from receiving the brief to its first hand-back, since the replay feeds only the first brief and not later continuations. The cases were picked by hand, not drawn at random: within a band the picked cases come from different repositories, impl keeps its most common problem class, a code change with tests, and the web lookups the most common lookup class, web verification, with one local extraction case added. Two lookups were swapped for others in the same band because their sources could not be fetched reliably.

| Kind | easy | mid | hard | Cases per band |
|---|---|---|---|---:|
| impl | 20 calls or fewer | 21 to 35 | 36 or more | 3 |
| lookup | 9 calls or fewer | 10 to 20 | 21 or more | 2 |

That gives 15 cases, 9 implementations and 6 lookups. Five of the six lookups verify facts on the web, four of them against official pages, and one extracts facts from local design documents.

| Kind | Band | What the brief asks for |
|---|---|---|
| impl | hard | a three-layer change to a benchmark's grading code (contract, referee, scorer), test-first, with a regrade guard over archived results |
| impl | hard | four pure-logic modules built from a contract file, with tests |
| impl | hard | a new label carried through a labelling page and three downstream consumers |
| impl | mid | a version field threaded through five code paths of a benchmark runner, old paths byte-identical |
| impl | mid | one server-side feature plus a template change in a Python labelling service, old batches unchanged |
| impl | mid | a front-end view change with its contract fixed and vitest tests |
| impl | easy | a small new module with a fixed data structure and truncation rules, standard library only |
| impl | easy | a CLI subcommand with tests in a TypeScript project |
| impl | easy | a front-end fix showing a neutral dash when cost is unknown |
| lookup | hard | four questions on a public data provider's APIs, from official API docs |
| lookup | hard | OS adoption figures from third-party telemetry, cross-checked |
| lookup | mid | whether an operating rule holds and whether a downstream prediction relies on it, from official documents |
| lookup | mid | OS version and device coverage of a vendor feature, from the vendor's support pages |
| lookup | easy | three model-pricing facts from a vendor's price page |
| lookup | easy | eight user-side facts extracted from four local design documents, with `file:line` |

### Arms and runs

Each case ran twice in each of four arms: a fresh opus `medium` reference, written to `v1/`, the directory name the September medium arm used, and haiku at `xhigh`, `high` and `medium`. The subagent's model and effort are set in the agent frontmatter while the dispatcher stays on Opus, and the runner checked the served model and the effort each request carried in every attempt. All runs took place on 8 October 2026 with Claude Code 2.1.293, giving 120 valid attempts and no errors.

Haiku at `max` was piloted once each on two mid-band cases, one implementation and one lookup, and dropped. On the implementation it passed but scored 0.80 of checks against 1.00 for every haiku `high` and opus attempt on that case, and cost $0.97 against $0.19 for the same rep at `high`, with 63 requests against 34, of which 54 of the 63 carried a prompt over 100,000 tokens. The lookup failed at `max` as well, graded with the checks as they stood before the audit; the pilot was not regraded. Haiku at `low` was not run, because implementation had cleared at `medium` and lookup had not cleared at any effort from `xhigh` down.

### Competence rule

The rule was fixed before the runs. Per kind and paired by case, the upper end of the 95% t interval on opus `medium` checks minus haiku checks must be at most 5 percentage points, the bar of ADR 0008, and no hard-band case may have opus passing both reps while haiku fails both. Among the efforts that meet both conditions the cheapest at list price is chosen, and it must cost less than opus `medium`.

Prices are taken from platform.claude.com/docs/en/about-claude/pricing, retrieved on 8 October 2026, in dollars per million tokens. Haiku 5.5 bills a whole request at the higher row once its prompt exceeds 100,000 tokens, so `request_costs` prices each request on its own prompt length.

| Model, prompt length | Input | 5-minute cache write | 1-hour cache write | Cache read | Output |
|---|---:|---:|---:|---:|---:|
| Opus 5.5 | 4 | 5 | 8 | 0.20 | 20 |
| Haiku 5.5, prompt up to 100,000 tokens | 0.10 | 0.125 | 0.20 | 0.01 | 0.50 |
| Haiku 5.5, prompt over 100,000 tokens | 0.50 | 0.625 | 1.00 | 0.05 | 2.50 |

### Grading audit

Before the arms were unblinded, a blind audit reviewed three kinds of item under one rule applied to every arm alike: a lookup check that half or more of all attempts, pooled across arms, missed; an impl landed-test command that failed in half or more of them; and every impl attempt failed on scope or on an unmatched self-check placeholder, meaning the brief asked the subagent to run tests it wrote and the attempt added no file matching that command (`expand_command` in `grade.py`). That came to 15 items: eight lookup checks, four landed-test commands and three impl attempts. The reports were anonymised and shuffled, and the items were split among three `researcher` subagents running on Opus, one auditor per item, who judged it from the brief, the conclusion the main thread adopted, the code and the current official pages, without seeing which arm an attempt came from. The main thread made the final call on every item before it opened the unblinding key; the one verdict changed afterwards is the nested-worktree attempt below.

Of the eight lookup checks, four were deleted because the brief never asked for the fact and only the adopted report had volunteered it: a platform share from a source the brief did not name, a second rule the brief did not ask about, the context size of a private-cloud offering and a long-context surcharge. Two were widened as too literal. One missed a synonym, and widening it raised its hits from 4 of 8 to 7 of 8. The other pinned an official source to one document version although the brief asked for any official agency document; the auditor judged that miss genuine, and the main thread overrode it and widened the check, since the adopted report itself cites the second document. Two checks were kept as genuine misses: the coverage of one endpoint, and an official archive that is still online although most reports said it did not exist. None of the official pages had changed since the dates the checks were anchored to, which was rechecked on 8 October 2026. For the long-context surcharge the auditor had offered widening as an option, and the main thread deleted the check so that "not asked, not graded" applies to every check alike.

The blind auditor judged all three impl attempts failed on scope or on a placeholder to be real violations of their briefs. Two were haiku attempts that edited a file outside the listed scope. The third, an Opus attempt, turned out on unblinding to be a blind spot of the grader: following its brief, which told it to create a worktree and a branch, it did all its work in a nested worktree and committed it. The grader now grades a nested worktree when the main checkout is untouched and soft-resets commits onto the base, for every arm, and no other attempt worked in one; that attempt was run again and passed. The change raises opus's score, so it can only make it harder for haiku to clear the bar. The workspace of every attempt is deleted after grading and the worktree's changes had never been graded, so there was nothing to regrade offline; the rerun's row replaced the original in `v1/`, and the $20.47 opus impl total excludes the replaced attempt's $0.55. Across four cases, 18 landed tests asserted details no brief fixed, such as the order of returned cards, the spelling of a colour, or behaviour the main thread added later, and the cases now exclude them through `hidden.exclude`. One landed-test replay of a haiku `xhigh` attempt stopped at collection and counts as indeterminate.

`regrade` applied the audited checks offline from the saved transcripts; with the checks unchanged it reproduced every grade exactly. Before the audit the lookup pass rates were 2/12 for opus, 0/12 for haiku `xhigh`, 1/12 for haiku `high` and 0/12 for haiku `medium`, and after it they are 7/12, 6/12, 5/12 and 4/12. The impl paired differences moved by at most 1.9 percentage points, and the offline regrade changed no impl pass; the one impl attempt that went from fail to pass is the nested-worktree attempt above, which was run again rather than regraded.

### Results

`python3 eval/effort-sweep/run.py summarize --data "$DATA" --ref v1 --arms haiku-xhigh,haiku-high,haiku-medium` prints these figures after the audit as shares; the table gives them in percentage points, and the verdict column applies the competence rule. Differences are opus minus haiku, so a negative value means haiku satisfied more. The cost column gives the arm's list-price total over all its attempts in brackets. Anyone can run the scripts on briefs of their own, but this table can be recomputed only from the private data directory.

| Kind | Arm | Pass | Paired checks difference, opus − haiku, pp (95% CI) | Landed-test share difference, pp (95% CI) | Haiku cost ÷ opus (arm total) | Verdict |
|---|---|---|---|---|---|---|
| impl | opus medium | 18/18 | | | ($20.47) | reference |
| impl | haiku medium | 18/18 | −2.8 (−9.2 to +3.6) | −0.2 (−0.6 to +0.3) | 0.16 ($3.28) | competent |
| impl | haiku high | 17/18 | +0.3 (−4.2 to +4.8) | +0.1 (−0.4 to +0.5) | 0.28 ($5.72) | competent |
| impl | haiku xhigh | 17/18 | −1.1 (−8.4 to +6.3) | −0.1 (−0.7 to +0.5) | 0.43 ($8.88) | interval too wide |
| lookup | opus medium | 7/12 | | | ($4.07) | reference |
| lookup | haiku xhigh | 6/12 | +1.4 (−13.7 to +16.4) | | 0.24 ($0.98) | not cleared |
| lookup | haiku high | 5/12 | +3.9 (−5.0 to +12.8) | | 0.16 ($0.66) | not cleared |
| lookup | haiku medium | 4/12 | +8.2 (−4.2 to +20.6) | | 0.10 ($0.40) | not cleared |

No hard-band case had opus at 2/2 and haiku at 0/2 at any effort. For implementation, haiku `medium` and `high` both meet the rule and `medium` is the cheaper, which on nine cases rules out a loss of more than 5 points of checks; for lookup no effort shows that haiku stays within 5 points of opus.

The medians per lookup attempt show that at `high` and `xhigh` haiku did not lose points by searching less, while at `medium` it searched less than opus:

| Arm | Tool calls | Web calls | Seconds |
|---|---:|---:|---:|
| opus medium | 13 | 9.5 | 107 |
| haiku xhigh | 25 | 16 | 292 |
| haiku high | 16 | 14.5 | 119 |
| haiku medium | 10.5 | 8.5 | 63 |

Haiku at `high` searched more than opus and still passed fewer attempts, and at `xhigh` it took a median of about 2.7 times as long. Its misses lie in judging sources and claims, such as an archive that is still online declared missing, a required official source absent or a wrong lower bound of support. Our reading, which the sweep did not test, is that nothing in a lookup pushes back on such a miss, whereas implementation briefs carry self-verification commands that do. The grading baseline also leans towards opus, since the lookup checks come from adopted reports mostly written by opus and the landed tests from changes opus made, so the lookup verdict should be read with that lean in mind.

Haiku uses more tokens than opus on the same brief, an impl median ratio of 1.8 at `medium` and 2.8 at `high`, but its list cost is far lower. At `high` the most expensive haiku case was an impl case whose haiku requests mostly exceeded 100,000 prompt tokens, at $1.7 to $2.0 per attempt at `high`.

At list prices the sweep's subagents cost about $46: $24.5 for the opus reference and $19.9 for the haiku arms, of which $9.86 at `xhigh`, $6.38 at `high` and $3.68 at `medium`, plus $1.26 for the haiku `max` pilot. The dispatching main thread added about $0.14 per attempt, and the audits and drafting by Opus subagents are not included. The runs themselves drew on a subscription allowance.

ADR 0021 (`docs/adr/0021-implementer-runs-on-haiku-when-tests-decide-every-change.md`) records the decision these results support: `implementer` runs on haiku at `medium` when existing tests or acceptance cases listed in the brief decide every changed behaviour, and on opus otherwise; `retriever` stays on opus at `medium`, and `researcher` is unchanged.

## Files

| File | Role |
|---|---|
| run.py | builds the workspace and config dir, dispatches the brief to the arm's model and effort, reads the subagent transcript, prices each request, grades, writes rows, traces and errors, summarizes, and reprices and regrades existing rows |
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
| test_arms.py | unit tests for the arms, subagent model by effort, and the summaries that pair an arm against a reference |
| test_cost.py | unit tests for the per-request cost, `reprice` and cost in the summaries |
| test_regrade.py | unit tests for keeping answer files in `raw/` and for `regrade` |
| test_hidden.py | unit tests for the landed-test share of impl rows and for `regrade` reading `meta.changed` |
| test_audit_rules.py | unit tests for the excluded landed tests and for grading the worktree an attempt built |

The data directory holds `cases.jsonl`, `inputs.html`, and after a run `_state.json` and one directory per arm: `baseline/` and `v1/` for the Opus `high` and `medium` arms and `<model>-<effort>/` for every other arm.

## Limits

A clone holds one branch, so a brief that names another branch, such as the unmerged branch that the five rechecks of numbered defects in one repository compare against, or `origin/main`, finds nothing under that name, whereas the original subagent could read it. The runner still records in `meta.leak_signals` any tool call that touches the original checkout, lists history across all refs or names the landed commit, as a second line of defence.

The read-only checks were written from reports that a model produced, most of them `claude-opus-5-5`, and kept only where the main thread later acted on the conclusion. They test the conclusion and its evidence, not the wording, but a report that reaches the same conclusion through different evidence can still miss a `file:line` check. Graded self-verification drops the parts that need the network or a running service, and one case runs `docker compose config` with placeholder secrets because the workspace has no `.env`.

The transcripts Claude Code writes do not show which effort a request ran at, so the runner has Claude Code write every request body of an attempt to a temporary directory (`OTEL_LOG_RAW_API_BODIES=file:<dir>`) and reads `output_config.effort` back from them. A request whose first user message holds the brief is the subagent's, every other one the dispatching main thread's; both sets go into `meta.effort_in_requests`, and an attempt whose subagent requests carried anything but the effort under test fails as `effort_mismatch`. The bodies themselves are removed with the attempt's temp directory. The historical token figures in `inputs.html` are the original runs' usage, not a pilot of this setup. With 20 cases a pass rate carries a noise floor of about `1/sqrt(20 × reps)`, roughly ±16 points at two reps, so a per-tier difference is visible only when it is large; `checks` and the paired design narrow this, and more reps narrow it further.
