# C2B-ARCH-V1-阶段合并记录

> 本文按阶段合并开发记录。来源文档内容原样保留，原文件继续留在本目录。

## 原始记录目录

- `C2B-ARCH-V1全系统架构收敛审计.md`
- `C2B-ARCH-V1模块接线与完成度矩阵.md`

---

<!-- 原始记录：C2B-ARCH-V1全系统架构收敛审计.md -->

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


---

<!-- 原始记录：C2B-ARCH-V1模块接线与完成度矩阵.md -->

# C2B-ARCH V1 模块接线与完成度矩阵

配套主报告：《C2B-ARCH-V1全系统架构收敛审计.md》。状态标尺：**Ⅰ**=仅接口存在 / **Ⅱ**=测试夹具可运行 / **Ⅲ**=显式宿主可用 / **Ⅳ**=默认生产装配已接入。"生产调用者"指 apps/agent（宿主）或内核默认执行链中的非测试调用方，均有 grep 证据；"—"表示无。路径省略前缀 `apps/agentOS/src/`（宿主文件以 `agent:` 前缀标示，位于 `apps/agent/app/`）。

## A. 任务与规划控制面

| 模块 | 实现证据 | 生产调用者 | 测试证据 | 持久化 | 权限 | 恢复 | 前端消费 | 状态 |
|---|---|---|---|---|---|---|---|---|
| Mission/Run 生命周期 | runtime/workflow_runtime.py:992/2309 | agent:api/agentos_v2.py:2264（创建/取消/审核/重试） | tests/runtime/test_kernel_vertical_slice.py | workflow.sqlite3 runs（乐观锁） | owner/tenant 盖章+404 收敛（agent:227/278） | creation_key 幂等+孤儿关闭 | 创建/进度/取消/重试全链 | Ⅳ |
| Mission 语义权威 | components/mission_manager/semantic_service.py | agent:wiring.py:416（默认关） | tests/components/planner/test_planning_commit.py | mission_semantic_state（UNIQUE mission,revision） | authorize 闭包 owner/tenant（wiring:401-414） | operationId 幂等 | semantics 端点（无 UI 专页） | Ⅲ（env 条件） |
| 规划循环（ReAct/Horizon/Intent） | components/planner/react_loop.py、planner/horizon.py | execute_prepared_run 规划段 | tests/components/planner/test_react_loop.py、test_horizon.py | run.execution_state.planningLoop | planner 身份+scope 冻结 | restartPending 重驱动 | SSE planner.* 事件流 | Ⅳ |
| Planning Commit（Initial/Revision ledger） | runtime/planning_commit.py、initial_planning_sources.py | **无**（enable_* 零命中） | test_initial_planning_sources.py、test_planning_commit_runtime.py | planning_commit_records | provider.authorize 双重 | 原 Key 幂等重放 | — | Ⅱ |
| Initial 可信编译 | runtime/initial_graph_compilation.py（recipe 指纹） | 经物化权威（未接） | test_initial_graph_materialization.py、test_binding_authority.py | 物化 journal 内封存 | 编译期 policy 校验 | IDEMPOTENT_REPLAY | — | Ⅱ |
| GraphMaterialization | runtime/graph_materialization.py | **无** | test_graph_materialization.py | graph_materializations | 权威 store 同一性断言 | Key+commit 唯一索引幂等 | — | Ⅱ |
| GraphActivation（Head） | runtime/graph_activation.py | **无** | test_graph_activation.py | graph_activations(+heads) 同库事务 | 权威唯一 | Head 重验+幂等 | — | Ⅱ |
| ACGLowerer/Topology（编译包） | components/executor/graph.py ACGGraphCompiler | _materialize_deferred_acg_run（legacy 编译）；C2A 物化（未接） | tests/contracts/test_compiled_acg.py | 编译包随 run/journal | 激活包只读 | 重编译确定性 | ACG 拓扑图组件 | Ⅳ（legacy 路径） |

## B. 执行内核

