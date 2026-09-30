# ADR 0004：上下文水位从会话记录的用量读取，并以交接文件为停止闸门

## 状态

已采纳，自 2026 年 9 月 19 日起生效。

## 背景

长会话的质量随上下文填满而下降，长上下文研究的结论与此同向：RULER 测得多数模型的有效上下文长度远短于标称长度，BABILong 测得上下文只有 10% 至 20% 被有效利用。编排手册应对上下文填满的办法是一份交接文件，按编排手册 §3 的交接格式写成，新会话从它接着做。

Claude Code 传给 `Stop` 钩子的输入不带任何词元字段。会话记录里有：末条助手消息的用量块记着 `input_tokens`、`cache_read_input_tokens`、`cache_creation_input_tokens`，三者之和就是这一轮真实送进模型的量。

`stop_hook_active` 只在因 `Stop` 钩子拦截而续跑的那一轮为真，用户下一条消息就重置。只靠它的闸门，会在超过阈值后的每一轮结束时都再拦一次。

## 决策

`hooks/context-watermark-gate.sh` 挂在 `Stop` 上，从会话记录读出末条用量块，把三者之和与窗口大小相比。

| 用量 | 行为 |
|---|---|
| 低于 35% | 放行 |
| 35% 起、低于 40% | 放行，并提醒在下一个自然断点写交接文件，写完继续当前任务 |
| 40% 及以上 | 拦截停止一次，要求按编排手册 §3 的交接格式写交接文件，放在本任务的工作目录，写完提示用户换新会话 |

拦截后，闸门把当时的水位写进会话暂存目录，此后水位再涨 5 个百分点才会再拦，所以写完交接文件的会话可以接着干活。拿不到会话暂存目录时，它在硬线以上每轮都拦，因为静默放行会让这道保护失守。以下三种情形一律放行：`stop_hook_active` 为真；钩子在子智能体内部触发；任何异常输入。子智能体豁免，是因为它有自己的生命周期，水位归主线程管。`CONTEXT_WINDOW_TOKENS`、`CONTEXT_WARN_PCT`、`CONTEXT_HARD_PCT`、`CONTEXT_REBLOCK_DELTA_PCT` 可覆盖一百万词元的窗口与三个阈值。

提示文案只写要做的动作，不写百分比，交接格式指向编排手册第 3 节，使格式只在一处定义。

## 后果

闸门拦截停止并要求写交接文件，但不检查交接文件是否真的写成。阈值按默认的一百万词元窗口设定，窗口更小的会话要设 `CONTEXT_WINDOW_TOKENS` 才能得到有意义的百分比。

用量数字依赖会话记录的格式。用量块的字段一旦改名，闸门就读不到用量而放行每一次停止，于是它会静默失效，但不会卡住工作。回归测试钉住三档水位、防循环、子智能体作用域、阈值覆盖、重复拦截抑制与异常输入。

## 出处

| 出处 | 支撑的内容 |
|---|---|
| `zh/hooks/context-watermark-gate.sh` 文件头注释 | `Stop` 输入不带词元字段；用量是会话记录末条助手消息里三个字段之和；两道线；只靠 `stop_hook_active` 为何会在硬线以上每轮都拦；再拦规则、子智能体作用域与异常放行 |
| `zh/hooks/context-watermark-gate.sh` 中 `WINDOW`、`WARN`、`HARD`、`REDELTA` 的默认值 | 默认窗口与阈值及其环境变量覆盖 |
| `zh/hooks/context-watermark-gate.sh` 中读完会话记录后对 `used` 的检查 | 读不到用量即放行 |
| `zh/hooks/context-watermark-gate.sh` 中硬线以下的 `additionalContext` 提示 | 两道线之间的提醒：在下一个自然断点写交接文件，写完继续 |
| `zh/hooks/context-watermark-gate.sh` 中的暂存目录标记与 `block` 理由 | 只有拿到会话暂存目录才记下拦截时的水位；拦截要求把交接文件写在本任务的工作目录，写完提示用户换新会话；此后没有任何检查确认它写成 |
| `zh/orchestrator-playbook.md` §3 | 交接格式；被水位硬线拦停时立即写交接，写完提示用户换新会话 |
| `zh/hooks/tests/context-watermark-gate.test.sh`「重复拦截抑制」一节 | 没有会话暂存目录时每轮都拦，不静默放行 |
| `zh/hooks/tests/context-watermark-gate.test.sh` | 测试用例，用例数见该测试输出的 `PASS=<n>` |
| Hsieh 等，「RULER: What's the Real Context Size of Your Long-Context Language Models?」，2024，https://arxiv.org/abs/2404.06654 | 有效上下文长度达不到标称长度 |
| Kuratov 等，「BABILong: Testing the Limits of LLMs with Long Context Reasoning-in-a-Haystack」，2024，https://arxiv.org/abs/2406.10149 | 常见模型只有效利用 10% 至 20% 的上下文 |
