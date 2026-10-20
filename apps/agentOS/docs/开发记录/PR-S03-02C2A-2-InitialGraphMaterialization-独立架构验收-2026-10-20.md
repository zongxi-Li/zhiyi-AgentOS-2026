# PR-S03-02C2A-2 Initial Graph Materialization 独立架构验收

日期：2026-10-20。验收人：独立架构验收工程师（与实施会话分离）。结论：**ACCEPT**。本轮验收产物未暂存、未提交；无 Push、Merge、部署、正式 ADR 或业务数据库变更；未开放首次图执行，未实施任何后续阶段行为。

## 结论

同一已接受的 Initial Planning Commit 经本轮合同生成唯一、可恢复的 GraphVersion 1，并通过正式 Head/Run 原子 CAS 进入 `ACTIVATED_PAUSED`；无 Permit 时真实派发入口全部拒绝；来源漂移、并发竞争、进程死亡与未知提交结果均不能产生冲突版本或错误激活。未发现 P0/P1；登记 2 项 P2 与 1 项 P3，均不破坏受限合同。跨库联合 CAS 仍不存在（已知限制），物化事务的剩余窗口经独立实验证实存在，且由激活前完整重验关闭。

## 1. 实际入场与最终源码摘要

实施记录声称的入场 HEAD `dac42178` 是 C2A-2 实施起点。当前仓库实际状态为：C2A-1 与 C2A-2 已由用户分两笔提交——`7265dd60`（固化首次规划提交的可信编译来源）与 `41a271cc`（实现首次图物化与暂停激活），当前 HEAD 为 `41a271cc`，master，工作区完全干净（`git status` 为空）。这与实施记录"所有修改未提交"的表述不同（提交发生在实施与验收之间），不影响验收对象：逐文件核对确认两笔提交内容与 C2A-1 已验收工作区、C2A-2 声明范围一致，无其他修改混入。

独立复算（原始字节，freeze_gate 同算法）：

- 当前树（= 41a271cc 检出）：443 个 src/tests Python 文件聚合 `d08de700d22e375ec480ab9b6bb8978cbb96bc6079874856e71fb43422ebe0c9`，与 C2A-2 最终摘要一致。
- 基线 `scripts/freeze_gate_baselines/s03-02c2a1-accepted.json` 原始字节 SHA-256 为 `1848fd570613c84fd0bf2afe9ca5312a61d642a0e6d013b7412a2e80a1b8bd97`；其内 441 文件清单聚合仍为 C2A-1 已验收摘要 `18c378633691a305b15a9036bb6ccafb40987db27a872ede3238fcb82dfcb8f6`。
- API 文件 `b78ffdd8…`（未变）；freeze_gate 脚本 `4ee8db0322cf289e30a06ab429cf9dc8072a07b7166c0af5cec523d827703a09`，均一致。

## 2. 工作区及测试基线差异

基线（441 文件）与当前树（443 文件）逐文件对表，差异恰好 8 个路径：6 个既有源码修改（`contracts/graph_materialization.py`、`contracts/graph_activation.py`、`runtime/graph_materialization.py`、`runtime/graph_activation.py`、`runtime/workflow_runtime.py`、`support/stores/graph_activation_store.py`）加新增 `runtime/initial_graph_compilation.py` 与 `tests/components/planner/test_initial_graph_materialization.py`。C2A-1 的六个文件逐字节保持不变；没有 C2A-2 新文件被错误纳入基线而消失于 diff；无 README、EX-00、图片或其他并行工作被触碰。

门禁脚本 diff 复核：默认基线切换为已验收 C2A-1 清单（采纳上轮 P2-2 建议）；新增 7 条映射（支持 `file::node` 精确节点，`missing` 检查相应剥离 node 后验文件存在）；300 秒预算、marker 策略、断言与失败语义未动。`src/runtime/workflow_runtime.py` 新旧两条映射并存，合并选择。11 个 node-ID 映射经 `pytest --collect-only` 独立收集验证全部真实存在（展开 33 个参数化实例）；`uncovered`/`missing` 为空。

