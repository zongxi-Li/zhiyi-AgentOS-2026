# PR-S03-02B1：Checkpoint / Identity 可信交接

Status: SELF-TESTED; all final gates passed; awaiting independent review (no self-ACCEPT).

## 1. 入场与 S03-02A 冻结

入场 master，HEAD `dadf0826419a2dff96bbd8661a172bf2bd003666`，index 为空。五个 tracked Python 修改、两个新增 Python 和 S03-02A 独立报告与报告清单一致；另有用户 EX-00 文档，保留、不纳入冻结。

先完整读取 diff、新增辅助模块、507 行独立测试和独立报告，按报告算法复算 src/tests 420 个 Python 文件 raw 聚合，得到 `08c02395b172950bfae92d6fd2294224d04fad3bea8fbb2f0eacf5ee469b5720`，与 ACCEPT 快照一致。`git diff --check`、staged check 通过；逐项比较 staged blob 与工作区 LF 规范化字节，全部相同，没有格式化源码凑摘要。S03-02A 最终四组既有证据为 43/395/1037/1652 passed，不冒充本轮重跑结果。

仅按本任务授权创建本地冻结提交：

`48b7fc950837e1bdcec07abfd181f4d8fa95b6db`

标题：`fix(agentos-planner): 冻结 S03-02A 激活权威独立验收修复`。八个文件，881 insertions / 6 deletions。没有 Push/Merge。该 SHA 为 B1 基线；B1 本身保持未提交。

## 2. 改动范围与合同

| 文件（apps/agentOS 下） | 职责 |
| --- | --- |
| src/contracts/graph_handoff.py | GraphHandoffRecord、StagedGraphCheckpoint、GraphVersionIdentityLink、Receipt；版本化、extra forbid |
| src/support/stores/graph_handoff_store.py | Workflow 交接账本与外部 staged Checkpoint，显式升级、唯一约束、正文摘要 |
| src/runtime/graph_handoff.py | 唯一受控准备入口、独立真源交叉校验、跨库对账 |
| src/runtime/workflow_runtime.py | 默认 None 的显式装配与 prepare_graph_handoff 门面，13 行增加 |
| tests/components/planner/test_graph_handoff.py | 真实执行前缀、来源损坏、崩溃、恢复、写保护 |
| tests/components/planner/test_graph_handoff_recovery.py | 双进程、跨连接唯一性、故障和 ACK 丢失、阶段间来源竞争 |

另新增本实施记录。S03-02A 冻结合同、Activation Store 精确内容绑定、OS 执行互斥、Scheduler、Executor、SemanticRevisionService、Compiler、普通 CheckpointStore、Identity 生命周期和数据库原表 Schema 均未修改。

`GraphHandoffRecord` 包含 Run/Activation/GraphVersion、原 Key、源 Checkpoint ID/单调版本/正文摘要、前缀与来源指纹、版本级 Identity 关联、完整 staged 候选正文及其摘要。没有 Permit、资源绑定或调度授权字段。

候选 `state` 是既有 `ACGExecutionState` 的 JSON 序列化；运行时复用原模型读取和校验，没有另造执行状态模型。合同层不反向 import executor。新状态仍只包含原有摘要/引用通道，不把输出、ContextPack 或 Memory 正文写入 Checkpoint。HandoffId 和 candidate checkpointId 按已验证内容确定性派生，原 Key 是唯一绑定元数据，不参与改变执行内容。

## 3. 真实权威与执行身份链

原 Run 原地 v1→v2，Head/Activation Journal/Materialization/Run 为正式图版本权威。v1 Checkpoint 是历史事实；v2 Run 的 checkpointId 仍为 None、executionPermit 仍为 None。B1 不改变这些事实。

正式调用链：`WorkflowRuntime.prepare_graph_handoff(activationId, key)` → `GraphHandoffAuthority.prepare` → 同 RunLock + 同 Workflow DB 路径/Run ID 的 OS fence → 完整当前验证 → Workflow STAGING → 外部 staged 正文 → Workflow 再验证与 STATE_PREPARED。

