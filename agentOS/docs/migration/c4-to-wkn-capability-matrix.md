# C4-mainline → wkn ACG Capability Disposition Matrix

## 审计边界

- 共同祖先：`87e6ee39126a49d25fa1c90f2810ea1fb9606a3e`
- C4 来源：`C4-mainline@e4a582f453d4db8f1fd6268de8a485d7904a7254`
- 唯一目标内核：`wkn-master@3f6c5365c7ca4358613001ab6529657ba56d36cf`
- 审计范围：共同祖先之后的生产代码、测试和提交；文件行号会随迁移变化，因此证据使用锁定提交下的路径与测试名。
- `REPLACED` 表示采用 wkn 实现并通过等价性测试；`MIGRATE` 表示按 wkn 分层补齐；`DEFER` 表示不阻塞本轮主链且有明确后续里程碑；`DROP` 表示明确删除。

这份矩阵是删除 C4 内核能力的门禁。所有已识别的 C4 ACG 核心能力均已分类；后续若发现新增能力，必须先补充本表再修改实现。

## Capability Matrix

| 领域 | 能力 | 共同祖先状态 | C4 代码 / 测试 / 提交证据 | wkn 代码 / 测试证据 | Disposition | 迁移动作 | 验收测试 |
|---|---|---|---|---|---|---|---|
| Planning | 有界语义意图解析 | 部分 | `core/planning/intent_parser.py`；`bdf917b` | `components/planner/service.py`、`algorithms.py` | REPLACED | 使用 wkn PlanningEngine；应用层注入 intent LLM | 固定输入的意图、约束和 fallback 等价性 |
| Planning | planning diversity | 无 | `core/planning/variants.py`；`test_stochastic_planning.py`；`3b49716` | `components/planner/algorithms.py`；runtime planning 参数测试 | REPLACED | 保留 wkn 归一化与确定性选择 | diversity 边界、多拓扑且语义不漂移 |
| Planning | planning seed | 无 | `core/planning/engine.py`；`test_stochastic_planning.py` | `normalize_planning_seed`、WorkflowRuntime | REPLACED | seed 进入 wkn 规划输入 | 同 seed 同 blueprint，不同 seed 只在允许空间变化 |
| Planning | entropy budget | 无 | `core/planning/budget.py`；`bdf917b` | planner contracts/algorithms 中预算约束 | REPLACED | 采用 wkn 预算合同 | 越界拒绝、预算耗尽后确定性收敛 |
| Planning | 模板匹配 | 部分 | `core/planning/template_matcher.py`；`test_generic_planning.py` | `components/planner` + workflow registry | REPLACED | 迁移业务模板为 pack/workflow 注册项 | Legal/General 模板命中与 fallback |
| Planning | capability dependency | 部分 | `core/planning/capabilities.py`；`605fd9b` | `support/acg/models.py` capability catalog | REPLACED | 使用 wkn capability catalog 与依赖验证 | 缺失依赖拒绝、交付节点可达 |
| Planning | C4 高级规划诊断字段 | 无 | `045b2b6`；C4 API planning diagnostics | wkn 仅保留内核所需规划状态 | DEFER | 不污染 Runtime state；产品需要时另做授权投影 | 后续 ADR；本轮验证不伪造字段 |
| Execution | ready-set 调度 | 部分 | `core/execution/acg_executor.py`；runtime graph tests | `components/executor/state_graph.py` | REPLACED | 使用 wkn StateGraph | 依赖未满足不执行、就绪节点一次入队 |
| Execution | 并行 superstep | 无 | `test_runtime_graph_execution.py`；`0eade86` | `state_graph.py`；`tests/runtime/test_acg_run.py` | REPLACED | 采用 wkn superstep | 同层并行、下一层等待屏障 |
| Execution | batch barrier | 无 | RuntimeGraph 批次检查点；`d0bb6be` | StateGraph superstep 边界 | REPLACED | 将 barrier 语义映射到 superstep | 上一批全终态后才推进 |
| Execution | 声明式条件路由 | 无 | `test_runtime_conditional_patch.py`；`0eade86` | `ACGConditionalRoute` in `graph.py/compiler.py` | REPLACED | 用 wkn route contract | true/false 分支及未选分支跳过 |
| Execution | 控制节点 | 无 | `runtime_graph.py` control/condition 节点 | compiler/state graph 条件节点 | REPLACED | 转换为 wkn 图节点/路由 | 控制节点不产生正文输出 |
| Execution | skip semantics | 无 | C4 条件补丁测试 | `skippedStepIds`、`StepStatus.SKIPPED` | REPLACED | 采用 wkn skip 投影 | 未选路径标记 skipped 且不调用 agent |
| Execution | 引用式 execution state | 无 | C4 后期压缩 checkpoint 仍混有旧 DTO | `ACGExecutionState`、`ExecutionValueStore` | REPLACED | 仅保存 output/context/memory/trace/provenance refs | state/checkpoint 正文泄漏扫描 |
| Execution | 稳定 commitId / committed replay | 无 | C4 无同等提交协议 | `ACGNodeRunner`；`58ca7be` | REPLACED | 使用 `commit:{run}:{step}:{attempt}` | 重启后 commitId 稳定且不重复调用 |
| Execution | graph version | 无 | `RuntimeGraph.version`、动态补丁预算 | `ACGExecutionState.graphVersion` + `GraphPatchService` + checkpoint CAS | MIGRATED | Phase 5 已增加不可变 graph revision，并由安全屏障内的 patch 原子递增 | `test_graph_patch.py`：stale version 冲突、重放版本一致 |
| Execution | 动态图修改 | 无 | `runtime_graph.py`；`test_runtime_dynamic_execution.py`；`0eade86` | `components/executor/graph_patch.py` 在审核屏障验证并产生新 Blueprint revision | MIGRATED | Phase 5 以不可变副本应用节点/边增删，不恢复 RuntimeGraph | 插入新节点、DAG 校验、恢复后执行新拓扑 |
| Binding | 候选过滤 | 部分 | planning/recovery bindings | `ResourceDirectory`、`PluginScopeResolver` | REPLACED | 使用资源目录和冻结 scope | capability/security/scope 不匹配被过滤 |
| Binding | 冻结资源绑定 | 无 | C4 binding snapshot | `RunExecutionScope`、`test_resource_binding.py` | REPLACED | run 启动时冻结资源引用 | 注册表改变不影响已启动 run |
| Binding | 健康过滤 | 部分 | C4 alternate binding policy | `components/resource/health.py` | REPLACED | 使用 wkn health snapshot | unhealthy 资源不入候选集 |
| Binding | alternate binding | 无 | `core/recovery/bindings.py`；`test_alternate_binding_policy.py`；`3c6626a` | `ResourceDirectory.resolve_agent_candidates` + `WorkflowRuntime.rebind_step` | MIGRATED | Phase 5 只允许在持久审核屏障、冻结 scope 内对未执行节点切换一次 | `test_graph_patch.py`：可审计切换、冻结 agentId 生效、预算耗尽终止 |
| Recovery | 节点 retry | 部分 | recovery policy/controller | `components/recovery`、prepared retry；`69cee8b` | REPLACED | 使用 wkn prepared commit 恢复规则 | prepared 节点重试，committed 节点只重放 |
| Recovery | checkpoint resume | 部分 | C4 governance checkpoint | `ACGCheckpointStore`、`ExecutionResumeCommand` | REPLACED | 使用独立 SQLite checkpoint | 重建 Runtime 后从同一版本恢复 |
| Recovery | checkpoint CAS / run 隔离 | 无 | C4 旧 store 不具备等价保证 | `components/recovery/checkpoint.py`；checkpoint tests | REPLACED | 保留 expected_version CAS | stale writer 冲突、跨 run 不可读 |
| Recovery | contract repair | 无 | `core/recovery/contract_adapter.py`；`399224f` | `components/recovery/contract_repair.py` 使用 wkn communication contract | MIGRATED | Phase 5 仅允许唯一数组包裹与显式 schema default，不做语义补造 | `test_contract_repair.py`：无损哈希、默认值、缺失必填拒绝 |
| Recovery | recovery recipe | 无 | `core/recovery/recipes.py`；`test_recovery_recipes.py` | `contracts.RecoveryRecipe` + `components/recovery/recipes.py` | MIGRATED | Phase 5 提供 capability-only registry、稳定匹配和每 run 应用预算输入 | `test_recipes.py`：匹配、复制隔离、预算耗尽拒绝 |
| Recovery | GraphPatch | 无 | `core/recovery/models.py/proposal.py`；patch compiler tests | `GraphPatch/Result` + `GraphPatchService` + `ExecutionValueStore` | MIGRATED | Phase 5 将 patch 正文存独立值仓库，State/checkpoint 只留引用 | `test_graph_patch.py`：引用归属、幂等、CAS、DAG 与 resume |
| Recovery | review interrupt/resume | 部分 | C4 review/checkpoint API | `ReviewManager`、`ExecutionInterrupt`；`57d68fe` | REPLACED | 采用 wkn 持久决定与 resume | WAITING_REVIEW→restart→approve→complete |
| Tool | 工具授权 | 部分 | `core/tool_execution.py`；`test_acg_tool_policy.py`；`d35e423` | `adapters/audited_tool_runtime.py` | REPLACED | 应用工具注册表接入 AuditedToolRuntime | 未授权/越权参数拒绝并审计 |
| Tool | offline policy / bounded execution | 无 | `test_acg_tool_policy.py` | AuditedToolRuntime policy | REPLACED | 保留显式 offline 与调用边界 | offline 禁止网络工具；超范围调用失败 |
| Tool | tool event / audit | 部分 | C4 runtime events | AuditedToolRuntime + Decision/Trace stores | REPLACED | 工具事件写引用和审计元数据 | 成功/拒绝/失败均可追踪且无正文泄漏 |
| Tool | 真实联网检索链 | 无 | `8107ed7`；`agent/app/tools`、RAG integration | Application `AgentsToolRuntime`/Tavily catalog 经 `AuditedToolRuntime` 注入 | MIGRATED | Phase 5 保留真实 provider 并验证只读授权、离线拒绝、安全事件和 citation 输出 | `test_wkn_network_tool_chain.py` + Legal tool vertical slice |
| Memory | working memory | 部分 | C4 context/runtime state | `components/memory`、SQLiteMemoryStore | REPLACED | 使用 wkn MemoryService | run/step 所有权隔离与预算 |
| Memory | episodic / semantic | 部分 | C4 memory modules | `MemoryType` 白名单；`e1424dd` | REPLACED | 使用 wkn 类型与 admission | 类型白名单、跨 run 访问门禁 |
| Memory | evidence memory | 部分 | Legal RAG/evidence 与 C4 memory | Legal retrieval/matching 节点使用 `MemoryType.EVIDENCE`，State 仅留 `memoryRef` | MIGRATED | Phase 5 在 Legal Blueprint 声明审计型 evidence 写策略 | Legal golden test 验证 evidence 类型、引用归属和 State 无正文 |
| Memory | memory policy / token budget | 无 | C4 planning/context budget | `contracts/memory.py`、planner memory policy tests | REPLACED | step policy 驱动读取/写入 | token 上限、禁止类型、审计事件 |
| Memory | 审核前延迟正式写入 | 无 | C4 review flow 部分实现 | `57d68fe` review-memory isolation | REPLACED | 采用 wkn pending/admission 语义 | approve 前无正式记忆，拒绝不落库 |
| Governance | Trace | 部分 | C4 trace/event DTO | `TraceStore`、execution trace tests | REPLACED | 使用 wkn Trace 类型与存储 | 生命周期与节点事件完整、不重复 |
| Governance | 持久 AuditDecision | 无 | C4 audit/review | SQLiteDecisionStore；`57d68fe` | REPLACED | 决定独立存储、按归属解引用 | run/step 归属错误拒绝 |
| Governance | 人工审核 | 部分 | `core/governance/review.py`、C4 UI | ReviewManager + persisted decision | REPLACED | Runtime 是唯一审核状态真源 | 冲突、重复批准、重启恢复 |
| Governance | Provenance / hash chain | 无 | C4 lineage fields | SQLiteProvenanceStore；`9b3c2a7`、`57d68fe` | REPLACED | 使用独立账本并启动时验证 | 篡改检测、并行事件隔离、不重复 |
| Governance | 引用所有权验证 | 无 | C4 引用检查不完整 | `dd48f0b`、value/memory/provenance/decision stores | REPLACED | 所有解引用校验 run/step/tenant scope | 跨 run 引用注入拒绝 |
| Product | Python Application wiring | 部分 | `agent/app/api/agentos_core.py`、`execution/runtime.py` 依赖 `agentos.core` | `app.execution.wiring` 完整注入六个存储、模型、工具和 Pack | MIGRATED | Phase 3 已切到唯一 WorkflowRuntime；生产代码旧导入为零 | `test_wkn_application_wiring.py` + kernel regression |
| Product | Legal Contract Review | 部分 | Legal prompts/RAG/pack 与端到端 API | wkn ACG + Legal Pack 非线性 Blueprint + 引用式输出 | MIGRATED | Phase 4 已完成并行、条件、审核重启、工具、记忆、血缘黄金纵切 | `test_legal_wkn_vertical_slice.py` |
| Product | General/Native、Programmer、Education、Writer packs | 部分 | C4 domain profiles/workflows/UI | wkn Runtime + Pack capability contribution + 声明式 workflow contract | MIGRATED | Phase 6 按固定顺序完成四个 Pack，旧 memory observation 改为 ContextPack | `test_wkn_domain_packs.py`：profile/capability/workflow/tool/memory/output |
| Product | HTTP API | 部分 | C4 `/agentos` API 投影旧 RuntimeGraph/正文 | wkn Runtime 无冻结产品 API | MIGRATED | ADR-001 冻结 `/ai/agentos/v2` 引用式投影；Run/Graph/Output/Trace/Provenance/Checkpoint/Review 分离，输出按 run 所有权解引用 | `test_agentos_v2_api.py`：正文隔离、引用归属、Trace 脱敏、幂等/冲突 |
| Product | Spring Gateway | 无 | backend AgentOS controller/service | 无内核实现（正确边界） | MIGRATE | 仅 auth/authz/scope/DTO/proxy/error mapping | 后端无状态机/checkpoint/recovery 逻辑 |
| Product | ACG 工作台、拓扑、Trace、Provenance、Review、成果 | 无 | C4 frontend stores/views/tests；`d2e4c11` | wkn 不含产品 UI 数据适配 | MIGRATE | 保留交互，重写模型/store/derived state | 浏览器 E2E 全链；不伪造缺失字段 |
| Product | 历史列表与运行历史 | 部分 | C4 API/frontend history | wkn WorkflowStore 提供新运行数据 | MIGRATE | 只展示新 runtime 数据 | 分页、scope、重启后查询 |
| Product | Docker 日常开发 | 部分 | compose 仅挂载 `agentOS/src`，ai-service 现有导入失配 | wkn 需要 repo/agentOS/src 三层 path | MIGRATE | 完整挂载 agent/agentOS，使用新 volume 和六个 DB 变量 | 五服务 healthy、源码热更新 smoke |
| Product | C4 历史运行/checkpoint/database | 部分 | C4 stores 与现有 volume | 与 wkn 引用式存储不兼容 | DROP | 旧 volume 仅备份；不转换、不加载、不删除 | 新 runtime 不读取旧 DB；备份仍存在 |
| Product | C4 RuntimeGraph DTO / `step.output` / legacy counters | 无 | C4 API 与前端旧数据模型 | wkn state 为引用式 | DROP | 对应能力迁移后删除表示层兼容 | 全仓生产代码扫描无旧字段依赖 |
| Hardening | 外部超时/重试/限流、commitId 外传、孤儿 GC、五阶段故障注入、BLACKBOARD、DEBATE | 无 | 非本轮 C4 必需基线 | `3f6c536` 仅设计文档 | DEFER | 单独 Phase 11 milestone，禁止混入主迁移 | 本轮报告明确未宣称完成 |

