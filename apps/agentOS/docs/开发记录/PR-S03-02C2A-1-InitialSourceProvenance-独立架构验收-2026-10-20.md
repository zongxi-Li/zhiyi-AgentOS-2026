# PR-S03-02C2A-1 Initial Source Provenance 独立架构验收

日期：2026-10-20。验收人：独立架构验收工程师（与实施会话分离）。结论：**ACCEPT**。全部验收产物未暂存、未提交；本轮无 Push、Merge、部署、正式 ADR 或业务数据库变更，未实施任何 C2A-2 行为。

## 结论

一个 Initial Planning Commit 确实封存了后续首次编译所需的全部语义输入，其接受身份在来源漂移、并发竞争、重放与历史兼容条件下可信。未发现 P0/P1；登记 2 项 P2 与 1 项 P3，均不破坏本阶段受限合同。跨库（Registry/代码文件/Identity 与 Workflow SQLite 之间）不存在联合 CAS，最后一次外部读取到 COMMIT 之间的竞争窗口经独立实验证实存在，但在"封存正文自洽、物化只消费封存正文"的合同下不构成 P1，必须由 C2A-2 的最终物化事务内重验继续约束。

## 已确认的证据

### 1. 入场基线与源码摘要（独立复算）

- HEAD `dac4217836f3ea468df25f61c8692d38a032704d` 与任务书一致；暂存区为空；工作区仅 4 个修改（`src/contracts/planning_commit.py`、`src/runtime/planning_commit.py`、`src/components/planner/planning_commit.py`、根 `scripts/freeze_gate.py`）加 4 个新增（`initial_planning.py` 合同、`initial_planning_sources.py` 捕获、34 项测试、实施记录），另有上一轮 C2A 提案原样保留，与本轮声明一致。
- 441 个 src/tests Python 文件聚合 SHA-256 独立复算为 `18c378633691a305b15a9036bb6ccafb40987db27a872ede3238fcb82dfcb8f6`；API 文件 `apps/agent/app/api/agentos_v2.py` 为 `b78ffdd8d0b1c004f9befdd63c7372070cf9a733c244f86591328897791ccc21`；`scripts/freeze_gate.py` 为 `46e7460d12ab2cbe8435deb0b9f711fe48424e6c3efb28fe5dfe1d45f0132cfd`。三者与实施记录逐字一致。
- `freeze_gate.py` 的 diff 仅为 5 行受影响模块→测试映射新增，预算、筛选策略、断言与基线机制未被修改。
- 实施记录自述的定向 280 / 扩大 1233 / 全量 1848 结果与最终源码摘要、测试计数映射（1814+34、1199+34）自洽；本轮按测试预算未机械重复三轮，以定向 34 项、映射门禁 139 项与独立对抗实验替代（见第 6 节）。

### 2. 来源正文完整性与真实消费调用链（8/8 类）

逐项精读合同、捕获器与消费方代码后确认：

| 来源 | 封存形态 | 消费调用链证据 |
|---|---|---|
| Mission/revision/Basis/scope | `basis`、`scope` 全文，`mission_revision=basis.source_revision`；coherent 校验 basis/scope/workflow 一致 | `_runtime_sources` 读 `mission_semantic_state` + `run_intent_basis(run)`，二者同 Workflow SQLite |
| WorkflowDefinition | 全文深拷贝（含 domain/version/planningNodes/steps），非仅 ID | `_workflow_for_run(run)`，模板下沉与 L1/L2 输入均取自该副本 |
| Agent Profiles | scoped 内 `AgentProfile.model_validate` 重验后复制，保留登记次序；coherent 校验 ID 唯一且覆盖 `scope.agent_ids` | `plugin_scope_resolver.scoped_agents(scope)`；CognitiveRouter `candidates_for` 只消费 profile 的 domain/capabilities/priority |
| Catalog 双封存 | scoped `catalog` 与全局 `validation_catalog` 均全文（各 ≤512） | 语义验证用 `initial_provenance.validation_catalog`（`_validate_proposal` L209-214），L1/L2 用 `origin.catalog` 注入 planner 三组件 |
| TaskPlan/Identity | TaskPlan 作为 `proposalPayload` 全文持久化；Identity 经 `task_plans.latest` 存全文+指纹；首次无计划显式 `null`+`digest(None)`；repository 缺失（`identity_lifecycle=None`）拒绝而非视为空 | Record validator 校验 payload 指纹与 `missionIntentBasisRef` 绑定 |
| 非模板 L1 Profile | `intent_parser.parse` 实际输出全文（模板路径 null，由 Workflow 提供下沉依据） | L499-506 冻结实际 profile 并重封指纹；`validate_initial_sources` 从 Record 读取，不重调模型 |
| materialRefs/seed/diversity/capabilityProfile | materialRefs 正文；`loweringOptions` 三项；run.input 其余仅存 `inputFingerprint` | `workset.validate_sources(run.input.materialRefs)`、variant_generator `generate(diversity, seed)` |
| 编译策略身份 | `initial-compilation-policy-v1`：6 个版本标签 + 6 组实现文件 SHA-256（topology 组含整个目录） | `TaskPlanTopologyCompiler`/`CapabilityBindingSolver` 真实默认构造与标签值一致（512）；`CognitiveRouter.route` 只依赖 profile+catalog+agents+常量 entropy_per_edge，全部可从封存正文确定性重建 |

