# PR-C2A-3 Initial Execution 独立架构验收（PR-C2A-3-AUDIT）

状态：**ACCEPT（受限合同下的 V1 Native Runtime 内核基线，可冻结）**。

验收人角色：独立架构验收工程师。全程未依据实施报告下结论；所有判定均来自对真实源码、真实 SQLite 链路与真实进程终止的独立检查与对抗实验。验收期间生产源码零改动，未发现 P0/P1，无需修复。

## 一、入场与最终源码摘要

| 项 | 声称值 | 独立核验 | 结果 |
|---|---|---|---|
| 实施前 HEAD | `44663b0e…da19` | `git rev-parse HEAD` | 一致 |
| 入场工作区 | 6 修改 + 4 未跟踪，暂存区空 | `git status --porcelain` | 一致 |
| src/tests 聚合摘要 | `cb5809b8…a2c47`（445 文件） | 独立复算（逐文件原始字节 SHA-256 → 排序 manifest → 聚合），不复用 `freeze_gate.py` 实现 | 一致 |
| 门禁脚本 SHA-256 | `06816f40…d0637` | 独立计算 | 一致 |
| 基线清单 SHA-256 | `cefc1464…cef3` | 独立计算；清单自洽（443 文件，聚合 `d08de700…e0c9` 与 HEAD 树 443 个 py 文件吻合） | 一致 |
| API 独立摘要 | `b78ffdd8…ccc21` | 独立计算 | 一致 |
| `git diff --check` | exit 0 | 复验 exit 0，仅 LF/CRLF 提示 | 一致 |

`scripts/freeze_gate.py` 相对 HEAD 的改动仅为：默认基线由 C2A-1 清单切换为 C2A-2 ACCEPT 清单，并为 6 个本轮变更路径新增测试映射规则；无门禁语义弱化（预算上限仍 300 秒、超时永不折算为通过）。

最终摘要：门禁运行前后源码聚合均为 `cb5809b8…a2c47`、445 文件，测试期间无变化。验收结束时工作区与入场逐文件一致，全部变更保持未提交、未暂存，未 Push、未 Merge、未部署。

## 二、Initial 与 Revision 执行合同对比（独立源码核验）

合同层（`src/contracts/graph_handoff.py`、`src/contracts/execution_permit.py`）四个 `model_validator` 构成来源类型隔离的单边强制：

| 合同事实 | Initial（v1） | Revision（≥2） | 源码位置 |
|---|---|---|---|
| sourceCheckpoint 三元组 | 必须全 null | 必须全非 null 且 version≥1 | `GraphHandoffRecord.consistent` |
| graphVersion | ==1 | ≥2 | 同上 + `ExecutionPermitRecord.consistent` |
| IdentityLink.sourceGraph/sourceBlueprintId | 必须为 null | 必须存在 | `GraphVersionIdentityLink.source_boundary` |
| prefixAttemptIds | 必须为空 | 携带已证前缀 | 同上 |
| staged 执行通道 | 除 runId/graphId/graphVersion/checkpointId 外必须为空 | 允许完成前缀正文 | `StagedGraphCheckpoint.consistent` |
| promoted checkpoint | version==1，源为 null | version==source+1 | `ExecutionPermitRecord.consistent` |

分派点安全：`GraphHandoffAuthority._validated_candidate` 在验证正式暂停 Head（`validate_activation_run`）、无 v2 恢复头、大小界限与执行槽占用之后，才按 `activation.source_kind == "initial_plan"` 分派到 `runtime/initial_execution.py`（graph_handoff.py:79-81）；Initial 不复用 revision 的前缀验证代码，也不存在缺字段推断路径。Permit 侧要求 `handoff.source_kind == activation.source_kind`（execution_permit.py:128-129）；`GraphActivationStore._issued_permit` 在正式 Run 写入时交叉校验 Permit/Handoff/Activation/Materialization 四方 source_kind 一致（本轮该文件唯一改动，diff 核实仅 3 行）。

Wire 兼容独立实测（pydantic 2.13.4）：默认 `graph_revision` 时 `exclude_if` 使 `sourceKind` 不序列化，历史 `content_fingerprint(handoff)`、staged 指纹与 checksums 不变；Initial 恒序列化显式 `sourceKind`。既有 revision Journal 的旧字段集指纹测试复跑通过。

## 三、Permit 唯一签发线性化点

