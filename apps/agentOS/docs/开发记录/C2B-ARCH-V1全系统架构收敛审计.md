# C2B-ARCH V1 全系统架构收敛审计

状态：独立审计完成。本轮零生产源码修改、零数据库升级、零 ADR 修改；仅新增本报告与《C2B-ARCH-V1模块接线与完成度矩阵.md》两份未提交文档。

审计方法：全部结论来自对当前工作区真实源码的静态调用链审计（附 `路径:行号` 证据）；C2A-1/2/3 与 B1/B2 已验收合同引用的是本轮审计人前期一手验收证据，关键断言在本轮重新抽验。未运行完整 pytest；未编写新探针（本轮所有关键问题均可由静态证据确定）。

## 1. 入场基线与源码摘要

| 项 | 任务书值 | 实际核验 | 结论 |
|---|---|---|---|
| 实施前 HEAD | `44663b0e` | 当前 HEAD `09860f8c`，`origin/master` 仍为 `44663b0e`（未 Push） | **用户已在两轮之间自行完成 C2A-3 冻结提交**，非任务书所述未提交态 |
| C2A-3 冻结提交 | 待识别/待创建 | 三笔：`1d853c3f` feat（7 文件：五源码+测试）、`6714e199` 门禁（freeze_gate.py+c2a2 基线）、`09860f8c` docs（实施记录+独立验收报告）。范围恰好等于 C2A-3 验收的 11 个文件路径，无混入其他工作 | 已冻结，无需本轮创建提交 |
| 树/工作区一致 | — | 9 个 src/tests/scripts 文件逐字节比对：6 个原样一致，3 个（graph_handoff.py、graph_activation_store.py、c2a2-accepted.json）仅行尾差异（库 LF/工作区 CRLF，既有状态），内容一致 | 一致 |
| 源码摘要 | `cb5809b8…a2c47` | 独立复算 445 文件聚合 `cb5809b8…a2c47` | 一致 |
| 工作区/暂存区 | — | 干净（除本轮新增两份文档） | 符合 |

已知既有状态（登记不处理）：3 个工作区 CRLF 文件下次被 Git 触碰时会产生行尾假 diff（记忆已登记的库 LF/工作区混行尾问题）。

## 2. V1 真实架构与核心调用链

### 2.1 当前生产链（legacy 模式，默认装配）

```
前端 CreateMissionView.vue:525 → POST /api/agentos/v2/missions (agentos_v2.py:2264)
  → runtime.create_mission（defer_identity_projection）→ [若启用] MissionSemanticService.commit
  → runtime.prepare_run(defer_acg_planning=True) → coordinator.submit (coordinator.py:30)
  → execute_prepared_run (workflow_runtime.py:992) → 规划循环（intent_analyzer/react_loop + horizon）
  → _materialize_deferred_acg_run（ACGGraphCompiler 编译，无 C2A 物化）
  → ACGExecutionService.execute → bind_ready（ResourceBinder 健康+能力+租约）
  → NodeRunner → AgentInvocationAdapter/embedded agent → model registry（OpenAI 兼容）
  → Receipt/ExecutionValueStore/Checkpoint/Identity outbox → Artifacts → Workspace 投影
```

此链路**无首次执行授权阶段**：`planning_commit_authority` 为 None 时 `planningCommitRequired` 标志从不设置（workflow_runtime.py:1185-1186），`execute_prepared_run` 不会停在授权边界（workflow_runtime.py:997-998 仅在"标志已设而权威缺失"时安全停住）。

### 2.2 已验收的 C2 授权链（未接生产）

```
accept_initial → materialize_initial_commit → prepare/commit_graph_activation（ACTIVATED_PAUSED）
  → prepare_graph_handoff（STAGING→staged 外库→STATE_PREPARED）
  → issue_execution_permit（PREPARING→Checkpoint 无源 CAS→Identity 登记→ISSUED@Workflow COMMIT 线性化点）
  → execute_prepared_run（claim→assert_dispatchable→Scheduler→invocation_guard 真实调用前）
  → reconcile_execution_checkpoint / 原 Key 幂等重放恢复
```