关键接受链验证：`_accept_initial` 两次显式捕获并比较（L455-458）；L1/L2 在 Run 锁外使用 `origin.workflow`/`origin.catalog` 私有副本，`_planning_engine_for_run` 对带 scope 的 Run 每次新建 PlanningEngine，冻结 Catalog 注入不污染共享实例；服务层 `service._accept` 在 BEGIN IMMEDIATE 事务内于语义验证前后各做一次完整重捕获比较，`get_source_provenance` 与 `store._append` 均以 `model_validate_json` 重新解析校验。接受后不存在任何从 Registry、全局 Catalog 或动态服务重新读取以构成接受语义的路径——重读仅用于漂移检测（不匹配即拒绝）。

### 3. 指纹、CAS、幂等与 outbox（真实 SQLite 对抗）

- `staticFingerprint` 为排除自身的规范化正文 SHA-256，由 coherent validator 强制自洽；`initial-acceptance-v1` 将 runtime 指纹与 static 指纹合成为 `strategyFingerprint`；`requestFingerprint` 覆盖含 sources 全文的请求；Record validator 再校验 Initial 绑定（类型/mission/revision/策略摘要/TaskPlan/basis 引用）。绑定关系一致。
- Record 与 outbox 在 `SQLitePlanningCommitStore._append` 同一 `BEGIN IMMEDIATE` 事务内插入两表；`UNIQUE(mission_id, revision)` 与 `idempotency_key UNIQUE` 是数据库层硬约束。34 项测试的 record/outbox trigger abort 与 commit/ack 故障切口证实零部分提交，ACK 丢失重试返回 IDEMPOTENT_REPLAY 且 outbox 不重复。
- 同 Key 重放先于来源重验命中（`_replay` 在 `_validate_sources` 之前）；不同 Key 同 expectedRevision 跨真实连接竞争得到恰一个 ACCEPTED 与一个 STALE_COMMITMENT。
- 独立对抗实验（`tmp/c2a1_audit_independent/adversarial_probe.py`，真实 Runtime/SQLite，无 Mock 成功）：
  - `polluted_provenance`：以 `model_copy(deep=True)` + `object.__setattr__` 篡改 workflow.domain 后注入 provider，接受被 AUTHORITY_DENIED 拒绝，ledger 无新 Record——绕过校验对象不能污染持久化来源。
  - `concurrent_accept_initial`：两个线程并发调用真实 `accept_initial` 入口，结果恰为 ACCEPTED + IDEMPOTENT_REPLAY，outbox 1 条，Mission head 唯一。
  - `preflight_readonly`：`validate_initial_sources` 执行前后对全部 SQLite 文件（workflow/ledger/identity/checkpoint/values/memory/provenance/audit/content）逐行 dump 对比为空——只读预检确认无 GraphVersion/Checkpoint/Receipt/执行态写入。
  - `drift_replay`：接受后清空 agent capabilities 再重放，返回 STALE_STRATEGY，Record 字节不变、outbox 不变（历史接受事实不可变）。
  - `replay_capture_count`：首次接受共 5 次完整捕获（显式 2 次 + 事务内 3 次），重放 1 次——重放路径确实重新捕获并比较（见 P2-1）。

### 4. 来源漂移与历史兼容反例

