# PR-C2A-3 Initial Graph 首次执行闭环

状态：SELF-TESTED，等待独立验收；不是独立 ACCEPT。

## 入场与最小设计

2026-10-20，本地 HEAD 与 GitHub master、Gitee origin/master 实时核对均为 `44663b0edfa107dc530cb5d3a85e8d26510ada19`。入场工作区和暂存区为空。443 个 src/tests Python 文件聚合 `d08de700d22e375ec480ab9b6bb8978cbb96bc6079874856e71fb43422ebe0c9`，对应 C2A-2 ACCEPT。

| 权威 | v1→v2 既有语义 | Initial 最小分支 |
|---|---|---|
| Activation | Head+Run 同 Workflow 事务，暂停 | 直接复用 v1 暂停 Head，不再激活、不造 v0 |
| Handoff | 验证历史 Checkpoint、完成前缀及源 Identity | 明确无源 Checkpoint/Blueprint；验证空执行证据、完整 Initial 来源，构造空 ACGExecutionState |
| Checkpoint | staged 正文后晋升到源 version+1 | 复用 staged 表与 save_promoted 的空 head CAS，正式首个 version=1 |
| Identity | 同一 Identity Run 从旧 Blueprint 晋升 | 通过已有 Lifecycle 首次登记当前 Run/Plan/Blueprint，不伪造执行事实 |
| Permit | PREPARING → 外库晋升 → ISSUED+Run 同事务 | 同一 Saga/Journal，显式 initial_plan 来源，确定性 generation |
| 执行 | claim → Scheduler/Binder → Attempt/NodeRunner/Receipt | 完全复用，最终授权、generation、Checkpoint 与副作用栅栏不旁路 |

Journal JSON 已保存完整来源、candidate、checkpoint 与 identity 指纹，现有唯一索引足以约束首次执行。没有新增表、Authority、Runtime、状态机或 HTTP API 的必要。源 Checkpoint 的 nullable 表达不等于伪造 version 0；CheckpointStore 内部空表计数 0 仅用于无头 CAS。

## 实现与权威边界

工作区范围共 10 文件：修改 `src/contracts/execution_permit.py`、`src/contracts/graph_handoff.py`、`src/runtime/execution_permit.py`、`src/runtime/graph_handoff.py`、`src/support/stores/graph_activation_store.py`、根目录 `scripts/freeze_gate.py`；新增 `src/runtime/initial_execution.py`、`tests/components/planner/test_initial_execution_permit.py`、根目录 `scripts/freeze_gate_baselines/c2a2-accepted.json` 及本报告。没有改动默认装配、API、Scheduler、Binder、NodeRunner、PermitRecovery、Identity Lifecycle、正式 ADR、Schema 或业务数据库。相对路径未特别说明者均位于 apps/agentOS。

- `contracts/graph_handoff.py`：在既有 IdentityLink、StagedCheckpoint、Handoff 中增加显式 `initial_plan` 来源。Initial 的 sourceBlueprint/sourceGraph/sourceCheckpoint 三元组明确为 null、prefixAttemptIds 为空、graphVersion=1，staged 执行通道必须为空。旧 revision 仍要求真实 source 和 graphVersion≥2，不能靠缺字段推断 Initial。
- `contracts/execution_permit.py`：Initial 的 sourceCheckpointId/Version 为 null、promotedCheckpointVersion=1、graphVersion=1；revision 仍按原规则晋升一次。没有新增执行状态、请求权限字段或 client-supplied generation。
- `runtime/graph_handoff.py`：唯一 Handoff Authority 在确认正式 Head 后按来源分派；Initial 只调用新增的纯验证/构造函数 `runtime/initial_execution.py`。原 revision 验证、前缀证明、staged 写入与 STAGING→STATE_PREPARED 三段流程继续使用。
- `runtime/initial_execution.py`：从正式 Ledger + Materialization 验证 Initial Commit、完整 Plan/Bindings/Blueprint、package checksum、recipe、当前 Mission head/revision、Frozen Basis、scope、Workflow/domain、Profiles、双 Catalog、loweringOptions、输入摘要和当前授权。不会重新规划、重新下沉或从可变目录补齐图。
- `runtime/execution_permit.py`：唯一 Permit Authority 复用 PREPARING→Checkpoint→Identity→Workflow ISSUED 的原 Saga，仅在必要位置增加 Initial 分支。通过现有 Lifecycle 的 `on_run_prepared` 首次登记 Identity；没有新建 Workflow Run，没有更改 GraphVersion，也没有创建执行 Attempt。
- `support/stores/graph_activation_store.py`：正式 Run 写入时交叉校验 Permit/Handoff/Activation/Materialization 的来源类型一致。

