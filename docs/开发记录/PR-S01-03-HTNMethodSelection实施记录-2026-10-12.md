# PR-S01-03：HTN Method Selection 与分层展开 Proposal

日期：2026-10-12。基线：`872ee9bd`（S01-02 本地提交）。状态：独立代码级架构验收 ACCEPT（修复后），本轮按用户授权整理为本地提交。未 Push、未部署，未修改生产数据库或正式 ADR。

## 基线与审计

S01-02 独立验收全文由用户在本轮提供，原结论 ACCEPT，原全量 1116 通过。提交前复核补充了最终交付的会话归属、撤销和截止期检查及 2 项测试，修复后全量 **1118 passed**；提交标题为 `feat(agentos-planner): 实现受控 ReAct 规划循环与工具反馈闭环`。

独立报告的非阻断 P2 仍保留：ReAct 的内部供应商重试实际次数留在局部 call_audit，未上抛运行审计；实际请求受既有绝对 deadline 与重试上限约束。本 PR 未扩大此观测改动范围。

审计链：`TaskDecomposer.decompose` → `SemanticPlanner` → `TaskPlan` → `TaskPlanTopologyCompiler`；Runtime 边界 → `PlanningEngine.decide_runtime` → ReAct → `PlannerActionGateway`。现有 `PlannedTask.parentKey` 和 `TaskPlanRelation` 已具备层次与依赖语义，无需复制计划模型。SemanticPlanner/TaskDecomposer 的正式计划生产路径保持原有行为；HTN 只接到 opt-in 工具缝隙。

## 方法表示与选择算法

- Abstract Task：现有正式计划中任务的 `metadata.taskType` 标签，如 `analysis`。目标仍由已有 semantic key 定位，不新建正式任务身份。
- `HTNMethod`：受信任代码目录中的 `methodId`、`abstractTask`、版本、优先级、适用条件、子任务、局部排序和定义来源。`HTNSubtask.task` 直接复用 `PlannedTask`；其 key 是定义内稳定槽位。设置 `abstractTask` 表示继续展开，否则恰有一个可见目录 capability，是原子槽位。方法不能设置执行身份、父 key 或材料 workset。
- Applicability：闭合集合的等值条件合取，支持冻结 Basis 来源类型、显式 constraintId 的精确值、当前唤醒原因，以及可信观测中指定任务的状态/审核结果。缺失或歧义观测不满足条件；冻结/继承约束同 ID 不同值拒绝。只读取 Run 的冻结 Basis，不读取最新 Mission 语义替代它。
- 查询返回各候选的真实定义、适用状态及封闭拒绝原因。根方法由模型选择已有 methodId；子层只对适用方法按 `preferredMethodIds`、定义优先级、methodId 稳定排序。未知方法、条件不满足和展开失败明确拒绝，不伪造有效计划，也不自动偷偷换另一种根方法。
- 目录最多 128 个方法、总定义 120k 字符；保存不可变序列化快照并计算内容 SHA-256 revision。请求只能引用 revision，不能提交定义、条件、权限或执行事实。展开全程使用同一目录快照，发生变化即拒绝。
- 内置最小词汇：`analysis.standard`（理解→分析）、`analysis.evidence`（已冻结 SEMANTIC Basis 时可选：理解→证据子任务）、`evidence.compare`（检索→证据分析→比较）。可由可信装配代码注入其他目录，未新增模型写目录入口或数据库状态。

## 展开与验证边界

1. 目标必须有明确 taskType、冻结来源引用，且可信当前观测及持久步骤状态均为未开始、无工作/审核收据。拒绝已完成、运行中、失败、跳过、待审任务，以及已有层次、受验证控制的目标或材料 workset；这些改动需要后续正式规划/恢复规则。
2. 有界深度优先递归；活动抽象类型栈检测循环。每个孩子继承父约束、验收条件及来源，并追加可信方法定义引用。来源必须属于冻结 Basis/约束来源或精确 Basis 指纹引用；子槽位不得发明新来源。引用仍是 UNVERIFIED，不被升格为已核实业务证据。
3. 候选 key = `htn:` + SHA-256(parent key, methodId, local slot) 的前 32 位；与文本、会话、Run、方法版本和目录内容版本无关。同逻辑槽位跨请求、方法版本变化和重启稳定，碰撞既有 key 则拒绝。父关系同时保留 parentKey 和 parent relation。
4. 方法局部 `depends_on` 使用既有“前置 source→后继 target”方向；抽象子组的先后约束保守展开到各组原子后代之间。没有另写 DAG 排序、能力绑定或拓扑修复器。
5. 原子投影交给 **既有** `validate_task_plan_for_execution` / `TaskPlanTopologyCompiler.validate_existing_plan`，采用固定模板声明边，不走模型 repair。能力前置条件、DAG、终端连接和产物生产者仍由现有门禁校验；抽象父节点不冒充产物/能力生产者。包含外部已有节点的层次结构另经现有 TaskPlan 合同检查。以上 TaskPlan 对象仅在内存用于验证，未写正式计划。
6. Proposal 保留目标原有 `boundaryRelations`，不将外部依赖接线转成正式执行图。与正式图的原子接线/提交由后续 S02/S03 负责。

预算默认：深度 8（根层为 0）、总节点 64（含抽象父）、展开依赖/父边 256、候选评估 256、节点内容 120k 字符，并共享网关单动作截止期；现有 ReAct 的轮数、工具数、上下文与总截止期继续生效。拓扑校验新增边同样计入预算。

## 工具闭环与权威

