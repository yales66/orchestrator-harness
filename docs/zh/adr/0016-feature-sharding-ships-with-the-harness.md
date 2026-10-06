# ADR 0016：feature-sharding 随仓库发布

## 状态

已采纳，自 2026 年 10 月 6 日起生效。

## 背景

编排手册 §1 里「多模块改造、从零建项目、并行意图」那一行，原先把这类工作路由到 `feature-sharding`，而仓库并不发布这个技能。563cfd9 把两份手册的这一行改成由主线程规划、按 §2 并行派，一个会话装不下时拆成阶段、阶段之间按 §3 交接；9bbeb5b 在 rules-missed-asks 实验的两份手册臂里做了同样的改动。

阶段交接只是把一个会话的状态依次带到下一个会话。它不测量工作是否装得进主线程预算，不按体量分箱，也不沿接缝把工作拆成可由独立会话并行跑的轨道。超出主线程预算的多模块工作因此既没有预算测量与分箱，也没有多会话的会话包。

## 决策

两份副本都发布 `skills/feature-sharding/`：`SKILL.md`、`calibration.md`，以及 `scripts/peak_context.py` 和它的 pytest 测试 `scripts/test_peak_context.py`。

§1 那一行改为：接缝与预算一眼可见、装进主线程余量时，主线程规划、按 §2 并行派；其余交给 `feature-sharding`。

技能在阶段 0 按预算、按是否需要用户中途裁决来路由，不按模块数或任务条数。读集与简报装得进主线程余量的工作退出技能、直接做。编排预算超载、某轨道需要用户中途裁决、或工作集强串行的，走分片模式。都不中但有多个互不依赖的变更时，走波次模式。直接做之外的情形，技能先写变更说明 `docs/changes/<change-id>/BRIEF.md`，作为各轨道共享决策的唯一出处。

阶段 1 剔除代码库已实现的需求，派只读子智能体列出共享文件、共享读集、隐式契约与需要同时知道两边才能写的测试，派 spike 消掉已知未知，并要求每个未知都消掉、封进单一轨道或用 golden fixture 钉死在接缝上，才能进阶段 2。阶段 2 按（启动成本 + 读集成本）× 迭代乘数把每个模块分进 S、M、L 箱。阶段 3 把 S 箱轨道在当前会话里按波次派给子智能体，把 M 箱轨道和需要用户裁决的轨道交给用户凭会话包（`HANDOFF-<轨道>.md`、`MERGE-PLAN.md` 与启动清单）拉起的独立会话，契约设计、合并裁决与跨轨道取舍留在主线程。

全部预算常数、分箱阈值与乘数都在 `calibration.md` 里，各自注明依据的日期与模型。`peak_context.py` 报出每份会话记录的峰值上下文，即单条助手消息的输入、缓存读、缓存写三项词元之和的最大值，供每个分片功能完工后回填常数。

## 后果

装不进主线程余量的工作先测量、沿接缝拆分再派发，不再在一条会话链上按阶段依次做。能并行的轨道有冻结的契约、端到端最小竖切与合并顺序，独立会话从自足的会话包开工。

技能会在用户仓库里写 `docs/changes/<change-id>/`：变更说明，以及波次模式下的 `PLAN.md` 或分片模式下的会话包。独立会话由用户亲手拉起；技能会告诉用户，分片换来的是上下文质量与墙上时钟，不省账号额度。

`calibration.md` 里的常数是初始估计，大多来自 2026 年 7 月 16 日一个项目里的一个功能，当时未记录模型，文件把这类条目标为待重测。

`HANDOFF-<轨道>.md` 不是 `HANDOFF.md`：`handoff-guard.sh` 不拦对它的写入，handoff 技能与 ADR 0010 也不管它。

CI 的 pytest 任务与 `scripts/ci-local.sh` 本来就跑每个带 `test_*.py` 的 `skills/*/scripts/` 目录，新测试无需改动就会被跑到。`scripts/check-parity.sh` 要求 `skills/*/scripts/` 下的文件在两份副本中逐字节相同，所以英文副本里的脚本带着中文注释，与 handoff 技能一样。

## 出处

| 出处 | 支撑的内容 |
|---|---|
| `zh/skills/feature-sharding/SKILL.md` | 阶段 0 路由、变更说明、阶段 1 至 3、会话包、合流协议、启动清单与校准回填 |
| `zh/skills/feature-sharding/calibration.md` | 预算常数、分箱上限与乘数及其日期，以及未记录模型的条目视为待重测 |
| `zh/skills/feature-sharding/scripts/peak_context.py` 与 `scripts/test_peak_context.py` | 峰值上下文的算法及其测试 |
| `zh/orchestrator-playbook.md` §1「多模块改造」那一行 | 何时主线程自己规划派发、何时交给 `feature-sharding` |
| 提交 563cfd9 | 两份手册里用阶段加 §3 交接取代 `feature-sharding` 的路由 |
| 提交 9bbeb5b | rules-missed-asks 实验两份手册臂里的同样改动 |
| `zh/hooks/handoff-guard.sh` 头部注释 | 只拦文件名恰为 `HANDOFF.md` 的写入，`HANDOFF-<轨道>.md` 不受限 |
| `.github/workflows/ci.yml` 的 `pytest` 任务与 `scripts/ci-local.sh` | 两份副本里每个带 `test_*.py` 的 `skills/*/scripts/` 目录都会被测试 |
| `scripts/check-parity.sh` 头部注释第 2 条 | 技能脚本在两份副本中必须逐字节相同 |
