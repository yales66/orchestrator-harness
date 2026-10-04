# orchestrator-harness

[![CI](https://github.com/yales66/orchestrator-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/yales66/orchestrator-harness/actions/workflows/ci.yml)

我每一次编码会话都运行在其中的一套 Claude Code 钩子、技能与编排规则。

这套框架分成两份可以各自独立安装的完整副本：英文版在 `en/`，中文版在 `zh/`，中文是我与 Claude 协作时使用的语言。两份的规则相同，译文尽可能贴近原意。两份里的钩子脚本与技能辅助脚本完全一样。脚本内的注释是中文，Claude 都能读懂；钩子的提示信息、`finalize.sh` 的报错与 `extract.py` 输出的小标题也是中文；生产合并闸门的理由出现在用户要回答的确认框里，所以是中英双语的一句话。本说明文件的英文版是仓库根目录的 `README.md`。

## 设计目标

这套框架为长程的智能体编程而建，目标是尽可能少的人工介入。

1. **子智能体上下文精简。** 编排规则只通过 SessionStart 钩子送达主线程；每个子智能体都会加载的 `CLAUDE.md` 只放每个会话都需要的规则。每次委派都是一份目标驱动的派发说明：带可验证验收标准的目标、文件范围、已知上下文、约束、一条自检命令，以及有界的返回格式。子智能体从结论起步，不必重新摸索，也不能再派出自己的子智能体。
2. **长程会话。** 主线程保留决策与结论，把探索、审查与实现委派出去，让上下文预算撑得更久。已有上下文能做完的收尾，例如提交、推送、开拉取请求与合并，不论水位都在当前会话做完。上下文窗口渐满时，上下文水位闸门拦下主线程结束这一轮的尝试，让它权衡是否换会话：接下来是新的大块工作时，由 handoff 技能从会话记录与 git 状态整份生成交接文件，主线程提示用户换新会话，新会话从这份交接文件接续。
3. **人只在决策点介入。** 编排手册的设计是只把答案属于用户的问题交给用户。交易、动用资金、删数据这类收不回的动作，可逆的准备照做，只在收不回的那一步之前请用户确认。方向有分叉时，只有各分支做出的东西实质不同、且取舍取决于只有用户知道的偏好或约束，才去问用户；否则按推荐分支做，并在开头一句话说明选了哪支。收尾时的下一步只要在用户当前目标之内、做错了可逆、不对外也不调用付费服务，就直接做完再汇报。用户给出的持续授权只覆盖授权时所指的对象与改动，在本会话内有效，用户改口即撤销。确实要请用户拍板时，每个待定项都写清背景、各选项的后果与推荐。回复以提议下一步的问句收尾时，Stop 钩子 `reply-gate` 拦停一次，并把上述判据写进拦截理由。改动影响用户看得见的产物时，交付前先截图对照受影响的状态，并给出能直接打开的预览链接或一行启动命令；面向他人的文稿交付前，先交给一个不带本轮语境的复核子智能体通读。

## 架构

图里画的是一轮工作怎样运行。会话开始、`/clear` 与压缩之后，SessionStart 钩子把编排手册注入主线程，子智能体收不到，它凭 `CLAUDE.md` 和拿到的派发说明干活，完成后交回有界回报。用户本人键入的消息提到生产模式时，UserPromptSubmit 钩子给主线程注入一句说明，讲怎样设置与查看仓库的生产标记。两条线程的每次工具调用都先经过 PreToolUse。调用属于子智能体内的嵌套派发、`git commit --no-verify`、会打印密钥值的调用、直接改写 `HANDOFF.md`，或 researcher、retriever 子智能体改动、移动、删除已有文件时会被拒绝，拒绝理由回到发起调用的线程，线程换一种做法。researcher 与 retriever 子智能体读文件、跑命令与新建文件都放行。在标成生产的仓库里执行 `gh pr merge`，要等用户当场同意才执行。放行的调用交给工具执行，之后 PostToolUse 在改了规则文件时把规则文件提醒作为附加上下文送回发起调用的线程，在进入新工作树时把主检出目录中的 `CLAUDE.md`、`node_modules` 与 `.env*` 软链进这个工作树，不回话。主线程想结束这一轮时，由两个 Stop 钩子决定这一轮能否结束。回复出口在回复末句是提议问句时拦一次，主线程随后要么直接把提议的那一步做掉，要么在确实需要用户拍板时按背景、各选项的后果与推荐的格式重新提问；设置 `REPLY_LANG=zh` 时（仅 `zh/` 副本的安装启用），较长的回复主要不是中文也会被拦一次，主线程用中文重写。上下文水位闸门在用量过上下文窗口的 35% 时每个会话提醒一次，没有会话暂存目录时则每轮提醒，过 40% 时拦一次。主线程随后把已有上下文能做完的收尾做完，接下来是新的大块工作时用 handoff 技能生成交接文件，并提示用户换新会话。此后以上次拦截时的水位为基准，用量每再涨 5 个百分点，闸门就再拦一次，主线程立即生成交接文件。新会话读这份交接文件接着做。两个闸门都不会拦刚被拦下而续跑的那一轮，所以这一轮再想停就放行；图中橙色箭头标出的，就是控制回到线程的每一条路径。

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../docs/architecture.zh.dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="../docs/architecture.zh.light.svg">
  <img src="../docs/architecture.zh.light.svg" alt="架构图，画的是一轮工作怎样运行。会话开始、/clear 与压缩之后，SessionStart 钩子把编排手册注入主线程，子智能体收不到。用户本人键入的消息提到生产模式时，UserPromptSubmit 钩子给主线程注入一句说明，讲怎样设置与查看仓库的生产标记。主线程向子智能体发出派发说明，子智能体交回有界回报。两条线程的每次工具调用在工具执行之前都经过 PreToolUse：子智能体内的嵌套派发、git commit --no-verify、会打印密钥值的调用、直接改写 HANDOFF.md，以及 researcher 或 retriever 子智能体改动、移动或删除已有文件的操作都被拒绝，researcher 与 retriever 子智能体读文件、跑命令与新建文件都放行；在标成生产的仓库里执行 gh pr merge，要等用户当场同意才执行；拒绝理由回到发起调用的线程，线程换一种做法；放行的调用交给工具执行。工具执行之后，PostToolUse 在改了规则文件时把规则文件提醒作为附加上下文送回发起调用的线程，在进入新工作树时把主检出目录中的 CLAUDE.md、node_modules 与 .env* 软链进这个工作树，不回话。主线程想结束这一轮时经过 Stop 钩子，都放行则这一轮结束。上下文水位闸门过 35% 时每个会话提醒一次并放行，没有会话暂存目录时则每轮提醒，过 40% 拦一次，此后以上次拦截时的水位为基准，每再涨 5 个百分点就再拦一次；回复出口在回复末句是提议问句时拦一次，仅 zh/ 副本的安装里，较长的回复主要不是中文时也拦一次；缓存保活在主线程上下文达到 150,000 词元且没有仍有效的保活时拦一次，主线程随后设一个每 30 分钟一次的重复任务，用户离开期间提示词缓存因此不过期。拦下都回到主线程。被回复出口拦下，主线程要么直接把提议的那一步做掉，要么在确实需要用户拍板时按背景、各选项的后果与推荐的格式重新提问，因语言被拦时用中文重写。被水位闸门第一次拦下，已有上下文能做完的收尾就做完，接下来是新的大块工作时用 handoff 技能生成交接文件，提示用户换新会话；此后每次再被拦都立即生成交接文件。新会话读交接文件接着做。所有 Stop 钩子都不会拦刚被拦下而续跑的那一轮，所以这一轮再想停就放行。">
</picture>

## 测量了什么

下面每项结果都能在仓库根目录用本仓库里的命令复跑。其中静态上下文测量要用你自己的凭据调用 Claude Code，其余几项不调用模型。[docs/zh/evaluation.md](../docs/zh/evaluation.md) 说明每项测量的方法与局限。

同一页还说明四项要大量花钱调用模型的实验各到了哪一步。它们的用例来自放在私有数据目录里的对话记录，所以数字只能从那个目录重算。推理强度对比测子智能体在推理强度 `medium` 与 `high` 下的质量与花费，已经跑完：实现与检索降到 `medium` 测不出损失，词元约为一半，审查判断类没有定论，据此作出的决策记在 [ADR 0008](../docs/zh/adr/0008-subagent-effort-per-kind-of-dispatch.md)。漏拦请示测编排手册里的请示判据能否减少回复出口漏掉的过度请示，跑过之后已搁置，因为得分测不到这条规则。请示判断探针测现行手册能否让模型该问时问、问了也多余时直接做，做过两次试跑后停止，因为回放读到的是运行回放时的文件而不是会话当时的，测不到规则。拦截后跟进测回复出口拦下一条本该请示的回复之后，模型会不会直接去做那一步，已设计、未运行。

| 测量 | 结果 | 复跑 |
|---|---|---|
| 钩子回归测试 | 每个副本 637 个用例全部通过 | `for t in en/hooks/tests/*.test.sh; do bash "$t"; done` |
| 交接脚本测试 | 每个副本 36 个 pytest 用例全部通过 | `python3 -m pytest -p no:cacheprovider en/skills/handoff/scripts`；第三方 pytest 插件加载报错时，在命令前加 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` |
| 钩子变异测试，[eval/hook-mutations](../eval/hook-mutations/README.md) | 往钩子里植入的 54 个缺陷，测试首轮抓住 42 个，为存活的缺陷补上边界用例后抓住 54 个；另有 35 个只照钩子头注释、不看测试写出的留出集缺陷，测试抓住 30 个，这是无偏估计 | `HM_MANIFEST=eval/hook-mutations/holdout.tsv HM_OUT=eval/hook-mutations/holdout-results.md bash eval/hook-mutations/run.sh` |
| 静态上下文，[eval/static-context](../eval/static-context/README.md) | 编排手册经钩子注入时，每个子智能体的首次请求输入是 10,186 词元，写进 `CLAUDE.md` 时是 13,529 词元（en/ 副本，Claude Code 2.1.286） | `bash eval/static-context/run.sh` |
| 回复出口回放，[eval/reply-gate-replay](../eval/reply-gate-replay/README.md) | 在回复出口上线前写成的 2,734 条收尾回复上，它的收尾提议规则精确率 68.5%，召回率 31.7% | `python3 eval/reply-gate-replay/score.py --data "$DATA"`，其中 `DATA` 是存放会话记录与标注的私有目录 |

静态测量比较两组隔离配置：H 组安装本框架，N 组同样安装本框架，但把编排手册写进 `CLAUDE.md`，不经 SessionStart 钩子注入。首次请求输入指线程第一次 API 请求的未缓存输入、缓存写入与缓存读取三项词元之和，只含固定内容，即 Claude Code 自带的系统提示词与工具定义、CLAUDE.md、技能清单、钩子注入的文本，子智能体还包括它收到的派发说明；线程之后读文件、调工具产生的内容都不算。

| 组 | 主线程首次请求输入（词元） | 子智能体首次请求输入（词元） |
|---|---|---|
| H | 20,649 | 10,186 |
| N | 20,638 | 13,529 |

把编排手册留在 `CLAUDE.md` 之外，每个子智能体的首次请求输入就从 N 组的 13,529 词元降到 H 组的 10,186 词元，减少 3,343 词元，约 25%；主线程两组都收到编排手册，首次请求输入只差 11 词元。脚本会重跑子智能体模型或延迟加载工具集不可比的运行，每组两次重复的总数都相同。中文副本 `zh/` 另做了一轮测量（`SC_COPY=zh`）：子智能体首次请求输入从 13,739 词元降到 10,108 词元，减少 3,631 词元，约 26%，每组两次重复的总数都相同；逐次数字见 [results.zh.md](../eval/static-context/results.zh.md)。编排手册控制在 10,000 个字符以内，因为 Claude Code 对更长的 SessionStart 注入只给模型 2KB 预览；任一副本超过这个长度，`scripts/check-parity.sh` 就会失败，结果里的加载核对也确认两组主线程都收到了完整的编排手册。测量安装的是英文副本 `en/`，所用的 Claude Code 版本为 2.1.286，主线程与子智能体都用 claude-opus-5-5。Claude Code 自带的系统提示词与工具定义随版本变化，所以这些绝对数值只对 2.1.286 成立，换版本需用该脚本重测。这些数字还测于加入 handoff 技能、缩短编排手册 §3 之前，描述的是那次改动之前的文件，重跑脚本才能测到现在的文件。逐次数字、加载核对与局限见 [eval/static-context/results.md](../eval/static-context/results.md)。

[docs/zh/evaluation.md](../docs/zh/evaluation.md) 的「[为什么会话日志前后对比不能当证据](../docs/zh/evaluation.md#为什么会话日志前后对比不能当证据)」一节说明我自己的会话日志为何说明不了本框架是否有益，同一文档还说明完整的受控实验需要什么。

## 目录结构

两个语言文件夹的结构相同，都与 `~/.claude/` 一致：

| 路径 | 是什么 |
|---|---|
| `CLAUDE.md` | 加载进每个会话的全局规则：怎样写文稿、怎样改现有代码、怎样测试 |
| `orchestrator-playbook.md` | 主线程作为编排者的规则：委派什么、怎样写子智能体派发说明、怎样交接长任务、交付闸门、git 约定 |
| `hooks/` | 在 `settings.json` 中注册的钩子，均为 `.sh` 脚本；每个钩子都从标准输入读取钩子 JSON |
| `hooks/tests/` | 覆盖全部十三个钩子的回归测试 |
| `agents/` | 三个子智能体的定义，各自在开头的配置字段里设定推理强度：`researcher`（强度 `high`）接需要判断的只读审查、诊断、调研与草拟，`retriever`（强度 `medium`）接只读检索与抽取，`implementer`（强度 `medium`）接设计决定已由派发说明定死的实现。`researcher` 与 `retriever` 只在派发说明给定的路径或系统临时目录下新建文件，不改已有文件。环境变量 `CLAUDE_CODE_EFFORT_LEVEL` 一旦设置，就会盖过这三个定义里的推理强度 |
| `skills/` | 为本框架编写的技能，由 Claude Code 按需加载。`handoff` 技能的辅助脚本及其 pytest 测试放在 `skills/handoff/scripts/` |
| `settings.example.json` | 注册全部钩子的 `hooks` 配置块，路径位于 `$HOME/.claude` 之下 |

## 钩子

| 钩子 | 事件 | 行为 | 测试 |
|---|---|---|---|
| `orchestrator-playbook-session-start.sh` | SessionStart | 把 `orchestrator-playbook.md` 注入主线程。编排手册放在这里而不放进 `CLAUDE.md`，是因为 `CLAUDE.md` 也会加载进每个子智能体，而编排规则只供主线程使用 | `orchestrator-playbook-session-start.test.sh` |
| `block-nested-subagent.sh` | PreToolUse，匹配 `Agent\|Task\|Workflow` | 拒绝子智能体再派出子智能体或工作流。它以 `agent_id` 为判据，该字段只在子智能体内部存在，因此用 `--agent` 启动的会话不会被拦 | `block-nested-subagent.test.sh` |
| `block-no-verify-commit.sh` | PreToolUse，匹配 `Bash` | 拒绝 `git commit --no-verify` 与 `git commit -n`，确保 `commit-msg` 钩子总会运行。它对命令做分词，只检查 `commit` 子命令的选项，因此 `[ -n "$C" ]` 或提交信息里的 `-n` 都会放行 | `block-no-verify-commit.test.sh` |
| `context-watermark-gate.sh` | Stop | 从会话记录读取末条助手消息的上下文用量。用量过上下文窗口的 35% 时每个会话提醒一次并放行，没有会话暂存目录时则每轮提醒。过 40% 时拦一次，没有会话暂存目录时每轮都拦，主线程把已有上下文能做完的收尾做完，接下来是新的大块工作时用 handoff 技能生成交接文件并提示换新会话。此后比上次拦截时的水位每再涨 5 个百分点就再拦一次，要求立即生成交接文件。两条拦截理由末尾都附会话记录路径，供 handoff 技能的抽取一步读取。标记记在会话暂存目录里，用量回落到 35% 以下（例如压缩之后）时清掉。在子智能体内部以及遇到格式错误的输入时放行 | `context-watermark-gate.test.sh` |
| `rule-file-edit-check.sh` | PostToolUse，匹配 `Edit\|Write` | 当被编辑的路径是大语言模型规则文件时，注入一条提醒，要求遵循 `rule-file-editing` 技能。触发是确定性的，不依赖技能自动加载 | `rule-file-edit-check.test.sh` |
| `worktree-symlink-claudemd.sh` | PostToolUse，匹配 `EnterWorktree` | 把主检出目录中的 `CLAUDE.md`、`node_modules` 与 `.env*` 以符号链接接入新建的 git 工作树，不覆盖已有的真实文件 | `worktree-symlink-claudemd.test.sh` |
| `reply-gate.sh` | Stop | 回复的末句是「要我…吗」「Shall I …?」这类提议下一步的问句时拦停一次，拦截理由重申何时直接做、何时以及怎样请用户拍板。设置 `REPLY_LANG=zh` 时（`zh/` 的配置已设置），超过 150 个字符的回复里中日韩字符不到中日韩字符与拉丁字母总数的五分之一，也拦停一次。两项检查都先剥掉围栏代码块、行内代码与 URL；`stop_hook_active` 为真时放行，因此不会循环拦截 | `reply-gate.test.sh` |
| `keepalive-gate.sh` | Stop | 主线程上下文达到 150,000 词元、且会话记录里没有仍有效的保活时拦停，让模型用 CronCreate 设一个保活：每 30 分钟一次的重复任务，触发分钟由钩子算好并避开 0 与 30，提示词以 `[保活]` 开头，只要求回一个句点，用户离开期间提示词缓存因此不过期。保活仍有效，是指它的 CronCreate 成功返回且之后没有 CronDelete 指向它的编号。保活的提示词让它在对话里找不到设定记录时（例如已 `/clear`）删掉自己；距用户本人最后一条消息满 8 小时后，钩子拦下保活那一轮，让它被删掉；子智能体回报、别的会话发来的消息与后台通知都不算用户本人的消息。订阅额度用尽、改由用量额度付费后，Claude Code 会把主对话的缓存降为 5 分钟有效期，这时 30 分钟一次的保活续不上缓存，还花付费额度，所以钩子不再设保活，已有仍有效的保活则拦停让模型删掉。有效期取主线程最近一次写入缓存的调用里的 `usage.cache_creation`，只有 `ephemeral_5m_input_tokens` 大于 0 时算 5 分钟，没有调用写入过缓存时按一小时处理。间隔以一小时的缓存为前提，见 [ADR 0013](../docs/zh/adr/0013-sessions-past-150k-keep-their-prompt-cache-warm.md)。在子智能体内部、`stop_hook_active` 为真时以及遇到格式错误的输入时放行 | `keepalive-gate.test.sh` |
| `secret-guard.sh` | PreToolUse，匹配 `Bash\|Read` | 拒绝会把密钥值打印进模型上下文的调用。Read 的目标文件名是 `.env` 或 `.env.*` 就拒绝，文件名按小写比较，`.example`、`.sample` 与 `.template` 样例放行。shell 命令按 `&&`、`\|\|`、`;`、`\|` 与换行拆成子命令逐段判断，命令替换也拆出来，交给 `bash -c`、`sh -c`、`zsh -c` 或 `eval` 的命令串同样逐段判断，最多嵌套三层。以下情形拒绝：用 `cat`、`head`、`tail`、`less`、`awk`、非就地的 `sed`、`sort`、`diff`、`base64`、`xxd` 这类打印文件内容的命令读 `.env`；用 `grep` 或 `rg` 读 `.env` 却不带只报计数、只报是否命中或只报文件名的选项；递归的 `grep`，或会搜点文件的 `rg`，搜索的目录树里有 `.env`，且没有被它的包含、排除或通配选项排掉；用 `echo` 或 `printf` 展开名称含 KEY、SECRET、TOKEN、PASSWORD、PASSWD 或 CREDENTIAL 的变量，其中 `${#VAR}` 只给长度，放行；不带参数或参数名含上述片段的 `printenv`；单独使用的 `env`、`export -p` 或 `set`。相对的搜索根跟随同一条命令里前面的 `cd` 或 `pushd`，`cd` 的目标不是字面量时按含 `.env` 算。遍历目录树时跳过 `.git` 与 `node_modules`，超过 20,000 项就放行。只用到值而不打印值的命令放行，例如 `source .env` 后接命令，拒绝理由里也给出这类替代写法 | `secret-guard.test.sh` |
| `subagent-readonly-guard.sh` | PreToolUse，匹配 `Edit\|Write\|NotebookEdit\|MultiEdit\|Bash` | 在 `researcher` 与 `retriever` 子智能体内部放行新建文件，拒绝改动已有文件。所有 Edit、MultiEdit 与 NotebookEdit 都拒绝，Write 只在目标已存在时拒绝。shell 命令的拆分与展开方式和密钥守卫相同，以下情形拒绝：`sed -i` 或 `perl -i`；重定向或 `tee` 写到已存在的文件（`/dev/null` 与新路径放行）；`rm`、`mv`、`truncate`、`chmod` 或 `ln -f`；`cp` 的目标已存在；改动工作区、暂存区、引用或远端的 git 子命令，以及 `git branch -d` 或 `-D`；内联解释器代码里有写入、改名或删除文件的调用，不论目标是否已存在。内联代码指 `python -c`、`node -e` 或 `-p`、`perl -e` 与 `ruby -e` 的参数，`<<<` 后的字符串，以及以 `<<` 内嵌文档形式喂给这几个解释器的正文；执行脚本文件的调用，例如 `python3 script.py`，看不到代码，不在判断范围内。相对路径跟随同一条命令里前面的 `cd` 或 `pushd`，`cd` 的目标不是字面量时，之后的相对写入目标一律按已存在算。它同时以 `agent_id` 与 `agent_type` 为判据，因此用 `--agent researcher` 或 `--agent retriever` 启动的会话不受限制 | `subagent-readonly-guard.test.sh` |
| `handoff-guard.sh` | PreToolUse，匹配 `Edit\|Write\|NotebookEdit\|MultiEdit\|Bash` | 拒绝直接改写文件名恰为 `HANDOFF.md` 的文件，主线程与子智能体一律适用，让交接文件只出自 handoff 技能。以它为目标的编辑或写入被拒绝；shell 命令重定向或 `tee` 写到它、用 `sed -i`、`perl -i` 或 `awk -i inplace` 就地改它、用 `ed` 或 `ex` 打开它、截断它、以它为 `cp`、`mv`、`rm` 或 `ln` 的源或目标、让 `git checkout`、`restore`、`rm` 或 `mv` 指向它，或在内联解释器代码里提到它，也被拒绝；命令的拆分与展开方式和密钥守卫相同。读它、写 `HANDOFF.new.md` 与运行技能的 `finalize.sh` 都放行。它防的是顺手的补丁动作，防不住刻意的绕过，例如用脚本文件去写交接 | `handoff-guard.test.sh` |
| `production-merge-gate.sh` | PreToolUse，匹配 `Bash` | 命令里有 `gh pr merge`、且目标仓库设了 `git config claude.production true` 时返回 `ask`，由 Claude Code 请用户当场同意这次合并。目标仓库取命令开头 `cd` 进入的目录，没有就取钩子输入的工作目录；`-R`/`--repo`、`GH_REPO=` 前缀或 PR 网址指向该目录远端以外的仓库时，读不到那个仓库的标记，按生产仓库处理。标记放在 git config 而不是仓库文件里，所以不进任何会话的上下文，且对同一仓库的所有工作树都成立 | `production-merge-gate.test.sh` |
| `production-mode-hint.sh` | UserPromptSubmit | 用户本人键入的消息提到「生产模式」或 production mode（不分大小写）时，注入一句说明，讲怎样设置与取消生产标记。子智能体的回报与后台通知也经 UserPromptSubmit 进来，一律跳过 | `production-mode-hint.test.sh` |

## 技能

| 技能 | 用途 |
|---|---|
| `rule-file-editing` | 编辑 `CLAUDE.md`、`SKILL.md` 等指令文件时的纪律：按改动如何改变运行时行为来裁决每处改动，把例外写成分支，并把删除以及新建的规则文件交给独立复核者 |
| `memory-audit` | 裁定哪些 Claude Code 记忆条目保留、合并或删除，并重建索引 |
| `handoff` | 整份生成 `HANDOFF.md`：`scripts/extract.py` 从会话记录抽出用户给过的每一条输入与 git 状态，一个不带本会话语境的 `researcher` 写出草稿，主线程审阅，未完成项不对时让同一个 `researcher` 重写，`scripts/finalize.sh` 把它落位并归档旧版。第 0 步在只剩收尾时不生成交接；有问题等用户拍板时设一个 50 分钟后的一次性唤醒，到时还没答复就生成交接。50 分钟的前提是会话的提示词缓存一小时后过期（2026 年 10 月 Claude Code 的情况），这样交接趁缓存还热时写完；缓存时长不同时，把第 0 步里的 50 分钟改成该时长减 10 分钟；缓存不超过 10 分钟时，第 0 步不设唤醒，直接生成交接 |

## 两个值得细看的机制

**编排手册只进主线程，而且完整送达。** SessionStart 钩子在会话开始、`/clear` 与压缩之后注入编排手册，不把它放进每个子智能体也会加载的 `CLAUDE.md`。静态测量里，这让每个子智能体的首次请求输入在英文副本中从 13,529 词元降到 10,186 词元，约 25%，在中文副本中从 13,739 词元降到 10,108 词元，约 26%。Claude Code 对超过 10,000 个字符的 SessionStart 注入只给模型 2KB 预览，所以任一副本的编排手册超过这个长度，`scripts/check-parity.sh` 就会失败。测量中的加载核对在送进模型的附件里找编排手册的最后一个标题，被截成预览的手册不会有这个标题，而每次运行的主线程都收到了完整的编排手册。

**Stop 闸门把控制交回主线程。** 回复以提议下一步的问句收尾时，回复出口把它拦下，拦截理由重申何时直接做、何时以及怎样请用户拍板，主线程接着要么直接把那一步做掉，要么在确实需要用户拍板时按背景、各选项的后果与推荐的格式重新提问。在回复出口上线前写成的 2,734 条收尾回复上离线回放，以「本该直接做」的标注为比对基准，标注由单一智能体完成，它知道回复出口的短语表但看不到它的输出，它的收尾提议规则精确率 68.5%（威尔逊 95% 区间 59.3% 至 76.4%），召回率 31.7%（14.5% 至 55.8%）。Stop 钩子的输入不含词元字段，所以上下文水位闸门从会话记录中读取真实用量。用量过上下文窗口的 40% 时，它拦一次，让主线程在换新会话与更长的上下文之间权衡：已有上下文能做完的收尾就做完，只有接下来是新的大块工作时才用 handoff 技能生成交接文件，交接结构里有一段给用户的接续说明，写清停在哪、下一步要用户做什么。两个闸门拦下时都附上理由，且都不会拦刚被拦下而续跑的那一轮，因为 `stop_hook_active` 为真时它们都放行，所以不会循环拦截。窗口大小默认 1,000,000 词元，不按所用模型自动识别；它与水位闸门的三个阈值，即 35%、40% 与每次再拦之前要再涨的 5 个百分点，都可以通过 `CONTEXT_WINDOW_TOKENS`、`CONTEXT_WARN_PCT`、`CONTEXT_HARD_PCT` 与 `CONTEXT_REBLOCK_DELTA_PCT` 覆盖。

## 安装

把本仓库克隆到本地，在仓库目录里启动 Claude Code，让 Claude 来完成安装，例如直接粘贴这句请求：

```text
请把本仓库的 zh/ 副本安装到 ~/.claude，按 zh/README.md 里「安装」一节的说明操作。
```

要装英文版就把请求里的 `zh/` 换成 `en/`。下面的步骤是写给执行安装的那个 Claude 会话的，它按顺序照做：

1. 检查 `bash`、`python3`、`jq` 与 `git` 是否都在 `PATH` 上，缺哪一个就在复制任何文件之前告诉用户。钩子靠 `python3` 与 `jq` 解析输入，缺少 `python3` 时，做拒绝、拦截或注入的钩子得不出任何判定就退出，于是每一次调用都未经检查地通过，而且没有任何提示。
2. 从用户指定的副本取源文件，即 `en/` 或 `zh/`；请求里两者都没提时先问用户。
3. 覆盖 `~/.claude/` 下任何已有文件之前（包括 `settings.json`），先把它复制到一个备份位置，并告诉用户备份放在哪里。
4. 把 `hooks/*.sh` 复制到 `~/.claude/hooks/`，不复制 `hooks/tests/`；把 `skills/` 下的每个目录复制到 `~/.claude/skills/`，不复制测试文件 `skills/*/scripts/test_*.py`；把 `agents/*.md` 复制到 `~/.claude/agents/`；把 `orchestrator-playbook.md` 复制到 `~/.claude/`。编排手册必须位于 `hooks/` 的直接上级目录，因为 SessionStart 钩子相对自身位置来定位它。
5. 把 `settings.example.json` 的 `hooks` 配置块合并进 `~/.claude/settings.json`，该文件不存在时就新建。其余键与已有的钩子条目全部保留，同一事件下命令已经注册过的钩子不重复添加。
6. 只有用户明确要求时才安装 `CLAUDE.md`。`~/.claude/CLAUDE.md` 已经存在时，改动之前先问用户是覆盖还是把两份合并。
7. 告诉用户启动一个新的 Claude Code 会话，因为钩子与技能只在安装之后启动的会话里生效。

编排手册与 `CLAUDE.md` 还会路由到 `grilling`、`write-pr`、`prose-discipline`、`tdd-watch-it-fail` 与 `debug-root-cause`。这些技能没有收录在这里，原因要么是它们来自第三方或主要基于第三方材料构建，要么是它们只适合我自己的环境；请安装你自己的等价技能，或删掉这些路由。主线程何时合并自己开的拉取请求，这条规则不依赖 `write-pr`，编排手册 §1 已经写全。想让某个仓库里的每次 `gh pr merge` 都等你同意，就在该仓库里运行 `git config claude.production true`，把它标成生产仓库；`git config --unset claude.production` 取消标记。

## 测试

在 `en/` 或 `zh/` 目录下运行钩子测试：

```bash
for t in hooks/tests/*.test.sh; do bash "$t"; done
```

每个钩子测试都会打印 `PASS=<n> FAIL=<n>`，任何一项失败都以非零状态退出。十三个测试在每个副本里共有 637 个用例。handoff 技能的脚本带 pytest 测试，每个副本 36 个用例，在 `en/` 或 `zh/` 目录下这样运行：

```bash
python3 -m pytest -p no:cacheprovider skills/handoff/scripts
```

第三方 pytest 插件加载报错时，在命令前加 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`。

两份副本里的测试模块同名，所以每份副本各用一个 pytest 进程运行。在仓库根目录下，核对 `en/` 与 `zh/` 两份副本一致的检查这样运行：

```bash
bash scripts/check-parity.sh
```

持续集成在每次推送与拉取请求时运行。它在 Ubuntu 与 macOS 上运行两份副本的钩子测试，每份 637 个用例，用 pytest 运行两份副本的技能脚本测试，用 shellcheck 检查钩子、钩子测试、技能的 shell 脚本与仓库脚本，并运行中英文副本的一致性检查。推送前想在本机一次跑完这四项检查，可以在仓库根目录下运行下面的命令。它需要装有 pytest 的 `python3`，以及 `jq`、`git` 与 shellcheck，都在 `PATH` 上，并且只覆盖你本机的操作系统和用来运行它的那个 bash；在 Mac 上用 `/bin/bash scripts/ci-local.sh` 运行，就和持续集成用的 bash 3.2 一致。一致性检查只看已纳入 git 跟踪的文件，新建的文件先 `git add` 再运行：

```bash
bash scripts/ci-local.sh
```

## 文档

| 文档 | 主题 |
|---|---|
| [ADR 0001：编排规则只送达主线程](../docs/zh/adr/0001-orchestration-rules-reach-only-the-main-thread.md) | 编排手册加载到哪里 |
| [ADR 0002：每份子智能体派发说明都写全六要素](../docs/zh/adr/0002-every-subagent-brief-carries-six-elements.md) | 一次委派必须包含什么 |
| [ADR 0003：子智能体不能再派子智能体](../docs/zh/adr/0003-subagents-cannot-spawn-subagents.md) | 谁可以派发工作 |
| [ADR 0004：上下文水位从会话记录的用量读取，并以交接文件为停止闸门](../docs/zh/adr/0004-context-watermark-read-from-transcript-usage.md) | 上下文水位怎样测量 |
| [ADR 0005：会拒绝、拦截或注入规则的钩子都带回归测试](../docs/zh/adr/0005-deciding-hooks-ship-with-regression-tests.md) | 哪些钩子要带测试 |
| [ADR 0006：只在答案属于用户时才问用户](../docs/zh/adr/0006-ask-the-user-only-where-the-answer-is-theirs.md) | 智能体何时提问、何时直接做 |
| [ADR 0007：交接时机在换会话与长上下文两头的代价之间权衡](../docs/zh/adr/0007-handoff-timing-weighs-switch-against-long-context.md) | 长会话何时交接 |
| [ADR 0008：子智能体的推理强度按派发种类设定](../docs/zh/adr/0008-subagent-effort-per-kind-of-dispatch.md) | 每类派发跑在什么推理强度 |
| [ADR 0009：只读子智能体只在派发说明指定处写文件，retriever 把判断留给主线程](../docs/zh/adr/0009-read-only-subagents-write-where-the-brief-points.md) | 只读子智能体能在哪里建文件，判断由谁来下 |
| [ADR 0010：交接文件由 handoff 技能整份生成，钩子禁止手改](../docs/zh/adr/0010-handoffs-are-generated-whole-by-the-handoff-skill.md) | 交接文件怎样生成，为什么从不打补丁 |
| [ADR 0011：收尾不论水位都在当前会话做完，待用户拍板的问题在缓存过期前设唤醒](../docs/zh/adr/0011-wrap-up-finishes-in-session-at-any-watermark.md) | 会话何时不交接，等用户时又何时交接 |
| [ADR 0012：非生产仓库里合并本任务开的拉取请求属于可撤回，生产仓库由钩子先问用户](../docs/zh/adr/0012-merging-own-pr-is-undoable-outside-production.md) | 主线程何时合并自己开的拉取请求 |
| [ADR 0013：上下文过 150k 的会话用 30 分钟心跳保住缓存](../docs/zh/adr/0013-sessions-past-150k-keep-their-prompt-cache-warm.md) | 会话何时设保活，保活又怎样结束 |
| [评测：方法与局限](../docs/zh/evaluation.md) | 本框架主张什么、不主张什么，以及受控实验要花多少 |
| [静态上下文测量](../eval/static-context/README.md) | 怎样运行这项测量，每组配置安装了什么 |
| [钩子变异测试](../eval/hook-mutations/README.md) | 怎样用植入的缺陷衡量钩子测试，以及留出集 |
| [回复出口回放](../eval/reply-gate-replay/README.md) | 怎样在历史会话上回放回复出口，并与盲标比对打分 |

## 许可证

MIT。见 `LICENSE`。

## 数据来源

| 数字 | 来源 |
|---|---|
| 提示词元的计法（输入、缓存写入与缓存读取三项相加） | Anthropic 提示词缓存文档，https://platform.claude.com/docs/en/build-with-claude/prompt-caching |
