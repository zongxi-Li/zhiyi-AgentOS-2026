# PR-S01-04：Adaptive Horizon Proposal

状态：实现完成，独立代码级验收为 CONDITIONAL；S01-04 保持未提交。条件及最新证据见文末独立验收补充。不 Push、不部署，不升级数据库，不修改正式 ADR。

## 基线

S01-03 已按独立 ACCEPT 报告核对完整变更及源码 SHA-256，保留五类 P1 修复，提交前重新运行 HTN/对抗/ReAct/网关测试：105 passed，61.20s。

本地提交：`ce1d67d117f678f211409fb4f47dee80fc24d37b`，`feat(agentos-planner): 实现 HTN 方法选择与分层展开提案`。提交后工作区为空，未 Push。

## 合同与算法

- 新增冻结且 `extra=forbid` 的 `PlanningFrontier`、`HorizonProposal`、`HorizonSelection`，schemaVersion=1，algorithmVersion=`adaptive-horizon.v1`。复用 `TaskPlanRelation`，不复制 TaskPlan。Proposal 表达候选、实际前置已完成的 readyKeys、延迟任务及原因、内部与跨窗口依赖、资源观察、任务内容指纹及预算；绑定 Mission、Frozen Basis 指纹、Observation、PlanVersion、Run 状态、策略/能力目录 revision 和完整输入指纹。
- 只读取正式 TaskPlan；原约束、来源、验收及能力字段保持原样，全部包含在 Plan/任务指纹中。使用 Run 的冻结 Basis，当前 Mission 编辑不会漂移旧 Run。
- 先调用既有 `validate_task_plan_for_execution` / `TaskPlanTopologyCompiler`，使用其已验证的依赖（含能力与终端规则推导的边），再做候选集合运算。Frontier 及 Proposal 的集合、分区、预算、依赖边界校验不承担 DAG 编译、修复或 GraphVersion 提交。
- 状态分为 completed、active、considerable、dependency_blocked、review_wait、failed、terminal、unknown、resource_wait、control_wait。完成前置要求可信观察提供 commit/audit 引用及 allow 或已解除审核阻塞的 review 结果；未知证据、部分/失败验证不会被当作已满足前置。已完成、执行中、重试、失败、取消及条件跳过节点均不重新列为候选。整个 Run 等待审核、completionBlockers 或循环控制分别保留审核/控制屏障。
- 可选任务先按风险升序、直接后继数降序、成本升序、稳定 Key 排序；每次加入节点后重新考虑前置已完成或已入选的后继。未来工作可在候选窗口内，但 readyKeys 只包含真实前置已完成的工作。未完成且不在窗口的前置不能被删掉以让消费者入选；所有原依赖均保留在 Frontier，全部跨窗口边另行列出。
- 风险取任务声明与可信能力目录风险的最大值（normal/elevated/high/critical=1/2/4/8）；成本取至少 1、能力数量与 Workset 已声明估算单元数的最大值。默认成本预算12、风险预算8、候选上限16；高风险任务隔离，审核型任务之后截断窗口。均为规划估算单位，不是费用报价、执行资源配额或资源预留。
- 反例：成本预算1时，独立 A/B/C 选择 A；加入 B→C 后选择 B；改任务排列仍选择 B。相同三个任务由低风险改为高风险，窗口由3个缩至1个；A 成本20时跳过 A，选择 B/C。不是固定节点数或前缀切片。
- 原输入上限256节点、1024声明关系、300k字符；编译后最多4096依赖。无新增递归展开；候选打包预计算后继数，最坏约 O(VE + V²(D + log V))，D 为最大入度，受上述输入及截止期约束。共享 Compiler 的内部工作受输入规模及返回后截止检查约束，未增加强制线程中断。

## 工具与权威隔离

`AGENTOS_PLANNER_ADAPTIVE_HORIZON` 默认关闭；只有 ReAct 同时启用且存在 LLM 装配时挂接。HTN Flag 独立。

ReAct 可查询 `planning_frontier` / `candidate_horizon`，再提交 `kind=horizon`、准确 inputFingerprint 和 selectedKeys。服务器重新计算候选，只接受其依赖闭合子集；模型不能提供预算、完成状态、预留、身份、权限、方法定义或执行图。回执仅在本会话内登记。真实结构化工具反馈进入下一轮模型提示，最终只允许 wait；Horizon 与 plan_revision 双向互斥。

复用会话锁、请求指纹日志、动作数/TTL/完整动作截止期、授权和版本 Fence。计算及缓存复用前后检查 Flag、策略/能力目录、授权、Run/Plan/Observation；内容 Fence 额外覆盖步骤、执行输入、收据相关状态。迟到结果不进入 journal 或 registry。审计仅记录指纹、计数、预算使用和拒绝码，不记录任务/来源/提案正文。

工具计算及登记不调用 WorkflowStore 写入，不修改正式 TaskPlan、ACG、Run 或执行收据。整个 ReAct 最终 wait 仍由既有 RuntimePlanningCoordinator 持久化轮次和审核屏障；该既有持久化与提案登记是不同操作。没有调用 SemanticRevisionService、新建替换 Run、绑定资源或激活候选窗口。

不采用 HTNExpansionProposal 作为 Horizon 输入，`sourceExpansionRef` 等字段明确拒绝。HTN 的局部原子投影及 boundaryRelations 不具备全局提交证明，不能冒充执行边。混合会话保留 HTN Catalog Fence；重启只能从正式计划、冻结 Basis 和可信观察重新计算，不能复用丢失的内存展开。未提前实现 S02。