## 汇总

### C4-only（需迁移）

业务图版本与动态修改、GraphPatch、alternate binding、无损 contract repair、recovery recipe、真实联网工具链、Legal evidence memory 接线、应用/领域 Pack/API/Spring/前端/Docker 产品链。

### wkn-only（直接保留）

引用式 Execution State、稳定 commitId、prepared/committed 恢复协议、checkpoint CAS、独立 ExecutionValue/Memory/Provenance/Decision 存储、持久审计决定、血缘哈希链、严格引用归属校验、审核记忆隔离。

### 等价能力（REPLACED）

语义规划、多样性/seed/entropy、模板和能力依赖、ready-set/并行屏障/条件路由/skip、资源冻结与健康过滤、retry/resume、工具授权与审计、受控记忆、Trace/Review/Provenance。

### 明确删除或延期

- `DROP`：C4 历史数据兼容、旧 RuntimeGraph DTO 与正文内嵌字段。
- `DEFER`：展示型高级规划诊断，以及 `3f6c536` 中列出的迁移后 Runtime Hardening。

## 变更门禁

1. `MIGRATE` 项必须先有失败测试，再实现，再将状态改为 `MIGRATED`（保留原 disposition 历史于阶段报告）。
2. `REPLACED` 项必须在 kernel regression 或 capability regression 中有证据。
3. 新发现的 C4 能力不得口头归类；必须新增矩阵行。
4. 不允许通过恢复 `agentos.core`、兼容 RuntimeGraph 或第二套 Executor 来关闭缺口。