旧 JSON 的兼容不仅是“能解析”：新增 sourceKind 对默认 graph_revision 不序列化，包含嵌套 IdentityLink、candidate 和 Permit，避免改变历史 `content_fingerprint(handoff)`、staged 指纹与 checksums。永久测试对真实 revision Journal 的旧 wire 字段集、规范化指纹、nullable source 拒绝和原生 Permit 验证建立闭环；Initial 始终序列化显式 sourceKind。未补写旧记录。

### Identity 的两个版本命名空间

真实 Lifecycle `_ensure_blueprint` 按 Mission 分配 Identity Blueprint 版本；正式 Activation Head 按 Run 管理图版本。首次新 Mission 两者都是 1；同 Mission 已有别的 Run/Blueprint 时，Initial Run 的正式 GraphVersion 仍为 1，而 Identity Blueprint 分配计数可能为 2。

本轮不修改 Lifecycle 的分配规则，也不造 GraphVersion 0。Initial 验证同时要求：Identity Run.graph_version == Identity Blueprint.version；完整 Blueprint.graph 的 graphId/version == 当前正式图；Mission 归属、Run.metadata.runtimeGraphId、compiledPackageChecksum、完整 Plan 和逐节点绑定/快照一致。B2 既有版本比较保持原分支语义。测试分别覆盖全新 Mission 和已有 Identity 历史的 Mission，不能把 Identity 分配计数当作第二个正式 Activation Head。

### 当前来源重验与合法 Identity 变化

`runtimeFingerprint` 保留其历史接受含义，不伪造激活前 Run 快照。当前执行态改由正式 Head、包、Run、Permit 和执行证据验证。重新捕获当前编译静态来源时，除 Identity snapshot 的合法晋升外均需逐字段匹配封存正文；Identity latest 只能是原 snapshot 或本次接受的完整 Plan，最终必须经实际 Blueprint/TaskBinding/TaskPlan/Identity 映射验证为本次候选。

PREPARING 的每个 Workflow fence 同时检查本 Run 仍未执行：无 completed/active/非 pristine Step、无 Receipt、无独立 NodeExecution、无 Identity Attempt。Checkpoint 晋升后突然出现未知 WAL 也不能签发。当前 Permit Authority 被卸除、当前身份/授权/取消、Mission revision、接受头、输入、scope、Profile/Catalog/Workflow/编译策略发生漂移均拒绝。原 B2 NodeRunner 前 guard、transport retry 前 guard、Attempt 与 ResourceBinding 校验没有被删除或放宽。

## 持久化、Saga 与执行线性化点

1. Handoff 先在 Workflow 表写 STAGING，再向既有独立 checkpoint DB 的 staged 表写空正文，再经重验确认 STATE_PREPARED。staged 不是正式恢复头。
2. Permit 在 Workflow 记录 PREPARING，固定 permitId、attemptGeneration、staged/promoted checkpoint 身份、sourceRun/Identity/Principal 指纹；同 Handoff 唯一索引与 key 纪律复用原实现。
3. `CheckpointStore.save_promoted(expected_source_version=0)` 对“无任何正式 Checkpoint”做 CAS，创建 version 1。这个 0 是空表计数，不是持久化或伪造的源 Checkpoint；Record 中历史 source 仍为 null。
4. 既有 Identity Lifecycle 在自己的数据库事务内登记接受 Plan、Blueprint、绑定及 Identity Run。部分登记失败回滚；ACK 丢失则通过完整正文验证识别已完成晋升。
5. 最终 Workflow `BEGIN IMMEDIATE` 再验证当前 Head、Run 全指纹、当前来源/授权、staged/promoted CP、Identity 与 journal，在同一事务将 Permit 更新 ISSUED 并安装 Run executionPermitId/generation/checkpoint 投影。**该 COMMIT 是执行许可线性化点。**
6. `execute_prepared_run` 的原 claim、Checkpoint 校验、Scheduler、ResourceBinder、Identity Attempt、NodeRunner、ValueStore/Receipt 流程随后才可运行。Permit 不提前选择或预留执行资源。

