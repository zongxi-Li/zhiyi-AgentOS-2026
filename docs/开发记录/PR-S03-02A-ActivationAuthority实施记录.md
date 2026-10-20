# PR-S03-02A Graph Activation Authority 实施记录

## 状态与基线

S03-02A 最小无控制 DAG 激活路径实施与自测完成，等待独立架构验收，不宣称 ACCEPT。本轮保持未提交，不 Push、Merge、部署，不升级业务数据库，不修改正式 ADR。

入场 master / HEAD：`345ed0a953e1e772e748334294467dfe453bd5a5`，暂存区为空，工作区唯一未跟踪文件为用户的 PR-EX-00 文档（未触碰、未提交）。以 S03-01 冻结并推送的 1540 passed 基线为起点，保留全部 S02-02/S02-03/S03-01 原测试与断言，不修改其任何冻结语义。

## 入场审计与真实调用链

精读范围：graph_materialization 合同/运行时/存储、graph_revision、semantic_revision、workflow_runtime、acg_execution、runtime_recovery、state_persistence、checkpoint、value_store、sqlite_workflow_store、binder，以及 S02-03/S03-01 实施与独立验收记录。独立确认的七个事实：

1. **正式 GraphVersion 权威散落且无 CAS**。正式图版本只存在于 Run 行 `acg_blueprint.version` 与 `execution_state.graphVersion`、CompiledACGPackage.blueprint_version、Checkpoint state.graph_version；`save_run`→`_upsert_run` 是整行 UPSERT，只有 Mission 不可变、终态不回退、planningCommitRequired 不可移除、intent basis 四道既有防线，**没有任何 GraphVersion 比较型 CAS**。
2. **Run/Blueprint/Package/Checkpoint 身份关系**：Run(run_id) 是聚合根，blueprint 与 package 内嵌在 Run 行；package.run_id 必须为 None 或 run.run_id（runtime/planning_commit.py:213）；Checkpoint 按 (run_id, checkpoint_id) 隔离且有版本 CAS，state 自带 run/graph/version 身份，`checkpoint()` 要求最新头被 Run 的 checkpointId 确认且与 Run 投影逐字段一致。
3. **旧 Run 快照可以覆盖新图版本**：所有执行路径（acg_execution_service.execute 持 Run 快照多次 save_run、审核续跑、planning 应用）都是"读 Run→内存修改→整行写回"，并发激活后旧线程写回会把 v1 蓝图+execution_state 整体覆盖回去；跨进程时 RunLock 完全无效，仅 BEGIN IMMEDIATE 串行化物理写、不阻止逻辑回退。这是本轮建立 CAS 防线的实证依据。
4. **Scheduler/Review/Recovery/异步续跑的真实入口**全部汇聚于 facade `_execute_acg`：execute_prepared_run（含 planningDeferred、supersededByRunId/RETRYING 循环）、apply_review（ReviewService→`_execute_acg`）、resume_from_checkpoint（load_resume_input→`_execute_acg`）、rebind/single-step-retry 产生 successor Run 后仍回到 execute_prepared_run。唯一漏斗是执行栅栏的天然落点。
5. **收据与 Run 强绑定**：NodeExecutionRecord 身份=(operation_id, execution_instance_id, run_id, step_id, attempt_id, loop_path) 不可变且 terminal 不可变；节点收据 commitId 形如 `commit:{run_id}:{step_id}:{attempt}`；output/context/graph-patch/memory/trace/provenance 引用全部按 run 隔离 assert_reference。
6. **`SemanticRevisionService.commit()` 跨库多写**：execution_value_store.put_graph_patch（values 库）+ trace_store.append + save_graph_patch_transition（workflow 库单事务：replacement Run upsert + 源 Run SUPERSEDED + outbox）+ identity outbox flush；prepare 阶段还会经 runtime_binding_service.prepare 注册资源。无联合事务。本轮不调用 prepare/commit，只复用其无 IO 的静态 `_validate_bindings`。
7. **既有权威模式**：PlanningCommitService/GraphMaterializationAuthority 均为"Run Lock→锁内验证→昂贵纯计算在事务外→Run Lock+BEGIN IMMEDIATE 事务内全量重验→单一 INSERT"的两段式；激活权威完全沿用该纪律与锁顺序（Run Lock→store RLock→BEGIN IMMEDIATE，无逆序）。

