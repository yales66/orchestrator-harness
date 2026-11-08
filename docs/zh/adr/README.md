# 架构决策记录

| 决策 | 主题 |
|---|---|
| [ADR 0001：编排规则只送达主线程](0001-orchestration-rules-reach-only-the-main-thread.md) | 编排手册加载到哪里；送达方式已由 ADR 0024 修订 |
| [ADR 0002：每份子智能体派发说明都写全六要素](0002-every-subagent-brief-carries-six-elements.md) | 一次委派必须包含什么，只读派发用其中四项 |
| [ADR 0003：子智能体不能再派子智能体](0003-subagents-cannot-spawn-subagents.md) | 谁可以派发工作；已由 ADR 0025 修订，子智能体可以再派一层 haiku 工人 |
| [ADR 0004：上下文水位从会话记录的用量读取，并以交接文件为停止闸门](0004-context-watermark-read-from-transcript-usage.md) | 上下文水位怎样测量；交接时机已被 ADR 0007 取代，交接格式已被 ADR 0010 取代 |
| [ADR 0005：会拒绝、拦截或注入规则的钩子都带回归测试](0005-deciding-hooks-ship-with-regression-tests.md) | 哪些钩子要带测试 |
| [ADR 0006：只在答案属于用户时才问用户](0006-ask-the-user-only-where-the-answer-is-theirs.md) | 智能体何时提问、何时直接做；与 ADR 0027 冲突处已由它修订 |
| [ADR 0007：交接时机在换会话与长上下文两头的代价之间权衡](0007-handoff-timing-weighs-switch-against-long-context.md) | 长会话何时交接；提醒内容已被 ADR 0018 取代 |
| [ADR 0008：子智能体的推理强度按派发种类设定](0008-subagent-effort-per-kind-of-dispatch.md) | 每类派发跑在什么推理强度 |
| [ADR 0009：只读子智能体只在派发说明指定处写文件，retriever 把判断留给主线程](0009-read-only-subagents-write-where-the-brief-points.md) | 只读子智能体能在哪里建文件，判断由谁来下 |
| [ADR 0010：交接文件由 handoff 技能整份生成，钩子禁止手改](0010-handoffs-are-generated-whole-by-the-handoff-skill.md) | 交接文件怎样生成，为什么从不打补丁；由谁来写已由 ADR 0026 修订 |
| [ADR 0011：收尾不论水位都在当前会话做完，待用户拍板的问题在缓存过期前设唤醒](0011-wrap-up-finishes-in-session-at-any-watermark.md) | 会话何时不交接，等用户时又何时交接 |
| [ADR 0012：非生产仓库里合并本任务开的拉取请求属于可撤回，生产仓库由钩子先问用户](0012-merging-own-pr-is-undoable-outside-production.md) | 主线程何时合并自己开的拉取请求 |
| [ADR 0013：上下文过 150k 的会话用 30 分钟心跳保住缓存](0013-sessions-past-150k-keep-their-prompt-cache-warm.md) | 已被 ADR 0014 取代。会话何时设保活，保活又怎样结束 |
| [ADR 0014：上下文过 150k 的空闲会话在 50 分钟后由异步唤醒保住缓存](0014-idle-sessions-past-150k-keep-their-prompt-cache-warm-with-an-async-rewake.md) | 空闲会话何时被唤醒以保住缓存，以及为什么它取代了 ADR 0013 的 30 分钟心跳；已由 ADR 0029 扩展 |
| [ADR 0015：保活在自己的唤醒之后照常计时，-p 无头会话不计时](0015-keepalive-keeps-timing-after-its-own-wake-up-and-skips-headless-sessions.md) | 保活为什么不看 `stop_hook_active`、不在 `-p` 运行里计时，并在没有拒用 `AskUserQuestion` 的安装里把选择题的作答算作用户本人的消息；已由 ADR 0029 扩展 |
| [ADR 0016：feature-sharding 随仓库发布](0016-feature-sharding-ships-with-the-harness.md) | 为什么随框架发布 `feature-sharding`，编排手册何时把多模块工作交给它；轨道怎样拉起已由 ADR 0028 修订 |
| [ADR 0017：拍板改为文字提问，AskUserQuestion 被拒用](0017-decisions-are-asked-in-text-and-askuserquestion-is-denied.md) | 怎样请用户拍板，以及为什么拒用选择题工具；与 ADR 0027 冲突处已由它修订 |
| [ADR 0018：水位提醒不再拦着新工作](0018-the-watermark-reminder-does-not-hold-back-new-work.md) | 提醒线与硬线之间为什么照常开工 |
| [ADR 0019：保活唤醒前先探测网络，最后一次唤醒在还有工作时写交接](0019-keepalive-probes-the-network-before-waking-and-hands-off-at-its-last-wake-up.md) | 网络一直不通时保活为什么在一轮结束后 57 分钟放弃，最后一次唤醒何时写交接；已由 ADR 0029 扩展 |
| [ADR 0020：5 小时用量到 95% 时挂起工具调用，每 50 分钟保活一次](0020-tool-calls-are-held-at-95-percent-of-the-five-hour-limit.md) | 工具调用怎样等到用量重置，用量从哪里读，谁的调用放行 |
| [ADR 0021：改动对错全由既有测试或写定的验收用例判定时，`implementer` 派到 Haiku](0021-implementer-runs-on-haiku-when-tests-decide-every-change.md) | 改动行为的对错全部由已有测试或派发说明里的验收用例判定时，`implementer` 为什么派到 Haiku 5.5 的 `medium`，`retriever` 为什么按胜任规则留在 Opus（`implementer` 两行已由 ADR 0023 修订，`retriever` 一行已由 ADR 0022 修订） |
| [ADR 0022：派发说明把查找限定在本地文件或点名的单个网页时，`retriever` 派到 Haiku](0022-retriever-runs-on-haiku-when-the-brief-limits-it-to-local-files-or-one-named-page.md) | 限定在本地文件、会话记录或点名单个网页的查找为什么在未满足胜任规则时派到 Haiku 5.5，其余查找为什么留在 Opus |
| [ADR 0023：改动对错由测试判定时，`implementer` 派到 Haiku，子智能体自写的测试也算](0023-implementer-runs-on-haiku-when-tests-decide-including-its-own.md) | 由测试判定对错的实现为什么即使测试由子智能体自写也派到 Haiku 5.5，有任何一处只能靠看或读来判定的实现为什么留在 Opus，以及主线程为什么要核对 haiku 那次运行的文件范围 |
| [ADR 0024：编排手册分段注入，每段都在单个钩子的上限之内](0024-the-playbook-is-injected-in-parts-under-the-per-hook-limit.md) | 编排手册钩子为什么按段各注册一次，怎样切段、怎样让各段按序送达，一致性检查核对什么 |
| [ADR 0025：子智能体可以再派一层 haiku 工人](0025-subagents-may-dispatch-one-layer-of-haiku-workers.md) | 子智能体能把哪些短活交给 haiku 工人，上下文上限是多少，钩子与派发深度怎样把它限制在一层 |
| [ADR 0026：交接由主线程自己写，接力会话由会话自己拉起](0026-the-main-thread-writes-the-handoff-itself.md) | 为什么交接不再由子智能体起草或审阅，写完之后会话怎样接力 |
| [ADR 0027：分叉先判类型再决定问不问，无人值守的会话持续推进](0027-forks-are-classed-before-asking-and-unattended-sessions-keep-working.md) | 三类分叉及其中哪些交给用户，结束一轮的常设约定，以及任务清单闸门 |
| [ADR 0028：分片轨道以后台会话运行，由规划会话统筹](0028-sharding-tracks-run-as-background-sessions-under-the-planning-session.md) | feature-sharding 为什么用 `claude --bg` 拉起轨道，并让规划会话当它们的父会话 |
| [ADR 0029：任务已完成或已交接的会话停止保活，有在跑轨道的分片父会话保持保活](0029-the-keepalive-stops-for-finished-or-handed-off-sessions-and-stays-on-for-sharding-parents.md) | 唤醒何时回停止词（中文安装回「完」，英文安装回 `Done`），分片父会话为什么在 150k 以下也保活，SessionEnd 标记与最后一次唤醒的几个分支各做什么；扩展 ADR 0014、0015 与 0019 |