Handoff 输入只有服务器 ID 和 Key；调用者不能提交 candidateGraph、执行状态、Attempt 身份或假授权。authority 默认 None，必须显式连接已升级的同一 Workflow ledger 和现有独立 Checkpoint DB。构造器不执行 DDL，不自动启用生产装配。

全仓引用搜索确认新表只由新 Store 读写；Runtime 的新增正式引用仅为门面和新 authority。普通恢复、Scheduler、Executor、ResourceBinder 不查询新表，不读取 staged 候选。没有替换 Run、新 GraphVersion、正式 Checkpoint 头或执行收据的写入入口。

## 4. 可信前缀与确定性推导

验证顺序的主要证据：

1. 用既有 `validate_activation_run` 校验同一 SQLite 快照中的 Head、Journal、Materialization、当前完整 Run/Package 和精确暂停投影。
2. 重读 graph_revision、parent plan_revision、完整有界接受祖先和当前 Mission 接受头；比对原始提案、候选全图、计划、绑定、Sources、commitment/proof 摘要与当前 Mission revision/Basis。
3. 使用原 ACGGraphCompiler 重编译完整候选比对 package，调用原绑定/语义校验和原 Safe-Cut；没有第二套拓扑编译器。完成前缀还必须在原 Compiler 的有效依赖边上闭合。
4. 从已存在的 v1 Identity Run、Blueprint、TaskPlan 和不可变包字段重建只用于验证的源视图，绝不保存或执行该视图。重新计算 accepted static provenance，并对比历史 Observation 和源 Checkpoint / SafeCutProof，检测当前输入、Scope、目录、Agent profile、Workflow/domain、Identity 等变化。不能可靠重建的来源直接拒绝。
5. Checkpoint 必须是 Run.supersededCheckpointId 指向的真实最新头，version 与 latest_version 一致；Run 与 Checkpoint 的全部执行通道一致，只豁免图版本、Checkpoint 引用、当前节点和已被替代的 Planner review 标记。新 Checkpoint 清理旧 review/current 标记，保留全部已验证完成证据。
6. 独立读取 ExecutionValueStore 的 receipt 和 node-execution 表，要求完整 committed、精确 Run/Step/commit/Attempt/实例身份，拒绝 prepared、unknown、缺失或多余工作。Identity Attempt 必须 succeeded，唯一 StepExecution 与 receipt 引用相同；所有 Identity Attempt 和缓存 Attempt ID 必须恰好属于该完成前缀。复用原 IdentityResolver 读取完整 ExecutionOrigin，显式核对 Mission/Run/Blueprint 外层身份、正文版本、SemanticTask Mission/Key、TaskBinding、ExecutionBinding 和实际 Attempt/StepExecution 的完整关联，将该独立来源纳入前缀摘要；读取旧绑定不会分配新资源。对 pending 源节点也核对完整 v1 TaskPlan 快照行、TaskId、SemanticTask 归属/Key 及唯一 primary Blueprint 绑定；Run 的 workflowId/runtimeGraphId/taskPlanVersion 引用必须相符。源身份摘要覆盖全部这些节点，不能只证明已完成 A。
7. 复用原 `validate_state_references` 检查输出/上下文归属、Memory 元数据、已成功 Trace 与 Provenance 哈希链/事件归属。再读取输出和 ContextPack，交叉校验已封存生产/消费摘要；Memory 正文与 committed pending-memory intent 相同，审计决定必须 allow。不会调用 NodeRunner 的重放发布路径，不重写记忆或补收据。
8. 每个输出、上下文、摘要、Memory、Trace、Provenance 通道恰好覆盖完成集合；新节点和未完成节点必须 pristine pending，不能继承 attempt、retry、输入/输出或开始/完成时间。控制图、未解决非 Planner review、skip、循环、共识、黑板/辩论状态和无法解释的旧 Attempt 保守拒绝。

