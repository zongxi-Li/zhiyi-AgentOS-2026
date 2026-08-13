# 步骤记忆策略

## 作用

步骤记忆策略规定某一个 ACG 步骤能否读取记忆、能否把本步骤的受控输出写入记忆，以及读取的范围。它由 ACG Blueprint 的 `StepNode.metadata.memoryPolicy` 声明，在创建运行时复制到该运行自己的 `WorkflowStep.input.memoryPolicy`。

这份复制很重要：已经创建的运行不会因后来修改蓝图而改变记忆权限。

## 字段

- `read`：是否把当前运行的允许记忆交给 Agent。
- `write`：是否把通过输出合同校验后的受控输出写为情节记忆。
- `allowedTypes`：允许读取或写入的记忆类型。首期规划器使用 `episodic`。
- `limit`：一次最多读取多少条记忆，默认 10。
- `tokenBudget`：一次最多注入多少估算 Token 的记忆正文。它是上下文容量上限，不是模型调用次数或费用上限；放不下的整条记忆不会被截断或偷偷放宽。
- `requireAudit`：该策略是否要求记录记忆访问的审计事实。
- `policyId`：策略版本标识，供 Trace 和后续治理规则稳定引用。

## 安全边界

记忆正文只保留在 `MemoryService` 与记忆仓库。执行状态、SQLite checkpoint、`WorkflowRun.executionState` 和 Trace 仅保存引用或以下统计：策略标识、读写开关、条数、类型、预算、实际 Token 数与是否成功写入。

执行图会再次对白名单字段裁剪，即使某个外部节点运行器错误传入 `memoryBody` 等扩展字段，也不会写入 Trace。

## 当前默认

没有声明策略的历史 Blueprint 保持兼容：允许读写、最多 10 条、不设 Token 内容量上限。新的能力目录规划中，`writesMemory=true` 的能力会生成允许写入并要求审计的策略；其他能力生成只读策略。