线性化点为 `_reconcile` 最终 Workflow 事务的 COMMIT（execution_permit.py:202-230）：同事务内重读 permit 必须仍等于原 PREPARING 事实、重跑 workflow fence 与外部晋升断言，经 `_issue` 的 SQL 级 compare-and-swap（`UPDATE … WHERE status='PREPARING' AND checksum=?`）翻转为 ISSUED，并安装 Run 的 executionPermit 投影 / executionPermitId / executionGeneration / checkpointId，`runtime_revision+1` 后提交。该 COMMIT 之前的一切中间态（STAGING、staged 外库写入、checkpoint 晋升、Identity 登记、PREPARING）都不构成执行许可。

唯一性由四层独立机制叠加：Permit 表 `permit_id` 主键 + `idempotency_key/handoff_id/activation_id` 三个 UNIQUE 索引（数据库层）；`BEGIN IMMEDIATE` 事务 + 进程内 run 锁 + 跨进程 run fence（OS 级）；签发前重验 `_validated_candidate` 与持久 handoff 逐字节一致；`_assert_workflow_fence` 拒绝 Run 已携带任何 executionPermit 投影（防双签）。跨进程/跨连接同 Key 重放实测返回 `IDEMPOTENT_REPLAY` 且 permit_id 不变；不同 Key 绑定同一 handoff 在数据库唯一索引与 `permit_for_handoff` 预检双重拒绝。

Checkpoint 首次晋升的无源头 CAS（`save_promoted`，checkpoint.py:152-166）：`expected_source_version` 与 `COALESCE(MAX(version),0)` 比较——Initial 传 0 即"当前不存在任何正式 Checkpoint"的空表断言，不是持久化或伪造的 v0；已有任意 checkpoint 即 `CheckpointConflictError`；同 identity 重放要求内容逐字节一致。

## 四、Identity、Checkpoint 与 Attempt 全身份关系

两个版本命名空间保持区分（本轮核心新增语义，独立反例 A5 实证）：

- **Identity Blueprint.version**：按 Mission 分配的计数（`_ensure_blueprint`）；同 Mission 第二个 Initial Run 分配 v2。
- **正式 Runtime GraphVersion**：按 Run 的 Activation Head；任何 Initial Run 恒为 1。

`_identity_matches_candidate` 的 Initial 分支（execution_permit.py:309-320）同时绑定两组事实：`identity_run.graph_version == blueprint.version`（Identity 命名空间内部一致）与 `blueprint.graph["version"]/graphId == record.graph_version/graph_id` + `runtimeGraphId` + `compiledPackageChecksum`（Identity 挂钩正式图与编译包）。A5 实测：第二 Run `blueprint.version==2`、`permit.graph_version==1`、两者互不混淆，第一 Run 已结算的 Permit/Receipt/Checkpoint 事实不受第二签发破坏。

Attempt 身份是 generation 的确定函数：`attempt_<sha(generation, run, step, attempt_no, loop_path)[:12]>`（acg_execution.py:602-611）；generation 又由 permit_id 派生，permit_id 由 handoff+key+staged 指纹派生——A1 独立复算该公式与真实 `nodeExecution.attemptId` 逐字节一致，`executionInstanceId` 以 permit generation 为前缀。检查点正文携带 `executionPermitId/executionGeneration`，`_assert_recovery_head` 要求当前 Run 引用的 head 与 permit 世代匹配，未确认的外部检查点写入是恢复屏障而非回退许可。

## 五、Saga 故障与真实进程恢复矩阵

全部切口在真实临时 SQLite 上独立复验（复跑 + 本轮新增切口）：

| 切口 | 验证方式 | 持久残留 | 恢复结果 |
|---|---|---|---|
| Checkpoint 写前失败 / 写后 ACK 丢失 | 既有真实存储实验（复跑通过） | PREPARING | 原 Key 重发 → ISSUED，同一 permit_id，无 Agent 调用 |
| Identity 事务中途回滚 / ACK 丢失 | 既有（复跑通过） | PREPARING，Identity 无 Run | 同上；回滚后 Identity 库确无残留 |
| Workflow 确认 SQL 中止 / 最终 COMMIT ACK 丢失 | 既有（复跑通过） | PREPARING / ISSUED | IDEMPOTENT_REPLAY 返回同一事实 |
| **Identity 真实 COMMIT 后、Workflow 确认前进程死亡（exit 84，本轮新增）** | spawn 子进程 `os._exit(84)`（独立脚本，非异常注入） | checkpoint v1 + Identity 已登记 + Permit 仍 PREPARING | 重启进程原 Key → ISSUED 同 permit_id；claim 先拒绝未签发态；随后执行 Agent 恰一次，Receipt/Checkpoint 唯一 |
| Checkpoint COMMIT 后进程死亡（exit 81）/ ISSUED COMMIT 后 ACK 前（exit 82） | 既有 spawn 真进程实验（复跑通过） | PREPARING / ISSUED | 同一持久事实，不重复签发 |
| 执行期 Checkpoint COMMIT 后、Run 确认前死亡（exit 83） | 既有（复跑通过） | head 领先 Run 确认 | 直接 claim 拒绝；`reconcile_execution_checkpoint` 对账后恢复，Agent 调用日志仅一行 |
| Checkpoint 已晋升、Permit 未签发即派发 | 本轮 A4 + 既有 | PREPARING | claim/assert_dispatchable 拒绝 |
| 已发生未结算外部副作用 | 既有 unknown-failure 实验（复跑通过） | 无成功 Receipt | 两次 execute 仅进入 Agent 一次，reconciliation 与再执行均不自动重试 |

