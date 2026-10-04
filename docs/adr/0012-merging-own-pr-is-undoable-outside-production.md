# ADR 0012: Merging a PR the task opened is undoable outside production repositories, and a hook asks first in production

## Status

Accepted. In effect since 4 October 2026. Supersedes, in the row of [ADR 0006](0006-ask-the-user-only-where-the-answer-is-theirs.md) on a next step at wrap-up, the classing of merging as external; the rest of ADR 0006 stands.

## Context

ADR 0006 lists merging among the external steps that wait for the user, next to deploying, sending messages and publishing. For most repositories a merge is not external in that sense. A pull request that the task itself opened, with no reviewer assigned, has no one else waiting on it, and once CI passes, merging it into a branch that nothing deploys from can be undone with a revert. Holding it for the user turns the last step of finished work into a round of waiting, the cost ADR 0006 set out to remove.

Some repositories are different. Where a merge to the main branch deploys, publishes or reaches other people, it is external, and the user has to agree to it at the moment it happens. Which repositories those are is a fact about each repository, not about the task, and it holds for every session and every worktree of that repository.

## Decision

Section 1 of the playbook counts as undoable the merge of a pull request that this task opened, with no reviewer assigned, once CI passes, or, where the repository has no CI, once the delivery gate of section 4 passes. A pull request left as a draft because its content is in doubt is not merged. Merging leaves the playbook's list of external steps.

A repository is marked as production with `git config claude.production true` and unmarked with `git config --unset claude.production`. `hooks/production-merge-gate.sh` runs on PreToolUse for `Bash`. When a command runs `gh pr merge` and the repository of the hook input's working directory is marked, it returns `ask`, so Claude Code asks the user to approve the merge on the spot. When `-R` or `--repo` names a repository that is not among the working directory's remotes, the hook cannot read that repository's mark and treats it as production.

The mark lives in git config rather than in a file in the repository, for two reasons. Git config enters no session's context, so the rule costs nothing in a session that never merges. It is also shared by every worktree of the repository, whereas a file would have to be present on each branch.

A session does not otherwise know what "production mode" refers to. `hooks/production-mode-hint.sh` runs on UserPromptSubmit and, when the user's own message mentions 生产模式 or production mode, adds one line saying how to set and unset the mark and that merges in a production repository ask first. Subagent reports and background notifications also arrive through UserPromptSubmit, so the hook skips messages that open as one of those.

## Consequences

Outside production repositories the main thread merges its own pull request once CI passes and reports it, and the user can revert the merge. In a repository marked as production the merge waits for the user's approval, whatever the session's rules say, because the hook decides it outside the model. A repository that should be marked and is not gets merged without asking, so marking is part of setting up a repository whose main branch deploys or publishes.

The hook recognises `gh pr merge` only. A merge made another way, such as `git merge` followed by a push to the main branch, or a merge through the GitHub API, does not pass through the hook and is not asked about. Both hooks carry regression tests under ADR 0005.

## Sources

| Source | What it supports |
|---|---|
| `en/orchestrator-playbook.md`, §1, the paragraph on next steps at wrap-up | Merging the task's own pull request counts as undoable, with its conditions; merging is no longer external |
| `en/hooks/production-merge-gate.sh`, header comment | The mark in git config, why it lives there, the working directory as the repository, and `-R` naming another repository counting as production |
| `en/hooks/production-merge-gate.sh`, the `ask` decision | The merge asks the user to approve it on the spot |
| `en/hooks/tests/production-merge-gate.test.sh` | The gate's cases; their number is the `PASS=<n>` the test prints |
| `en/hooks/production-mode-hint.sh`, header comment and the prefix check | The hint is injected only for the user's own messages that mention production mode |
| `en/hooks/tests/production-mode-hint.test.sh` | The hint's cases |
| `en/settings.example.json`, the `UserPromptSubmit` and `PreToolUse` `Bash` entries | Where the two hooks are registered |
| `docs/adr/0006-ask-the-user-only-where-the-answer-is-theirs.md`, the row on a next step at wrap-up | The classing this ADR supersedes |