两链在 `execute_prepared_run`/`_claim_acg_execution` 处汇合：凡 Run 带 `graphActivation` 投影，claim 强制要求 ISSUED Permit（workflow_runtime.py:1160-1167），无权威挂载即拒绝执行——激活 Run 不可能无许可执行，也不可能被孤儿清理误杀（runtime_recovery.py:215-226 显式豁免并验证激活证据）。

## 3. 各子系统完成状态与证据（四态标尺：接口存在 / 测试夹具可运行 / 显式宿主可用 / 默认生产装配已接入）

| 域 | 子系统 | 状态 | 关键证据 |
|---|---|---|---|
| A | Mission/Run 创建与语义权威 | 生产已接（语义收敛默认关） | agentos_v2.py:2264；wiring.py:394-416（`AGENTOS_MISSION_SEMANTIC_CONVERGENCE` 默认 false，部署 env 亦无配置） |
| A | Planning Commit / Source Provenance（Initial/Revision） | 测试夹具可运行（权威未挂生产） | runtime/planning_commit.py、initial_planning_sources.py；grep `enable_planning_commit` 于 apps/agent/app 零命中 |
| A | Initial 可信编译 / Materialization / Activation | 测试夹具可运行 | initial_graph_compilation.py、graph_materialization.py、graph_activation.py；C2A-1/2 一手验收 |
| B | ExecutionPermit / Handoff / Checkpoint / Identity / Attempt | 测试夹具可运行（安全合同全立） | execution_permit.py、graph_handoff.py、checkpoint.py save_promoted CAS、identity projection；C2A-3 一手验收+对抗 10/10 |
| B | Native Scheduler / ResourceBinder / NodeRunner / Receipt / ValueStore | 生产已接 | binder.py:142、node_runner.py:425-431、acg_execution.py:635 |
| B | Recovery（孤儿关闭/规划唤醒/permit 对账/检查点和解） | 生产已接（C2 permit 对账除外） | runtime_recovery.py:210-226、coordinator.py:63-85、permit_recovery.py:160 |
| C | 资源平面三层 + Binder + 健康闭环 | 生产已接 | service.py:74、health.py:17、binder.py:40/281；Redis 租约条件接线 wiring.py:346-352 |
| C | 模型端点目录（ModelDemand→model_candidates） | 仅测试夹具（生产不可达死分支） | binder.py:246-254；生产唯一 ExecutionRequirement 构造 binding.py:36-47 不含 model |
| C | 模型路由（实际生产路径） | 生产已接（确定性排序+首候选+候选级 failover） | acg_execution.py:1658 _freeze_model_binding、app_setup.py:117 default_model_binding（priority 排序）、model_compatibility.py:117 resolve=candidates[0] |
| C | 远程执行 HTTP（调度链路） | 显式宿主可用（单射 POST /execute，无会话/取消/对账） | resource_execution.py:55-111；服务端 events/cancel 仅工具层消费 |
| C | ACP / 第三方 Harness | 未实施（设计文档阶段） | 全仓 grep 零命中；PR-EX-00 自述未实施，源码状态一致 |
| D | Memory（run 级写入/召回） | 生产已接 | node_runner.py:352-363/707、service.py:223/281 |
| D | 长期记忆检索（search/hybrid_search）、lifecycle、compression | 仅接口存在（无生产调用方） | service.py:215/70；lifecycle.py:8、compression.py:6 零引用 |
| D | ContextPack / Provenance | 生产已接 | assembler.py:32-73、provenance.py:94、node_runner.py:314/589 |
| D | Runtime Events（SSE broker）+ Trace | 生产已接（broker 非持久 by design） | live_events.py:32、agentos_v2.py:2848-2889、trace.py:16 |
| D | Operation Audit / Decision Store | 生产已接（决策先于输出持久化） | node_runner.py:486-505（save/assert 在 put_output:576 之前） |
| E | Canonical run_deliverable / Artifact / 下载 | 生产已接（触发器不可变+槽位唯一） | node_runner.py:1023-1091、identity_projection.py:859-952、repositories.py:1117-1128、schema.py:399-451 |
| E | Workspace Projection / 上传→执行链 | 生产已接 | workspace.py:218、attachments service.py:122/41-79、acg_execution.py:1190-1194 |
| F | 默认装配注入 C2 五权威 | **未注入** | wiring.py:221-498 无 enable_planning_commit/materialization/activation/handoff/execution_permit；main.py:44 |
| F | C2 HTTP 端点（查询/首次执行/恢复） | **不存在** | agentos_v2.py grep graphActivation/executionPermit 零命中 |
| G | 前端主链路（创建/规划/执行/审核/取消/重试/交付） | 完整用户流程（真实 API+token+幂等键+乐观锁） | G 域审计（矩阵文档第 G 节） |
| G | 前端 graphActivation/Permit 状态 | **零消费** | 前端全仓 grep 零命中 |