## 执行身份策略：源 Run 原地激活

**选择：原地激活（in-place）。放弃 replacement Run。**

依据：

- GraphMaterializationRecord 的 `package.run_id == source_run_id` 被三层锁死（record.coherent 校验、packageChecksum、行 checksum）。replacement Run 要求以新 run_id 重编译包，等价于改写不可变 Journal，或另建第二套"改绑"映射链——两者都引入无法用现有 checksum 合同证明的改写。
- 收据、Checkpoint、provenance、memory、trace 全部按 run_id 隔离且 terminal 不可变。replacement Run 下旧前缀收据全部失去身份，"已完成前缀继承"只能靠重执行（违反不得隐式重执行副作用）或伪造收据（违反不得重置 receipts）。
- S02-03 Safe-Cut 合同本身按"同一 Run 上冻结前缀+新后缀"设计：protectedNodeIds 冻结、新增节点只允许挂在 pending 区域。原地激活与该合同同构，是最小闭环改动。
- 通信、记忆、证据命名空间随 run_id 保留，无迁移需求。

原地激活的两项义务及其证明方式：

- **旧执行快照无法覆盖新版本**：`_upsert_run` 新增激活头防线——`graph_activation_heads` 表存在且该 run 有 head 时，任何 blueprint graphId/version 与 head 不一致的 Run 快照在写事务内被拒绝（sqlite_workflow_store.py:_upsert_run）。激活事务自身在同一事务先写 head 再 upsert v2 Run，因此不受影响。旧线程（含跨进程独立连接）写 v1 快照在 BEGIN IMMEDIATE 串行化下必然读到已提交的 head v2 而被拒。测试以真实双线程+独立 store 连接证明。
- **旧 Checkpoint 不会被误判为新版恢复点**：激活将 Run 的 `checkpointId` 置空（原值记入 graphActivation.supersededCheckpointId 供 S03-02B 重建），checkpoint 库历史数据一字节不动。置空后旧 checkpoint 头不再被 Run 确认：任何规划/图接受链重验 `checkpoint()` 立即 CONTROL_BARRIER_BLOCKED；resume 入口即使被喂真实 v1 checkpoint，也会在执行栅栏前/身份校验（state.graph_version=1 vs blueprint v2）处失败。双重 fail-closed。

## 合同、权威与调用链

新增 `contracts/graph_activation.py`：GraphActivationRecord（frozen/extra=forbid，activationId/idempotencyKey/materializationId/sourceCommitId/mission/run/graph/source+candidate 版本/packageChecksum/commitmentFingerprint/proofFingerprint/activationPolicy/status，coherent 校验版本恰好 +1）；GraphActivationHead（run 唯一正式图版本头）；GraphActivationReceipt（ACTIVATION_PREPARED/ACTIVATED_PAUSED/IDEMPOTENT_REPLAY/REJECTED，复用既有结构化拒绝码）；`activation_projection()` 生成写入 Run 的 S03-02B 交接合同（status=ACTIVATED_PAUSED、executionPermit=None）。

新增 `support/stores/graph_activation_store.py`：继承 SQLiteGraphMaterializationStore（构造校验链自动要求物化 Journal 已就绪）。`graph_activations` 表（PK activation_id + UNIQUE idempotency_key + UNIQUE materialization_id）+ `graph_activation_heads` 表（PK run_id + UNIQUE activation_id）。显式 upgrade_schema（管理事务 BEGIN IMMEDIATE，要求物化 schema 已准备）；构造器只 mode=rw 校验实际表/索引 SQL 定义，不建库不迁移；读取时校验 typed Record、行 checksum 与全部索引列身份；`_activate_head` 单一受控状态迁移（PREPARED→ACTIVATED_PAUSED 的 UPDATE + head upsert，事务内执行）。

