# PR-S02-02：Durable Planning Commit 与首次规划 / revise 接入

状态：实施完成，最终全量通过；根据后续用户授权整理提交并推送。尚未进行独立架构验收。

## 基线

- S01-04 本地提交：`59f949e12d5da261d80b75aacb89a5842c52c3e8`。
- S02-01 本地提交 / 当前 HEAD：`26764272cb4f3f65bf6673458cd1468111d33d8c`。
- 固定基线前补测 S02-01 中断回滚：provider guard 退出抛出 `KeyboardInterrupt` 时撤销临时记录并重新抛出中断。联合基线回归 317 passed（213.43s）。S01-04 原 Windows 默认计时环境的 CONDITIONAL 记录保留。

## 合同及持久化

`FrozenPlanningSources.sourceKind` 区分 initial/runtime。首次规划尚无正式 Plan/Graph/Observation，相应四字段必须为空；runtime 相应字段必须完整。来源均由 Runtime adapter 捕获，模型无法提交接受请求或执行身份。`expectedCommitmentRevision` 用于 Mission 接受头的 CAS，版本独立于 TaskPlan.planVersion。

Record 复用原 `TaskPlan` / `TaskPlanPatch` 保存原始候选内容及校验摘要，不新增任务/图/Run 合同。状态为 ACCEPTED，物化状态固定 `COMMITTED_NOT_MATERIALIZED`。同 key 的请求全字段摘要绑定；相同请求重放历史 receipt，不同内容或来源冲突拒绝。历史 receipt 不作为当前执行许可。

`SQLitePlanningCommitStore` 使用现有 Workflow SQLite 文件，仅新增 planning_commit_schema、planning_commit_records、planning_commit_outbox。`BEGIN IMMEDIATE` 内接受头读取、CAS、记录和 outbox 原子提交；Mission+revision 唯一约束及跨连接写锁防止双接受。故障回滚不留下成功记录或事件。读取重新验证候选摘要与索引身份。

构造器使用 mode=rw，既不创建 DB，也不自动升级。`upgrade_schema()` 是显式管理入口，本轮只在测试临时目录调用；业务数据库未升级。没有 outbox 消费、激活、调度或资源绑定逻辑。

## 接受链与权威隔离

配置入口是 `ExecutionRuntime(planning_commit_store=...)` / `enable_planning_commit(store)`，默认不配置，未新增环境 Feature Flag。ledger 必须与 Runtime Workflow store 指向同一 SQLite 文件。

- 首次 ACG 规划：prepare_run 保留既有 Run 创建权威并冻结 Basis，改为 deferred、持久化 planningCommitRequired。随后独立生成 L1/L2 语义候选，重复校验来源后接受。原 ACGLowerer、绑定与图物化路径不进入；Run 继续停留 deferred。
- Runtime revise：原结构化 RuntimePlanningDecision / TaskPlanPatch → 现有决策绑定验证 → Commit 接受 → 普通 wait → 原 RuntimePlanningApplication 保存审核屏障。决策在持久化 decided 前转换，恢复不会把 revise 当成替换执行指令。
- 直接 apply_semantic_patch：在 opt-in 模式返回 Commit receipt，既不调用 SemanticRevisionService，也不创建 replacement Run。
- 恢复入口另有同一决策 gate。接受后 checkpoint 失败时先完成已持久化 decided-wait 屏障，再刷新易变 observation；不会重新规划形成第二份承诺。
- 持久化标记存在而权威缺失时，执行与 revise 均停止。普通审核批准只能恢复原图，不采用接受候选。

Commit 服务本身只写 ledger/outbox。Run 模式标记、runtimeRevision、wait 审核屏障属于既有 Runtime 编排操作，必须与“接受不写正式计划/图/执行收据”的保证区分。

## 可信校验

Run lock 在 ledger 事务之前取得，provider 不反向取得 Run lock。事务内读取正式 Mission revision、Run 的 Basis/TaskPlan/Graph/步骤/收据引用/输入/冻结 scope；来源指纹另包含能力目录与 Identity 最新 TaskPlan snapshot。接受前后校验来源及可信调用方读写权限、Mission ACTIVE、取消状态。