## 验证

所有 Runtime 集成测试使用测试临时 SQLite，真实准备 Run、构造 Observation、经过工具反馈及 Runtime wait；未调用真实模型供应商。

新增 Horizon 测试覆盖稳定性、自适应反例、全部执行分类、审核和资源观察、完整依赖边界、Compiler 推导依赖、预算/输入/截止期、模型越权、合同伪造、并发幂等、请求冲突、失效权限、版本/内容变化、HTN 混合会话目录变化、重启重建、审核恢复丢失 Proposal、Frozen Basis 及 Flag 组合。

运行目录为 `apps/agentOS`，Python 3.14；结果均为本轮实际执行。

| 命令 / 范围 | 实际结果 |
| --- | --- |
| `python -m pytest -q tests/components/planner/test_horizon.py` | 77 passed，32.40s；后续强化 SQLite 全库只读断言，单独复跑对应测试 1 passed，2.32s，并由最终全量再次覆盖 |
| `python -m pytest -q tests/components/planner/test_horizon.py tests/components/planner/test_htn.py tests/components/planner/test_htn_adversarial.py tests/components/planner/test_react_loop.py tests/components/planner/test_unified_actions.py` | 中间实现快照 169 passed，94.37s（当时 Horizon 64 项）；不代替最终全量 |
| `python -m pytest -q tests/components/planner tests/contracts tests/architecture tests/runtime` | 中间实现快照 638 passed，381.68s（当时 Horizon 69 项）；后续合同/审核完成证据及新增反例由最终全量覆盖 |
| `python -m pytest -q` | 首轮 1260 passed / 1 failed，411.86s；唯一失败为未修改的既有 20ms 流式活动计时测试，单独普通重跑亦复现 |
| 以下完整套件命令 | **最终 1261 passed / 0 failed**，405.49s；1184 基线 + 77 Horizon。仅既有 PyPDF2 弃用警告 1 项 |

```powershell
python -c "import ctypes, pytest; timer = ctypes.WinDLL('winmm'); assert timer.timeBeginPeriod(1) == 0; result = pytest.main(['-q']); timer.timeEndPeriod(1); raise SystemExit(result)"
```

`test_private_provider_activity_keeps_stream_alive_until_public_json_arrives` 的夹具每10ms输出活动，首事件窗口20ms。Windows 默认定时唤醒精度下发生超时；测试进程临时请求1ms定时分辨率后，单项 1 passed（0.60s），完整原套件也全绿。未改该测试、未放宽时限、未跳过失败用例、未修改 LLM Gateway；测试进程结束前恢复定时请求。普通默认环境的时间敏感失败仍如实保留，不宣称普通全量首轮通过。

最终 `git diff --check` 通过；原有测试文件未修改，架构门禁未降低。S01-04 仅4个修改文件 + 2个新增源码文件 + 1个新增测试文件 + 本记录，暂存区为空，HEAD 保持 S01-03 提交。

## 限制

成本/风险为确定性保守估算，未通过真实供应商或负载进行策略调参；资源观察只是绑定 Observation 时的快照。循环控制计划保守暂停 Horizon 选择，循环迭代仍由原 Runtime 决定。HTN 展开到全局 DAG 的验证与正式 Planning Commit 均不在本轮；没有 Scheduler 消费方或持久化 Proposal 权威。既有20ms流式测试对普通 Windows 定时环境敏感，以上计时环境条件应随验收结果保留。

## 独立代码级验收补充（2026-10-12）

独立验收依据实际 Diff、源码及先失败后修复的反例，确认并最小修复7类P1：完成输出/验证证据不足、编译依赖受节点输入顺序影响、观察与Run步骤映射不一致、蓝图控制屏障丢失、不支持的risk逸出异常、步骤级审核要求丢失，以及取消信号早于终态持久化（含最后策略读取期间的取消竞争）。保留原77项Horizon断言，仅为completed夹具补齐outputRef；新增20项独立对抗测试。未改共享Compiler、LLM Gateway、Scheduler、SemanticRevisionService或既有20ms用例。

最终定向Horizon/HTN/ReAct/Gateway **202 passed，97.29s**；扩大回归中间快照 **665 passed，264.40s**，最后取消检查由最终定向和完整套件覆盖。相同最终源码快照：默认Windows全量 **1280 passed / 1 failed，359.71s**；请求1ms定时分辨率的完整原套件 **1281 passed / 0 failed，384.29s**。两次全量各有1项既有PyPDF2弃用警告。默认失败仍是既有 `test_private_provider_activity_keeps_stream_alive_until_public_json_arrives`，未修改、跳过或放宽测试，未将1ms结果冒充默认环境通过。

结论 **CONDITIONAL**：本轮未发现未修复的Horizon P0/P1；默认Windows回归稳定性仍需单独处理。候选合同可按Proposal-only边界冻结，所有相关Flag保持默认关闭；不授权生产开启或执行提交。完整调用链、文件行号、可复现命令、性能边界和剩余风险见[独立代码级架构验收](PR-S01-04-独立代码级架构验收-2026-10-12.md)。HEAD仍为 `ce1d67d117f678f211409fb4f47dee80fc24d37b`，本轮未提交、未Push、未部署、未升级业务数据库或修改正式ADR。