新增 `runtime/graph_activation.py` GraphActivationAuthority：构造时校验与物化 Journal、Planning ledger、Workflow store 同一绝对 DB 路径。`prepare(materializationId, idempotencyKey)` 与 `commit(materializationId, idempotencyKey)` 两个显式入口，输入仅可信引用与幂等身份，主体身份从服务端 `semantic_principal_provider()` 读取。

真实链路：

`ExecutionRuntime.prepare_graph_activation / commit_graph_activation → GraphActivationAuthority → 物化 Journal 正文/checksum → GraphMaterializationAuthority._validate（完整接受链+当前头+256 层有界祖先+权限+Frozen sources+source_provenance+safe-cut 重算+Fence 关闭检查）→ 激活专属验证（Run 蓝图/包仍是源版本、package.blueprint_hash==候选图摘要、_validate_bindings 语义一致）→ Run Lock → Workflow BEGIN IMMEDIATE → 同事务重验（幂等/唯一/head CAS/expected 全等/principal 一致）→ INSERT 激活行（prepare）或 UPDATE 行+upsert head+_upsert_run v2 投影（commit）→ commit`。

激活时 Run 投影切换（`_activated_run`，构造于最终事务外）：acg_blueprint=候选图、taskPlan/taskPlanVersion/taskBindings=next、compiledACGPackage 及四个包指纹=物化包、graphId/graphVersion/sourceBlueprintVersion=v2、graphDiff=graph_patch、checkpointId 置空、写入 graphActivation 交接投影；**completed_step_ids、steps 状态、output/context/memory/trace/provenance 全部证据通道原样保留**；`_sync_run_steps_to_acg` 以候选图重建 steps 列表（已有步骤状态保留、新增节点 pending）；runtime_revision+1、active_step_ids 清空（safe-cut 已要求无活跃）。历史 ACCEPTED/PROVEN/MATERIALIZED_INACTIVE 从不构成激活许可——每次 prepare/commit 都重跑全链验证。

## 持久化激活协议与 GraphVersion CAS

四类事实的区分与持久化位置：

| 事实 | 位置 | 状态 |
| --- | --- | --- |
| 物化事实 | graph_materializations（不可变） | MATERIALIZED_INACTIVE，激活后也不变 |
| 激活准备事实 | graph_activations（受控迁移） | ACTIVATION_PREPARED：完整验证通过的幂等锚点与竞争占位，**不改 Run、head 不存在，Scheduler 完全无视** |
| 正式激活事实 | graph_activations 行升级 + graph_activation_heads + Run v2 投影，三者同一事务 | ACTIVATED_PAUSED |
| 执行许可 | Run 投影 graphActivation.executionPermit | 本轮恒为 None，S03-02B 另行验证后发放 |

**线性化点**：commit 的单一 Workflow `BEGIN IMMEDIATE` 事务的 conn.commit。事务内依次：prepared 行内容复核→head CAS 判定→全量重验（expected 逐字段相等+principal+取消+authority）→journal 行升级→head upsert→Run v2 upsert（过同事务刚写的 head 防线）。任何一步失败全部回滚：head 无、Run 仍 v1、journal 行保持 PREPARED（触发器故障测试证明）。

**CAS 语义**（`_head_state`）：head 缺失→允许（首次激活）；head.activation_id==本次→已提交，幂等重放；head.active_graph_version==本次 source 版本→连续修订升级路径（v2 交接后 v3 激活，head REPLACE）；其余（含 head 高于 source、同 source 不同激活）→STALE_GRAPH 硬拒。跨进程唯一性由 SQLite 写锁+两个 UNIQUE 索引保证，不依赖单进程 RunLock。