| 模块 | 实现证据 | 生产调用者 | 测试证据 | 持久化 | 权限 | 恢复 | 前端消费 | 状态 |
|---|---|---|---|---|---|---|---|---|
| ExecutionPermit 权威 | runtime/execution_permit.py:66/174/414 | **无**（claim gate 已在生产内核） | test_initial_execution_permit.py（33 项）、test_execution_permit(_audit).py | graph_execution_permits 四重唯一 | principal 指纹+fence 全链 | 原 Key 幂等（exit 81/82/84 实证） | — | Ⅱ |
| GraphHandoff 权威 | runtime/graph_handoff.py:51/392 | **无** | test_graph_handoff.py、test_initial_execution_permit.py | graph_handoffs+staged 表 | 权威同一性+三段重验 | 原 Key 对账 | — | Ⅱ |
| 正式 Checkpoint（晋升/native） | components/recovery/checkpoint.py:126 save_promoted | 内核（激活链）；legacy native 亦用 | test_checkpoint_promotion.py、test_permit_recovery.py | checkpoint.sqlite3（内容寻址） | permit 绑定 generation | reconcile_execution_checkpoint | checkpoints 端点（只读） | Ⅳ（native）/Ⅱ（晋升链未接） |
| Identity Lifecycle/投影 | runtime/v2/identity_projection.py、reconciliation.py | wiring.py:353-369/443-446 | test_kernel_vertical_slice.py | identity_v2.sqlite3+outbox/inbox | 投影只读消费 | replay_unapplied+启动对账 | execution-tree/attempts 端点 | Ⅳ |
| Attempt Fence / 执行槽 | workflow_runtime.py:1134 _claim_acg_execution；run_execution_fence | 内核执行入口 | test_scheduler_handoff.py | OS fence+内存槽 | permit gate | 释放+重claim | — | Ⅳ |
| Native Scheduler/ResourceBinder | components/scheduler/binder.py:142 | acg_execution.py:635 bind_ready | test_binder.py、test_scheduler_handoff.py | resources 三库+租约 | scope 冻结+硬约束 | 失败释放+健康降级 | scheduling 端点 | Ⅳ |
| NodeRunner/invocation guard | components/executor/node_runner.py:425-431 | acg_execution.py:1230 | test_execution_permit.py、C2A-3 对抗 | — （调用期） | assert_invocation 绑定 Attempt | commitId 幂等重放 | SSE node.* | Ⅳ |
| Receipt/ValueStore | components/executor/value_store.py | node_runner:576 | test_kernel_vertical_slice.py | execution_values.sqlite3（PK 引用） | run/step 隔离 assert_reference | committed 重放不重调 | outputs 端点 | Ⅳ |
| PermitRecovery/对账 | runtime/permit_recovery.py:24/160 | reconcile_execution_checkpoint（无 HTTP） | test_permit_recovery(_final_audit).py（20 项复验） | 只读+Run 确认 | ISSUED 前置 | 和解矩阵（C2A-3 §五） | — | Ⅱ（无入口） |
| 孤儿清理/规划唤醒 | runtime/runtime_recovery.py:210；workflow_runtime.py:2087 | agent:coordinator.py:63-85 startup | test_kernel_vertical_slice.py | run 快照 | — | 激活 Run 豁免+证据验证 | — | Ⅳ |

## C. 资源与模型运行面

| 模块 | 实现证据 | 生产调用者 | 测试证据 | 持久化 | 权限 | 恢复 | 前端消费 | 状态 |
|---|---|---|---|---|---|---|---|---|
| ResourcePlane 三层 | components/resource/service.py:74 | wiring.py:335-352 | test_binder.py、资源 GET 端点测试 | resources/nodes/health 三库 | credential_key 生产强制 | 健康监测+心跳 | resources/nodes 端点+资源面板 | Ⅳ |
| 租约（InMemory/Redis） | scheduler/leases.py:91/176 | binder.py:153；Redis 条件 wiring:346 | leases 测试（Lua 原子） | Redis（条件） | — | COORDINATION_UNAVAILABLE 拒绝 | — | Ⅳ/Ⅲ（env） |
| ModelEndpoint 目录+绑定分支 | service.py:805 model_candidates；binder.py:246-254 | **无**（ModelDemand 无生产构造点） | test_binder.py | resources 库 | — | — | — | Ⅰ（死分支） |
| 模型路由（registry） | adapters/model_compatibility.py:117；app_setup.py:117 | acg_execution.py:1658；native.py:122 | model_runtime 测试 | 内存注册表 | key 经 RotatingKeyProvider | 候选 failover+健康刷新 | 模型管理页（半 mock，P2-7） | Ⅳ |
| embedded Agent 后端 | components/resource/embedded_runtime.py:26 | wiring.py:497 注册 | test_scheduler_handoff.py | 资源投影 | scope 白名单 scoped() | 心跳保活 | — | Ⅳ |
| 远程执行 HTTP | adapters/resource_execution.py:55 | acg_execution.py:388/675（条件 endpoint） | 远程执行测试 | 无状态单射 | HMAC+nonce+幂等键 | **无对账**（P2-4） | — | Ⅲ |
| Local Runtime（工具面） | components/resource/local_runtime.py:116；adapters/local_runtime*.py | wiring.py:449-482（env）；agent:tools/local_runtime.py | local-runtime 集成测试 | 资源注册+健康投影 | credential+workspace 授权 | events/cancel（工具层） | 桌面工具链 | Ⅲ（env） |
| ACP/外部 Harness | —（零实现；contracts/resource.py:64 docstring 预留） | — | — | — | — | — | — | 未实施（设计文档 PR-EX-00） |