门禁报告 125 个收集 node ID 与 125 passed、与实施记录声明的 125 完全一致（见第 9 节）。

## 3. 真实 Initial 物化与激活调用链

`ExecutionRuntime.materialize_initial_commit(commit_id, idempotency_key)`（显式宿主入口）→ 既有唯一 `GraphMaterializationAuthority.materialize(source_kind="initial_plan")` → `_materialize_initial`（纯重建 + 同一 `graph_materializations` Journal）→ 既有唯一 `GraphActivationAuthority.prepare/commit` → 同库 `graph_activations` Journal + `graph_activation_heads` Head + Run CAS。旧入口 `materialize_graph_revision` 显式限定 `graph_revision` 来源，两个入口不能互相冒充（测试断言交叉拒绝）。

无第二套图版本、Journal 或 Head 权威：`GraphMaterializationRecord`/`GraphActivationRecord` 在既有合同上加 `sourceKind` 分支而非新表新类；激活复用 `_verify` → 权威 `_validate` 全链。生产装配边界如实：`materialize_initial_commit` 在 src 内除定义外无调用方，agent HTTP API 无暴露——宿主入口可用与正式 Composition Root/HTTP 接入是两回事，本轮只承诺前者（与实施记录声明一致）。

## 4. 来源封存、recipe 与完整编译包

`runtime/initial_graph_compilation.py` 为纯函数：不持有 Runtime/Store/Agent；从 Ledger Record 重新解析 `sourceProvenance` 与 `proposalPayload`；模板路径用封存 Workflow 构造 lowering input；原生路径用封存 Agent Profiles 构造独立逻辑 Registry + 封存 scoped Catalog + 封存 L1 Profile（复用 PlanningEngine 纯 rebind 方法）、封存 seed/diversity 驱动 VariantGenerator，选择逻辑（最大分 + 封存 seed 平局裁决）与既有 `service.plan` 等价；逻辑绑定必须完整落在封存 Profiles 内（enabled + capabilities 覆盖，越界拒绝）。Topology 唯一权威 `validate_task_plan_for_execution` 先行；ACGLowerer/ACGGraphCompiler 为唯一编译链。测试证明把 `runtime.capability_catalog/agent_registry/identity_lifecycle` 置 None 后重建结果与持久化 Journal 逐字段相等——当前 Registry/Identity/全局 Catalog 不参与候选内容。

recipe 绑定本轮重建、物化、激活、投影及 PlanningEngine 纯方法的 5 个实现文件摘要，写入 Blueprint metadata；物化最终事务内（登记前）与激活 `_verify`（prepare 与 commit 各一次）三处重验（`test_initial_recipe_identity_is_fenced` 双相位反例：编译期或激活期指纹变化均 STALE_STRATEGY 拒绝且零残留）。

完整候选与执行包身份：Journal 保存 `InitialGraphContent`（Plan + Bindings + Blueprint）与 `CompiledACGPackage`；激活侧一致性校验覆盖 `content.plan == graph.proposal_payload`、commitment/proof 指纹、sources、metadata 身份与 package checksum，不是只比 GraphPatch 或图结构。进程重建实验（四切口）断言 `compile_initial_content(timestamp=持久化时间) == Journal.initial_content` 且重编译 package 相等。

`reasoningEffort` 越权审查：旧 Step 投影会从 Run.input 覆盖 reasoning 并应用 evolutionPolicy；Initial 激活对投影使用临时空 `input`/`execution_state` 上下文，只投影封存 Blueprint（`test_initial_step_projection_uses_blueprint_without_run_input_overrides`：显式 `reasoningEffort=high` 保留在 Run 中，但每个 Step 的输入与 Blueprint 的 input_spec 一致）。真实 Run.input 原样保留、未被用于补齐图或 Step。

历史缺失来源（`sourceProvenance=None`）与损坏 package（checksum 篡改）均结构化拒绝，旧记录不自动升级；4MB Journal 上限防无界写入。