**为何 save_run 整行 UPSERT 不构成 CAS、以及现在的防线**：普通 save_run 至今没有版本比较。本轮在 `_upsert_run` 事务内联激活头查询：head 存在时 blueprint graphId+version 必须与 head 完全一致，否则拒绝写回。旧 Worker、旧恢复请求、旧 Review 路径持有激活前 Run 快照的任何整行写回（version v1 或伪造 v99）都会在该防线被拒绝；未升级 activation schema 的既有库行为不变（向后兼容）。

## 执行隔离与旧图栅栏

核心不变量：**没有执行许可的 GraphVersion 不能被任何 Runtime 入口调度**。落地为两道防线：

1. **执行栅栏（`_execute_acg` 入口）**：所有调度/审核续跑/恢复入口的唯一漏斗处，重读权威 Run 投影——`graphActivation.executionPermit is None` 即拒绝（ValueError）；同时传入快照与权威蓝图 version 不一致时抛 ExecutionStateChanged（挡激活前快照的执行体）。
2. **激活头写防线（`_upsert_run`）**：见上节。旧图在激活切口之后既不能被持久化回写，也不能借旧快照继续执行。

激活期间的其余要求逐项：激活前置验证要求无活跃 Worker（active_step_ids/running/retrying/waiting_review 全拒）与无未收敛 Attempt（safe-cut 收据/attempt 检查）；已完成节点与全部正式收据按 run_id 保留、不重置不删除；旧异步结果只能经 save_run 持久化、被防线拒绝；普通审核路径在 paused Run 上因状态/观察失配整体 fail-closed（STALE_OBSERVATION，实测）；旧恢复逻辑无法把 inactive package 当执行图（S03-01 已证 inactive 无消费者，本轮栅栏再挡执行）；新旧版本不可能同时取得许可——head 单行 + 同事务切换。

**Scheduler 为何绝对不能运行新版节点**：`ACTIVATED_PAUSED` 投影显式携带 `executionPermit: None`，`_execute_acg` 是唯一执行漏斗且无条件检查该字段；没有任何代码路径在本轮发放许可。即使有人手工改投影伪造许可，Run 蓝图版本仍被 head 钉死，无法引入未激活版本。

## 跨库状态与恢复

不宣称跨库原子性。Workflow DB 是唯一激活权威（journal 行+head+Run 投影同事务）；Checkpoint/values/identity/目录库在每次 prepare/commit 时作为独立已提交读重新验证（物化链的既有语义），最终检查到提交之间的窗口与 S03-01 相同、如实保留，S03-02B 交接时必须再次验证。

- 切换前崩溃：无 head、Run 仍 v1、journal 行 PREPARED（或不存在）——原 key 重放 prepare/commit 走全量重验。
- 切换后崩溃/ACK 丢失：DB 已原子落盘 head+Run v2；原 key commit 重放命中 `_head_state` 幂等分支直接返回同一 activationId（不重跑验证，因为 Run 合法地持有 v2）；新连接/新进程只读 journal+head 即可对账。测试以真实 commit-后-异常+重启对账证明。
- 部分完成的跨库准备：本轮激活不写任何跨库数据（不写 values graph patch、不写 identity outbox、不动 checkpoint 库），因此不存在跨库部分完成态。
- 自动恢复 vs 人工介入：PREPARED 行可自动重放（验证通过则继续 commit）；ACTIVATED_PAUSED 是显式可恢复中间状态，恢复= S03-02B 交接（验证前缀→重建 v2 checkpoint→发许可），在此之前调度保持禁止；不存在自动把 paused 变可执行的路径。
- 不重建空 Checkpoint、不丢弃历史收据、不篡改旧 checkpoint 的 graphVersion（v1 checkpoint 原样保留为历史，新 checkpoint 由交接阶段按 v2 状态建立）。

