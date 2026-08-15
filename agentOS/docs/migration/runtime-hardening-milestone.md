# Runtime Hardening 后续里程碑

## 定位

本里程碑承接 C4 → wkn ACG 主迁移之后的运行时强化工作。它不属于 Phase 0–10 的迁移验收范围，也不改变 `wkn-master@3f6c536` 作为唯一内核目标的结论。

## 前置条件

- 单一 `WorkflowRuntime`、引用式状态与 checkpoint 已稳定。
- Legal 纵切及四类领域 Pack 已完成回归。
- Application API、Spring Gateway、前端数据层和 Docker 链路已切至 v2 合同。
- Capability Matrix 中本轮 `MIGRATE` 项均有实现与测试证据。

## 工作流

### RH-1 外部调用韧性

- 为模型与工具调用定义可配置 timeout、retry 和 rate-limit 合同。
- 区分可重试传输错误、不可重试业务错误和人工审核中断。
- 验收：确定性时钟下覆盖超时、退避、限流和重启恢复，且不产生重复提交。

### RH-2 提交身份外部传播

- 将稳定 `commitId` 传到支持幂等键的模型、工具或代理适配器。
- 验收：prepared retry 和进程重启均复用同一外部幂等身份。

### RH-3 ExecutionValue 生命周期治理

- 定义 orphan 判定、保留窗口、引用扫描和安全回收协议。
- 验收：仍被 State、Checkpoint、Provenance 或授权输出引用的值不会被回收。

### RH-4 五阶段故障注入

- 对 prepare、invoke、value persist、audit/provenance persist、commit/checkpoint 五个边界注入故障。
- 验收：每一边界均证明重放幂等、引用完整和 checkpoint CAS 行为。

### RH-5 协作执行模式

- 在现有合同和调度器上分别设计 `BLACKBOARD`、`DEBATE`，不得引入第二套 Executor。
- 验收：协作消息有持久血缘、受预算和审核策略约束，并可从 checkpoint 恢复。

## 非目标

- 不恢复 C4 Executor、RuntimeGraph 或旧 checkpoint。
- 不迁移历史 C4 数据库。
- 不把正文重新放入 Execution State 或 checkpoint。
- 不借 hardening 名义重做已冻结的 v2 API。

## 交付约束

每个工作流必须单独形成 ADR、失败测试、实现、故障测试和迁移说明；只有在对应验收测试通过后，才能从 `DEFER` 改为已交付状态。
