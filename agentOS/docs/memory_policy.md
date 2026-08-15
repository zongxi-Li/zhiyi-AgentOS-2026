# 步骤记忆策略

## 作用

步骤记忆策略规定某一个 ACG 步骤能否读取记忆、能否把本步骤的受控输出写入记忆，以及读取的范围。它由 ACG Blueprint 的 `StepNode.metadata.memoryPolicy` 声明，在创建运行时复制到该运行自己的 `WorkflowStep.input.memoryPolicy`。

这份复制很重要：已经创建的运行不会因后来修改蓝图而改变记忆权限。

## 字段

- `read`：是否把当前运行的允许记忆交给 Agent。
- `write`：是否把通过输出合同校验后的受控输出写为情节记忆。
- `readTypes`：允许读取的记忆类型。读取开启时必须至少声明一种类型；它只约束注入 Agent 的既有记忆，不能决定本步骤的写入类别。
- `writeType`：本步骤受控输出写入的唯一记忆类型。写入开启时必须声明；写入关闭时必须为 `null` 或不声明。首期能力目录使用 `episodic`，但执行器已可准确写入 `semantic`、`procedural` 等其他受支持类型。
- `limit`：一次最多读取多少条记忆，默认 10。
- `tokenBudget`：一次最多注入多少估算 Token 的记忆正文。它是上下文容量上限，不是模型调用次数或费用上限；放不下的整条记忆不会被截断或偷偷放宽。
- `requireAudit`：该策略是否要求记录记忆访问的审计事实。
- `policyId`：策略版本标识，供 Trace 和后续治理规则稳定引用。

## 安全边界

记忆正文只保留在 `MemoryService` 与记忆仓库。执行状态、SQLite checkpoint、`WorkflowRun.executionState` 和 Trace 仅保存引用或以下统计：策略标识、读写开关、条数、类型、预算、实际 Token 数与是否成功写入。

执行图会再次对白名单字段裁剪，即使某个外部节点运行器错误传入 `memoryBody` 等扩展字段，也不会写入 Trace。

## 当前默认

没有声明策略的历史 Blueprint 保持兼容：允许读写、最多 10 条、不设 Token 内容量上限，写入类别固定为 `episodic`。旧字段 `allowedTypes` 仅在读取旧 Blueprint 时被接受：它会转换为 `readTypes`，旧写入仍固定为 `episodic`。新 Blueprint 不再生成该字段。

## 冻结与校验

`prepare_run` 会在保存运行前解析每个步骤的策略，并把它冻结成统一格式。也就是说，诸如“开启写入但未写 `writeType`”“读写新字段与旧字段混用”“读取开启却没有 `readTypes`”都会在 Agent 尚未调用、运行尚未持久化前明确报错。

Trace 与检查点只记录 `readTypes`、`writeType`、条数和预算等执行事实，不记录任何记忆正文。