## 失败反例与自测证据

新增 `tests/components/planner/test_graph_activation.py` 29 项（全部真实临时 SQLite、原 Runtime、原 Compiler/ValueStore）：合法准备/提交与投影切换、prepare 幂等重放与不同 key 竞争（跨连接线程池，仅一胜）、commit 必须匹配 preparation、过期 Plan/Mission/权限/Scope/GraphVersion/Input 拒绝、新收据拒绝（STALE_STRATEGY）、最新 Checkpoint 变化拒绝（CONTROL_BARRIER_BLOCKED）、未决 Review/活跃步骤/控制帧拒绝、激活事务触发器故障全回滚后重试成功、commit ACK 丢失原 key 对账（真实 commit-后-异常+新 store 实例）、**旧线程持 v1 快照在激活后被写防线拒绝（真实双线程+独立 store 连接并发反例）**、跨连接版本回退与伪造 v99 双拒、全部调度入口（execute_prepared_run/_execute_acg 旧快照/resume/apply_review）在 paused 状态拒绝且 Run 投影不变、prepare 不暂停原 v1 执行（原规划正常完成 A 后激活被 AUTHORITY_DENIED 终态拒绝）、真实已确认 v1 checkpoint 在激活后存活但无法 resume、缺 authority/schema fail-closed、schema 显式管理与错误索引拒绝、激活行 checksum 损坏拒绝、paused 上规划双 lane（patch/graph）fail-closed 且激活事实不变。

调试中修正的三个实施缺陷（均先有失败反例后有修复）：commit 幂等对账分支位于全量验证之后导致已激活重放被 STALE_GRAPH 拒绝（对账前置）；`_verify` 的 Run 源版本检查位于接受链重验之后导致蓝图版本漂移报宽泛的 STALE_STRATEGY 而非精确 STALE_GRAPH（便宜检查前移）；测试侧三处 fixture 叠加态误报（拆分为独立场景）。

最终命令在 apps/agentOS，Python 3.14.5 / Windows 11 默认计时，不请求 1ms、不修改/跳过/放宽任何既有测试：

```powershell
python -m pytest -q tests/components/planner/test_graph_activation.py tests/components/planner/test_graph_materialization.py tests/components/planner/test_graph_revision_commit.py tests/components/planner/test_graph_revision_audit.py tests/components/planner/test_graph_materialization_audit.py tests/components/planner/test_planning_commit.py tests/components/planner/test_planning_commit_runtime.py tests/components/planner/test_planning_commit_audit.py tests/contracts tests/architecture --tb=short
python -m pytest -q tests/components/planner tests/contracts tests/architecture tests/runtime --tb=short
python -m pytest -q --tb=short
```

| 最终源码上的范围 | 实际结果 |
| --- | --- |
| 定向（含新增 29 项） | **355 passed，323.20s（5:23）** |
| 扩大回归 | **954 passed，783.13s（13:03）** |
| 全量（apps/agentOS 下） | **1569 passed，1 warning，811.96s（13:31）** |

全量 1569 = 冻结基线 1540 + 新增 29；唯一 warning 为原 PyPDF2 弃用提示，0 failed、0 skipped。三组均在下列最终源码快照上顺序执行，期间无源码修改。首次从仓库根误跑全量时出现 6 个既有收集冲突（apps/agent 与 apps/agentOS 同名测试模块、output/ 杂散文件），与本轮变更无关，按 S03-01 口径在 apps/agentOS 下执行后干净通过。

## S03-02B 交接合同与阶段边界

graphActivation 投影即交接合同：activationId/materializationId/sourceCommitId/图身份/源与激活版本/supersededCheckpointId（v1 checkpoint 头的显式引用）/executionPermit。S03-02B 职责：以 head+journal+Run 投影为输入重新验证前缀完整性（收据/证据通道归属）→ 按 v2 状态建立首个正式 checkpoint → 通过独立验证的许可权威发放 executionPermit → 恢复调度并处理 planningLoop v1 观察的换代。S03-02C 负责完整执行前缀迁移与运行期生命周期。