```
ReAct READ method_catalog(targetKey)
  → 可信候选定义 + applicability + catalogRevision
ReAct PROPOSE method(targetKey, methodId, catalogRevision, preferredMethodIds?)
  → 确定性展开 + 现有语义/拓扑门禁
  → 会话登记 + HTNExpansionProposal 回执
  → 下一模型轮真实 toolFeedback
  → wait（经既有 Runtime 审核等待链）
```

`HTNExpansionProposal` 仅封装既有 PlannedTask/TaskPlanRelation、原子 key、方法选择轨迹及 Basis/Observation/PlanVersion/目录绑定信息，不是 TaskPlanPatch、Runtime Graph 或 Planning Commit。模型 rationale 不进入展开或审计。

使用 HTN 的会话不可登记 plan_revision，已登记 revision 的会话也不可进入 HTN。HTN 轮次最终动作仅允许 wait，禁止通过 revise/recover/continue/complete 兑现层次提案。因此不能接到既有“替换 Run 重执行全部节点”的通道。标准 Planner/ReAct 的非 HTN 修订与 SemanticRevisionService 行为保持原样。

默认关闭：`AGENTOS_PLANNER_HTN` 未设置时，不装配方法目录；生产入口还需 S01-02 的 `AGENTOS_PLANNER_REACT_LOOP` 开启且注入 LLM。旧 capability-only method 建议仍兼容。HTN 请求显式拒绝关闭/未装配状态。会话内有效重复请求幂等重放；按既有协议，预算耗尽/会话过期后不重放。HTN 重放前重新检查持久 Run/Plan/Observation/Graph/步骤状态、开关及目录版本，不能用缓存越过世界变化。重启不恢复旧 sessionId，新会话可确定性重建相同 Proposal。

## 实际验证

所有数据库均由测试创建在临时目录；模型为确定性 Fake LLM。真实 Runtime 测试使用独立重建的 ExecutionRuntime 与既有 SQLite/ACG/身份/审核组件，通过 `execute_prepared_run` 的恢复边界运行查询、选择、展开反馈和 wait。逐项核对正式计划、绑定、ACG 和冻结 Basis 不变，Agent 未执行；重复进入审核等待不重复调模型。

| 测试 | 实际结果 |
|---|---|
| 新增 `tests/components/planner/test_htn.py` | 44 passed |
| planner + contracts + architecture + runtime | 546 passed（435.61s，该轮采集 43 个新增用例）；随后补充第 44 个用例及真实 Runtime 重建验证，定向 44 passed |
| 最终代码全量 `python -m pytest -q` | **1162 passed / 0 failed**（390.66s = 6:30；S01-02 基线 1118 + HTN 44；仅既有 PyPDF2 弃用警告 1 项） |

覆盖多合法方法、约束/观测适用性、未知/不适用/冲突方法、多层与子方法排序、循环、非法 DAG、缺少能力前置生产者、来源、产物生产者、五类预算与截止期、稳定身份、目录深层不可变、模型伪造合同拒绝、已有执行收据/层次/workset 拒绝、外部依赖保留、版本/观测/图/状态/开关变化时缓存失效，以及晚于 Run 的 Mission 修订不改变冻结选择。ReAct 测试既消费目录反馈决定方法，又消费真实工具拒绝反馈后改选合法方法；直接网关登记逐字比对 Run 与 outbox 无写入。

扩大回归中测试 harness 直接给枚举字段赋字符串产生 1 项 Pydantic 序列化警告；已改用 `StepStatus.COMPLETED`，随后定向 44 项无警告通过。未跳过失败用例或降低架构门禁。

最终 `git diff --check` 通过。HEAD 仍为 `872ee9bd`，S01-03 范围为 4 修改 + 4 新增（含本记录），暂存区为空；代码、测试、记录均留在工作区待独立验收。

本轮首个 Runtime 集成测试的 harness 直接从 PENDING 调协调器，违反既有 PENDING→WAITING_REVIEW 生命周期。已修正为真实重启 RUNNING Run → `execute_prepared_run` 的恢复边界，不修改状态机或降低门禁；随后该用例通过。

## 剩余限制

- 条件是有限、精确值匹配；不解释任意自然语言矛盾，不进行成本搜索、最优性保证、全局回溯或自动生成方法。目录作者须维护 methodId/slot 的稳定语义。
- 需可信计划显式 taskType 与冻结来源；不会自动把每个普通原子任务改造成抽象任务。保守拒绝已有执行前缀、层次、受控节点和材料分块对象，不承诺 HTN 已解决其正式变更问题。
- Proposal/登记仅在会话内存中存在，不新增正式持久状态，跨重启按同一冻结输入重新展开。真实供应商模型的策略质量和 schema 服从率未实测。
- 正式 Planning Commit、外部执行图接线、资源绑定、执行承诺、Adaptive Rolling Horizon 均未实施；无 S02/S03、LLM Gateway 或 ADR 变更。

## 独立验收与提交前复核

独立验收报告为 `PR-S01-03-独立代码级架构验收-2026-10-12.md`，结论 ACCEPT（修复后），最终全量 1184 passed。五类 P1 已保留：发布前复核及完整动作截止期、撤销授权后禁用缓存、同版本内容变化的会话指纹、父能力覆盖、约束内部来源闭合校验。新增对抗测试 22 项，原 44 项 HTN 断言未修改。

提交前逐文件比对独立验收最终 SHA-256，源码与测试全部 MATCH；再次运行 HTN/对抗/ReAct/网关四文件：**105 passed**（61.20s）。`git diff --check` 通过。将四修改与六新增路径整理为本地 Commit：`feat(agentos-planner): 实现 HTN 方法选择与分层展开提案`；提交 Hash 由提交完成后的 Git 查询及下一阶段记录保存，避免写入自身提交树。
