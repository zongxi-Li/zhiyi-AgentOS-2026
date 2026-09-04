# AgentOS V2 身份图技术规范

> 创建：2026-08-21 09:04:08 +08:00（本地文件，尚未提交到 Git）
> 最近一次 Git 修改：未记录（本地未提交）

版本：1.1

## 权威性

V2 身份图是解释某个节点、资源或结果为何存在的权威来源。WKN 的
`WknWorkflowRun` 运行投影不得被当成 AgentOS 领域对象直接导入此图。

## 身份边界

- `TaskNodeId` 描述规划器判定必须完成的事项。
- WKN 的 `ACGNode.nodeId` 描述蓝图如何实现该事项。
- `TaskNodeId` 使用 AgentOS 身份合同；WKN 节点保留其原生稳定 ID，二者绝不能相等或互相替代。
- `BlueprintId` 标识不可变的设计版本；`graphId` 标识其编译后的运行时图，绝不是蓝图主键。
- `AttemptId` 拥有一项资源绑定；`StepExecutionId` 拥有一项执行事实。

## 固化关系矩阵

| 来源 | 目标 | 关系 |
| --- | --- | --- |
| UserTask | TaskNode | HAS_NODE |
| TaskNode | ACGNode | REALIZED_BY |
| AcgBlueprint | ACGNode | CONTAINS |
| ACGNode | Resource | BOUND_TO |
| WorkflowRun | Attempt | HAS_ATTEMPT |
| Attempt | StepExecution | EXECUTES |
| StepExecution | Evidence | PRODUCES |
| StepExecution | Memory | WRITES |

## 必需执行路径

仅当以下完整路径存在时才允许执行：

`UserTask -> TaskNode -> TaskNodeBinding -> AcgBlueprint -> ACGNode -> ExecutionBinding -> Attempt`

WKN ACG 是唯一的执行内核。现有的 `ACGGraphCompiler`、调度器、
`ACGNodeRunner` 与 `WknWorkflowRuntime` 仍是编译和执行的权威来源。第 3 阶段仅将它们的
身份、绑定与生命周期投影到 V2 仓库。未记录 WKN `ExecutionBinding` 的
`StepExecution` 无效。

本协议不引入 `RuntimeGraphV2`、`SchedulerV2` 或 `ExecutorV2`。

规划器必须先发布 `TaskPlan`，再通过 `PlannerIdentityBridge` 按稳定语义键幂等持久化
TaskNode。Agent、模型、资源和任何运行身份在 TaskPlan 边界均会被拒绝。

Blueprint Builder 同时发布 `TaskNodeImplementationBinding`，显式说明每个 TaskPlan
节点由哪个 WKN ACG 节点实现。`WknIdentityLifecycleAdapter` 只验证并持久化这些绑定，
禁止根据 WKN 节点反向补建 TaskNode。外部传入 `WknBlueprintSpec` 时必须同时提交
`taskPlan` 与 `taskNodeBindings`；缺少绑定或新增未规划执行节点时必须拒绝创建或修订。

## Blueprint 修订协议

- Blueprint 是不可变版本；Run 修订时创建下一版 Blueprint，并把该 Run 固定到新版本。
- 仅修改边或控制节点时，沿用原 TaskPlan 版本，不制造 TaskNode。
- 新增可执行 ACG 节点时，Graph Patch 必须携带 `TaskPlanPatch`。
- `TaskPlanPatch.planVersion` 必须等于 `basePlanVersion + 1`，新增的每个语义节点必须恰好绑定一个新增 ACG 节点。
- 删除既有可执行节点会破坏已固化的规划语义，当前协议直接拒绝。
- 重放同一 Blueprint 修订必须幂等；相同身份但内容不同属于身份冲突。

## 生命周期可靠性

`Attempt` 与 `StepExecution` 的建立由 Repository 事务完成，而不是由 Runtime 拼接多次写入：

- `(runId, nodeId, attemptNumber)` 唯一，显式重放返回同一 Attempt。
- 同一 Attempt 只允许一个 StepExecution；相同输入重放返回原执行，不同输入冲突。
- Attempt 编号在事务内分配，保证同一节点的并发重试连续且不重复。
- 执行终态只允许同结果幂等重放，禁止把已完成事实改写为另一终态或输出。
- 数据库外键、同任务触发器和绑定触发器共同阻止跨 Task 的 Blueprint、Attempt 与资源绑定。
- 同一 UserTask 允许多个 Run 并行：存在进行中的 Run 时，单次失败不会把任务降回 READY；任一 Run 成功即表示用户目标已满足并把任务置为 COMPLETED，其他 Run 的后续失败不得回退该状态。

WKN 与身份库是两个独立 SQLite 边界，无法获得单数据库事务。为关闭崩溃窗口，适配器在身份库中记录
确定性 `LifecycleProjectionEvent`，失败事件可安全重放；应用启动时还会用 WKN 持久化的
`TaskPlan`、绑定和 Blueprint 对非终态 Run 做身份投影对账。该机制是“持久化投影日志 + 启动对账”，
不是对两个数据库作虚假的原子提交承诺。

## Phase 4 查询真源

产品查询只组合 V2 Repository，不从 WKN 运行快照反推领域身份：

| 查询模型 | 真源 |
| --- | --- |
| TaskDetail / TaskRunHistory | UserTask、TaskNode、WorkflowRun V2 |
| RunExecutionTree / AttemptHistory | Blueprint、TaskNodeBinding、Attempt、StepExecution |
| StepExecutionDetail | IdentityResolver 解析出的完整执行来源 |
| ExecutionProvenance | ProvenanceLink |

内部 API 提供 `/agentos/v2/tasks`、任务详情与 Run 历史、Run 执行树与 Attempt 历史、
StepExecution 详情与 provenance。现有 Run 图接口在 V2 身份可用时，以 AcgBlueprint 为图和版本真源，
仅使用 WKN 快照叠加实时步骤状态与运行产物引用；旧接口仍可作为兼容读取面存在。

`/agentos/v2/identity/health` 暴露未应用投影数量和启动对账摘要，不返回内部异常文本。

## 解析保证

对于每个已持久化的 StepExecution，`IdentityResolver.resolve_execution_origin`
必须返回其 UserTask、TaskNode、AcgBlueprint、WorkflowRun、Attempt、ACG 节点绑定及选定的资源绑定。
