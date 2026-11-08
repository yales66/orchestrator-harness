# orchestrator-harness

[![CI](https://github.com/yales66/orchestrator-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/yales66/orchestrator-harness/actions/workflows/ci.yml)

我每一次编码会话都运行在其中的一套 Claude Code 钩子、技能与编排规则。主线程只做编排与委派，子智能体照主线程写的派发说明干活。一组钩子拦下有风险的工具调用，在上下文渐满时要求交接，在用户离开时保住提示词缓存，另外还附带几个技能。

这套框架分成两份可以各自独立安装的完整副本：英文版在 `en/`，中文版在 `zh/`。两份里的钩子脚本、技能辅助脚本与 `agents/*.md` 里的子智能体定义逐字节相同，所以即使安装 `en/` 副本，钩子发给 Claude 的提示也大多是中文，SessionStart 钩子注入的编排手册则与所装副本同一语言。本说明文件的英文版是 [README.md](../README.md)。

## 设计目标

这套框架为长程的智能体编程而建，目标是尽可能少的人工介入。

1. **子智能体上下文精简。** 编排规则只通过 SessionStart 钩子送达主线程；每个子智能体都会加载的 `CLAUDE.md` 只放每个会话都需要的规则。落盘型派发说明写全六项：带可验证验收标准的目标、文件范围、已知上下文、约束、一条自检命令，以及有界的返回格式；只读型派发说明写其中的目标、文件范围、已知上下文与返回格式。子智能体只能再派一层 haiku 工人做短小的机械活。
2. **长程会话。** 主线程保留决策与结论，把探索、审查与实现委派出去。要跨好几轮的任务登记成任务清单，清单上还有未完成项时，一个 Stop 钩子让主线程接着做。上下文窗口渐满时，上下文水位闸门拦下主线程结束这一轮的尝试：已有上下文能做完的收尾就在当前会话做完；接下来是新的大块工作时，主线程经 handoff 技能写出 `HANDOFF.md`，拉起一个从这份文件接续的新会话，剩下的工作在等用户答复时则把文件路径告诉用户。
3. **人只在决策点介入。** 用户不在实时盯着，所以主线程不以计划、问句或自己能做却还没做的承诺结束一轮。每个分叉都先分类。B 类交给用户：收不回的动作、对外的动作、超出预批额度的花费、推翻用户亲口定下的决定或缩小用户定的范围，以及在业务范围、目标用户、平台、对外可见的命名或核心体验方向上真实存在的取舍。B 类问题攒成一次文字提问，带编号的选项与推荐，不依赖答复的工作照常推进。A 类有最优解，智能体自己定下并记下依据。C 类是实现细节上的偏好、做错可撤回，智能体按推荐做完，标为待用户确认。`AskUserQuestion` 在 `permissions.deny` 里被拒绝，所以没有工具调用在等答复（[ADR 0017](../docs/zh/adr/0017-decisions-are-asked-in-text-and-askuserquestion-is-denied.md)、[ADR 0027](../docs/zh/adr/0027-forks-are-classed-before-asking-and-unattended-sessions-keep-working.md)）。回复以提议下一步收尾时，回复出口把它拦下。

## 架构

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../docs/architecture.zh.dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="../docs/architecture.zh.light.svg">
  <img src="../docs/architecture.zh.light.svg" alt="架构图，画的是一轮工作怎样运行。会话开始、/clear 与压缩之后，以 --part 1 到 4 注册四次的 SessionStart 钩子把编排手册注入主线程，每段不超过 9,500 个字符，各段依次错开 0.3 秒，按段号先后送达；子智能体收不到。用户本人键入的消息提到生产模式时，UserPromptSubmit 钩子给主线程注入一句说明，讲怎样设置与取消仓库的生产标记。主线程向子智能体发出派发说明，子智能体凭 agents/*.md 里设定了推理强度与禁用工具的定义、CLAUDE.md 与派发说明干活，可以再派一层 haiku 工人做短小的机械活，交回有界回报。两条线程的每次工具调用在工具执行之前都经过 PreToolUse：子智能体内除模型为 haiku 的 Agent 或 Task 调用之外的派发被拒绝，CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=2 让工人不能再往下派；git commit --no-verify、会打印密钥值的 Bash、Read 或 Grep 调用、直接改写 HANDOFF.md，以及 researcher 或 retriever 子智能体改动、移动或删除已有文件的操作都被拒绝，researcher 与 retriever 子智能体读文件、跑命令与新建文件都放行；密钥守卫与只读守卫把每次拒绝记进 permission-denied.jsonl，PermissionDenied 钩子把自动模式分类器的拒绝也记进这个文件；在标成生产的仓库里执行 gh pr merge，要等用户当场同意才执行；5 小时用量到 95% 及以上时，PreToolUse 里的限额暂停把两条线程的每次调用挂起到重置，每过 50 分钟拒绝一次被挂起的调用，线程随即发出暂停调用（: 限额暂停）并再被挂起，过了重置时间才放行；主线程里，用户本人在用量到 95% 之后发出的输入与缓存保活的最后一次唤醒不被挂起；限额暂停的用量取自本地文件，由状态栏包装把 Claude Code 传给状态栏的 rate_limits 记进这个文件；拒绝理由回到发起调用的线程，线程换一种做法；放行的调用交给工具执行。工具执行之后，PostToolUse 在线程第一次改某个规则文件时把规则文件提醒作为附加上下文送回发起调用的线程，在进入新工作树时把主检出目录中的 CLAUDE.md、node_modules 与 .env* 软链进这个工作树，不回话。主线程想结束这一轮时经过 Stop 钩子，都放行则这一轮结束，其中三个是同步闸门。上下文水位闸门过 35% 时每个会话提醒一次并放行，没有会话暂存目录时则每轮提醒，过 40% 拦一次，没有会话暂存目录时则每轮都拦，此后以上次拦截时的水位为基准，每再涨 5 个百分点就再拦一次；任务清单闸门在主线程登记的任务清单还有 todo 或 doing 的项时拦下，有后台任务或定时唤醒未完成时、或同一份没有变化的清单已被拦满三次后放行；回复出口在回复末句是提议问句时拦一次，仅 zh/ 副本的安装里，较长的回复主要不是中文时也拦一次。这三个闸门拦下都回到主线程。被回复出口拦下，主线程要么直接把提议的那一步做掉，要么在确实需要用户拍板时按背景、各选项的后果与推荐的格式重新提问，因语言被拦时用中文重写。被任务清单闸门拦下，主线程接着做未完成的项，或把卡住的项标成 blocked 并写明原因。被水位闸门第一次拦下，已有上下文能做完的收尾就做完，接下来是新的大块工作时运行 handoff 技能，由主线程自己写出 HANDOFF.new.md，再由 finalize.sh 落位成交接文件，然后接力：拉起一个读这份文件接着做的新会话，剩下的工作在等用户答复时则告诉用户文件在哪里；此后每次再被拦都立即生成交接文件。回复出口与水位闸门都不会拦刚被自己拦下而续跑的那一轮，所以一次停止尝试被每个闸门最多拦一次，这一轮再想停就放行；水位闸门在之后的轮次里仍会随用量上涨再拦。第四个 Stop 钩子缓存保活不拦停：它在这一轮结束后于后台计时，主线程上下文达到 150,000 词元，或是还有轨道在跑的分片父会话（不论上下文大小），且 50 分钟里没有新的一轮时，唤醒主线程只回一个句点，用户离开期间一小时的提示词缓存因此不过期；任务已做完或会话已交接时回停止词（中文安装回「完」，英文安装回 Done），保活随即停下，直到用户本人再发消息。唤醒之前先探测 API，连不上就每 30 秒再探，到这一轮结束后 57 分钟仍连不上就放弃，因为再唤醒已来不及在缓存过期前续上。每次唤醒后照常重新计时，直到距用户本人最后一条消息满 8 小时，分片父会话从这条消息与最后一次轨道状态中较晚的那个算起；到上限前的最后一次唤醒，还有工作或待用户答复的问题就让主线程用 handoff 技能写交接，只剩收尾时记下收尾清单再回一个句点，否则只回一个句点。缓存保活还注册在 SessionEnd 上，给结束的会话留下标记，让它的计时不会唤醒 /clear 之后的新会话。">
</picture>

## 各类派发跑在哪个模型上

编排手册 §2 要求主线程每次派发都指定模型，`agents/` 里的定义设推理强度，不设模型。除非用户点名，编排手册从不选用 fable 模型。

| 派发 | 模型 | 推理强度 | 条件 |
|---|---|---|---|
| 开放式的全仓定位 | Explore，跑在 haiku | 本仓库未设定 | 总是 |
| 机械批量活：找文件、跑脚本、扫描 | haiku，分头并行 | 未设定，跟随会话的推理强度（[ADR 0008](../docs/zh/adr/0008-subagent-effort-per-kind-of-dispatch.md)） | 总是 |
| `implementer` | haiku | `medium` | 每处改动行为的对错由测试判定，不论是已有测试、派发说明列出的验收用例还是子智能体自写的测试；主线程核对 haiku 那次运行改动的每个文件都在派发说明的文件范围内（[ADR 0021](../docs/zh/adr/0021-implementer-runs-on-haiku-when-tests-decide-every-change.md)、[ADR 0023](../docs/zh/adr/0023-implementer-runs-on-haiku-when-tests-decide-including-its-own.md)） |
| `implementer` | opus | `medium` | 其余所有实现，包括有任何一处只能靠看或读来判定的，例如界面外观或文档的修改 |
| `retriever` | haiku | `medium` | 派发说明把查找限定在本地文件、会话记录或其点名的单个网页（不是 PDF），并要子智能体在答案不在其中时回报、不外追链接（[ADR 0022](../docs/zh/adr/0022-retriever-runs-on-haiku-when-the-brief-limits-it-to-local-files-or-one-named-page.md)） |
| `retriever` | opus | `medium` | 其余所有查找，以及 haiku 回报在限定范围内查不到的查找 |
| `researcher` | opus | `high` | 总是 |
| 端到端测试里针对单个元素截图的是非题，例如文字是否被截断、重叠或看不清 | haiku | 本仓库未设定 | 总是；它报告的问题要经 opus 复核才算数 |
| `retriever` 以外的子智能体派出的工人：汇总测试结果、核对文案、单个元素截图的是非题、机械错误的修复建议 | haiku，只有一层 | 本仓库未设定 | 子智能体的派发说明写明它可以外派哪些活与上下文上限；工人只拿到路径与问题，上下文控制在 50,000 词元以内（[ADR 0025](../docs/zh/adr/0025-subagents-may-dispatch-one-layer-of-haiku-workers.md)） |

## 测量了什么

[docs/zh/evaluation.md](../docs/zh/evaluation.md) 说明每项测量的方法与局限。

| 实验 | 要回答的问题 | 状态 |
|---|---|---|
| [推理强度对比](../eval/effort-sweep/README.md) | 子智能体在推理强度 `medium` 与 `high` 下、以及换用 Haiku 5.5 代替 Opus 5.5 时，质量与花费相比如何？ | 于 2026 年 9 月与 10 月运行；上一节的派发由此定下（[ADR 0008](../docs/zh/adr/0008-subagent-effort-per-kind-of-dispatch.md)、[ADR 0021](../docs/zh/adr/0021-implementer-runs-on-haiku-when-tests-decide-every-change.md)、[ADR 0022](../docs/zh/adr/0022-retriever-runs-on-haiku-when-the-brief-limits-it-to-local-files-or-one-named-page.md)、[ADR 0023](../docs/zh/adr/0023-implementer-runs-on-haiku-when-tests-decide-including-its-own.md)） |
| [漏拦请示](../eval/rules-missed-asks/README.md) | 编排手册里的请示判据能否减少回复出口漏掉的过度请示？ | 跑过之后已搁置，因为得分测不到这条规则 |
| [请示判断探针](../eval/ask-or-act/README.md) | 现行手册能否让模型该问时问、问了也多余时直接做？ | 做过两次试跑后停止，因为回放读到的是运行回放时的文件而不是会话当时的 |
| [拦截后跟进](../eval/gate-followthrough/README.md) | 回复出口拦下一条本该请示的回复之后，模型会不会照样去做那一步？ | 已设计、未运行 |

| 测量 | 结果 | 复跑 |
|---|---|---|
| 钩子回归测试 | 每个副本 17 个测试文件共 878 个用例全部通过 | `for t in en/hooks/tests/*.test.sh; do bash "$t"; done` |
| 技能脚本测试 | 每个副本 124 个 pytest 用例全部通过，其中交接脚本 36 个，feature-sharding 脚本 88 个 | `python3 -m pytest -p no:cacheprovider en/skills/handoff/scripts en/skills/feature-sharding/scripts` |
| 钩子变异测试，[eval/hook-mutations](../eval/hook-mutations/README.md) | 2026 年 9 月 30 日，往最早的 9 个钩子里植入的 54 个缺陷，测试抓住了全部 54 个；只照钩子头注释、不看测试写出的 35 个留出集缺陷，测试抓住 30 个 | `bash eval/hook-mutations/run.sh`；钩子此后改过，已复现不出这些数字 |
| 静态上下文，[eval/static-context](../eval/static-context/README.md) | 编排手册经钩子注入时，每个子智能体的首次请求输入是 10,186 词元，写进 `CLAUDE.md` 时是 13,529 词元（en/ 副本，Claude Code 2.1.286） | `bash eval/static-context/run.sh` |
| 回复出口回放，[eval/reply-gate-replay](../eval/reply-gate-replay/README.md) | 在回复出口上线前写成的 2,734 条收尾回复上，它的收尾提议规则精确率 68.5%，召回率 31.7% | `python3 eval/reply-gate-replay/score.py --data "$DATA"`，其中 `DATA` 是存放会话记录与标注的私有目录 |

## 目录结构

两个语言文件夹的布局都对应 `~/.claude/`。测试文件不安装，`settings.example.json` 要合并进 `~/.claude/settings.json` 而不是直接复制。

| 路径 | 是什么 |
|---|---|
| `CLAUDE.md` | 加载进每个会话的全局规则：密钥与凭据、文稿、改现有代码、测试、数字要从哪里来，以及本机 Docker 清理 |
| `orchestrator-playbook.md` | 主线程作为编排者的规则：无人值守时的常设约定、怎样给分叉分类与何时提问、委派什么及派到哪个模型、怎样写子智能体派发说明、任务清单与怎样交接长任务、交付闸门、git 约定，以及技能自带的提问或停下指令在多大程度上算数 |
| `hooks/` | 在 `settings.json` 中注册的 shell 钩子，以及状态栏包装 `statusline-tee.sh` |
| `hooks/tests/` | 覆盖 `hooks/` 下全部十七个脚本的回归测试 |
| `agents/` | 三个子智能体的定义，各自设定推理强度：`researcher`（`high`）接需要判断的只读审查、诊断、调研与草拟，`retriever`（`medium`）接只读检索与抽取，`implementer`（`medium`）接设计决定已由派发说明定死的实现。`researcher` 与 `retriever` 可以新建文件，不能改动已有文件。每个定义在 `disallowedTools` 里列出它没有的工具；`retriever` 没有 `Agent` 工具，所以只有 `researcher` 与 `implementer` 能派 haiku 工人。环境变量里设置的 `CLAUDE_CODE_EFFORT_LEVEL` 会盖过这三个定义里的推理强度 |
| `skills/` | 为本框架编写的技能。`handoff` 与 `feature-sharding` 两个技能的辅助脚本及其 pytest 测试放在 `skills/*/scripts/` |
| `settings.example.json` | `env` 里的 `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=2`，`permissions.deny` 里的 `AskUserQuestion`，在 `$HOME/.claude` 之下注册全部钩子的 `hooks` 配置块，以及一条运行 `statusline-tee.sh`、不带被包装命令的 `statusLine` 条目，所以只记录用量、不显示任何内容 |

## 钩子

| 钩子 | 事件 | 行为 | 测试 |
|---|---|---|---|
| `orchestrator-playbook-session-start.sh` | SessionStart，按段各注册一次 | 把 `orchestrator-playbook.md` 注入主线程。带 `--part N` 时只注入第 N 段，在 `## ` 节标题处切成每段不超过 9,500 个字符的几段，因为钩子输出更长时 Claude Code 只把预览交给模型。第 N 段先等 (N−1)×0.3 秒再输出，让各段按序送达（[ADR 0024](../docs/zh/adr/0024-the-playbook-is-injected-in-parts-under-the-per-hook-limit.md)） | `orchestrator-playbook-session-start.test.sh` |
| `block-nested-subagent.sh` | PreToolUse，匹配 `Agent\|Task\|Workflow` | 在子智能体内只放行模型为 haiku 的 `Agent` 或 `Task` 调用，其余派发与所有工作流一律拒绝；`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=2` 让这些工人不能再往下派。主线程与用 `--agent` 启动的会话都不受限 | `block-nested-subagent.test.sh` |
| `block-no-verify-commit.sh` | PreToolUse，匹配 `Bash` | 拒绝 `git commit --no-verify` 与 `git commit -n`，确保用户自己配置的 `commit-msg` 钩子总会运行 | `block-no-verify-commit.test.sh` |
| `context-watermark-gate.sh` | Stop | 从会话记录读取上下文用量。用量过上下文窗口的 35% 时提醒一次；过 40% 时拦一次，主线程把已有上下文能做完的收尾做完，接下来是新的大块工作时经 handoff 技能交接。此后用量每再涨 5 个百分点就再拦一次，要求立即生成交接。没有会话暂存目录时每轮都提醒、每轮都拦。窗口大小默认 1,000,000 词元；写在该钩子命令前面的 `CONTEXT_WINDOW_TOKENS`、`CONTEXT_WARN_PCT`、`CONTEXT_HARD_PCT` 与 `CONTEXT_REBLOCK_DELTA_PCT` 覆盖窗口大小与三个阈值 | `context-watermark-gate.test.sh` |
| `rule-file-edit-check.sh` | PostToolUse，匹配 `Edit\|Write` | 当被编辑的文件是大语言模型规则文件时，即 `CLAUDE.md`、`CLAUDE.local.md`、`AGENTS.md`、`SKILL.md`，`.claude/commands/`、`.claude/agents/` 或 `.claude/skills/` 下的 `.md` 文件，`.claude/output-styles/` 下的任何文件，或 `.claude/orchestrator-playbook.md`，注入一条提醒，要求加载 `rule-file-editing` 技能，每条线程里同一文件只提醒一次 | `rule-file-edit-check.test.sh` |
| `worktree-symlink-claudemd.sh` | PostToolUse，匹配 `EnterWorktree` | 把主检出目录中的 `CLAUDE.md`、`node_modules` 与 `.env*` 以符号链接接入新建的 git 工作树，不覆盖已有的真实文件 | `worktree-symlink-claudemd.test.sh` |
| `reply-gate.sh` | Stop | 即回复出口。回复的末句是「要我…吗」「Shall I …?」这类提议下一步的问句时拦停一次，并重申何时直接做、怎样请用户拍板。设置 `REPLY_LANG=zh` 时（`zh/` 的配置已设置），超过 150 个字符的回复里中日韩字符不到中日韩字符与拉丁字母总数的五分之一，也拦停一次。代码与 URL 不计入 | `reply-gate.test.sh` |
| `task-checklist-gate.sh` | Stop | 主线程登记在 `~/.claude/state/checklists/<会话 id>.json` 的任务清单里还有状态不是 `done` 或 `blocked` 的项时拦停，并点名这些项。在子智能体内部、有后台任务或定时唤醒未完成时，以及同一份没有变化的清单已被拦满三次后放行 | `task-checklist-gate.test.sh` |
| `keepalive-gate.sh` | Stop，配 `asyncRewake`；SessionEnd | 每一轮结束后在后台运行。主线程上下文达到 150,000 词元、会话空闲满 50 分钟时，唤醒模型只回一个句点，一小时的提示词缓存因此不过期；任务已做完或已交接时改回停止词 `Done`（`REPLY_LANG=zh` 时回「完」），此后不再计时，直到用户本人再发消息。还有轨道在跑的 feature-sharding 父会话不论上下文多大都保活。唤醒之前它先探测 API，连不上时每 30 秒再探一次，直到唤醒已来不及续上缓存为止。它每 50 分钟唤醒一次，直到距用户本人最后一条消息满 8 小时；最后一次唤醒在还有工作或待用户答复的问题时交接，只剩收尾时记下收尾清单，其余情形只回一个句点。它从不唤醒子智能体或 `-p` 无头会话，缓存已降为 5 分钟有效期时不起计时。SessionEnd 时它给结束的会话留下标记，所以 `/clear` 之前起的计时不会唤醒之后的新会话（[ADR 0014](../docs/zh/adr/0014-idle-sessions-past-150k-keep-their-prompt-cache-warm-with-an-async-rewake.md)、[ADR 0015](../docs/zh/adr/0015-keepalive-keeps-timing-after-its-own-wake-up-and-skips-headless-sessions.md)、[ADR 0019](../docs/zh/adr/0019-keepalive-probes-the-network-before-waking-and-hands-off-at-its-last-wake-up.md)、[ADR 0029](../docs/zh/adr/0029-the-keepalive-stops-for-finished-or-handed-off-sessions-and-stays-on-for-sharding-parents.md)） | `keepalive-gate.test.sh` |
| `secret-guard.sh` | PreToolUse，匹配 `Bash\|Read\|Grep` | 拒绝会把密钥值打印进模型上下文的调用。密钥文件指 `.env` 与 `.env.*`（`.example`、`.sample` 与 `.template` 样例除外）、`~/.ssh` 下的 SSH 私钥，以及路径含 `.kamal/secrets` 的文件。以下调用被拒绝：Read 密钥文件；在 `content` 模式下 Grep 密钥文件；用 `cat`、`head`、`grep` 或 `base64` 这类 shell 读取命令读密钥文件；递归搜索含密钥文件的目录树；用 `echo` 或 `printf` 展开名称含 KEY、SECRET、TOKEN、PASSWORD、PASSWD 或 CREDENTIAL 的变量；单独使用的 `printenv`、`env`、`export -p` 或 `set`。`bash -c`、`eval`、命令替换以及喂给 shell 的内嵌文档（heredoc）里的命令同样判断。只用到值而不打印值的命令放行，例如 `source .env` 后接命令。每次拒绝都记进 `~/.claude/state/permission-denied.jsonl` | `secret-guard.test.sh` |
| `subagent-readonly-guard.sh` | PreToolUse，匹配 `Edit\|Write\|NotebookEdit\|MultiEdit\|Bash` | 在 `researcher` 与 `retriever` 子智能体内部放行新建文件，拒绝改动已有文件：所有 Edit、MultiEdit 与 NotebookEdit，目标已存在的 Write，以及就地改文件、重定向写到已存在的文件、删除、移动、截断或 `chmod` 文件、改动 git 状态，或在内联解释器代码里写文件的 shell 命令。每次拒绝都记进 `~/.claude/state/permission-denied.jsonl` | `subagent-readonly-guard.test.sh` |
| `handoff-guard.sh` | PreToolUse，匹配 `Edit\|Write\|NotebookEdit\|MultiEdit\|Bash` | 拒绝直接改写 `HANDOFF.md`，主线程与子智能体一律适用，编辑、重定向、就地编辑、`cp`、`mv`、`rm`、git 还原或内联解释器代码都算在内，让交接文件只出自 handoff 技能。读它、写 `HANDOFF.new.md` 与运行技能的 `finalize.sh` 都放行 | `handoff-guard.test.sh` |
| `production-merge-gate.sh` | PreToolUse，匹配 `Bash` | `gh pr merge` 的目标仓库设了 `git config claude.production true` 时，请用户当场同意这次合并。`-R`/`--repo`、`GH_REPO=` 前缀或 PR 网址指向工作目录远端以外的仓库时，按生产仓库处理。标记放在 git config 里，所以对同一仓库的所有工作树都成立 | `production-merge-gate.test.sh` |
| `production-mode-hint.sh` | UserPromptSubmit | 用户本人键入的消息提到「生产模式」或 production mode 时，注入一句说明，讲怎样设置与取消生产标记。子智能体的回报与后台通知跳过 | `production-mode-hint.test.sh` |
| `limit-pause-gate.sh` | PreToolUse，匹配所有工具（`*`），配 `"timeout": 3300` | 在 Claude.ai Pro 或 Max 订阅的 5 小时用量逼近上限时挂起所有线程的工具调用，免得工作在中途中断。它从 `statusline-tee.sh` 写的 `~/.claude/state/rate-limits.json` 读用量，装了状态栏插件 claude-hud 时也读它的用量缓存。达到或超过 95% 时把调用挂起到重置，每满 50 分钟拒绝一次，让模型发一条简短的暂停调用（`: 限额暂停`），这次调用保住提示词缓存，随即又被挂起。主线程里，跟在用户本人于用量到 95% 之后发出的输入之后的调用，以及跟在保活最后一次唤醒之后的调用，都不挂起；调用被挂起期间用户键入消息时，它立即拒绝这次调用，让模型处理这条消息。`~/.claude/state/limit-pause-off` 存在时它不起作用（[ADR 0020](../docs/zh/adr/0020-tool-calls-are-held-at-95-percent-of-the-five-hour-limit.md)） | `limit-pause-gate.test.sh` |
| `permission-denied-log.sh` | PermissionDenied | Claude Code 的自动模式分类器每拒绝一次，就往 `~/.claude/state/permission-denied.jsonl`（或 `PERMISSION_DENIED_LOG` 指定的路径）追加一行，记工具名、被拒的命令、路径或网址的前 300 个字符与拒绝理由，供事后找出该补哪条放行规则 | `permission-denied-log.test.sh` |
| `statusline-tee.sh` | `statusLine` 命令，不是钩子事件 | 包在作为参数传入的状态栏命令外面：把 Claude Code 传给状态栏的 5 小时 `rate_limits` 写进 `~/.claude/state/rate-limits.json`，包括用量第一次到 95% 的时刻 `pause_since`，再把标准输入原样交给被包装的命令。不带参数时只记录限额，不显示任何内容。同一窗口里从不用较低的读数替换较高的读数 | `statusline-tee.test.sh` |

## 技能

| 技能 | 用途 |
|---|---|
| `rule-file-editing` | 编辑 `CLAUDE.md`、`SKILL.md` 等指令文件时的纪律：按改动如何改变运行时行为来裁决每处改动，把例外写成分支，并把删除以及新建的规则文件交给独立复核者 |
| `memory-audit` | 裁定哪些 Claude Code 记忆条目保留、合并或删除，并重建索引 |
| `handoff` | 整份生成 `HANDOFF.md`。主线程凭自己的上下文写出 `HANDOFF.new.md`，`scripts/extract.py` 把用户发过的每一条消息连同 git 状态抽到 `.handoff-archive/material/`，`scripts/finalize.sh` 把新文件落位并归档旧版（[ADR 0026](../docs/zh/adr/0026-the-main-thread-writes-the-handoff-itself.md)）。随后接力：剩下每一项都在等用户答复时，把交接路径与开工指令告诉用户；否则经 feature-sharding 的 `launch_tracks.py` 在新的 Ghostty 窗口里拉起接力会话，这需要 macOS 与 Ghostty，拉起失败时改为把路径告诉用户。有 B 类问题等用户答复、且答复之后是一大块工作时，会话先做完不依赖答复的工作，再设一次 50 分钟后的唤醒，赶在一小时的提示词缓存过期之前 |
| `feature-sharding` | 规划可能装不进主线程剩余预算的多模块工作：按测得的预算与接缝路由，按工作量分箱，要么在当前会话按波次并行派子智能体，要么用 `scripts/spawn_tracks.py` 把每条轨道拉成各在一个工作树里的 `claude --bg -w` 后台会话。规划会话留作父会话：用 `wait_tracks.py` 等候各轨道，回答轨道的问题，为轨道接力，并按顺序合并各轨道（[ADR 0028](../docs/zh/adr/0028-sharding-tracks-run-as-background-sessions-under-the-planning-session.md)）。只有轨道需要凭据或付费额度时，才先请用户批准启动清单。它需要支持后台会话（`claude --bg`）的 Claude Code 版本 |
| `grilling` | 围绕一个计划或决定逐轮追问用户，直到双方理解一致。每轮提问之前，它像编排手册那样给每个待定决定分类，只把 B 类问题拿去问，每个问题附推荐答案。改写自 [mattpocock/skills](https://github.com/mattpocock/skills) |

## 安装

把本仓库克隆到本地，在仓库目录里启动 Claude Code，让 Claude 来完成安装，例如直接粘贴这句请求：

```text
请把本仓库的 zh/ 副本安装到 ~/.claude，按 zh/README.md 里「安装」一节的说明操作。
```

要装英文版就把请求里的 `zh/` 换成 `en/`。下面的步骤是写给执行安装的那个 Claude 会话的，它按顺序照做：

1. 告诉用户，这一版在 Claude Code 2.1.319 上测试过，需要支持 `asyncRewake` 钩子、PermissionDenied 与 SessionEnd 钩子事件、并在钩子输入里提供 `scratchpad_dir` 的版本。检查 `bash`、`python3`、`jq` 与 `git` 是否都在 `PATH` 上，缺哪一个就在复制任何文件之前告诉用户：缺少 `python3` 或 `jq` 时，钩子得不出判定就退出，于是每一次调用都未经检查地通过。
2. 从用户指定的副本取源文件，即 `en/` 或 `zh/`；请求里两者都没提时先问用户。
3. 覆盖 `~/.claude/` 下任何已有文件之前（包括 `settings.json`），先把它复制到一个备份位置，并告诉用户备份放在哪里。
4. 把 `hooks/*.sh` 复制到 `~/.claude/hooks/`，不复制 `hooks/tests/`；把 `skills/` 下的每个目录复制到 `~/.claude/skills/`，不复制测试文件 `skills/*/scripts/test_*.py`；把 `agents/*.md` 复制到 `~/.claude/agents/`；把 `orchestrator-playbook.md` 复制到 `~/.claude/`，即 `hooks/` 的直接上级目录，SessionStart 钩子在那里找它。
5. 把 `settings.example.json` 的 `hooks` 配置块合并进 `~/.claude/settings.json`，该文件不存在时就新建。其余键与不属于本框架的钩子条目全部保留。同一事件下有条目运行同一个脚本，编排手册钩子则是同一个脚本加同一个 `--part` 段号，就算本框架的钩子已经注册；每条这样的条目都整条换成 `settings.example.json` 里的写法，命令、匹配器、`timeout` 与 `asyncRewake` 都在内，不再添加第二条。换好之后，把用户自己加在原命令前的前缀放回新命令前，例如 `CONTEXT_WINDOW_TOKENS`，而 `REPLY_LANG=zh` 只取自所装副本。不带 `--part` 运行编排手册钩子的条目换成四条分段条目。本框架的条目与用户自己的钩子同在一个匹配器分组里时，把本框架的条目移进单独的分组，匹配器取 `settings.example.json` 里的写法。把 `env` 配置块里的 `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` 加进 `~/.claude/settings.json` 的 `env` 配置块，再把 `permissions.deny` 里尚未列出的每一项追加进去。`statusLine` 一项：`~/.claude/settings.json` 里没有时，照 `settings.example.json` 加上；已经运行着某个状态栏命令时，在它前面加上 `bash $HOME/.claude/hooks/statusline-tee.sh`，例如 `bash $HOME/.claude/hooks/statusline-tee.sh node /path/to/statusline.js`。原有命令用了管道、`&&` 或 `VAR=value` 前缀这类 shell 语法时，改为包成 `bash $HOME/.claude/hooks/statusline-tee.sh bash -c '<原有命令>'`，原有命令本身已是一条 `bash -c '…'` 时除外，包之前先把其中每个单引号写成 `'\''`，并保留 `statusLine` 的其余键，例如 `padding`。命令已以 `statusline-tee.sh` 开头时保持不动。告诉用户限额暂停只在 Claude.ai Pro 或 Max 订阅下起作用，因为 Claude Code 只在这两种订阅下把 5 小时用量传给状态栏。
6. 用户所用模型的上下文窗口不是 1,000,000 词元时，在 `~/.claude/settings.json` 里水位闸门的命令前加上 `CONTEXT_WINDOW_TOKENS` 设为该窗口大小，例如 `CONTEXT_WINDOW_TOKENS=200000 bash $HOME/.claude/hooks/context-watermark-gate.sh`，不清楚窗口大小时先问用户。窗口只有 200,000 词元时，默认值会把 35% 的提醒线放在 350,000 词元，闸门永远不起作用。
7. 只有用户明确要求时才安装 `CLAUDE.md`。`~/.claude/CLAUDE.md` 已经存在时，改动之前先问用户是覆盖还是把两份合并。`CLAUDE.md` 装的是我个人的规则，分六节：密钥与凭据（一律不读、不打印）、产出文稿、改现有代码、测试、出处与验证，以及本机 Docker。安装之前先提醒用户：Docker 一节让主线程在用过 Docker 的任务结束时不问就运行 `docker system prune -a --volumes -f && docker volume prune -a -f`，这会删掉本机所有没在用的镜像、容器、数据卷与构建缓存，所以要留着没在用的镜像或数据卷的用户应删掉或改写这一节；`zh/` 副本的 `CLAUDE.md` 还要求始终用中文沟通。
8. 告诉用户启动一个新的 Claude Code 会话，因为钩子与技能只在安装之后启动的会话里生效；同时告诉用户编排手册与 `CLAUDE.md` 点名了几个本仓库没有收录的技能，详见下一段。还要告诉用户：handoff 技能在新的 Ghostty 窗口里拉起接力会话，这只在装了 Ghostty 的 macOS 上可行；feature-sharding 需要支持 `claude --bg` 的 Claude Code 版本。

编排手册与 `CLAUDE.md` 还点名了五个没有收录在这里的技能：`prose-discipline`、`tdd-watch-it-fail`、`debug-root-cause`、`domain-modeling` 与 `write-pr`。编排手册还点名了 Claude Code 内置的 `artifact-design`。缺了某个技能时，点名它的那条规则文字仍然有效，只是那个技能加载不到；请安装你自己的等价技能，或删掉这些引用。

想让某个仓库里的每次 `gh pr merge` 都等你同意，就在该仓库里运行 `git config claude.production true`；`git config --unset claude.production` 取消标记。

## 测试

在 `en/` 或 `zh/` 目录下运行钩子测试：

```bash
for t in hooks/tests/*.test.sh; do bash "$t"; done
```

每个钩子测试都会打印 `PASS=<n> FAIL=<n>`，任何一项失败都以非零状态退出。handoff 与 feature-sharding 两个技能的脚本带 pytest 测试，在 `en/` 或 `zh/` 目录下这样运行：

```bash
python3 -m pytest -p no:cacheprovider skills/handoff/scripts skills/feature-sharding/scripts
```

第三方 pytest 插件加载报错时，在命令前加 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`。

在仓库根目录下，核对 `en/` 与 `zh/` 两份副本一致、两份编排手册的每一段都不超过 9,500 个字符的检查这样运行：

```bash
bash scripts/check-parity.sh
```

持续集成在推送到 `main` 与每个拉取请求时运行：在 Ubuntu 与 macOS 上运行两份副本的钩子测试，运行技能脚本测试，用 shellcheck 检查钩子、钩子测试、技能的 shell 脚本与仓库脚本，运行一致性检查，并检查已跟踪的 Markdown 文件里没有作者本机的用户目录路径。想在本机跑同样的检查，在仓库根目录下运行下面的命令。它需要装有 pytest 的 `python3`，以及 `jq`、`git` 与 `shellcheck`，都在 `PATH` 上；在 Mac 上用 `/bin/bash scripts/ci-local.sh` 运行，就和持续集成用的 bash 3.2 一致。一致性检查只看已纳入 git 跟踪的文件，新建的文件先 `git add` 再运行：

```bash
bash scripts/ci-local.sh
```

## 文档

| 文档 | 主题 |
|---|---|
| [ADR 0001：编排规则只送达主线程](../docs/zh/adr/0001-orchestration-rules-reach-only-the-main-thread.md) | 编排手册加载到哪里；送达方式已由 ADR 0024 修订 |
| [ADR 0002：每份子智能体派发说明都写全六要素](../docs/zh/adr/0002-every-subagent-brief-carries-six-elements.md) | 一次委派必须包含什么，只读派发用其中四项 |
| [ADR 0003：子智能体不能再派子智能体](../docs/zh/adr/0003-subagents-cannot-spawn-subagents.md) | 谁可以派发工作；已由 ADR 0025 修订，子智能体可以再派一层 haiku 工人 |
| [ADR 0004：上下文水位从会话记录的用量读取，并以交接文件为停止闸门](../docs/zh/adr/0004-context-watermark-read-from-transcript-usage.md) | 上下文水位怎样测量；交接时机已被 ADR 0007 取代，交接格式已被 ADR 0010 取代 |
| [ADR 0005：会拒绝、拦截或注入规则的钩子都带回归测试](../docs/zh/adr/0005-deciding-hooks-ship-with-regression-tests.md) | 哪些钩子要带测试 |
| [ADR 0006：只在答案属于用户时才问用户](../docs/zh/adr/0006-ask-the-user-only-where-the-answer-is-theirs.md) | 智能体何时提问、何时直接做；与 ADR 0027 冲突处已由它修订 |
| [ADR 0007：交接时机在换会话与长上下文两头的代价之间权衡](../docs/zh/adr/0007-handoff-timing-weighs-switch-against-long-context.md) | 长会话何时交接；提醒内容已被 ADR 0018 取代 |
| [ADR 0008：子智能体的推理强度按派发种类设定](../docs/zh/adr/0008-subagent-effort-per-kind-of-dispatch.md) | 每类派发跑在什么推理强度 |
| [ADR 0009：只读子智能体只在派发说明指定处写文件，retriever 把判断留给主线程](../docs/zh/adr/0009-read-only-subagents-write-where-the-brief-points.md) | 只读子智能体能在哪里建文件，判断由谁来下 |
| [ADR 0010：交接文件由 handoff 技能整份生成，钩子禁止手改](../docs/zh/adr/0010-handoffs-are-generated-whole-by-the-handoff-skill.md) | 交接文件怎样生成，为什么从不打补丁；由谁来写已由 ADR 0026 修订 |
| [ADR 0011：收尾不论水位都在当前会话做完，待用户拍板的问题在缓存过期前设唤醒](../docs/zh/adr/0011-wrap-up-finishes-in-session-at-any-watermark.md) | 会话何时不交接，等用户时又何时交接 |
| [ADR 0012：非生产仓库里合并本任务开的拉取请求属于可撤回，生产仓库由钩子先问用户](../docs/zh/adr/0012-merging-own-pr-is-undoable-outside-production.md) | 主线程何时合并自己开的拉取请求 |
| [ADR 0013：上下文过 150k 的会话用 30 分钟心跳保住缓存](../docs/zh/adr/0013-sessions-past-150k-keep-their-prompt-cache-warm.md) | 已被 ADR 0014 取代。会话何时设保活，保活又怎样结束 |
| [ADR 0014：上下文过 150k 的空闲会话在 50 分钟后由异步唤醒保住缓存](../docs/zh/adr/0014-idle-sessions-past-150k-keep-their-prompt-cache-warm-with-an-async-rewake.md) | 空闲会话何时被唤醒以保住缓存，以及为什么它取代了 ADR 0013 的 30 分钟心跳；已由 ADR 0029 扩展 |
| [ADR 0015：保活在自己的唤醒之后照常计时，-p 无头会话不计时](../docs/zh/adr/0015-keepalive-keeps-timing-after-its-own-wake-up-and-skips-headless-sessions.md) | 保活为什么不看 `stop_hook_active`、不在 `-p` 运行里计时，并在没有拒用 `AskUserQuestion` 的安装里把选择题的作答算作用户本人的消息；已由 ADR 0029 扩展 |
| [ADR 0016：feature-sharding 随仓库发布](../docs/zh/adr/0016-feature-sharding-ships-with-the-harness.md) | 为什么随框架发布 `feature-sharding`，编排手册何时把多模块工作交给它；轨道怎样拉起已由 ADR 0028 修订 |
| [ADR 0017：拍板改为文字提问，AskUserQuestion 被拒用](../docs/zh/adr/0017-decisions-are-asked-in-text-and-askuserquestion-is-denied.md) | 怎样请用户拍板，以及为什么拒用选择题工具；与 ADR 0027 冲突处已由它修订 |
| [ADR 0018：水位提醒不再拦着新工作](../docs/zh/adr/0018-the-watermark-reminder-does-not-hold-back-new-work.md) | 提醒线与硬线之间为什么照常开工 |
| [ADR 0019：保活唤醒前先探测网络，最后一次唤醒在还有工作时写交接](../docs/zh/adr/0019-keepalive-probes-the-network-before-waking-and-hands-off-at-its-last-wake-up.md) | 网络一直不通时保活为什么在一轮结束后 57 分钟放弃，最后一次唤醒何时写交接；已由 ADR 0029 扩展 |
| [ADR 0020：5 小时用量到 95% 时挂起工具调用，每 50 分钟保活一次](../docs/zh/adr/0020-tool-calls-are-held-at-95-percent-of-the-five-hour-limit.md) | 工具调用怎样等到用量重置，用量从哪里读，谁的调用放行 |
| [ADR 0021：改动对错全由既有测试或写定的验收用例判定时，`implementer` 派到 Haiku](../docs/zh/adr/0021-implementer-runs-on-haiku-when-tests-decide-every-change.md) | 改动行为的对错全部由已有测试或派发说明里的验收用例判定时，`implementer` 为什么派到 Haiku 5.5 的 `medium`，`retriever` 为什么按胜任规则留在 Opus（`implementer` 两行已由 ADR 0023 修订，`retriever` 一行已由 ADR 0022 修订） |
| [ADR 0022：派发说明把查找限定在本地文件或点名的单个网页时，`retriever` 派到 Haiku](../docs/zh/adr/0022-retriever-runs-on-haiku-when-the-brief-limits-it-to-local-files-or-one-named-page.md) | 限定在本地文件、会话记录或点名单个网页的查找为什么在未满足胜任规则时派到 Haiku 5.5，其余查找为什么留在 Opus |
| [ADR 0023：改动对错由测试判定时，`implementer` 派到 Haiku，子智能体自写的测试也算](../docs/zh/adr/0023-implementer-runs-on-haiku-when-tests-decide-including-its-own.md) | 由测试判定对错的实现为什么即使测试由子智能体自写也派到 Haiku 5.5，这一结论在多大程度上依赖盲审，有任何一处只能靠看或读来判定的实现为什么留在 Opus，以及主线程为什么要核对 haiku 那次运行的文件范围 |
| [ADR 0024：编排手册分段注入，每段都在单个钩子的上限之内](../docs/zh/adr/0024-the-playbook-is-injected-in-parts-under-the-per-hook-limit.md) | 编排手册钩子为什么按段各注册一次，怎样切段、怎样让各段按序送达，一致性检查核对什么 |
| [ADR 0025：子智能体可以再派一层 haiku 工人](../docs/zh/adr/0025-subagents-may-dispatch-one-layer-of-haiku-workers.md) | 子智能体能把哪些短活交给 haiku 工人，上下文上限是多少，钩子与派发深度怎样把它限制在一层 |
| [ADR 0026：交接由主线程自己写，接力会话由会话自己拉起](../docs/zh/adr/0026-the-main-thread-writes-the-handoff-itself.md) | 为什么交接不再由子智能体起草或审阅，写完之后会话怎样接力 |
| [ADR 0027：分叉先判类型再决定问不问，无人值守的会话持续推进](../docs/zh/adr/0027-forks-are-classed-before-asking-and-unattended-sessions-keep-working.md) | 三类分叉及其中哪些交给用户，结束一轮的常设约定，以及任务清单闸门 |
| [ADR 0028：分片轨道以后台会话运行，由规划会话统筹](../docs/zh/adr/0028-sharding-tracks-run-as-background-sessions-under-the-planning-session.md) | feature-sharding 为什么用 `claude --bg` 拉起轨道，并让规划会话当它们的父会话 |
| [ADR 0029：任务已完成或已交接的会话停止保活，有在跑轨道的分片父会话保持保活](../docs/zh/adr/0029-the-keepalive-stops-for-finished-or-handed-off-sessions-and-stays-on-for-sharding-parents.md) | 唤醒何时回停止词（中文安装回「完」，英文安装回 `Done`），分片父会话为什么在 150k 以下也保活，SessionEnd 标记与最后一次唤醒的几个分支各做什么；扩展 ADR 0014、0015 与 0019 |
| [评测：方法与局限](../docs/zh/evaluation.md) | 本框架主张什么、不主张什么，以及受控实验要花多少 |
| [静态上下文测量](../eval/static-context/README.md) | 怎样运行这项测量，每组配置安装了什么 |
| [钩子变异测试](../eval/hook-mutations/README.md) | 怎样用植入的缺陷衡量钩子测试，以及留出集 |
| [回复出口回放](../eval/reply-gate-replay/README.md) | 怎样在历史会话上回放回复出口，并与不看回复出口输出、但知道其短语表的智能体所作的标注比对打分 |

## 许可证

MIT。见 `LICENSE`。两份副本里的 `skills/grilling` 改写自 [mattpocock/skills](https://github.com/mattpocock/skills)，按 MIT 发布，版权归原作者，见该目录下的 `LICENSE`。

## 数据来源

| 数字 | 来源 |
|---|---|
| 提示词元的计法（输入、缓存写入与缓存读取三项相加） | Anthropic 提示词缓存文档，https://platform.claude.com/docs/en/build-with-claude/prompt-caching |