权限/Identity hook 位于后续真源检查之前；最后重读 Workflow Run 检测阻塞 hook 后的缓存投影变化；取消信号和 authority 装配身份再次检查。外部 stage 写入后，以及读回 stage 后的最终 Workflow 事务内，都重新验证并要求与最初候选完全相同；不在最后 Fence 后再捕获新的身份正文构造 Journal。

## 5. Checkpoint 和 Identity 策略

原 `ACGCheckpointStore.save()` 的 MAX(version)+1 会推进正式恢复头，故本轮不调用它写 v2。

Checkpoint DB 新增独立 `staged_graph_checkpoints`，以 checkpointId 主键和 handoffId UNIQUE 保存完整引用型候选及摘要。原 `acg_execution_checkpoints`、load_latest/latest_version/list_states/resume 语义均保持。原 v1 行的完整列值（含 state_json 原字节）前后相同；用旧 Store 按候选 ID load 得到 None。

Identity 区分为：原 Mission；同一个 Run；source GraphRef 和 candidate GraphRef；既有真实 Attempt；源 Checkpoint 和 staged Checkpoint。`GraphVersionIdentityLink` 存于唯一 Workflow Handoff 决策中，关联原 BlueprintId、v1/v2 GraphRef、包摘要、原 Identity 快照摘要及完成 Attempt IDs。这里 GraphRef.checksum 采用该版本的 compiled package checksum；完整 Blueprint hash 仍由既有 Package/Materialization 链验证，不混淆两种摘要。通过 ActivationId 可追溯已接受 nextPlan / nextBindings 全文。

本轮选择版本级关联，而非通过普通 lifecycle reconcile 覆写 Domain Run 的 v1 包字段。原 Identity、SemanticTask、Blueprint、Attempt、StepExecution 行不变；缺失或损坏时拒绝，绝不自动补建。新 D 不创建 Attempt/StepExecution。B2 必须显式消费此版本关联处理新版绑定/Resolver，不能假设旧 v1 Domain Run 已经变成 v2 执行身份。

## 6. Durable Handoff 与跨库恢复

Workflow 新增 `graph_handoffs`：handoffId PRIMARY KEY、idempotencyKey UNIQUE、activationId UNIQUE，状态仅为两类真实事实：

- STAGING：Workflow 已持久化通过校验的完整意图；外部正文可能尚未写入。
- STATE_PREPARED：外部 staged 正文已读回验证，且当前可信来源在 Workflow 确认事务再次通过。

阶段均不写 Run，不进入 ACTG/GraphVersion 激活，不产生执行许可。不同 Key 竞争同一 Activation 必须拒绝并提示原 Key 对账；相同 Key 完整内容相同才能重放。忙时可返回 CONTROL_BARRIER_BLOCKED；源变化、无法证明或存储异常保持暂停，不猜测成功。

外部写入在 Workflow 写事务之外；stage 的 ID、完整正文、校验和在其自身单事务保存。外部写完进程死亡后，Workflow STAGING 仍保存完整候选，原 Key 重新验证可信来源后才能补全/确认。Workflow 确认后 ACK 丢失则读回唯一 STATE_PREPARED。已确认 stage 丢失或损坏拒绝，不静默重建掩盖损坏。

Schema 只提供显式 upgrade_schema，测试仅在临时数据库执行。构造及每次相关读取对照规范化 CREATE TABLE SQL，错误同名表不能当作有效升级；重复显式升级幂等，UNIQUE 为持久化最终保护，不拿 OS 锁代替数据库约束。

普通 save_run 无法写 checkpointId 或 graphHandoff 伪造交接，因为原完整 execution_state 暂停绑定没有放宽。历史 STATE_PREPARED 是过去准备事实，不代表当前仍可执行；重放也需重新验证，普通重启不采用它。

## 7. 验证与源码快照

开发期的绑定查询参数顺序错误通过真实成功前缀测试定位并修正；所有旧用例保持原字节。先后 32、49 项通过是开发反馈，后续增加检查和测试后重新统一运行，不能代替以下最终快照门禁。