## 4. 唯一 Authority / Store 矩阵

| 核心事实 | 唯一写入权威 | 持久化 | CAS/幂等 | 恢复方式 | 生产调用方 |
|---|---|---|---|---|---|
| Mission / Run | ExecutionRuntime | workflow.sqlite3 `runs`（payload+runtime_revision 乐观锁） | save_run CAS；creation_key 幂等 | find_run_by_idempotency_key 重放 | HTTP missions/runs |
| Mission 语义（revision） | MissionSemanticService | workflow.sqlite3 `mission_semantic_state`（UNIQUE(mission,revision)） | operationId 幂等 | 幂等重放收据 | HTTP semantics（启用后） |
| Planning Commit（Initial/Revision 同库同构） | RuntimePlanningCommitAuthority | workflow.sqlite3 `planning_commit_records` | Key 幂等+UNIQUE(mission,revision) | 原 Key 重放 | **无（未接线）** |
| Materialization / Activation Head | GraphMaterializationAuthority / GraphActivationAuthority | workflow.sqlite3（journal+`graph_activation_heads`） | Key 幂等+materialization 唯一索引+Head 事务 CAS | 幂等重放/Head 重验 | **无** |
| Handoff + staged 检查点 | GraphHandoffAuthority | workflow.sqlite3 `graph_handoffs` + checkpoint 库 `staged_graph_checkpoints` | Key/handoff 双唯一+三段确认 | 原 Key 对账 | **无** |
| ExecutionPermit | ExecutionPermitAuthority | workflow.sqlite3 `graph_execution_permits`（四重唯一） | PREPARING→ISSUED SQL CAS；线性化点=最终 Workflow COMMIT | 原 Key 幂等重放 | **无** |
| 正式 Checkpoint | ACGCheckpointStore | checkpoint.sqlite3 | save_promoted 无源头 CAS；native 内容寻址 | load_latest+reconcile | 内核（激活链启用后） |
| Identity（Blueprint/Plan/Run/Attempt/Artifact） | AcgIdentityLifecycleService（经 IdentityProjectionBridge） | identity_v2.sqlite3 | 事务原子+outbox→inbox+projection journal 幂等（死信 5 次） | replay_unapplied+启动对账 reconciliation.py:46 | 生产已接 |
| Resource Binding / 租约 | ResourceBinder | resources.sqlite3 + InMemory/Redis 租约 | 租约原子授予+版本复核 | 失败释放+健康降级 | 生产已接 |
| 模型路由 | model registry + default binding | 内存注册表 | 排序确定性+候选 failover | 健康刷新 | 生产已接 |
| Runtime Event | RuntimeEventBroker（进程内，非持久） | 无（Trace 落 run 快照） | — | 终态合成兜底 | SSE |
| Audit 决策 | ExecutionAuditService→DecisionStore | audit_decisions.sqlite3 | checksum+幂等 | assert 重验 | 内核 |
| Artifact / Deliverable | node_runner→identity projection | content_manifests.sqlite3 + identity `artifacts`（UPDATE 触发器 ABORT、run_deliverable 槽位唯一） | manifest sha256+artifact_id 内容派生 | commitId 幂等+replay | HTTP artifacts |
| Workspace / API 投影 | MissionWorkspaceProjector / 各查询服务（纯读模型） | 无（读时投影） | — | — | HTTP workspace |

