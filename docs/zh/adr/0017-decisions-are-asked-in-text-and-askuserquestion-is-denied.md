# ADR 0017：拍板改为文字提问，AskUserQuestion 被拒用

## 状态

已采纳，自 2026 年 10 月 6 日起生效。取代 [ADR 0006](0006-ask-the-user-only-where-the-answer-is-theirs.md) 中「收不回的那一步前用 AskUserQuestion 确认」的规定；ADR 0006 其余内容不变。

## 背景

编排手册原先让智能体在收不回的那一步前，以及取舍取决于用户自己偏好的分叉处，用 AskUserQuestion 提问。AskUserQuestion 的弹框挂着时，整轮停在工具调用中途。保活这类 `asyncRewake` 唤醒只能排在它后面，所以问题挂着的时候保活没法给提示缓存续期，挂过 1 小时缓存就过期。

作者本机的会话记录显示了代价：等待超过 60 分钟才作答的选择题，5 例中有 4 例之后的那次请求把提示缓存整段重写；等待 5 到 55 分钟作答的，96 例中有 95 例命中缓存。

Claude Code 2.1.291 给选择题设了超时（`askUserQuestionTimeout` 或 `CLAUDE_AFK_TIMEOUT_MS`），但终端有焦点时它的计时持续归零，用户把终端留在前台离开时，它无法赶在缓存过期前把题提交掉。

把 AskUserQuestion 写进 `permissions.deny` 后，这个工具从交给模型的工具列表中消失，这一点经会话实测。

## 决策

两份副本的 `settings.example.json` 都在 `permissions.deny` 中列出 `"AskUserQuestion"`。

编排手册中的拍板一律用文字提问。收不回的那一步前，用文字提问确认，并结束本轮等回复。分叉的取舍取决于只有用户知道的偏好或约束时，先把不依赖答复、可撤回的部分做完，再用文字提问并结束本轮。每个待定项的选项都编号，用户回编号即可。

提问之后由后台通知、子智能体回报或保活唤醒开启的回合不算答复：只处理该通知，待答项原样留给用户，不替用户选。

## 后果

等待拍板时会话已经结束本轮，所以 [ADR 0014](0014-idle-sessions-past-150k-keep-their-prompt-cache-warm-with-an-async-rewake.md) 与 [ADR 0015](0015-keepalive-keeps-timing-after-its-own-wake-up-and-skips-headless-sessions.md) 的保活像覆盖任何上下文过 150,000 词元的空闲会话一样覆盖这段等待。

用户失去点选选项的弹框界面，改为打字回复选项编号。

文字提问并不让每次拍板多出一个来回。用户回答选择题之后，Claude Code 同样要再发一次请求，把答案作为工具结果带上，与发送用户打字的回复一样。

保活的回合与其他通知都不算答复，所以即使会话在此期间被唤醒多次，待定项也一直留到用户亲自回答。

handoff 技能对选择题答案的抽取，以及保活把选择题作答算作用户本人消息的规则，都保留下来，用于没有拒用该工具的安装，以及拒用之前写下的会话记录。

## 出处

| 出处 | 支撑的内容 |
|---|---|
| `zh/settings.example.json` 的 `permissions.deny` | AskUserQuestion 被拒用 |
| `zh/orchestrator-playbook.md` §1「收不回的动作」与「方向有分叉」两行 | 确认与分叉都用文字提问，先做完不依赖答复的部分，并结束本轮 |
| `zh/orchestrator-playbook.md` §1 关于用户拍板的那一段 | 选项编号，以及通知、子智能体回报或保活唤醒开启的回合不算答复 |
| 作者本机的 Claude Code 会话记录 | 等待超过 60 分钟作答的选择题 5 例中 4 例之后整段重写缓存，5 到 55 分钟的 96 例中 95 例命中缓存 |
| Claude Code 2.1.291 的选择题超时 `askUserQuestionTimeout` / `CLAUDE_AFK_TIMEOUT_MS` | 终端有焦点时计时持续归零 |
| 一次把 AskUserQuestion 写进 `permissions.deny` 的会话实测 | 该工具从模型的工具列表中消失 |
| [ADR 0011](0011-wrap-up-finishes-in-session-at-any-watermark.md) | handoff 技能本来就用普通文字提出待答问题，因为 AskUserQuestion 挂着时定时唤醒不会触发 |
| [ADR 0014](0014-idle-sessions-past-150k-keep-their-prompt-cache-warm-with-an-async-rewake.md) 与 [ADR 0015](0015-keepalive-keeps-timing-after-its-own-wake-up-and-skips-headless-sessions.md) | 结束本轮后覆盖会话的保活，以及它对选择题作答的计数 |
| [ADR 0006](0006-ask-the-user-only-where-the-answer-is-theirs.md) | 本 ADR 取代的那一处规定 |