## 六、安全反例（独立对抗实验，10/10 通过）

脚本：`tmp/c2a3_audit/test_c2a3_audit.py`（gitignore 内，零生产改动；实现零修改、零测试放宽）。

| # | 反例 | 结果 |
|---|---|---|
| A1 | 无 Permit claim 拒绝；全链签发后真实 Native Agent 仅执行当前图合法节点；同 Key 重放/异 Key 拒绝；幂等重入无第二次副作用 | 全部按合同拒绝/通过 |
| A2 | DB 直写伪造"已完成"步骤 | handoff REJECTED、permit REJECTED、执行拒绝，零 Receipt |
| A2b | 注入图外节点 GHOST 的绑定需求 | 执行拒绝（编译包与 Run 需求一致性防线） |
| A3 | 全指纹自洽的伪造 ISSUED Permit 行 + 完整 Run 投影（强攻击者，含正确 principal/candidate 指纹与 checksum） | Identity 库无对应登记即拒绝执行 |
| A3b | 重算 checksum 篡改已签发 Permit 的 attemptGeneration | Run 投影与 Permit 逐字段绑定拒绝执行 |
| A4 | 已有 checkpoint v1 时 `save_promoted(expected_source_version=0)`；删除 handoff Journal 后重建 Initial handoff | CAS 冲突；REJECTED，无源 CAS 无旁路 |
| A5 | 同 Mission 第二个 Initial Run | Blueprint v2 / GraphVersion 1 命名空间不混淆；第一 Run 已结算事实不变；两 Run 各自恰一次执行 |
| A6 | ISSUED 后卸除 Permit Authority | 执行拒绝（claim 与 fence 双防线）；重挂后同一事实可执行 |
| A7 | staged 篡改三变体：伪造完成前缀（合同层直接拒绝）、改写合同未约束字段并重算 checksum（指纹绑定拒绝）、saga 中断后篡改（恢复阻断） | 全部拒绝，PREPARING 不可派发 |
| P1 | 真实进程死亡切口 exit 84（见矩阵） | 同一 Permit 事实恢复，Agent 恰一次 |

安全合同 10 项逐条结论：全部成立。逐项证据为——(1) 来源隔离：§二合同层+分派点+四方校验；(2) 无伪造 v0/历史 CP/完成节点/Receipt：CAS 空表断言 + pristine 检查 + A2/A4；(3) 唯一 Handoff Authority 与既有 Journal：构造器同一性校验 + 三段 prepare 复用 + authority 身份复检；(4) 无源头 CAS：§三 + A4；(5) 命名空间：§四 + A5；(6) PREPARING 非许可：线性化点 CAS + A1/A4/P1/A7 的 PREPARING claim 拒绝；(7) 重放/并发唯一：四层机制 + A1 + 既有并发测试复跑；(8) 撤权/取消/漂移不绕过调用前 guard：claim/每步/invocation 三层 guard + A6/A3b + 既有 14 项漂移与 last-guard 测试复跑；(9) 未知副作用阻断：`assert_settled_operations`（prepared WAL 非失败回执）+ unknown-failure 复跑；(10) 不破坏 B2：20 项恢复/C1 回归 + 门禁 revision 集合 + wire 指纹测试复跑通过。

## 七、门禁结果与未覆盖范围

正式门禁 `python scripts/freeze_gate.py`（本轮独立执行，仓库根目录）：**PASSED，84 passed / 0 failed / 0 skipped，墙钟 255.63 秒 < 300 秒预算**，exit 0；changed-file 映射覆盖全部 7 个 src/tests 变更路径，无未映射/缺失；运行前后源码摘要不变。原始记录：`tmp/freeze_gate/20261020T131858Z.{log,json}`。

辅助独立验证（不计入门禁，单独执行）：新增 Initial 33 项复跑 134.90 秒全通过；恢复深实验与 C1 纵向回归 20 项复跑 148.04 秒全通过；本轮对抗反例 10 项 70.04 秒全通过。三次均为空载顺序执行。