## 5. Initial / Revision / Execution / Recovery 状态交接图（文字版）

- **接受**：`initial_plan` / `plan_revision` 提交 → PlanningCommit `ACCEPTED`（sources 封存，static_fingerprint 锚定）。
- **物化**：`MATERIALIZED_INACTIVE`（包只读，recipe 三处重验；不可发布窗口）。
- **激活**：`ACTIVATED_PAUSED`——Head 安装 v1（Initial）或 vN+1（Revision），Run 投影带 `graphActivation.executionPermit=None`。**暂停是交接边界，不是执行失败，也不是可执行态**：孤儿清理豁免（runtime_recovery.py:215）、claim 拒绝（workflow_runtime.py:1160-1163）。
- **交接**：Handoff `STAGING→STATE_PREPARED`（staged 空正文/前缀正文入独立 checkpoint 库；staged 不是恢复头）。
- **许可**：Permit `PREPARING→ISSUED`（Saga 三库；只有最终 Workflow COMMIT 后可执行）。
- **执行**：claim fence → 每 step `assert_dispatchable` → 真实调用前 `assert_invocation`（Attempt/绑定/Identity 绑定）→ Receipt committed → native checkpoint（内容寻址）。
- **恢复**：进程死亡后 —— PREPARING 按原 Key 重放（不重新 prepare 无源 Handoff）；head 领先 Run 确认 → 先拒绝直接 claim，经 `reconcile_execution_checkpoint` 和解；未知副作用 fail-closed 阻断（`assert_settled_operations`：prepared WAL 不是失败回执）。
- **取消/审核**：`cancel` 后 permit fence 拒绝执行；review 批准经 `_execute_acg`→claim gate（激活 Run 无 permit 即拒）。

## 6. 正式生产装配与 HTTP / Frontend 接线矩阵（摘要，逐端点见矩阵文档）

- **生产装配已注入**：workflow/checkpoint/value/content/memory/provenance/audit/resource 三库/identity/attachment/模型 registry/本地 Runtime（env 条件）/Redis 租约（env 条件）/embedded agent 注册/单实例锁（wiring.py:333）。
- **未注入**：C2 五权威、语义收敛（默认关）、对应 schema（显式管理操作，禁止装配期隐式升级——已验收合同）。
- **HTTP 已有**：missions CRUD、runs 查询/取消/审核/单步重试/rerun、graph/outputs/context-packs/artifacts/trace/events(SSE)/provenance/checkpoints/reviews/scheduling/memory-events、materials/attachments、semantics、mission revision（REQUEST_REPLAN→successor，属无激活 replan 链）、copilot、evolution、resources/nodes 管理。
- **HTTP 缺失**：C2 查询投影（activation/permit）、首次执行请求（handoff+permit 签发）、恢复对账入口。
- **前端**：主链路真实接线（鉴权/幂等/乐观锁齐全）；`graphActivation/executionPermit` 零消费零展示；`waiting_review` 借用 paused 视觉态（无功能错误）；Resource Center 模型管理半 mock（fixture 兜底+假操作按钮）；FileUpload.vue 死代码；Landing 演示动画（明示 demo）。

### 6.1 F 域专项验证结论（任务书特别验证项）