本轮不做：新 Scheduler/NodeRunner、ACP/外部 Harness、模型路由、控制图激活、跨库分布式事务、执行前缀迁移运行、前端交互。

**当前阻止正式激活后立即执行的具体事项**（即为何停在 ACTIVATED_PAUSED）：paused Run 上不存在被确认的 checkpoint 头，规划/图接受链与恢复链在此状态下 fail-closed（实测），必须先交接重建 checkpoint；planningLoop 仍持 v1 观察需换代；执行许可权威尚未存在。这三项全部留给 S03-02B，属于设计内的显式阻断项，不是缺陷。

## 保留限制

- 范围仅无控制 DAG 的 graph_revision 链。跳版激活（链上 v2 未激活而直接激活 v3 的物化）被 `_verify` 的"Run 蓝图必须是激活源版本"拒绝——只支持逐版本连续激活（v1→v2→交接→修订→v3）。
- 多次连续修订在 A 档的可扩展性：head CAS 的升级分支（head.active==source）已实现并支持任意长度版本序列，但完整的 v2 之上再修订链路依赖 S03-02B 交接后的执行边界，本轮只验证了首版激活与 CAS 拒绝语义。
- 单进程 RunLock + 跨连接 SQLite 写锁；未做真实双进程 kill/断电/WAL 损坏实验，对账验证为新 store 实例重放。
- `_upsert_run` 防线对未升级 activation schema 的库不生效（向后兼容的取舍）；防线不能抵抗有权限任意改 SQL 的管理员。
- 激活验证继承物化链的全部输入上限与同步无 deadline 限制（S03-01 第 6 节）；BEGIN IMMEDIATE 仍是全库写锁。
- 与 S03-01 相同的跨库最后瞬间窗口（权限提供器/目录/Identity 在最终检查后、提交前的变化）如实保留，交接阶段必须重验。

## 十项问题的回答

1. **原地 Run 还是 replacement Run**：原地。依据见"执行身份策略"节——物化包 run_id 被 checksum 锁死、收据按 run_id 强绑定且 terminal 不可变、Safe-Cut 合同与原地激活同构。放弃 replacement：重编译毁 Journal 不可变性或需第二套改绑链，且旧前缀收据必然失身份，违反不得重置收据/不得隐式重执行副作用两条红线。
2. **正式 GraphVersion 权威在哪里**：Workflow SQLite 的 `graph_activation_heads` 表（每 run 单行，含 graphId/activeGraphVersion/activationId），由激活事务与 Run v2 投影同事务写入；未激活的 run 仍以 Run 行蓝图为准（防线不设限，行为与 S03-01 一致）。
3. **CAS 如何保证旧版本不能覆盖新版本**：head 存在时 `_upsert_run` 在同一写事务内要求蓝图 graphId+version 与 head 完全一致，v1 回写与 v99 伪造均拒绝；激活切换本身用 head 的条件判定（缺失/同源升级/幂等/否则拒绝）在 BEGIN IMMEDIATE 内完成，跨进程由 SQLite 写锁串行化，不依赖 RunLock。
4. **Activation Journal 与状态迁移如何持久化**：graph_activations 不可变插入（PREPARED）+ 单一受控迁移（_activate_head 事务内 UPDATE 至 ACTIVATED_PAUSED + head upsert），读取时校验行 checksum 与索引列身份；幂等键与 materialization 各有 UNIQUE 索引。
5. **Scheduler 为何绝对不能运行未许可的新版节点**：`_execute_acg` 唯一漏斗无条件检查权威 Run 投影的 executionPermit（本轮恒 None）；没有任何代码路径发许可；即使伪造投影，蓝图版本仍被 head 钉死。三项测试覆盖全部四个执行入口。
6. **激活前、中、后故障**：前——无持久状态或 PREPARED 行可重放（全量重验）；中——单事务全回滚（触发器反例）；后崩溃/ACK 丢失——head+Run 已原子落盘，原 key 幂等对账返回同一 activationId（真实反例）。
7. **与 S03-02B/C 的职责边界**：A=版本权威+激活事实+栅栏+对账+交接合同；B=前缀重验、v2 checkpoint 重建、许可发放、调度恢复；C=执行前缀迁移与运行期完整生命周期。
8. **当前支持的最小场景**：无控制 DAG、物化 Journal 就绪、Run 静止（无活跃 Worker/未决 Review、checkpoint 头与投影一致）时的 v1→v2 激活，含幂等重放、跨连接竞争仲裁、故障对账与全入口执行隔离；v1 前缀（含已完成步骤与收据引用）在 v2 投影中原样保留。
9. **仍阻止正式激活后执行的问题**：无被确认的 v2 checkpoint 头（规划/恢复链 fail-closed）、planningLoop v1 观察未换代、执行许可权威未建——全部为 S03-02B 显式交接项。
10. **是否达到独立架构验收条件**：29 项定向对抗全绿、定向 355/扩大 954 全绿、冻结基线测试零改动；全量结果与源码快照见上表。建议按 S03-01 先例进行独立代码级架构验收，重点审计：`_upsert_run` 防线的表缺失分支、`_head_state` 升级路径（本轮未端到端行使）、栅栏重读成本、以及与 S03-01 相同的跨库窗口。