未覆盖范围（如实登记，不因门禁通过视为消失）：

- 全量 AgentOS pytest 未运行（按本轮任务书约定不重复执行）。
- 无大图/多数据库读取的性能基准（当前来源重验的多库读取开销未量化）。
- 默认生产 Composition Root、HTTP API、前端、宿主操作入口均未接入（C2B 范围）。
- 同 Mission 多 Initial Run 的 mission-latest-commitment 语义：后一次 Initial 接受会使先前未执行 Run 的签发/执行 fence 以 STALE_MISSION fail-closed（安全方向正确；A5 以"先执行完再接受第二 Run"的顺序验证正向路径，逆序拒绝行为属设计语义，C2B 宿主合同应明确"每 Mission 一个活跃 Initial Run"）。

## 八、跨库与单机限制（保留边界）

Checkpoint/Identity 与 Workflow 非联合事务：跨库步骤完成而最终未确认只留下 PREPARING，恢复以原 Key 逐库对账；不同 Key 不允许抛弃旧 PREPARING。无跨数据库联合 CAS、无跨机持久租约；最后一次外部来源/授权读取与 Workflow COMMIT、外部调用之间不是全局原子撤销；已进入 Agent/远端执行体的副作用不能由本地 Permit 原子撤销；版本/来源不匹配、Receipt-only、未知 WAL、无法证明的恢复点继续阻断；不承诺跨 Run 外部副作用去重。运行形态为单机受控 Native Runtime、无控制 DAG。

## 九、最终判定

**ACCEPT。** Initial Graph 首次执行在受限合同下可安全获得执行许可，与既有 Revision 执行体系共同构成统一 Native Runtime 内核；可冻结为 V1 核心内核基线。该结论限于本 PR 交付的受限宿主 SDK 能力与测试证据，不构成生产部署许可——默认产品装配、HTTP/前端入口与人工操作验收属下一阶段。

## 十、C2B-ARCH 入场清单（下一阶段横向审计范围）

需横向审计的正式生产调用链（全部为显式装配，当前默认装配未接入）：

1. **宿主装配链**：`enable_planning_commit` → `enable_graph_materialization` → `enable_graph_activation` → `enable_graph_handoff（含 staged store）` → `enable_execution_permit` + Identity Lifecycle，共用同一规范化 Workflow SQLite 与正式 Checkpoint/Identity/ValueStore；装配服务不得升级业务数据库。
2. **认证与授权链**：`semantic_principal_provider` / `MissionSemanticService.authorize` / owner·tenant / 当前 Mission 授权；请求体不得携带 permission、sourceKind、执行身份、generation、checkpoint 或恢复点。
3. **查询链**：MissionSemanticService 授权读 → Run → `activation store.head(run_id)` → `handoff_for(activationId)` → `permit_for_handoff(handoffId)`，验证同一正式身份链后仅返回精简投影；不返回完整封存正文或原始输入。
4. **首次执行请求链**：Head 必须 Initial v1 → 未有 Handoff 才 `prepare_graph_handoff`，已存在则查询原事实 → `issue_execution_permit(handoffId, idempotency_key=原Key)`；Key 按 Run/Activation 命名并由宿主持久保留；ISSUED/IDEMPOTENT_REPLAY 为持久事实，PREPARING/REJECTED 不授权。
5. **原生运行链**：`execute_prepared_run` → claim fence → Scheduler/ResourceBinder → invocation guard → Receipt/ValueStore → `reconcile_execution_checkpoint`；Historical replay 不得当作绕过当前授权的 bearer token。
6. **取消链**：`cancel(run_id)` 走正式写授权；不通过改投影撤回或伪造 Permit。
7. **恢复链**：PREPARING 按原 Permit Key 对账（不重新 prepare 依赖"无源 CP"的 Handoff）；执行期 `reconcile_execution_checkpoint` 与既有 Runtime 恢复入口；不确定副作用保持阻断。

尚未接入、C2B 需新建或补齐的模块：默认生产 Composition Root（wiring）、HTTP API 的 Initial 执行入口（apps/agent/app/api/agentos_v2.py 现仅覆盖 revision 链）、前端授权状态组合展示（ACTIVATED_PAUSED 是历史激活事实，UI 须组合当前 Permit 与 Run 状态）、宿主幂等 Key 持久化、审计/操作日志投影、跨机部署形态评估。Identity 消费端须保持 Blueprint.version（Mission 分配计数）与 GraphVersion（Run 图版本）的命名空间区别。