1. **Coordinator 绕过首次授权？** 不能绕过已启用的授权（标志+权威缺失即安全停住；激活 Run 必须持 ISSUED Permit 才能 claim）。但默认装配下不存在首次授权阶段——Run 创建即执行（legacy 路径）。属"未启用"而非"被绕过"。
2. **ACTIVATED_PAUSED 误判？** 不会被孤儿清理关闭（显式豁免+证据验证），不会被自动 submit（coordinator.startup 仅重启 restartPending 的 retrying Run）。
3. **请求体伪造？** 请求模型全部 `extra="forbid"`；语义控制字段显式 422（agentos_v2.py:839-840）；owner 由可信边界盖章覆盖（`_actor_input` :227-241）；无 permission/sourceKind/generation/checkpoint 字段可传。
4. **幂等 Key 宿主持久化？** Mission/Run/review/rerun 层已持久化（creation_key/operation key 落库可恢复）；C2 handoff/permit 幂等 Key 无宿主管理（无端点）。
5. **取消/审核/重试/恢复/查询入口？** 取消✓审核✓重试✓查询✓；恢复（C2 对账）✗。

## 7. 跨库事务、Saga 与故障恢复边界

**单库事务**（workflow.sqlite3 内）：Mission 语义、Planning Commit、物化、激活（journal+Head+Run 投影同事务）、Permit 最终签发、Artifact 身份投影。
**跨库 Saga**（无联合原子性，恢复=逐库幂等对账）：
- Permit Saga：workflow(PREPARING) → checkpoint(晋升 CAS) → identity(登记) → workflow(ISSUED，线性化点)。中间死亡留 PREPARING，原 Key 重放收束到唯一事实（C2A-3 实证含 exit 81/82/84 真进程切口）。
- Handoff：workflow(STAGING) → staged 外库 → workflow(STATE_PREPARED)。孤儿 staged 不可被正常恢复消费。
- Identity 投影：outbox→inbox→apply，journal 幂等，死信 5 次后留修配。
**只能拒绝或人工对账（明确边界）**：未知外部副作用、跨 Run 外部副作用去重、无法证明的恢复点、未确认 WAL、同 Mission 多 Initial Run 的先前未执行 Run（fence fail-closed，STALE_MISSION）。单机 SQLite 事务不是跨库联合原子事务；无跨机持久租约（Redis 租约仅调度容量层）。

## 8. 真实断链、重复职责与不必要抽象清单

**断链（6 项）**：① C2 五权威未注入默认装配（wiring.py:221-498）；② 语义收敛默认关且部署未配置（wiring.py:394）；③ C2 无 HTTP 端点（agentos_v2.py 零命中）；④ 前端 activation/permit 零消费；⑤ C2 幂等 Key 无宿主持久化；⑥ C2 恢复无 HTTP 入口。

**无生产调用方（全仓 grep 证据，处置=删除或登记推迟）**：`LocalResourceExecutionAdapter`（resource_execution.py:34）、`issue_lease`（leases.py:311）、`ResourcePlane.update_runtime_capacity`（service.py:473）、binder ModelEndpoint 绑定分支（binder.py:246-254，无 ModelDemand 生产者）、`MemoryService.search/hybrid_search`（service.py:215/70）、`WorkingMemory/working_from_run`、`MemoryWriteBatch`、`memory/lifecycle.is_expired`、`memory/compression.compact_record`、`auditor/service.AuditorService`（连带 risk/quality/structural/evidence 四模块）、`RunArtifactDisposition.REUSED`+`source_run_id`、`SQLiteRunArtifactBindingRepository.find_for_slot`、`runtime/legacy` 门面、`apps/agentOS/drafts/legacy_execution/` 整目录、前端 `FileUpload.vue`。

**重复职责/双实现**：`algorithms.is_runtime_available` 与 binder.evaluate 并行可用性判断（调度器不经 algorithms）；`lifecycle.is_expired` 与 service.py:251-256 内联重实现；react_loop 局部 call_audit 与 intent_analyzer last_audit 两套审计上抛通道（后者丢数据）。

## 9. P0/P1/P2/P3 问题登记

**P0：无。** 未发现数据破坏、越权执行或重复不可逆副作用路径；全部安全合同在内核层成立。

**P1-1（唯一 P1）：C2 执行授权链未接入生产装配。** 这不是安全缺陷（fail-closed，legacy 模式不含激活 Run），但它阻断 V1 目标形态"首次执行授权 + 统一 Native Runtime 内核"的用户可达性：已验收的 Initial v1/Revision Permit/恢复合同在默认生产路径上不可达。补齐=第 11 节 C2B-INTEGRATION。

