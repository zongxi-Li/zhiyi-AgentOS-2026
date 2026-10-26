# Codex 提示词｜S00 最小语义内核落地前的只读代码审计

> 本文件是可以直接粘贴到 Codex 的审核任务，**当前阶段仅允许阅读、评估、拟定计划，不得修改仓库文件或提交代码**。

你现在是知弈 AgentOS 的高级架构审计与重构工程师。请先阅读实际本地仓库状态并与 S00 v0.12、ADR-0001/0002/0003/0004、ADR-0005 D1/D3/D4、ADR-0006、ADR-0008、ADR-0009 的已采纳设计对齐。不要把已采纳的架构文档当成代码已实现的证据。优先复用现有架构，不建立第二套 Mission、Run、Planner、Graph Compiler 或 Memory Store。

## 严格限制

1. **只读审计**：不创建、不修改、不删除仓库文件；不运行会写数据库/生成大量文件的命令；不执行 DB migration；不做 Git 提交、推送、切分分支或重置工作区。需要运行会改变本地环境的测试时先告知我。
2. 首先输出 `git status --short`、`git rev-parse HEAD`、当前分支以及与 `master@3b04839a39a1d01172b041ec11c0bf40cca24fea` 的差异；如果存在我未提交的修改，先保护并分析，不假定远端就是最新代码。
3. 不自动实现 S01 ReAct/HTN、S02 Progressive Commit、S03 Graph Evolution、S07 算法与 S09 Effect Ledger。本轮只聚焦第一个最小任务 **PR-S00-01** 的详细施工准备。
4. 不因新增“语义状态”而将 `RuntimeMissionRecord`、`IdentityV2`、既有 `lifecycle_outbox` 或 `WorkflowStore` 删除/重命名。保留所有正式写入权威、权限审批、资源隔离与 Artifact/Trace 的契约。

## 必须核对的调用链和疑点

- `ExecutionRuntime.create_mission` → `MissionManager.create_mission` → `WorkflowStore.save_mission` → SQLite `tasks`/`lifecycle_outbox` → IdentityV2 投影；枚举全部 Mission 更新路径和生命周期状态写入路径。
- `RuntimeMissionRecord` 及旧 Mission 列表/API、MissionWorkspace 数据投影，确认现有字段含义与“正式语义目标/硬约束”的区别。
- `SQLiteWorkflowStore._init_schema`、`MemoryWorkflowStore`、`WorkflowStore` 基类/Port 和测试；确认真实生产 SQLite 文件位置、备份策略、migration 入口。
- 现有 `lifecycle_outbox` 的事件类型、消费者、去重、dead-letter/重试，不得直接把 `mission.created` 认定为 SemanticCommit。
- `components/mission_manager/store.py` 两份 `WorkflowRegistry` / `ScopedWorkflowRegistry` 同名定义，分析实质影响与可安全单独清理方案。
- `components/auditor/decision_store.py` 的 Run/Step PolicyDecision 不同于 Mission scoped UserDecision，不能擅自复用其语义。
- 枚举 S00 语义提交与 S02 TaskPlan Commit、S03 Runtime 状态的当前相关字段，确保没有一个尚不存在的跨数据库事务被假设为已有。

## 请输出严格结构化的审计报告

A. **证据矩阵**：每项写 `现有能力/缺口/影响范围/真实文件:行号/建议复用点`，禁止泛泛而谈。

B. **PR-S00-01 最小接口**：草拟 `MissionSemanticAggregate`、`SemanticCommit`、`expectedMissionRevision` CAS、`operationId` 幂等、无操作 no-op、`EffectiveMissionSnapshot` 的内部合同；说明旧 Mission 创建/读取如何渐进映射。避免复制完整 Run、TaskPlan 和 Memory 内容。

C. **单库原子性方案**：在现有 SQLiteWorkflowStore 所用 DB 中附加最小语义 schema，与适配器边界一致；提交一笔事务内如何完成 `CAS + Semantic History + Outbox`，何处抛出 Conflict，重复投递如何返回已存结果。说明事务期间失败及进程重启的恢复行为；指出哪些数据不在同一个数据库里。

D. **文件级变更计划**：具体新建/修改文件、调用方影响、旧 API 和 JSON 兼容、是否需要新增抽象 Store Port 与内存替身、数据迁移和回滚方式。文件数控制合理，不切碎成几十个零散 PR，也不一次重构全仓。

E. **测试与验收**：至少 CAS 冲突、重复 OperationId、相同 ID 不同内容、no-op、断电/DB 异常、旧数据 bootstrap、重启读取、现有 identity/outbox/mission/run 回归。列出现有相关测试和新增测试名称；本轮如果无法安全执行，标记 NOT RUN。

F. **关键风险**：旧 Mission 两处可写真相、Outbox `mission.created` 命名、敏感 `input` 下沉到 Outbox、SQLite migration、MemoryWorkflowStore 与 SQLite 不一致、审批授权作用域遗漏。

G. **终稿**：给出一个符合 `feat(s00): 中文描述` 形式的候选 Git 提交说明，仅建议、不执行。以“可以开始实施 / 需要先解决阻塞项”作条件性结论。

**结束条件**：只交付审计和 PR-S00-01 的可落地施工计划，等待我下一次明确允许写代码，不能自行开始实现。
