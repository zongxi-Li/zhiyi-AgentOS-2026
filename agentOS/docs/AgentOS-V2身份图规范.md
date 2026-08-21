# AgentOS V2 身份图技术规范

> 创建：2026-08-21 09:04:08 +08:00（本地文件，尚未提交到 Git）
> 最近一次 Git 修改：未记录（本地未提交）

版本：1.0

## 权威性

V2 身份图是解释某个节点、资源或结果为何存在的权威来源。旧版
`WorkflowRuntime` 记录不得导入此图。

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
`ACGNodeRunner` 与 `WorkflowRuntime` 仍是编译和执行的权威来源。第 3 阶段仅将它们的
身份、绑定与生命周期投影到 V2 仓库。未记录 WKN `ExecutionBinding` 的
`StepExecution` 无效。

本协议不引入 `RuntimeGraphV2`、`SchedulerV2` 或 `ExecutorV2`。

规划器集成仅通过 `PlannerIdentityBridge` 持久化语义化的 TaskNode 树。Agent、模型、
资源和 WKN ACG 节点身份在该边界均会被拒绝；这些决策仍属于 WKN ACG 的设计和运行时阶段。

## 解析保证

对于每个已持久化的 StepExecution，`IdentityResolver.resolve_execution_origin`
必须返回其 UserTask、TaskNode、AcgBlueprint、WorkflowRun、Attempt、ACG 节点绑定及选定的资源绑定。
