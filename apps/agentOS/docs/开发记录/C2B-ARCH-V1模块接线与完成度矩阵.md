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