环境：Windows 默认计时，Python 3.14.5。本轮不请求 timeBeginPeriod(1)，不跳过/放宽既有测试。日志、原始清单、实际命令和每组前后校验在 ignored `tmp/S03-02B1-final-*`，runner 为 `tmp/s03_02b1_gate.py`。

src/tests 共 425 个 Python 文件 raw 聚合：

`a26cd3ec2959eae8d1556e9fc3e53ccbdb90a8cd229552728c7d30591de5083c`

算法沿用独立报告：仓库相对路径排序，每行 `path + 空格 + sha256(raw bytes)`，LF 连接，无尾 LF，然后 SHA-256。文档不参与源码摘要。

| 六个 B1 源码/测试文件 | raw SHA-256 |
| --- | --- |
| src/contracts/graph_handoff.py | ab1a818537f80aacbbbf7ee877cf94319fc475e10123854c83ec89b6dc0dbd8b |
| src/runtime/graph_handoff.py | aba66fc8e447fa73775cf3572b0d88cfe186dcbc06373fbefe685a04e605afc7 |
| src/runtime/workflow_runtime.py | 337ea7f00790d9835df1ca4304c028ca0c0f84eae08c04d1e0ac26c101a630cd |
| src/support/stores/graph_handoff_store.py | e3465d0d6bdd63c6c4ab58033f14a2665596a0d176dae502aa01e560836fb9cd |
| tests/components/planner/test_graph_handoff.py | b8cb88ac1062b671e141e10726ab39e5f4d9878aafbd138775c0de4a0e96653d |
| tests/components/planner/test_graph_handoff_recovery.py | 64b58c04895fc508ae4461c017ba824089794eed74d871a139daa1c30bacc90d |

该六文件聚合：`bb11d09d3c425aadea8d70c3eacb1c0cec78faa9105d28888b8c071f1797b6b7`。

### 开发尾项发现的 P1：跨 Run Trace 归属（已修复）

旧快照曾得到 52 passed / 293.88s，但尾项核查发现原共享 `validate_state_references` 只按 stepId 和 STEP_SUCCEEDED 检查 `trace:A`，不检查成功事件的 runId。独立反例从真实已完成 A 出发，只通过普通 save_run 把成功 Trace.runId 改为另一个 Run；B1 当时仍错误返回 STATE_PREPARED。`tmp/S03-02B1-trace-before.log` 稳定记录 **1 failed / 8.14s**。此前单独 probe 因缺 src 路径的 collection error 是 fixture 环境问题，补齐与测试相同导入路径后才得到该真实失败。

最小修复只在 B1 validator 检查每个完成节点的成功 Trace 存在且全部归属当前 Run，不改 S03-02A 保存接口或共享 Executor；永久测试保留普通保存的完整失败路径。修复后该项 **1 passed / 20 deselected / 6.65s**。

旧门禁进程 PID 18584 及其 pytest 子进程 11348 经完整命令确认后停止，未终止其他项目进程。旧 52 项快照、结果与未完成 broad 日志存为 `tmp/S03-02B1-pre-trace-*`，不计为最终扩大回归通过。修复后增加为 53 项，曾取得 53 passed / 293.14s 与扩大 1090 passed / 1279.44s；随后发现下项 Identity 关系缺陷，故这两组也不冒充最终快照结果。

### 开发尾项发现的 P1：Identity 外层身份和语义归属未联验（已修复）

保留 Blueprint 正文、包、receipt 和所有执行事实不变，仅在真实 Identity SQLite（FK 开启）修改以下任一项：acg_blueprints.version、acg_blueprints.graph_id、A 对应 semantic_tasks.semantic_key，或把 A 的 SemanticTask.mission_id 指向另一个真实已存在的 Mission。旧 B1 均错误返回 STATE_PREPARED。`tmp/S03-02B1-identity-before.log` 为 **4 failed / 1 deselected / 28.49s**；此前版本/graphId 两例也得到 **2 failed / 1 deselected / 16.90s**。不是关闭 FK 的孤立伪造，也没有改 Blueprint 正文或补造收据。

