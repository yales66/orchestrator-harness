# ADR 0005：会拒绝、拦截或注入规则的钩子都带回归测试

## 状态

已采纳，自 2026 年 7 月 16 日起生效。

## 背景

拒绝工具调用或拦截停止的钩子在每个匹配事件上都会运行，而它的错误两个方向都是静默的：漏拒会放过它本该阻止的行为，误拒会挡住正当的工作。`block-no-verify-commit.sh` 的早先版本用正则匹配整条命令，两头都错了。那条正则要求 `git` 与子命令之间至少夹一个字符，而最常见的绕过写法两个词正好相邻，所以从未被拦下；同时含 `git` 与 `commit` 字样、又带独立 `-n` 的命令，例如 `git log` 后接 shell 条件测试 `[ -n "$C" ]`，在实际使用中被拒过，测试把这些命令留作标注 2026 年 7 月 15 日的回归用例。

从没失败过的测试，证明不了它能抓住一个坏掉的钩子。

## 决策

凡是能拒绝工具调用、拦截停止或向上下文注入规则的钩子，都随附 `hooks/tests/<钩子名>.test.sh`。测试把 Claude Code 会发送的 JSON 喂给钩子并断言其判定，覆盖必须拒绝或拦截的调用、必须放行的调用，以及异常输入；对异常输入这类钩子一律放行，使坏掉的输入永远不会卡死会话。每个测试打印 `PASS=<n> FAIL=<n>`，有任何失败即以非零状态退出。

测试要先亲眼看到它对一个坏掉的钩子失败才算数：坏掉的钩子可以是修复前的版本，也可以是故意注入、看到测试变红后再还原的缺陷。

## 后果

本规则覆盖的每个钩子在每个语言副本里都带有测试，`zh/README.md`「钩子」一节的表格列出每个钩子对应的测试。各测试的用例数见该测试输出的 `PASS=<n>`。

`rule-file-edit-check.sh` 只追加提醒，从不拒绝或拦截；`worktree-symlink-claudemd.sh` 在新工作树里建符号链接。两者都不在本规则现有的适用范围内，但同样带有表征测试，即钉住现有行为的测试。工作树钩子会用 `rm -f` 删掉工作树里受版本控制的 `CLAUDE.md` 再换成链接，所以它的测试钉住三件事：只在这个文件与 `HEAD` 一致且链接目标存在时才替换它；即使工作树路径经过符号链接目录，新链接也解析到主工作树的 `CLAUDE.md`；异常输入什么都不改。其中符号链接路径与未提交改动两类用例，是测试暴露出缺陷后补的回归用例。

持续集成在每次推送与拉取请求时对两个副本运行全部钩子测试。

## 出处

| 出处 | 支撑的内容 |
|---|---|
| `zh/hooks/block-no-verify-commit.sh` 文件头注释 | 为什么用分词解析：整条命令匹配漏掉相邻写法的绕过，又误拒含 `[ -n "$C" ]` 的命令 |
| `zh/hooks/tests/block-no-verify-commit.test.sh` 中标注 2026-07-15 的回归一节 | 实际使用中被误拒的命令，留作标注 2026 年 7 月 15 日的回归用例 |
| `zh/CLAUDE.md`「测试」一节 | 写不出「改错时会变红」的测试就不写 |
| `zh/hooks/block-nested-subagent.sh` 与 `zh/hooks/context-watermark-gate.sh` 对异常输入的处理 | 输入异常放行，钩子不卡死会话 |
| `zh/hooks/worktree-symlink-claudemd.sh` 中的 `link_target` | 工作树钩子先删掉受版本控制的 `CLAUDE.md` 再建链接 |
| `zh/hooks/tests/rule-file-edit-check.test.sh` | 规则文件提醒的表征用例 |
| `zh/hooks/tests/worktree-symlink-claudemd.test.sh` | 工作树钩子的用例 |
| `zh/hooks/tests/reply-gate.test.sh` | 回复出口检查的用例 |
| `zh/hooks/tests/secret-guard.test.sh` | 密钥防护的用例 |
| `zh/hooks/tests/subagent-readonly-guard.test.sh` | 只读子智能体防护的用例 |
| `.github/workflows/ci.yml` 的 `on` 触发条件与 `Hook tests (en and zh)` 步骤 | 持续集成在每次推送与拉取请求时运行两个副本的全部钩子测试 |