Checkpoint/Identity 与 Workflow 不是联合事务。跨库步骤完成但最终未确认，只留下 PREPARING，不能执行；恢复以原 Key 和已持久化正文逐步对账。不同 Key 不允许抛弃旧 PREPARING。Workflow COMMIT 后 ACK 丢失返回或重建历史同一事实，不签发第二份 Permit。

## 实际失败切口与永久反例

新测试全部使用真实临时 SQLite 和正式 Initial 接受→物化→暂停激活→Handoff 链。没有预填成功 Receipt、Step、Checkpoint 或 Agent 输出。

- 无 Permit 拒绝 claim；ISSUED 后实际调用注册 Native Agent A，输出经过原审计/Provenance/ValueStore，生成 committed Receipt、真实 Attempt/StepExecution、实际资源绑定与后续 Checkpoint。重放 key 不重复签发或调用 A。
- 两个独立 Runtime/SQLite 连接同/异 Key 竞争：一个 ISSUED；锁占用可明确拒绝，后续原 Key 查询/重放确认唯一事实。
- Checkpoint 写前失败、Checkpoint COMMIT ACK 丢失、Identity 事务中途失败（真实 create_run 后抛错、事务整体回滚）、Identity ACK 丢失、Workflow SQL trigger 中止最终更新、Workflow COMMIT ACK 丢失均有真实存储实验。
- Checkpoint 写入后权限撤销、Profile 漂移、Authority 卸除、未知 WAL 注入均保留 PREPARING，不能派发。
- source/permission/cancel/Checkpoint/Identity/Workflow/Catalog/Mission/scope/input 各类已签发后的变化仍不能调用 Agent。
- node.started 已持久化后再撤权、取消、篡改资源绑定或 Identity，触发原调用前 guard；事件切口明确触发，Agent 调用数为零。预期异常包括既有 ACGSuperstepError 包装，不将其误判为成功。
- Agent 确实进入后抛异常，无成功收据，Checkpoint reconciliation 和下一次执行均不能自动重试；不生成 not_invoked 证明。
- spawn 子进程在首次正式 CP COMMIT 后 `os._exit(81)`，及 ISSUED 的 Workflow COMMIT 后、ACK 前 `os._exit(82)`，独立 Runtime 通过原 Key 恢复同一 Permit 后执行 A。
- 另一 spawn 子进程实际执行 A，并在完成 Checkpoint COMMIT、Run 尚未确认时 `os._exit(83)`。新 Runtime 的直接 claim 首先拒绝；既有 PermitRecovery 用 committed 证据对账后不重调 A。实际调用日志仅一行 A，Receipt 唯一，Permit ID 不变。

开发反馈中确认两类夹具问题并修正：CheckpointStore 的线程归属不能靠跨线程共享实例规避，竞争测试改用各自重建 Runtime；SQLite backup 目标必须在源树外，避免递归复制自身。用真实已准备但未执行的 SQLite 只读种子隔离克隆，减少重复规划/建库；保留每例真实签发、执行与失败断言，没有放宽任何生产 guard 或既有测试。

## 下一 PR 的最小宿主合同

无需新增 Runtime 或控制状态机。显式装配既有 Planning Commit、Materialization、Activation、Handoff（含 staged store）、ExecutionPermit 与 Identity Lifecycle，使用同一规范化 Workflow SQLite、正式 Checkpoint/Identity/ValueStore。这里只依赖已准备的 Schema；不把构造服务变成业务数据库升级。

