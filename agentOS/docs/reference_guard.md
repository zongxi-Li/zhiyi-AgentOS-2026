# 执行引用守卫

执行图、检查点和 `WorkflowRun.executionState` 只能保存引用，不能保存输出正文、ContextPack 正文或记忆正文。引用守卫用于确认这些引用在恢复时仍指向正确的受控数据。

## 校验内容

每个 `outputRef` 与 `contextRef` 都同时校验三项：

- 引用类别正确；
- `runId` 与当前运行一致；
- 产生该引用的 `stepId` 与 State 字典中的步骤键一致。

`memoryRef` 会按标识读取真实的 `MemoryRecord`，确认其 `scope` 等于当前 `runId`，并确认
`tags=["execution", stepId]` 中的来源步骤与 State 键一致。它不读取、复制或返回记忆正文。

`traceRef` 除了必须符合当前步骤的固定标识外，还必须能在同一 `WorkflowRun.trace` 找到该步骤
已经提交的 `step_succeeded` 事件。单独伪造 `trace:步骤标识` 不能通过恢复。

`provenanceRefs` 是 `stepId -> eventId[]` 的纯引用映射。恢复时运行时从独立 SQLite 账本重新
加载并验证哈希链，再逐项确认事件存在且由该步骤生产或消费；它不会把通信正文或 Trace 载荷
写入检查点。任何 State 引用字典出现 Blueprint 外的步骤键也会被拒绝。

任一项不匹配都会在创建 Agent、修改运行状态或追加新的血缘事件前终止恢复。

## 审计写入门槛

当步骤记忆策略设置 `requireAudit=true` 时，节点必须先取得包含稳定 `decisionId` 和 `allow`、`review` 或 `deny` 结果的审计决定。没有有效决定时，节点保留可重试的 `prepared` 提交记录，但不会写入输出、记忆或通信血缘。

`deny` 仍由执行图阻断下游步骤；`review` 会按既有审核中断流程保存检查点并等待恢复命令。

## 旧数据兼容

SQLite 值仓库为旧表自动增加 `step_id` 列。旧记录缺少来源步骤时，恢复校验会明确拒绝，而不会猜测其归属；这保证升级后不会把历史不完整引用放入新的恢复路径。
