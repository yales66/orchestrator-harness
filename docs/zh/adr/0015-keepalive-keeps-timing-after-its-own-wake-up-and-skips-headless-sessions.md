# ADR 0015：保活在自己的唤醒之后照常计时，-p 无头会话不计时

## 状态

已采纳，自 2026 年 10 月 6 日起生效。取代 [ADR 0014](0014-idle-sessions-past-150k-keep-their-prompt-cache-warm-with-an-async-rewake.md) 中 `stop_hook_active` 那一条件，并扩充它对用户本人消息的界定；ADR 0014 其余内容不变。

## 背景

ADR 0014 让 `keepalive-gate.sh` 在 Stop 输入的 `stop_hook_active` 为真时什么也不做。这一条件沿自 ADR 0013：那时钩子同步拦停，若再拦刚被拦下而续跑的那一轮，就会循环拦截。

Claude Code 2.1.291 在 `asyncRewake` 唤醒起的那一轮结束时，以及在被水位闸门这类同步 Stop 钩子拦下后续跑的那一轮结束时，都把 `stop_hook_active` 设为真。于是保活自己那一轮结束时触发的 Stop 被钩子跳过，空闲的会话只被唤醒一次就再无下文；被别的 Stop 钩子拦过的那一轮之后，也不起计时。

`-p` 无头会话里，Claude Code 把 `CLAUDE_CODE_ENTRYPOINT` 设为 `sdk-cli`，配了 `asyncRewake` 的钩子不转到后台，而是同步运行，整次运行被它 50 分钟的睡眠卡住；而这次运行一结束就退出，没有缓存可保。

用户用 AskUserQuestion 回答选择题时，回答以工具结果进入会话记录，是一条顶层 `toolUseResult` 带 `questions` 的用户角色消息。ADR 0014 不把任何工具结果算作用户本人的消息，所以只靠选择题作答的会话被当成用户已经离开，距用户最后一条打字消息满 8 小时就不再唤醒。无人作答时，Claude Code 超时自动提交这道题，这条工具结果另带 `toolUseResult.afkTimeoutMs`。

## 决策

`keepalive-gate.sh` 不再看 `stop_hook_active`。在交互会话里它只在后台计时，从不拦停，没有拦截循环可防。

`CLAUDE_CODE_ENTRYPOINT` 为 `sdk-cli` 时它什么也不做，与在子智能体内部时一样。

`toolUseResult` 带 `questions` 的用户角色行算用户本人的消息，因为有人在场作答；`toolUseResult` 同时带 `afkTimeoutMs` 的不算，因为没有人作答。

## 后果

上下文过 150,000 词元的空闲会话按 ADR 0014 的本意每 50 分钟被唤醒一次，直到距用户本人最后一条消息满 8 小时，被水位闸门或回复出口拦过的那一轮之后也一样。

`-p` 运行不会被保活卡住，也不会被唤醒。

用户靠选择题作答的会话，只要还在作答，保活就一直有效。超时自动提交的题不重置 8 小时上限，上限仍从用户最后一次真正的作答或消息算起，所以被遗忘的会话照样会停止唤醒。

钩子测试检查：`stop_hook_active` 为真的 Stop 照常起计时；入口为 `sdk-cli` 时不起计时，其他入口照常；以及刚作答、作答在 9 小时前、超时自动提交这三种情形。

## 出处

| 出处 | 支撑的内容 |
|---|---|
| `zh/hooks/keepalive-gate.sh` 与 `zh/hooks/tests/keepalive-gate.test.sh` | 入口为 `sdk-cli` 时退出、不再因 `stop_hook_active` 退出、选择题作答算用户本人消息与 `afkTimeoutMs` 的排除，以及检查这些行为的用例 |
| Claude Code 2.1.291 的打包源码，可按这些片段检索：`priority:"next",stopHookActive:!0,turnAttribution:"inherit"`（`asyncRewake` 退出码 2 入队时带上该标志）、`malformedToolUseRetried:!1,stopHookActive:!0`（同步 Stop 钩子拦下后续跑的那一轮）、`hook_event_name:"Stop",stop_hook_active:`（标志写进 Stop 输入）、`e.asyncRewake&&io`（打印模式下 `io` 为假，`-p` 会话同步运行钩子），以及超时提交时选择题结果里的 `afkTimeoutMs` | Claude Code 把保活自己那一轮与被别的 Stop 钩子拦下后续跑的那一轮都标为 `stop_hook_active`，`-p` 会话里 `asyncRewake` 同步运行，以及区分超时提交的字段 |
| 2026 年 10 月 6 日的一次真实交互会话实测，门槛改为 0、睡眠缩短到 100 秒 | 第一次唤醒后的那次结束回合带着 `stop_hook_active` 为真，改后的钩子照常计时并按时第二次唤醒 |
| 2026 年 10 月 6 日的一次 `-p` 运行，其 Stop 钩子打印了 `CLAUDE_CODE_ENTRYPOINT` | `-p` 会话里入口为 `sdk-cli`，交互会话里为 `cli` |
| [ADR 0014](0014-idle-sessions-past-150k-keep-their-prompt-cache-warm-with-an-async-rewake.md) | 本 ADR 沿用的条件、50 分钟睡眠与 8 小时上限 |