| 宿主动作 | 既有接口及纪律 |
|---|---|
| 查询 | 先用正式 MissionSemanticService 对可信主体授权读取，再读 Run、activation store.head(run_id)、handoff_for(activationId)、permit_for_handoff(handoffId)；验证同一正式身份链，返回精简投影 |
| 请求首次执行 | 当前 Head 必须为 Initial v1；未有 Handoff 才调用 prepare_graph_handoff；已存在则查询原事实。随后 issue_execution_permit(handoffId, idempotency_key=原Key) |
| 取得回执 | ISSUED/IDEMPOTENT_REPLAY 表示持久事实；PREPARING/REJECTED 不授权执行。key 应按 Run/Activation 命名并由宿主持久保留，不让模型指定 generation/checkpoint/权限 |
| 原生运行 | 显式 await execute_prepared_run(run_id)，保留当前可信主体上下文与所有调用前 guard。Historical replay 不是绕过当前授权的 bearer token |
| 取消 | 使用现有 cancel(run_id)，入口仍需正式写授权；不通过改投影撤回或伪造 Permit |
| 重启/恢复 | PREPARING 直接按原 Permit key 对账，不重新 prepare 一个依赖“无源 CP”的 Handoff；执行期使用 reconcile_execution_checkpoint 与既有 Runtime 恢复入口。不确定副作用保持阻断 |

激活 Journal 的 ACTIVATED_PAUSED 是历史激活事实；UI 应组合当前 Permit 与 Run 状态显示已授权/执行中，不能新增一套执行状态权威，也不能仅凭 Identity pending 或原始 Run 投影推断可执行。下一 PR 应复用正式认证、owner/tenant 和当前 Mission 授权，不能接受请求体提供的 permission、sourceKind、执行身份或恢复点；不返回完整封存正文或原始输入。

本轮未接入 HTTP、前端或默认生产 Composition Root。当前交付为受限宿主 SDK 能力和测试证据，不代表默认产品入口已完成人工验收。

## 测试快照与剩余边界

本轮 445 个 src/tests 文件，新用例 33 项。未运行全量 pytest。门禁仍为 300 秒；以独立 ACCEPT 的 C2A-2 443 文件清单作为变化基线，旧恢复深实验与 C1 纵向场景单独记录，避免与门禁机械重复。

运行环境：Windows 11 build 26100，Python 3.14.5，默认计时环境，没有请求 1ms 分辨率；使用临时 SQLite、注册的确定性 Native Agent，无外部模型服务调用。测试中的故障注入不触碰正式业务数据库。

开发专项执行于中间快照 `79998a7e3c373c61a640aa702898a66ed3c7f489b42fdead7385a2802599f135`：

- `python -m pytest -q tests/components/planner/test_initial_execution_permit.py --tb=short --durations=0`：33 passed，pytest 141.48 秒，含进程启动墙钟 144.486 秒，exit 0。原始记录 `tmp/c1_audit/c2a3_initial_l1.log`、同名 JSON。
- `python -m pytest -q tests/components/planner/test_permit_recovery.py tests/components/planner/test_permit_recovery_final_audit.py tests/runtime/test_kernel_vertical_slice.py::test_contract_revision_restart_delivers_canonical_artifact_and_http --tb=short --durations=0`：20 passed，2 warnings，pytest 140.95 秒，含启动墙钟 145.064 秒，exit 0。原始记录 `tmp/c1_audit/c2a3_recovery_regression.log`、同名 JSON。这是独立深度验证，不混入五分钟门禁耗时。

第一次正式 `python scripts/freeze_gate.py`：83 passed / 1 failed，墙钟 251.557 秒，exit 1，未超预算。失败证据保留于 `tmp/freeze_gate/20261020T114519Z.log` 和 JSON。门禁按历史耗时排序，导致 fresh Mission 用例在模块可复用数据库种子建立之后运行；该用例克隆了已有物化 Journal，却复用通用 `initial-materialize` Key，正式 Authority 正确以 DUPLICATE_CONFLICT 拒绝。专项按默认顺序运行没有暴露这一夹具问题。

修复仅限新测试夹具：显式 fresh Mission 用例使用真实独立空数据库，其他用例仍采用 SQLite backup 隔离种子；没有改 Key 冲突合同、没有修改生产实现或既有断言。先以 `test_initial_saga_recovers_same_key_after_real_store_failures[checkpoint_before]` 再以 `test_initial_permit_and_native_first_node[True]` 重现顺序，修正后 2 passed / 18.80 秒。完整失败门禁和该修正均保留，不将第一次运行计为通过。