仅支持完整 initial_plan 与 plan_revision；HTN/Horizon 不被隐式采用。局部 scope 拒绝。正式 Basis 缺失或漂移、过期 Observation/Plan/Graph/接受头、权限撤销、活跃任务拒绝。观察必须覆盖实际 Run 每个步骤，状态与绑定一致。

复用 `apply_task_plan_patch` / `validate_task_plan_for_execution` 的现有 Topology Compiler；没有第二个 DAG 编译器。原始候选字符上限 300000，最终节点最多 256、关系最多 1024，修订进入编译前有输入上限。已开始/完成/失败等非 pending 节点及其父级不可修改；pending 但已有 attempt、输出、时间戳或收据引用亦受保护。替换不得减少来源、验收、能力或约束；新增任务必须继承 Frozen Mission 约束，Workset 来源和冻结能力 scope 重新验证。

控制图/控制策略保守拒绝，等待后续 safe-cut 设计。本轮不实现 S03，不改 SemanticRevisionService、Scheduler、Executor 或 ACGLowerer 的覆盖规则。

## 实测

工作目录：`apps/agentOS`。以下均为实际运行，未跳过或放宽已有用例。

- `python -m pytest -q tests/components/planner/test_planning_commit.py tests/components/planner/test_planning_commit_runtime.py tests/contracts tests/architecture --tb=short`：140 passed，13.27s（随后补充控制策略测试）。
- `python -m pytest -q tests/components/planner/test_planning_commit_runtime.py --tb=short`：26 passed，13.67s（控制策略反例补入后的快照）。
- 补充 worker 竞争反例及修复后，重跑 Commit + Runtime Commit + contracts + architecture 同一命令：142 passed，24.75s；新增集此时为 27 项。
- `python -m pytest -q tests/components/planner tests/contracts tests/architecture tests/runtime --tb=short`：739 passed，252.79s；此运行收集后新增控制策略反例，由上述 26 项定向测试及随后全量覆盖。
- 修复 worker 竞争前启动的 `python -m pytest -q --tb=short`：1355 passed，1 个 PyPDF2 弃用警告，280.26s，Windows 默认定时环境，未请求 1ms；该结果是中间快照，不能代替最终代码全量验证。
- 最终代码重新运行 `python -m pytest -q --tb=short`：**1356 passed / 0 failed**，1 个 PyPDF2 弃用警告，285.32s（4:45）。Windows 默认定时环境，未请求 1ms；包括最终 27 项新增集成测试及既有流式计时用例。本次通过不否定 S01-04 已登记的默认 Windows 20ms 测试波动。
- 最后一次返回类型注解修正后补跑 `python -m pytest -q tests/components/planner/test_planning_commit_runtime.py tests/architecture --tb=short`：41 passed，18.70s；随后 worker 竞争修复由 142 项及最终全量覆盖。
- 新增测试使用真实临时 SQLite、Runtime/语义服务、原 TaskPlan/ACG 合同与原审核/恢复入口；不调用真实 LLM 供应商。
- 故障注入复现接受后 checkpoint 失败导致第二个 Commit；修复后同一 outbox 仅一条、无 Agent 执行、恢复到 WAITING_REVIEW。所有已有测试保留。
- 首次接受返回后的 worker 旧快照覆盖操作员输入：新增反例先得到 1 failed / 26 deselected（1.69s），随后 opt-in worker 直接返回持久化最新 Run，不再保存旧快照或刷新无关 Identity outbox。最终测试结果见后续快照。

## 限制与下一阶段

尚无应用装配默认接入、业务 DB 升级、前端 Commit 查询接口或 outbox 消费。首次接受后 deferred Run 不自动完成/激活，等待后续物化阶段。HTN/Horizon 的 durable 接受、部分窗口、安全控制图修订均不在本轮。

Identity snapshot 位于独立数据库，读取摘要双检不能承诺跨数据库原子性；后续物化必须再次验证相关正式来源并执行对应 CAS。当前同步拓扑验证具有输入上限，但没有可抢占硬截止期。单进程 Runtime 生命周期锁仍是既有前提；未声明跨实例完整执行隔离。

实施阶段未提交或推送；后续用户明确授权本轮提交并推送。未部署、未升级业务数据库、未修改正式 ADR。