## D. 记忆、上下文与审计

| 模块 | 实现证据 | 生产调用者 | 测试证据 | 持久化 | 权限 | 恢复 | 前端消费 | 状态 |
|---|---|---|---|---|---|---|---|---|
| Memory（run 级） | components/memory/service.py:25/223/281 | node_runner.py:353/707；review.py:200 | 记忆相关测试 | execution_memory.sqlite3 | scope=run 硬绑+memoryPolicy | 写幂等（同 id 异容抛错） | memory-events 端点+MemoryView | Ⅳ |
| 长期检索/lifecycle/compression | service.py:215/70；lifecycle.py:8；compression.py:6 | **无** | — | — | — | — | — | Ⅰ |
| Phase Capsule | service.py:137；acg_execution.py:1484-1548 | 内核 superstep 投影 | kernel 测试 | memory store+trace 事件 | — | 确定性幂等 | memory-events（kind=phase_capsule） | Ⅳ（写入）/回读缺（P2-6） |
| ContextPack | components/communicator/assembler.py:32-73 | node_runner:1134 | communicator 测试 | value store（封存） | 字段白名单 | 引用重放 | context-packs 端点 | Ⅳ |
| Provenance | provenance.py:94；provenance_store.py:13 | node_runner:314/589；graph_handoff:222（未接链） | C2A/B2 验收链 | provenance.sqlite3（哈希链） | 封存事件模型 | 幂等+链校验 | provenance 端点 | Ⅳ |
| Runtime Event Broker（SSE） | runtime/live_events.py:32 | agent:agentos_v2.py:2848 | SSE 契约测试 | 无（by design） | 发布端裁剪（P2-2） | 终态合成 | 前端 SSE 消费 | Ⅳ |
| Trace | components/auditor/governance/trace.py:16 | run 快照 UPSERT | trace 投影测试 | workflow 库 run.trace | API _redact | append_batch 防重 | trace 端点 | Ⅳ |
| Decision Store/ExecutionAudit | decision_store.py:129；execution_audit.py:16 | node_runner:486-505 | 审计测试 | audit_decisions.sqlite3 | 决策先于输出持久化 | assert 重验 | — | Ⅳ |
| Planner call_audit | complexity.py:292；intent_analyzer.py:104 | intent 通道上抛；**react_loop.py:161 丢弃（P2-3）** | planner 测试 | trace promptAudit | — | — | trace 视图 | 部分（P2-3） |
| 敏感过滤 | agent:agentos_v2.py:202 _redact | /trace /scheduling memory-events | 投影测试 | — | 分层白名单 | — | — | 分层非统一（P2-1/2） |

## E. Artifact、Workspace 与交付

| 模块 | 实现证据 | 生产调用者 | 测试证据 | 持久化 | 权限 | 恢复 | 前端消费 | 状态 |
|---|---|---|---|---|---|---|---|---|
| Canonical run_deliverable | contracts/artifacts.py:11-143；identity_projection.py:859-952 | node_runner:1023（artifact_generation 节点） | test_kernel_vertical_slice.py（crash-restart 唯一交付） | content_manifests+identity artifacts（UPDATE 触发器 ABORT） | owner 404 收敛 | artifact_id 内容派生+槽位唯一 | 交付面板/ArtifactEditor | Ⅳ |
| Artifact 查询/下载 | runtime/v2/queries.py:184；agent:2644-2820 | HTTP artifacts 端点 | 投影测试 | 同上 | sealed+owner 校验 | checksum 流式校验 | 下载/分片 | Ⅳ |
| Workspace Projection | runtime/v2/workspace.py:218 | agent:1585/1945 | workspace 测试 | 读模型 | mission owner | — | MissionWorkspaceView | Ⅳ |
| 附件上传→执行链 | components/attachments/service.py:122/41-79 | agent:946（upload）/831（绑定） | attachments 测试 | storage+MATERIAL manifest+绑定表 | 本人 403/404+READY 校验 | 上传状态机 | drag-drop 上传组件 | Ⅳ |
| legacy-outputs | agent:agentos_v2.py:2822-2839 | HTTP（仅无 outputRefs 老 Run） | C1-FIX 验收边界 | — | owner 鉴权有、**无 _redact（P2-1）** | — | — | Ⅲ（兼容回退） |
| REUSED 绑定/门面 | domain/identity_graph/bindings.py:73-90；runtime/legacy/__init__.py | **无** | — | — | — | — | — | Ⅰ |