修复在 B1 显式联验 Domain Blueprint 的外层 ID/Mission/graphId/version 与已验证正文和原 Run；确认既有 Domain Mission 存在。再用既有 IdentityResolver 的完整 ExecutionOrigin 核对 SemanticTask Mission/Key、Run/Blueprint、Attempt、唯一 StepExecution、TaskBinding 与旧 ExecutionBinding；将完整来源纳入前缀摘要，sourceIdentityFingerprint 同时绑定 Mission/Run/Blueprint，防止只改外层身份而不改变指纹。没有修改 Resolver、Identity 生命周期、Schema、Scheduler 或 Executor，也没有新绑定资源。

新增四个真实 SQL 损坏反例、缺失 Mission/SemanticTask 读故障，以及 stage 后版本/语义身份改变。针对合法前缀和这些变化的组先取得 **9 passed / 52 deselected / 49.67s**。

经完整命令确认后，仅停止旧 gate PID 38844 和 pytest 子进程 35700。其 53/1090 通过和未完成全量日志保存为 `tmp/S03-02B1-pre-identity-*`；未完成全量不计通过。该次增加为 61 项并取得 61 passed / 319.65s，随后完成下面的同组映射补核，再统一运行最终门禁。

同组补核：只把 pending B 的 SemanticTask Key 改错，或把 task_plan_nodes 的 B.taskId 改指向真实 A.taskId，之前只查完成 Origin 的 B1 仍错误 STATE_PREPARED。两者保留 FK 和全部真实执行证据；`tmp/S03-02B1-pending-identity-before.log` 为 **2 failed / 5 deselected / 14.48s**。补齐完整源计划映射校验，不仅检查完成节点；保守限定为原正式模板的一对一 primary 绑定。新 D 无 v1 源身份，不在源节点集合中补建。

开发中该新循环曾覆盖方法参数 idempotency key，合法路径得到 `handoff intent changed`；针对组 **1 failed / 12 passed / 52 deselected / 73.43s** 及时发现，已更名局部 node_key 修正，未放宽断言。修复后的组为 **13 passed / 52 deselected / 74.25s**，包括真实合法前缀和新增反例。

旧 gate 12588、pytest 38836 经完整命令核对后停止；taskkill 报告子进程 22812 已无法终止，随即按 PID 查询确认其已不存在，没有遗留旧测试工作进程。61 项快照及未完成 broad 存为 `tmp/S03-02B1-pre-source-map-*`，不计为最终扩大回归通过。最终共 **65** 项，以下三组全部基于本节最终 SHA 执行。

最终命令（cwd=apps/agentOS，依次执行）：

```powershell
python -m pytest -q tests/components/planner/test_graph_handoff.py tests/components/planner/test_graph_handoff_recovery.py --tb=short
python -m pytest -q tests/components/planner tests/contracts tests/architecture tests/runtime --tb=short
python -m pytest -q --tb=short
```

| 最终门禁 | 结果 |
| --- | --- |
| B1 定向/对抗 | 65 passed，369.77s，退出码 0，组前后源码摘要一致 |
| Planner / Runtime / Contracts / Architecture | 1102 passed in 1370.26s; exit 0; source snapshot unchanged |
| Full suite | 1717 passed, 1 warning in 1316.20s; exit 0; source snapshot unchanged |

Final gate evidence:

Source snapshot: `a26cd3ec2959eae8d1556e9fc3e53ccbdb90a8cd229552728c7d30591de5083c` across 425 Python files under src/tests. The runner recomputed the complete manifest before and after each gate; all three gates report unchanged=true.
Environment: Python 3.14.5, Windows 11 10.0.26100, default Windows timer settings. Commands ran from apps/agentOS. Pytest durations: target 369.77s, broad 1370.26s, full 1316.20s; runner elapsed times were 372.84s, 1376.07s, and 1320.11s.
The sole warning is the existing PyPDF2 DeprecationWarning from tests/components/attachments/test_attachments.py::test_pdf_and_docx_extractors. No tests were skipped, modified, or weakened.