## 5. Journal、GraphVersion 1、Head、Run 的唯一性与事务边界

- 唯一性三层：幂等 Key 事务内重查（同 Key 同 commit 返回 `IDEMPOTENT_REPLAY` 且不覆盖已持久化候选，异 commit `DUPLICATE_CONFLICT`）；`materialization_for(source_commit_id)` 唯一索引（数据库层跨进程约束，异 Key 竞争拒绝）；Run lock 串行同进程竞争。真实双进程 spawn + Barrier 汇合实验：恰一个 `MATERIALIZED_INACTIVE`，同 Key 竞争者返回同 materializationId/checksum，异 Key 竞争者 `REJECTED`。
- 无伪造 GraphVersion 0：合同强制 Initial `sourceGraphVersion=null`、`candidateGraphVersion=1`、Blueprint `version=1`，Head `active_graph_version>=1`；`save_run` 层对已接受 Initial 的 Run 反查 `planning_commit_records`，Head 建立前禁止普通 Run 快照携带 blueprint/steps/taskPlan/graphVersion/checkpoint（伪造写入被拒，测试断言）。
- 事务边界（最高优先级项）：最终激活 `BEGIN IMMEDIATE` 内依次完成 prepared 事实重读、Head 重放判定、`_verify` 完整重验（权限/来源/recipe/Run pristine/head/祖先链）、完整 Run CAS（`_run_from_ledger != run` 即拒绝）、`_activate_head`（Journal 状态升级 + Head upsert，同一事务连接）、`_upsert_run`（Run 全量投影含 Blueprint/TaskPlan/Bindings/Package/pending Steps/`planningDeferred=false`/`graphActivation` 投影，前置 `validate_activation_run`）。三写同连接同事务，源码与 trigger 故障实验（中止 Head 写或 Run 写 → Journal 仍 PREPARED、Head 不存在、Run 无图）双重确认。线性化点为该事务 COMMIT。
- 进程死亡与恢复：四切口（编译后/Journal 后/prepared 后/Head+Run COMMIT 后）均为真实 `os._exit`，重启后按原 Key/Journal/Head 查回同一事实，重放不重编译（compiler 被替换为即失败断言）；Head 建立后迟到写入（绕过 API 直接改 Run 行）不改变 Head，`_claim_acg_execution` 以"workflow run conflicts with the durable activation head"拒绝，commit 重放不 bless 回退状态（本轮独立实验）。

## 6. 独立构造的失败反例与修复

本轮独立对抗实验（`tmp/c2a2_audit_independent/adversarial_probe.py`，真实 Runtime/SQLite）：

1. **权限撤销后的物化重放**：物化成功后把 `semantic_principal_provider` 置 None，同 Key 重放返回 `AUTHORITY_DENIED` 而非历史收据，Journal 完好——历史物化回执不构成当前权限豁免（第六节第 6 条的独立验证；现有测试只覆盖来源漂移维度）。
2. **物化事务剩余窗口**：在事务内最后一次 `_validate` 通过后、Journal 写入前清空 Registry capabilities——物化仍成功（窗口存在，与实施记录 P2 声明一致），封存正文保持原值，随后激活 prepare 被完整重验以 `STALE_STRATEGY` 拒绝且不建 Head——窗口危害由激活围栏关闭。
3. **激活后迟到 Run 写入**：见第 5 节末条。

无 P0/P1，故本轮未做任何修复；未删除任何安全反例、未放宽任何断言。

## 7. 无 Permit 时拒绝真实派发的证据

既有测试已断言（本轮复核采信并经门禁执行）：Handoff 与 ExecutionPermit Authority 的 prepare/issue 被"被调用即失败"监测，物化/激活全程零触发；`_claim_acg_execution` 与 `execute_prepared_run` 对激活后 Run 均抛错拒绝；`graphActivation.executionPermit` 为 None；Steps 全部 `pending` 且 `attempt=0`；无 Attempt、StepExecution、Receipt、Checkpoint、Artifact（全库逐行 dump 扣除 Journal 行前后相等）；新进程重启后同样拒绝。C1 既有合法执行链与 graph_revision 路径未改语义，其既有测试（前缀替换、checkpoint 证据、物化/激活故障、Permit 门禁、C1 纵向恢复）全部在门禁 125 项内通过。B2 的 Permit/Recovery/Handoff/NodeRunner 代码未被修改。

