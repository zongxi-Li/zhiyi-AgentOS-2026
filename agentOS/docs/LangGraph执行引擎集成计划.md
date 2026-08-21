# LangGraph 执行引擎集成计划

> 创建（Git）：2026-08-13T13:50:54+08:00，WKN
> 最近一次 Git 修改：2026-08-13T13:50:54+08:00，WKN

## 当前边界

已完成的融合层提供了 ACG Blueprint 编译、StateGraph 构建、Pregel 式并发调度、
条件分支、审核中断/恢复命令、节点固定管线、SQLite checkpoint 与持久化执行值仓库。
新的 ACG Blueprint 已由 `WorkflowRuntime` 执行：运行状态、检查点和最终产物只保存摘要
与引用；审核批准可在重建 Runtime 后从 SQLite 断点续跑。只有缺少新 Blueprint 的历史
`runtimeGraph` 快照仍返回 `ACG_EXECUTION_ENGINE_MIGRATING`，避免旧执行器混入新路径。

当前最大的缺口不再是首次执行，而是运行级记忆持久化、工具运行时注入、模型调用
元数据投影，以及并行/条件路径的端到端恢复覆盖。节点运行器已经只能通过服务按引用
读取上游 slot 输出和 ContextPack；完整正文不能进入执行 State。

通信、记忆、审计和外部能力适配的自研实现已拆解为逐项可执行计划：
[`docs/超能力/plans/2026-08-13-acg-runtime-services.md`](超能力/计划/2026-08-13-acg-runtime-services.md)。
该计划以执行值存储为共同基础，明确了每个服务的接口、测试、接线次序和验收矩阵；
本文件保留执行底座迁移的总体阶段定义。

## 阶段 1：补齐运行时数据引用与节点适配

目标：让 `ACGNodeRunner` 使用真实且受治理的数据，而非测试期的空上游输出。

1. 定义 `ExecutionValueStore` 内部接口。
   - 按 `runId + stepId + outputRef` 写入、读取受控输出。
   - 输出由 `outputSpec.properties` 白名单裁剪后存储；完整原始输出不得进入 State。
   - 为 ContextPack、Memory、Trace 分别生成稳定引用，并保持 runId 隔离。
2. 将节点运行器的上游输入改为从 `ExecutionValueStore` 按通信边和 `inputSpec.from` 读取。
   - `STRICT_CONTRACT`：按字段白名单装配并强制校验 schema。
   - `EVENT`：仅传递事件引用与最小通知载荷，不允许读取数据正文。
   - 计算并校验熵预算；预算超限时在 Adapter 调用前拒绝。
3. 接入 AgentRegistry 与既有 Agent/Tool Adapter。
   - 编译时冻结每个 Step 的 Agent 绑定和插件作用域。
   - 运行时只解析该 scope 内的 Agent，禁止重新全局匹配。
4. 扩展测试。
   - 多上游 slot 字段选择、缺少必填字段、EVENT 无正文、scope 越权、熵超限。

完成标准：一个真实 ACG 节点可从服务读取上游 slots 和受限记忆、调用 Agent、写入输出
存储，并只把摘要/引用写回 `ACGExecutionState`。

## 阶段 2：接回 WorkflowRuntime 的首次执行

目标：解除 `execute_prepared_run` 的迁移拦截，但保留公开 API 签名不变。

1. 在 `WorkflowRuntime.__init__` 注入/构造：
   - `ACGGraphCompiler`
   - `ACGCheckpointStore`
   - `ExecutionValueStore`
   - `CommunicatorService`、`MemoryService`、`TraceStore` 的 run 级组合
2. 改造 `execute_prepared_run(run_id)`：
   - 从已持久化 `run.acg_blueprint` 读取 Blueprint，而非重新规划。
   - 编译执行图，创建引用型 `ACGExecutionState`，以 `runId` 为 checkpoint thread ID。
   - 通过 `astream` 执行，并逐事件投影为既有 `TraceEvent`、更新 `WorkflowRun` 的摘要字段。
   - 成功后设置 `COMPLETED` 并生成最终输出引用；异常按既有 `fail_run_safely` 收敛。
3. 将 `engineMigration` 从 `langgraph_pending` 改为带版本的实际引擎标识，例如
   `langgraph_fused_v1`；仅在新路径真正开始后写入。
4. 保留非 ACG runtime adapter 的既有行为，不扩大改造范围。

完成标准：`start()` 和 `execute_prepared_run()` 能执行线性、并行和条件 ACG，并保持查询、
取消与 Trace 导出可用。

## 阶段 3：审核中断、恢复与 SQLite 续跑

目标：接回 `apply_review` 与 `resume_from_checkpoint`，支持服务重启后的安全续跑。

1. 捕获 `ExecutionInterrupt`：
   - 保存 `ACGExecutionState`、checkpoint ID 和审核引用到 SQLite。
   - 将 run/Task 转为 `WAITING_REVIEW`，投影 `REVIEW_REQUIRED` Trace。
2. 改造 `apply_review`：
   - 校验 runId、审核步骤、操作幂等键和版本。
   - 通过 `ExecutionResumeCommand` 恢复 approved/rerun；reject/cancel 走受控终态。
3. 改造 `resume_from_checkpoint`：
   - 读取 SQLite 中 runId 对应 checkpoint，校验 Blueprint/插件 scope 版本。
   - 重建执行图与 run 级服务后调用 `graph.resume`；不得读取草稿旧 RuntimeGraph。
4. 为每个超步、审核中断和恢复后节点写 checkpoint；Trace 必须按 run 连续。

完成标准：进程重启后可读取暂停 run，审核批准只从断点后继续，不重复已完成审核步骤，且
不同 run 的 checkpoint/恢复命令完全隔离。

## 阶段 4：收敛迁移保护与治理验证

目标：只在新执行链覆盖的情形解除迁移错误，并让迁移态可以被安全删除。

1. 移除 ACG 的 `ExecutionEngineMigratingError` 拦截；保留该错误给不兼容历史运行的
显式迁移提示，直到历史数据迁移方案完成。
2. 为历史 `runtimeGraph` JSON 提供只读兼容展示，明确禁止作为新状态或恢复来源。
3. 增加端到端测试：
   - 线性、并行、IF 分支、审核中断/批准/拒绝、取消、进程重启。
   - slot 白名单、输入输出 schema、记忆权限、插件 scope、熵预算。
   - SQLite runId 隔离、Trace 连续性、许可证与草稿区导入边界。
4. 删除已无引用的迁移壳代码与过渡测试，更新 README/运维配置说明。

完成标准：新的融合底座成为唯一 ACG 执行、checkpoint 和恢复来源；草稿区只保留用于历史
对照，不参与任何生产运行、打包或测试。

## 实施纪律

- 每一阶段先增加会失败的行为测试，再修改生产代码。
- 不安装 `langgraph` 或 `langgraph-checkpoint-*`；只保留固定的 `langchain-core` 基础依赖。
- 不把 LangGraph 类型、chunk 或 callback 暴露到 `contracts/`。
- 不在运行中修改图结构；任何结构调整都生成新 Blueprint 与新执行版本。