34 项正式测试（本轮独立运行 51.3s 全过）覆盖：接受后 capabilities 漂移、同 version 的 Workflow domain 漂移（持久快照保持原值）、10 类当前来源围栏（catalog/policy/identity/scope/input/permission/principal/mission/basis 篡改拒绝/authority 摘除）、锁外规划期间 profile/workflow/policy 三类变化拒绝、损坏/未知版本/缺 Workflow/重封指纹四种 Record 拒绝、legacy `sourceProvenance=None` 记录重放 IDEMPOTENT_REPLAY 且不升级、`validate_initial_sources` 对历史记录返回 INVALID_PROPOSAL、凭证配置拒绝且不落盘、ResourceBinder 动态资源隔离（`assess` 被调用即断言失败，封存文本无 leaseId/heartbeatAt）、Identity 权威不可用拒绝、首次无 Identity 计划显式 null、非模板实际 L1 Profile。

捕获失败的降级方向正确：`get_current_sources` 捕获失败时返回 `initial-source-unavailable-v1` 失效指纹，必然不等于请求指纹 → STALE_STRATEGY，不存在退回旧来源投影的路径。Scope/Policy 无法捕获时同样收敛为拒绝。

### 5. 唯一权威与权限边界

- Record 写入路径唯一：`Store._append` 仅被 `PlanningCommitService._accept` 调用；Runtime 侧 `accept_initial` 是 Initial 唯一入口（`_materialize_acg_run` L878-883），API 层（`agentos_v2.py`）无暴露。Runtime Provider 只提供正文，`requires_versioned_initial_sources` 缺证明即 INVALID_PROPOSAL。
- 客户端/模型合同未新增来源正文或权限字段；来源正文全部服务端捕获。
- Initial 不构造图、不生成 GraphVersion、不创建 Head、不签发 Permit：34 项测试断言 `execute_prepared_run` 后仍 `planningDeferred`、无 Blueprint/Steps/Agent 调用/收据；现有物化链强制 `source.proposal_type == "plan_revision"`，Initial 记录无法进入；`validate_initial_sources` 成功不构成物化许可。
- 旧 runtime/graph_revision 来源链（`runtime-static-v2`）未被修改。

### 6. 门禁结果与未覆盖范围

- `pytest tests/components/planner/test_initial_planning_sources.py`：34 passed（51.32s）。
- 默认基线 `python scripts/freeze_gate.py`：INCOMPLETE_TIMEOUT（300.9s）。阻断原因已定位：s03-02b1 基线累积了 B2、C1、C2A-1 三轮未提交源码变化，映射出 11 个测试文件（含 execution_permit、permit_recovery、kernel_vertical_slice、contract_review_delivery 等重组件），300 秒预算物理不够（10-19 历史先例：3 个文件 257s、另一次 300.4s 超时）。这是多轮冻结堆叠在同一未提交工作区的门禁使用问题，不是 C2A-1 代码回归；未以任何方式放宽预算换取通过。
- C2A-1 定向门禁：以"当前工作区快照剔除本轮 6 个源码/测试文件"为基线（等价于 C2A-1 前状态，规避不可重建的历史行尾差异），changed 恰为本轮 6 文件，映射选出 4 个测试文件，**PASSED 148.3s / 300s，139 passed / 0 failed，无 uncovered、无 missing，`git diff --check` 退出码 0**。新映射自身经门禁闭环验证。
- 未覆盖范围（如实登记）：实施记录的三轮大规模结果本轮未重复执行，仅通过摘要独立复算与映射一致性核验采信；Java、Vue、浏览器、外部供应商模型、多进程/跨机故障不在本轮与实施记录的验证范围。

### 7. 跨库一致性限制（第六节要求的具体时序）

Workflow SQLite（runs/mission_semantic_state/ledger）在 BEGIN IMMEDIATE 事务内读取，写锁排除并发写，该部分无窗口。Registry（内存对象）、实现代码文件、Identity（独立 `identity.sqlite3`）分属不同存储，只有"捕获-摘要-事务内重读比较"模式。可观察的剩余窗口时序：

1. T0 事务内最后一次 `_validate_sources` 完整重捕获（读取 Registry/文件/Identity）；
2. T1 `authorize` 第二次调用、CAS 检查、Record 构造与两表插入；
3. T2 COMMIT。