**P2**：
- P2-1 legacy-outputs 对无 outputRefs 的老 Run 原样返回 step.output 正文，无 `_redact`（agentos_v2.py:2822-2839；owner 鉴权存在，仅老数据兼容路径）。
- P2-2 SSE 端点不做统一 redact，安全性质依赖各发布方自律（live_events.py 发布端裁剪是当前唯一防线；新增发布方即新增审计面）。
- P2-3 ReAct 规划循环的 call_audit（attemptsByStage）每次调用新建局部 dict 被丢弃，审计统计缺口（react_loop.py:161-166）。
- P2-4 调度侧远程执行为单射 HTTP：无会话、无取消、无对账（resource_execution.py）；V1 以"受限支持、单机 Native Runtime 为主"声明。
- P2-5 长期记忆检索（跨 Run）未接入：生产仅 run 级召回（service.py:223）。
- P2-6 Phase Capsule 有写入+展示链，无下游模型回读消费。
- P2-7 前端 Resource Center 模型管理 tab 半 mock（fixture 兜底+纯前端假操作按钮）。
- P2-8 同 Mission 多 Initial Run：后一次 Initial 接受使先前未执行 Run fence fail-closed（设计语义，宿主合同须明确"每 Mission 一个活跃 Initial Run"）。

**P3**：§8 孤儿/双实现清单全部条目；前端 `waiting_review` 复用 paused 视觉态（标签已写"等待审核"）；ProjectRunSidebarView.vue:182-183 重复表达式（无害）；模型端点目录绑定死分支的评分维度极简（仅 preferred +0.1）。

## 10. V1 必需 / 受限 / 明确不支持 / 之后实现

| 能力 | 分级 | 依据 |
|---|---|---|
| C2 授权链生产接入（Initial v1 + Revision Permit + 恢复） | **V1 必需** | P1-1；C2A-3 已验收 |
| 语义收敛启用 + schema 显式升级流程 | **V1 必需** | 授权链前置（mission revision 是 fence 输入） |
| 交付链 / 审核 / 取消 / 重试 / 查询投影 | V1 必需（已达成） | §3 E/G 域 |
| 前端授权状态展示与授权操作 | **V1 必需**（随 P1-1 接线） | G 域零消费 |
| 单机 Native Runtime（单实例锁 + embedded agent） | V1 必需（已达成） | wiring.py:333 |
| 远程执行 HTTP 单射 | **V1 可受限支持**（声明无会话/取消/对账） | P2-4 |
| run 级记忆 / Redis 租约 / 本地 Runtime 工具面 | V1 可受限支持（env 条件） | §3 C/D 域 |
| 控制图 / 循环拓扑 | **V1 明确不支持** | Safe-Cut `reject-control-regions-v1`（合同级拒绝） |
| 多主机运行 / 跨机持久租约 | V1 明确不支持 | 单实例锁+单机 SQLite+无跨机租约 |
| 联邦学习 / 差分隐私 | **V1 之外**（apps/agent/app/api/federated*.py 为独立遗留功能域，非 AgentOS 内核，不纳入冻结范围） | 与内核零调用关系 |
| ACP / 第三方 Harness | V1 之后再实现 | 零实现，PR-EX-00 设计文档 |
| 模型端点目录路由（ModelDemand） | V1 之后再实现（现为死分支，保留或删除随孤儿清理裁决） | §8 |
| 长期记忆检索 / Capsule 回读 | V1 之后再实现 | P2-5/6 |

## 11. 最小化 C2B-INTEGRATION 任务拆分（依赖序）