## 变更范围与快照

修改 2 文件（纯增量）：workflow_runtime.py（authority 字段+enable+两入口+执行栅栏，+38 行）、sqlite_workflow_store.py（_upsert_run 激活头防线，+21 行）。新增 4 文件：contracts/graph_activation.py、support/stores/graph_activation_store.py、runtime/graph_activation.py、tests/components/planner/test_graph_activation.py。未改 Compiler、Lowerer、SemanticRevisionService、Scheduler、Executor、S02/S03 接受服务与 Schema、正式 ADR、生产装配。所有修改保持未提交。

最终 6 个 Python 文件按路径排序，每行 `path + 空格 + sha256(文件原始字节)`，LF 连接后 SHA-256：`b975df71f573b592393753de3d31bc917d8b21a465f61d098aff8c706e63a621`。测试全部完成后重算聚合值一致。定向/扩大/全量完整输出在仓库 tmp/S03-02A-broad.log 与 tmp/S03-02A-full.log（定向为前台执行）。

| 文件（相对仓库根） | 文件 SHA-256 |
| --- | --- |
| apps/agentOS/src/contracts/graph_activation.py | 6272f04c9f04ed60df478e8e3c7ca6787b8e33648aeb0e3774bb79ba9b5bfeb9 |
| apps/agentOS/src/runtime/graph_activation.py | c978738423c44ccad14ad12895a9593a3ed2829feb3a9a0343984cd48626ec0e |
| apps/agentOS/src/runtime/workflow_runtime.py | 27bf3cc1c97a3a2c2d40ad99bef1c7bff3eb2f702474ac1bc11d548498e402e3 |
| apps/agentOS/src/support/stores/graph_activation_store.py | 9e387f33dee1e8b1f20608518a0774cd96978119982c75786d0537833a143abd |
| apps/agentOS/src/support/stores/sqlite_workflow_store.py | f994c258662c9b1420d75f0d75824f7e7255b92a982632bb1403a8c216bebfc7 |
| apps/agentOS/tests/components/planner/test_graph_activation.py | 19a3dd803cfb59b2c39b715dc74e9e065493fc3428f8c6efef4f941761dc1804 |

`git diff --check` 通过；HEAD 仍为 `345ed0a953e1e772e748334294467dfe453bd5a5`，暂存区为空，工作区仅上述 2 修改+4 新增+本记录+用户的 PR-EX-00 未跟踪文档。