## 8. C2A-1 幂等重放问题的处置

P2-1 保持为剩余限制（PlanningCommitService 未重写）。C2A-2 的恢复路径确认：漂移导致 `accept_initial` 返回 `STALE_STRATEGY` 时，调用方从 `ledger.get_by_idempotency_key("initial-planning:"+run_id)` 恢复原 Commit 身份（不换 Key、不重建）；查回的历史接受与历史物化回执不是当前激活许可——同一场景下 `prepare_graph_activation` 仍因来源漂移被拒绝（`test_replay_lookup_survives_drift_but_cannot_activate`）。新宿主入口直接接收 Commit ID，不依赖重放行为。

## 9. 五分钟门禁结果及未覆盖范围

`python scripts/freeze_gate.py`（仓库根，正式一次）：**PASSED，196.196 秒 / 300 秒，125 passed / 0 failed / 0 skipped，退出码 0**，`git diff --check` 0，uncovered/missing 空，运行前后源码摘要一致（`d08de700…`）。基线为已验收 C2A-1 清单。125 个收集 node ID 与实施记录声明、最终通过数三方一致。与实施记录的 157.8 秒差异为环境负载，均在预算内。

未覆盖范围（如实登记）：全量 pytest 未运行（按测试预算）；未验证超大 DAG、深接受链性能与锁时长；未做多机竞争、外部供应商模型、浏览器/桌面端；默认 Composition Root 与 HTTP API 未接入故无端到端生产链路可验。

## 10. P0/P1/P2/P3 清单

- **P0/P1：无。**
- **P2-1 跨库剩余窗口**：物化最终事务内最后一次外部来源重验到 SQLite COMMIT 之间，Registry/Identity/代码文件变化不被物化事务发现（本轮实验给出具体时序）。封存正文自洽使已持久化候选不谎报；激活前完整重验（含 recipe 与 `validate_sources` 再比较）关闭危害；但开放真实执行（后续阶段）时，任何"激活后免重验"的捷径都会重新暴露该窗口，必须保持分层围栏。
- **P2-2 默认生产装配未接入**：宿主入口可用 ≠ 正式装配可用；Composition Root/HTTP API 接入是后续阶段边界。
- **P3 异常合同不一致**（继承 C2A-1 P3）：`GraphRevisionError` 之外的 AttributeError/文件 I/O 异常在物化/激活入口部分路径以原始异常传播而非结构化拒绝；行为仍是拒绝且无部分提交，仅上层错误处理不一致。
- 门禁时长余量观察：196s/300s（本轮），映射继续增长时建议监控（流程项，非缺陷）。

## 11. 跨库一致性与默认生产装配限制

Registry（内存）、Identity（独立 SQLite）、实现代码文件与 Workflow SQLite 之间没有联合 CAS，本轮不宣称跨库原子性。受同一 Workflow 写事务保护的只有 Record/Head/Journal/Run；外部来源在物化事务与激活事务内各做一次完整重读比较，发现漂移即拒绝，剩余窗口见 P2-1。默认应用装配（含 agent HTTP API）未接入 Initial 物化；测试夹具中的装配是宿主显式调用，不代表生产链路。

## 12. 最终判定

**ACCEPT**。最终验收标准逐项成立：同一已接受 Initial Commit 生成唯一、可恢复的 GraphVersion 1（数据库唯一索引 + 幂等 Key + 进程实验），经同一 Workflow SQLite 事务的 Head/Run CAS 进入 `ACTIVATED_PAUSED`；失败、漂移与未知提交结果均收敛为拒绝或幂等恢复，无冲突版本、无错误激活、无 Permit 执行。本轮验收报告与实验产物未暂存、未提交。
