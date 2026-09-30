# ADR 0003：子智能体不能再派子智能体

## 状态

已采纳，自 2026 年 9 月 13 日起生效。

## 背景

主线程是编排者：派什么、派给哪个模型、带什么派发说明（见 ADR 0002）都由它决定，结论也留在它手里。子智能体若自己再派子智能体，或者跑工作流脚本，就多出一层编排者既没规划、也看不见的扇出，即一次分出多路并行的派发。

Claude Code 只在钩子从子智能体内部触发时，才在钩子输入里带上 `agent_id`。主线程永远不带它，用 `--agent` 启动的会话也一样：那种会话的主线程带 `agent_type`，但没有 `agent_id`。

## 决策

`hooks/block-nested-subagent.sh` 挂在 `Agent`、`Task`、`Workflow` 的 `PreToolUse` 上，只要 `agent_id` 存在且非空就拒绝调用。拒绝理由告诉子智能体把这一步自己做完；确实需要拆分时，把结论和拆分建议写进返回值，由编排者决定怎么派。

判据取 `agent_id` 而不取 `agent_type`，因为 `--agent` 会话的主线程同样带 `agent_type`，按它判会把那种会话的主线程一并拦住。`Workflow` 与 `Agent` 同样拦截，因为在子智能体里跑起来的工作流同样是一层不受控的扇出。输入异常一律放行，因为钩子不该卡死会话。

## 后果

派发只有一层深。子智能体发现任务太大时向上汇报，而不是自己拆分，会话里的每一次派发都经过主线程的路由规则与派发说明规则。

主线程仍能派子智能体、跑工作流，`--agent` 会话的主线程也一样。回归测试覆盖两侧：子智能体内部对 `Agent`、`Task`、`Workflow` 的必须拒绝的调用，以及主线程、`--agent` 会话主线程、`agent_id` 为空串或 null、输入异常这些必须放行的情形。

## 出处

| 出处 | 支撑的内容 |
|---|---|
| `zh/hooks/block-nested-subagent.sh` 文件头注释 | 钩子的作用范围、`agent_id` 判据、按 `agent_type` 判会误伤 `--agent` 会话主线程的原因，以及 `Workflow` 作为不受控扇出一并拦截 |
| `zh/hooks/block-nested-subagent.sh` 中输入解析失败时的放行分支 | 输入异常放行 |
| `zh/hooks/block-nested-subagent.sh` 中的 `permissionDecisionReason` | 拒绝理由把拆分交回编排者 |
| `zh/hooks/tests/block-nested-subagent.test.sh` | 拒绝与放行用例，用例数见该测试输出的 `PASS=<n>` |