新增覆盖包括真实 A→B→C→D、所有旧事实保持、Receipt/Execution/Value/Context/Memory/Provenance/Identity/Attempt/Checkpoint 损坏、过期 Head/Scope/权限/Basis/输入/Catalog/Workflow/Profile、真实进程死亡六个切口、双进程同/不同 Key、独立 SQL UNIQUE、写入/ACK 故障、外部 stage 后十一类来源变化、阻塞 hook 陈旧输入、普通保存伪造、重启恢复及有/无 authority 的无许可拒绝。

## 8. 限制与 S03-02B2 前置条件

1. 本轮只自测当前 Runtime、同机规范化 Workflow SQLite 路径和首次无控制 DAG 的可重建成功前缀。控制、skip/失败/多历史 Attempt、黑板/辩论等拒绝；依赖原 Identity 保留源定义，无法重建原 pending 语义的修订也拒绝，不声称通用状态迁移已完成。
2. Workflow、Checkpoint、Identity、ValueStore、Memory/Provenance 和权限没有跨库联合事务。最后各自验证之后仍可能变化，STATE_PREPARED 仅证明该验证批次及持久化引用；B2 发许可前必须重验，不能把历史记录或 OS 锁当成当前授权。
3. 同机 OS fence 不等于跨机器 lease；必须沿用 A 阶段关于 NTFS/当前生产漏斗、锁文件不可运行时删除、混合旧 worker 与网络文件系统未验证的限制。
4. P2：完整包多次重编译/解码、原 Safe-Cut 和外部证据校验在最终 Workflow 写事务内，持有 SQLite 全库写锁；5s busy 超时保守失败。同步校验无硬 deadline，部分跨库列表先读再判断，无最大包/多 Mission 性能基准。没有为性能放松必要 Fence。
5. 未实现 staged 孤儿/失效 STAGING 的自动清理或新 Key 接管；不能确认时保持暂停，使用原 Key 对账。来源绑定包含完整 Run，普通诊断/Trace 更新也可能保守地使重复 prepare 拒绝；原 Key 仍可在 ledger 查询历史事实，但不能借历史成功跳过当前验证。没有物理断电/WAL 损坏、POSIX/网络文件系统、真实 Provider E2E 或生产部署验收。Schema/摘要用于一致性，不是对管理员同步篡改全部真源的签名防护。
6. 旧 ContextPack/Trace 延用现有归属合同；正文 data/output 依赖封存 Provenance 摘要，旧引用不会被包装成新的 v2 外部结果。没有宣称覆盖所有历史 Artifact/复杂通信模板或旧资料修复。

B2 必须另设持久 ExecutionPermit Authority 和 AttemptGeneration Fence，绑定 `RunId + ActivationId + GraphVersion + CheckpointIdentity + AttemptGeneration`；验证当前 Head/原 Key Handoff/完整 stage/来源与权限后，显式决定是否接入正式 v2 Checkpoint 头、版本化 Identity/任务绑定和恢复入口。普通 lifecycle、review approval、load_latest 或 Run 字典不得代行这个状态迁移。

发许可、READY 调度、ResourceBinder、Native Executor、旧 Attempt/迟到结果拒绝及跨机器租约属于 B2，本轮均未实现。B1 没有第二套 TaskPlan/Graph/Run，也没有调用 Scheduler、Agent、Binder 或 SemanticRevision prepare/commit。后续不能通过删除 `_claim_acg_execution` 的有 Head 拒绝或把 executionPermit 改成非空字典来接线。

Final status: SELF-TESTED and awaiting independent review. HEAD=48b7fc950837e1bdcec07abfd181f4d8fa95b6db; index empty; B1 remains uncommitted. The unrelated user EX-00 document remains byte-identical (SHA-256 `2bbea373edeaefcfe9e6caca072f15c8f249c1f81dfd21380bcd8c7a0c39bf35`). No push, merge, deployment, business database upgrade, or ADR change.