最终 src/tests 聚合：445 文件，`cb5809b8a2e29278d39d6ab70c6bd1567da7073148195201d013f1105f9a2c47`。该摘要与中间快照仅相差新夹具的 fresh Mission 隔离；20 项恢复深度验证涉及的生产源码和测试未再改变，作为同一生产实现的辅助证据，不冒充最终聚合快照的全量结果。最终门禁单独覆盖新夹具、全部新增安全反例及旧 Permit 核心拒绝合同。

最终正式门禁：仓库根目录执行 `python scripts/freeze_gate.py`，UTC 2026-10-20 11:52:28 至 11:56:50（精确时间见 JSON），总墙钟 **262.076 秒 / 300 秒**，**84 passed / 0 failed / 0 skipped**，exit 0，未超时，PASSED。原始日志与机器结果为 `tmp/freeze_gate/20261020T115233Z.log`、`tmp/freeze_gate/20261020T115233Z.json`；最终源码摘要与上文一致，测试期间未变化。集合包括新增 Initial 33、既有 Permit 9 与独立对抗 17、架构 15、原 Handoff 2、Initial 物化/暂停/CAS/进程恢复 7、旧 Worker 快照拒写 1；没有重复节点。此前失败门禁不计入此次通过数。

最终 `git diff --check` exit 0；仅有 Git 的 LF/CRLF 提示，不是空白错误。HEAD 保持 `44663b0edfa107dc530cb5d3a85e8d26510ada19`，暂存区为空，10 个阶段文件全部保留未暂存/未提交；无 Push、Merge、部署或业务数据库升级。

摘要算法复用 `scripts/freeze_gate.py::source_snapshot`：对 apps/agentOS 的 src/tests Python 文件按相对 POSIX 路径排序，逐一计算原始字节 SHA-256，再依原函数规定聚合；不进行换行归一化。API 独立摘要保持 `b78ffdd8d0b1c004f9befdd63c7372070cf9a733c244f86591328897791ccc21`。门禁脚本 SHA-256 `06816f400a6d5a6143ead0f9d32af1d70a2715202cbbcd7223e05df1469d0637`，基线清单文件 SHA-256 `cefc1464bf5031dcb0b57bdce5dfb603c2de92c899cd9d9dd8a1c66cea63cef3`。

门禁 changed-file 映射覆盖本轮 7 个 src/tests Python 变更，无未映射或缺失路径。旧 GraphActivationStore 的实际改动只有 Permit 来源类型一致性，选择其 CAS/暂停/重启/旧 Worker 关键节点，未重复运行不受该改动影响的全部编译反例。旧深度恢复 20 项另列；未运行全量、扩大性能矩阵、默认生产应用及前端人工验收，不宣称全量无回归。

本阶段实现范围为 Initial v1 的唯一许可、真实首节点执行以及已支持故障切口的恢复，不声称 Initial 业务样例的整份最终交付物已经通过产品人工验收。旧 C1 完整交付物/HTTP 场景的独立回归只证明既有链路兼容。下一 PR 仍需显式宿主装配、正式认证与当前 Mission 授权、查询/取消/恢复入口及人工操作验收；不能将本报告升级为生产部署许可。

问题分类：开发验证中未留下已证实、未解决的 P0/P1；夹具排序缺陷已保留失败日志并修正。剩余 P2/受限范围包括：当前来源重验带来的多数据库读取开销尚无本阶段大图性能基准；默认生产装配与用户操作入口未接入；同 Mission 多 Run 的 Identity 分配计数不同于正式 Run GraphVersion，已分别校验，未来图修订消费端必须保持此命名空间区别。跨库非联合 CAS、未知副作用以及不支持的恢复切口是明确保留边界，不能据门禁通过宣称消失。

保留限制：单机受控 Native Runtime、无控制 DAG；无跨数据库联合 CAS/跨机器持久租约；最后一次外部来源/授权读取与 Workflow COMMIT、外部调用之间不是全局原子撤销。已经进入 Agent/远端执行体的副作用不能由本地 Permit 原子撤销。版本/来源不匹配、Receipt-only、未知 WAL、无法证明的恢复点继续阻断；不承诺跨 Run 外部副作用去重。Initial 图的后续任意图修订/控制循环、换主体重新授权、新后端及默认产品装配均未开放。
