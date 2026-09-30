# Hook mutation test

This directory measures how many deliberately injected defects the hook regression tests in `en/hooks/tests` catch. ADR 0005 says a hook test counts once it has been seen to fail against a broken hook; this measurement applies that criterion to a fixed set of defects per hook, so the answer is reproducible and can be rerun after the hooks or their tests change.

Each defect, called a mutant, is one textual edit to one hook, and each edit breaks one rule that the hook's header comment states: a condition is negated, an alternative is dropped from a pattern or a command list, a deny becomes an allow, a threshold moves, or a sanity check such as `stop_hook_active` is removed. The hook's own test file then runs against the mutated copy. A mutant is killed when that test exits non-zero and survives when it exits 0.

## Running

From a clean checkout, with `bash`, `python3`, `jq` and `git` on the PATH (the hooks and their tests need all four):

```bash
bash eval/hook-mutations/run.sh
```

The script prints a one-line summary and rewrites `results.md`. It uses only bash and the Python standard library, runs under the macOS system bash 3.2 and on Ubuntu, and takes three to six minutes on a laptop with the default of four parallel runs. Two runs on the same hooks and tests produce identical `results.md` files, because the report holds no timings, dates or temp paths.

| Variable | Default | Effect |
|---|---|---|
| `HM_JOBS` | 4 | number of test runs in parallel |
| `HM_TIMEOUT` | 120 | floor, in seconds, of a mutant's timeout |
| `HM_BASELINE_TIMEOUT` | 600 | timeout, in seconds, of each unmutated test run |
| `HM_MANIFEST` | `mutations.tsv` here | the mutant list to run |
| `HM_OUT` | `results.md` here | where the report is written |
| `HM_KEEP` | unset | when set, keeps the temp directory with every mutated copy and its `test.log`, and prints its path |

## Method

For every run, mutated or not, the script copies `en/hooks` together with its `tests` directory and `en/orchestrator-playbook.md` into a fresh temp directory with the same layout, because the tests locate their hook as `../<hook>.sh` relative to themselves and the SessionStart test reads the playbook one level above `hooks/`. Only the copy is edited; nothing under `en/` or `zh/` is written. The hooks under `zh/` are byte-identical to `en/` (CI checks the parity), so mutating `en/` covers both.

The script first runs every hook's test file once against an unmutated copy. A hook whose unmutated test fails or times out is marked baseline red and its mutants are skipped, since a test that is already red would count every mutant as killed. The wall-clock time of that run also sets the mutant timeout for the hook: the larger of `HM_TIMEOUT` and five times the unmutated run. A timeout counts as a kill, because a hang is a failure the user would notice, and the process group of the test is killed so that nothing is left running.

Before a mutant runs, the script checks that its anchor occurs exactly once in the current hook. An anchor that occurs zero times or more than once means the hook has changed since the row was written, and the row is reported stale instead of being applied somewhere unintended. The script then checks that the mutated hook still parses, with `bash -n` and by compiling each embedded `python3 -c` body. Every hook allows on any internal error and discards its stderr, so a mutant that no longer parses would behave as "always allow" and be killed without saying anything about the tests; such a row is reported invalid and not run.

The test processes run with the hook settings `REPLY_LANG`, `CONTEXT_WINDOW_TOKENS`, `CONTEXT_WARN_PCT`, `CONTEXT_HARD_PCT` and `CONTEXT_REBLOCK_DELTA_PCT` removed from their environment, so a value exported in the developer's shell cannot change what the tests observe.

## The manifest

`mutations.tsv` holds one mutant per line in five tab-separated columns. Lines starting with `#` and the header line are skipped.

| Column | Content |
|---|---|
| id | short unique name; the prefix names the hook, for example `SG` for `secret-guard.sh` |
| hook | file name under `en/hooks` |
| anchor | exact text to replace, on one line; it must occur exactly once in the hook |
| replacement | literal replacement text, which may be empty |
| rule | the rule from the hook's header comment that the edit breaks |

Every row was written against a rule the header comment states, and rows whose edit cannot change behaviour, such as changing the Python exit code where the shell wrapper always ends in `exit 0`, were left out. No row is currently suspected of being equivalent to the original hook. When a hook changes, a stale row is repaired by updating its anchor to the new text of the same rule, or removed when the rule itself is gone.

The regression tests were strengthened against the survivors of `mutations.tsv`, so the score on that set overstates how well they pin rules they were not tuned to. `holdout.tsv` is a second set of 35 mutants, ids prefixed `H-`, written from the header comments without reading the tests or the first set; its score is the less biased estimate. Tuning the tests to its survivors would spend it, and a fresh held-out set would then be needed. It runs with `HM_MANIFEST=eval/hook-mutations/holdout.tsv HM_OUT=eval/hook-mutations/holdout-results.md bash eval/hook-mutations/run.sh`, and the report names the manifest it was generated from.

## Reading results.md

The summary counts the mutants in each state and gives the mutation score, which is killed divided by evaluated, where evaluated means killed plus survived.

| Result | Meaning |
|---|---|
| killed | the hook's test exited non-zero, or timed out, against the mutated copy |
| survived | the test passed although the hook breaks the rule named in the row |
| stale | the anchor occurs zero times or more than once in the current hook, or the hook file is gone |
| invalid | the mutated hook no longer parses, so the row says nothing about the tests |
| skipped | the hook's unmutated test is red, so its mutants were not run |

The per-hook table shows each hook's baseline, its killed and evaluated counts and a fingerprint, which is the first 12 hex digits of the SHA-256 of the hook followed by its test file. When two reports disagree, a changed fingerprint shows which hook or test changed between them. A survivor is a rule that the tests do not pin: either a missing test case, which the test owner decides whether to add, or an equivalent mutant, which is fixed by removing the row.

## Limits

The mutants are chosen by hand from each header comment, with two to eight per hook, so the score measures the tests against these sets and says nothing about rules the sets do not cover or about defects of other shapes. A killed mutant means at least one case in the test file failed; the script does not check that the failing case is the one that targets the broken rule, which `HM_KEEP=1` and the kept `test.log` allow a reader to confirm by hand. The parse check catches syntax errors only, so a mutant that fails at run time, for example with an undefined name, still looks like "always allow" and would be counted as killed. Anchors are exact text, so ordinary edits to a hook turn rows stale until someone updates them. The measurement is not part of CI.

## Files

| File | Role |
|---|---|
| run.sh | driver: baseline runs, anchor and parse checks, mutant runs in isolated copies, report rendering |
| mutations.tsv | the mutant manifest |
| results.md | the report from the latest run, generated by run.sh |
| holdout.tsv | the held-out mutant manifest, written without reading the tests or `mutations.tsv` |
| holdout-results.md | the report from the latest run of `holdout.tsv`, generated by run.sh |
