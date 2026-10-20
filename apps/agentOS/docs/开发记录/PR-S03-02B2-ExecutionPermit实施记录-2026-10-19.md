# PR-S03-02B2｜Execution Permit Authority 实施记录

日期：2026-10-19

状态：实现完成，等待独立验收；工作区未提交。

## 范围

在 S03-02A/B1 的显式激活与 `STATE_PREPARED` Handoff 之上增加 opt-in Execution Permit Authority。Permit 只在服务端从持久化 Handoff、已接受 Graph Revision、当前权限、Frozen Run/Checkpoint 和 Identity 来源重新验证后签发。客户端只传 `handoff_id` 与幂等键，不能传 candidate package、checkpoint 内容、attempt 身份或执行授权。

新增 `ExecutionPermitRecord`，以 `PREPARING → ISSUED` 表示跨 Workflow、Checkpoint、Identity 三个持久化边界的可恢复交接；只有 Workflow SQLite 中的 `ISSUED` Record、正式 Run Permit 投影和 promoted checkpoint 身份在同一最终事务中一致时，执行入口才接受 Permit。相同键重放返回历史 Receipt；同一 Handoff 使用其他键或同键绑定不同来源时拒绝。Runtime 装配不运行 DDL，Permit Store Schema 只能通过显式管理升级接口建立。

交接顺序为：复验 B1 候选及来源 → Workflow 写入 `PREPARING` → Checkpoint 按来源版本 CAS 提升并绑定 Permit/attempt generation → Identity 以独立幂等事件更新同一个 Run 的图与 TaskPlan → 再验 Workflow、权限和外部提升 → 单个 Workflow 事务将 Permit 与 Run 投影一并置为 `ISSUED`。跨库步骤不声称联合原子；任何中断保留 `PREPARING`，同一幂等键可在新 Runtime 实例中重驱动。失败的来源变化不会生成可调度 Permit。

`ACGNodeRunner` 的新图 receipt key 含有 attempt generation，使新 GraphVersion 的 attempt 不会复用旧图完成收据。执行入口在资源分配前、分配后及 NodeRunner 调用前复核当前 Permit、Mission 权限、激活头、Identity 投影和取消/终态；授权失效会阻止新节点派发。资源要求只从激活包的 Binding Manifest 派生，不作资源预留；调度前会与包复核，避免普通 Run 写入降低候选节点能力要求。可信 Recovery 可调整非权威 `agentRole` 排序偏好，能力与其余执行约束仍须匹配编译包。

## 变更文件

- `src/contracts/execution_permit.py`
- `src/support/stores/execution_permit_store.py`
- `src/runtime/execution_permit.py`
- `src/runtime/workflow_runtime.py`
- `src/runtime/ports.py`
- `src/runtime/acg_execution.py`
- `src/runtime/binding.py`
- `src/runtime/graph_activation.py`
- `src/runtime/v2/identity_projection.py`
- `src/components/recovery/checkpoint.py`
- `src/components/executor/graph.py`
- `src/components/executor/node_runner.py`
- `src/contracts/acg_lifecycle.py`
- `src/support/stores/graph_activation_store.py`
- `tests/components/planner/test_execution_permit.py`
- `scripts/freeze_gate.py`（为本阶段实现补充受影响源码到测试的映射）

## 权威边界

- `ACTIVATED_PAUSED`、`PREPARING` 与历史 Receipt 均不授予执行权；Scheduler 只接受当前 `ISSUED` Record 与 Run 投影匹配且重新授权成功的图。
- 签发只提升已有 Checkpoint 并更新同一 Run 的正式激活投影，不创建新 Run、不修改正式 GraphVersion、不重写已完成节点或旧 receipt。
- Identity 事件专用于 Permit Saga，不调用会创建 replacement Run 的普通 Blueprint Revision 路径。
- 新增能力未接入默认生产装配；没有 Permit Authority 时，带正式 Activation Head 的 Run 在执行入口 fail-closed。
- 激活图的 `bindingRequirements` 是包约束的派生投影，不是资源绑定或租约；真正资源选择仍由现有 Runtime Binder/Scheduler 在执行时完成。

## 回归证据

冻结门禁命令：`python scripts/freeze_gate.py`（Windows Python 3.14.5，默认计时；不运行全量 pytest）。

- 结果：`PASSED`，9 passed、0 failed、0 skipped；pytest 阶段约 40.97 秒，门禁总耗时约 40.97 秒，低于 300 秒预算。
- 覆盖：无 Permit 时执行拒绝；合法 Permit 后通过真实临时 Runtime/SQLite/Native Scheduler 派发新增节点；Binding Manifest 约束；checkpoint 版本竞争；同一来源跨两个独立 Runtime 的并发重复请求；权限撤销；Identity 提升失败后重建 Runtime 恢复；运行状态变化拒绝；attempt generation receipt namespace。
- `git diff --check` 通过。CRLF 提示仅为 Windows 行尾提醒。
- `src/` 与 `tests/` 最终聚合 SHA-256：`eb28f420b1934fbfcc750051ff1edf423f4467e9b9aee3f0b932b7b543b582bc`，文件数 430。门禁实际收集和执行的源码快照与此摘要一致。
- 未运行全量 pytest，亦未请求 1ms 定时分辨率；S03-02B1 历史全量结果未作为本轮代码测试结果。

## 保留限制

Workflow、Checkpoint 与 Identity 数据库之间没有联合事务，使用持久化 PREPARING Saga 做可重试恢复；执行许可只在 Workflow 最终提交后生效。跨数据库极端故障及多主机分布式执行栅栏未在本阶段验证。该实现不发放 Permit 给控制图，也不实现 Checkpoint Promotion 以外的跨库自动协调；Feature Flag、默认生产装配及业务数据库升级均未实施。

本记录不代表独立架构验收、S03-02B 冻结或生产执行验收。