独立实验（`post_fence_window`，在 authorize 第 3 次调用即 T1 时刻注入变化）：T1 时刻清空 agent capabilities → 接受仍成功，封存 profile 保持原 capabilities；T1 时刻向 Identity 库写入 planVersion 99 → 接受仍成功，封存 snapshot 保持 planVersion 1。窗口真实存在且未被子事务排除。

定性：不构成本阶段 P1。Record 声明的是"捕获时刻"的来源，封存正文完全自洽；T1-T2 的外部变化不进入 Record，也不使 Record 谎报（其内容指纹与正文一致）。危害仅在 C2A-2 若从 Registry/Identity/全局 Catalog 重读输入时才会出现，因此必须作为 C2A-2 的硬性消费合同（第 8 节）。ABA（外部状态变化后在 T0 前变回相同内容）产生内容一致的来源，语义等价，无害。两次显式捕获+事务内重验能保证的是"各次读取时刻内容一致"，不是跨库原子快照；不得宣称联合 CAS 已解决——实施记录同此声明，无夸大。

### 8. C2A-2 必须遵守的来源消费合同

1. 物化输入只能从 `ledger.get(commit_id).source_provenance` 封存正文构造：Workflow、scoped Catalog、Agent Profiles、Identity snapshot、semantic_profile、loweringOptions、policy；禁止以 Registry、`runtime.capability_catalog`、`identity_lifecycle`、默认配置或任何动态服务的当前值替代或补齐封存字段。Router/绑定可由封存 profiles+catalog 确定性重建（`route` 仅依赖这三者与常量），或等价地直接构造 CollaborationNetwork。
2. 最终物化事务内必须重复来源/权限/Mission head 验证（附着 Authority、当前 head、权限、封存来源与重读比较），不得以 `validate_initial_sources` 预检成功或历史 Receipt 替代；预检不是物化许可。
3. `run.input` 中 materialRefs 之外的内容只有 `inputFingerprint` 无正文；若物化确需其他输入正文（如附件上下文），必须新增显式封存字段并重走接受合同，不得回读运行时 input。
4. Initial→GraphVersion1 需要：确定性 ID/时间、完整候选/Bindings/CompiledACGPackage 持久化、MaterializationAuthority 唯一 Journal、Head+Run 原子 CAS、无 Permit 真实派发拒绝——均未在本轮实施，C2A-2 不得以 Initial 证明绕过。
5. 重放恢复路径重审：同 Key 重放在来源漂移后返回 STALE_STRATEGY（P2-1）；ACK 丢失叠加漂移时调用者须经 `get_by_idempotency_key`/`latest` 恢复事实，C2A-2 编排器不得假设重放必然取回 commit_id。

## 发现清单与处置

- **P2-1 重放语义与恢复路径**：`accept_initial` existing 分支先执行 `validate_sources`（重新捕获比较）再进入服务层幂等重放。来源漂移后重放返回 STALE_STRATEGY 而非 IDEMPOTENT_REPLAY；历史 Record/outbox 不受影响（实验证实）。保守正确（避免向编排器掩盖漂移），但 ACK 丢失窗口叠加漂移时只能查库恢复。不修复本轮；列入 C2A-2 前置重审（第 8 节第 5 条）。
- **P2-2 默认门禁基线过期**：B1 基线在本工作区必然超 300s 预算。建议冻结提交序列化后以最新快照刷新 `freeze_gate_baselines`，属流程项非代码缺陷。
- **P3 异常合同不一致**：`accept_initial`/`get_current_sources` 仅捕 `ValueError/KeyError/TypeError`；捕获期 `AttributeError`、`RuntimeError`、SQLite 异常会以原始异常传播而非 STALE_STRATEGY 拒绝。行为仍是拒绝且无部分提交，仅上层错误处理不一致。
- 无 P0、无 P1。未删除任何安全反例，未放宽任何断言，未将未执行测试计为通过。

## 最终判定

**ACCEPT**。核心问题的回答为"是"：首次编译所需全部语义输入（八类正文齐全，消费链逐项核对）已被封存，接受身份经真实 SQLite 竞争、故障切口、漂移反例、污染注入与真实入口并发验证可信；历史兼容不升级旧记录；跨库窗口如实存在、如实登记、且在"物化只消费封存正文"合同下不破坏本阶段承诺。修复与报告均保持未暂存、未提交。
