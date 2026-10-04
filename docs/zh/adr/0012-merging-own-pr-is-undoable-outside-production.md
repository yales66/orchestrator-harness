# ADR 0012：非生产仓库里合并本任务开的拉取请求属于可撤回，生产仓库由钩子先问用户

## 状态

已采纳，自 2026 年 10 月 4 日起生效。取代 [ADR 0006](0006-ask-the-user-only-where-the-answer-is-theirs.md)「收尾时的下一步」一行里把合并归为对外动作的规定；ADR 0006 其余内容不变。

## 背景

ADR 0006 把合并与部署、发消息、公开发布一起列为要等用户的对外动作。对大多数仓库来说，合并并不是这个意义上的对外。本任务自己开的、没有指派审阅人的拉取请求，没有别人在等它；持续集成通过之后，把它合进一个不触发部署的分支，用一次还原提交就能撤回。把它留给用户，就让已经做完的工作的最后一步变成一轮等待，这正是 ADR 0006 要消除的代价。

有些仓库不一样。合进主分支就会部署、发布或送到别人手里的仓库，合并就是对外动作，必须由用户在合并的那一刻同意。哪些仓库属于这一类，是每个仓库自身的事实，与任务无关，而且对这个仓库的每个会话、每个工作树都成立。

## 决策

编排手册 §1 把合并本任务开的、未指派审阅人的拉取请求算作能撤回，条件是持续集成通过，仓库没有持续集成时以 §4 的交付闸门通过为准。因为内容存疑而留成草稿的拉取请求不合并。合并从编排手册的对外动作列表里移出。

仓库用 `git config claude.production true` 标成生产仓库，用 `git config --unset claude.production` 取消。`hooks/production-merge-gate.sh` 在 PreToolUse 上匹配 `Bash`。命令里有 `gh pr merge`、且钩子输入的工作目录所在仓库带这个标记时，它返回 `ask`，由 Claude Code 请用户当场同意这次合并。`-R` 或 `--repo` 指向的仓库不在工作目录所在仓库的远端之列时，钩子读不到那个仓库的标记，按生产仓库处理。

标记放在 git config 而不是仓库里的文件，理由有两条。git config 不进任何会话的上下文，所以从不合并的会话不为这条规则付任何代价。它还由同一仓库的所有工作树共用，而一个文件得在每个分支上都存在才行。

会话平时不知道「生产模式」指的是什么。`hooks/production-mode-hint.sh` 在 UserPromptSubmit 上运行，用户本人的消息提到「生产模式」或 production mode 时，注入一句说明：怎样设置与取消这个标记，以及生产仓库的合并会先问用户。子智能体的回报与后台通知也经 UserPromptSubmit 进来，所以以这几类开头的消息被跳过。

## 后果

在非生产仓库里，主线程在持续集成通过后合并自己开的拉取请求并汇报，用户可以把合并还原。在标成生产的仓库里，不论会话里的规则怎么写，合并都要等用户同意，因为这一判定由钩子在模型之外做出。该标而没标的仓库会被直接合并，所以主分支会部署或发布的仓库，设置时就要打上这个标记。

钩子只认 `gh pr merge`。用别的方式完成的合并，例如 `git merge` 之后推送到主分支，或经 GitHub 接口合并，不经过这个钩子，也不会被问到。两个钩子都按 ADR 0005 带回归测试。

## 出处

| 出处 | 支撑的内容 |
|---|---|
| `zh/orchestrator-playbook.md` §1 关于收尾时下一步的一段 | 合并本任务开的拉取请求算作能撤回及其条件；合并不再属于对外动作 |
| `zh/hooks/production-merge-gate.sh` 文件头注释 | 标记放在 git config 及其理由，以工作目录所在仓库为准，`-R` 指向别的仓库时按生产处理 |
| `zh/hooks/production-merge-gate.sh` 中的 `ask` 判定 | 合并要用户当场同意 |
| `zh/hooks/tests/production-merge-gate.test.sh` | 合并闸门的用例；用例数是测试打印的 `PASS=<n>` |
| `zh/hooks/production-mode-hint.sh` 文件头注释与开头检查 | 只对用户本人提到生产模式的消息注入说明 |
| `zh/hooks/tests/production-mode-hint.test.sh` | 生产模式提示的用例 |
| `zh/settings.example.json` 中 `UserPromptSubmit` 与 PreToolUse `Bash` 的条目 | 两个钩子注册在哪里 |
| `docs/zh/adr/0006-ask-the-user-only-where-the-answer-is-theirs.md`「收尾时的下一步」一行 | 本 ADR 取代的归类 |