## F. 生产装配与 API

| 模块 | 实现证据 | 生产调用者 | 测试证据 | 持久化 | 权限 | 恢复 | 前端消费 | 状态 |
|---|---|---|---|---|---|---|---|---|
| Composition Root | agent:execution/wiring.py:316 build_default_runtime | agent:main.py:44 | 宿主集成测试 | 11 个默认库路径 | 生产强制 credential key | close_runtime 全释放 | — | Ⅳ |
| Coordinator | agent:execution/coordinator.py:19 | main.py:47；全部 submit 端点 | 协调器测试 | — | submit 白名单状态 | worker_shutdown 持久化失败 | — | Ⅳ |
| 单实例锁 | agent:execution/instance_lock.py | wiring.py:333 | 锁测试 | OS 锁文件 | — | — | — | Ⅳ（单机约束） |
| C2 五权威装配 | —（wiring 无 enable_*；grep 零命中） | **无** | 夹具装配（test_initial_execution_permit.py:191 open_existing） | — | — | — | — | **未装配（P1-1）** |
| C2 HTTP 端点 | —（agentos_v2.py 零命中） | — | — | — | — | — | — | **不存在（P1-1）** |
| Mission revision（replan 链） | agent:agentos_v2.py:2134-2207 | HTTP | revision 测试 | decisions+successor run | principal 一致性+409 | successor Key 幂等 | MissionRevisionNotice | Ⅳ |
| 既有 AI 功能域（chat/federated 等） | agent:app/api/*.py（30 文件） | 独立路由 | 各自测试 | 各自库 | 各自鉴权 | — | 对应页面 | V1 之外既有域 |

## G. 前端（apps/frontend）

| 功能 | 实现证据 | 数据来源 | 状态 |
|---|---|---|---|
| Mission 创建 | views/CreateMissionView.vue:525→startWorkflowAsync | POST /missions（幂等 clientRequestId+失败重试缓存） | 完整流程 |
| 规划查看 | components/agentos/AcgTopologyGraph.vue；RunProgressEditor.vue:103 | /runs/{id}/graph+provenance+trace+execution-tree+SSE planner.* | 完整流程 |
| 执行授权/激活状态 | **无**（全仓 grep graphActivation/executionPermit 零命中） | — | **缺失（P1-1 组成）** |
| 执行中状态/事件 | workbench/runtime/runtimeEvents.ts:312（SSE）；useWorkflowProgress.ts:39（2s 轮询） | /runs/{id}/events(SSE)+多路轮询 | 完整流程 |
| 审核 | components/agentos/WorkflowReviewPanel.vue:29 | POST /runs/{id}/reviews（幂等+乐观锁+409/404 分类） | 生产流程 |
| 取消/恢复/重试 | MissionWorkspaceView.vue:748/796/790 | cancel/steps/{id}/retry/missions/{id}/runs | 生产流程 |
| 最终交付 | services/api/agentos/api/acg.ts:203-233；ArtifactEditor.vue | artifacts+download（completed+outputRef 才升级交付） | 完整流程 |
| 文件上传 | CreateMissionView.vue:497-522（drag-drop） | attachments/materials 端点 | 完整流程 |
| 资源中心·模型管理 | components/resource-center/ModelManagementPanel.vue:336/583 | 真实 API 失败/空时回落本地 fixture；部署/评估按钮纯前端假操作 | 半 mock（P2-7） |
| 死代码 | components/FileUpload.vue（零引用）；Landing demo 动画（明示演示） | — | 待清理/豁免 |

## 收尾核对表

- P0：0 项。P1：1 项（C2 链未接生产装配）。P2：8 项。P3：孤儿/双实现/体验类（主报告 §8/§9）。
- 本轮零生产修改；两份文档未提交未暂存；未 Push/Merge/部署/升级数据库/改 ADR。