1. **INT-1 schema 显式升级操作**：为 workflow 库安装 planning_commit_records / graph_materializations / graph_activations(+heads) / graph_handoffs / graph_execution_permits 表与 checkpoint 库 staged 表（全部既有 `upgrade_schema` 显式管理入口，禁止装配期隐式升级）；一次性运维脚本 + 幂等。
2. **INT-2 wiring 条件装配**：新增 env 开关（如 `AGENTOS_EXECUTION_AUTHORITY=initial_v1`）：启用语义收敛（复用既有 `enable_existing_mission_semantics`）+ 注入五权威（同一 workflow db、staged 挂 checkpoint db、identity 复用现有 bridge）+ 校验 wiring 构造期 store 同一性断言不回退。关闭开关时 legacy 行为零变化。
3. **INT-3 HTTP 入口（三个）**：① 查询投影：activation head / handoff / permit 只读端点（复用 `_require_access`/mission owner 404 收敛）；② 首次执行请求：单端点串 `prepare_graph_handoff`（幂等：已有 handoff 查原事实）+ `issue_execution_permit`（幂等 Key 由宿主按 Run/Activation 命名生成并持久化，ACK 丢失可恢复）；③ 恢复入口：PREPARING 原 Key 对账 + `reconcile_execution_checkpoint`。请求体不收 permission/sourceKind/generation/checkpoint。
4. **INT-4 生命周期集成验证**：ACTIVATED_PAUSED 不自动执行、不误报失败（孤儿豁免已有，补装配形态集成测试）；取消→permit fence 拒绝（既有，补演示）；review 恢复经 claim gate。
5. **INT-5 前端授权状态**：复用现有工作台组件组合 activation+permit+run 三态（不新设计 UI）：待授权（ACTIVATED_PAUSED）/已授权（ISSUED）/执行中/阻断原因（含未知副作用 fail-closed 文案）；授权按钮调 INT-3②。
6. **INT-6 验收与 V1 冻结门禁**：见第 12 节。

不做的事：不新增 Authority/Store/状态机；不接入 ACP；不实现模型端点目录路由；不动已冻结合同与 ADR；孤儿清理（P3 清单）在 INT-6 后按"删或登记"单独裁决，不混入 INT。

## 12. V1 架构冻结的可执行验收标准

1. **开关全链红绿**：启用装配下，仅经 HTTP+前端完成 创建 Mission（含语义）→ Initial 接受 → 物化 → 暂停激活 → 授权（handoff+permit）→ 原生执行 → 交付 全流程，零手工 DB 操作；未授权前任何路径不能执行首节点。
2. **开关关闭回归**：legacy 模式行为与当前基线一致（既有全量测试空载通过 + 主链路前端冒烟）。
3. **安全合同复验**：C2A-3 十项安全合同在装配形态下以同型对抗探针复验（伪造持久化事实/CAS 冲突/撤权/漂移/staged 篡改），全部拒绝。
4. **崩溃恢复演示**：进程死亡于 Checkpoint COMMIT 后、Workflow 确认前（及 Identity COMMIT 后），重启经 HTTP 恢复入口对账，Agent 副作用恰好一次，Permit 事实唯一。
5. **幂等与 ACK 丢失**：宿主幂等 Key 持久化；同 Key 重放 IDEMPOTENT_REPLAY；ACK 丢失后同 permit_id。
6. **ACTIVATED_PAUSED 语义**：服务重启后不自动执行、前端显示"待授权"而非失败。
7. **门禁**：`python scripts/freeze_gate.py` PASSED（≤300s），基线更新为本轮冻结清单；全量空载 pytest 通过。
8. **收敛核对**：P3 孤儿清单每项有"已删除/已登记推迟"归宿；P2-1/2/3 有修复或明确豁免理由。

## 附：尚未验证事项与设计建议（与已证实事实区分）

- 尚未验证：INT-2 开关装配在真实容器环境的运行行为（本轮纯静态+测试证据）；`AGENTOS_MODELS` 与语义收敛同时启用时 planner 授权链的端到端时序（需 INT-3 集成测试覆盖）。
- 设计建议（非结论）：SSE 统一 redact 建议随 INT-3 一并收敛为端点级过滤，替代发布方自律；call_audit 建议统一单一上抛通道（修 P2-3 时顺带消除双实现）。
