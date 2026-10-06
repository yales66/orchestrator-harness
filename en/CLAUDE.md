# General rules

This file records only the deltas from Claude Code's default behaviour.

## Producing prose

Applies to prose written for humans to read (documents/reports/explanations/artifacts); does not apply to conversation replies or rule files. Details are in the prose-discipline skill.

- No unordered lists and no dashes: genuinely parallel items go in a table, and everything else is written as sentences with connectives; ordered lists are allowed when the numbering carries order.
- In Chinese prose, translate a term into Chinese at its first occurrence and use that translation throughout, without an English abbreviation in parentheses; in English prose, keep the original term.
- When revising prose, keep only statements that are true now; do not write sentences such as "originally X, now Y" that exist only to prove something was changed.

## Changing existing code

- Before touching anything, run git log/blame on the relevant lines (micro-why); if the repo has docs/adr/, ls that directory and read in full every file whose name matches the task at hand (macro-why). If you retrieve a reason and it agrees with this change, make the change along it and cite the source in your report; if the retrieved reason shows the current state is intentional and this change conflicts with it, ask first and cite the source in the question; if you cannot retrieve a reason and the change would alter that spot's behaviour, or the change touches a business threshold whose source cannot be found in the repository, leave that spot untouched, do the rest, and list separately in your report its location and the question the user needs to answer. A spot the user names for change in this turn is changed directly.
- When corrected, change the instance that was named. When the correction is about an objective defect (a bug, a typo, a factual error), also fix the same-cause instances of the same kind in the files this task has already changed, and list each one in your report; when the correction is about style or wording, list the locations of similar instances and leave them unchanged. When the correction itself states a general rule ("from now on always", "all"), follow it within this task's scope and write it into a feedback memory, stating its scope and exceptions.

## Testing

- New code with logic is test-first (tdd-watch-it-fail); if you cannot write a test that "turns red when the code is wrong", do not write the test.
- Before removing or refactoring behaviour that no test covers, first add characterisation tests that pin the current state (watch them go green), and they must still be green after the change.
- The second time the same setup appears, extract it into a helper/fixture; when the same assertion is repeated with different inputs, use `parametrize` (with `ids=`).
- During development, run only the test files related to the change, not the full suite.
