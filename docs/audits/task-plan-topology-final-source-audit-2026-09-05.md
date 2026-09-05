# TaskPlan Topology Final Source Audit

## 1. Executive Conclusion

结论评级：**B**。

当前仓库已经有一条主要的生产规划链，也已经具备 TaskPlan 的 DAG 校验、能力目录依赖补全、终点连接和 bounded `relations.repair`。但拓扑事实源的职责仍然分散：模型关系在 `TaskDecomposer._decompose_staged()` 中局部修复，能力依赖和 terminal 边在 `_to_plan()` 中继续修改，`TaskPlan` 只做最终结构校验，`ACGBuilder` 又把能力级依赖重新投影为执行图边。真实失败证明：局部关系图通过校验后，后续能力依赖补全仍可能制造间接环。

因此当前不能宣称 `TaskPlan` 是“单一最终拓扑事实源”。最小安全迁移边界应是抽取一个 Planner 内部的 topology compilation boundary，先统一构造最终候选关系和控制策略，再一次性校验；不应新建第二套 Planner、Runtime 或 Scheduler。

## 2. Repository Baseline

审计时工作树已有用户此前的性能/环修复改动，未回滚：

```text
branch: master
HEAD: 740f7cf
working tree: modified (.env.example, compose.yaml, runtime, planner and tests)
```

本审计没有修改既有文件；仅新增本报告。

已运行：

```text
pytest apps/agentOS/tests/components/planner -q
47 passed
```

此前同一工作树中 Runtime 相关回归为 `142 passed`，本报告不把它们重新归因于拓扑审计。

## 3. Production Planning Call Chain

正式入口是 `POST /missions/{mission_id}/runs`，见 [agentos_v2.py](../../apps/agent/app/api/agentos_v2.py:1466)。它调用 `runtime.prepare_run(..., defer_acg_planning=True)`，随后由后台 coordinator 执行 prepared Run。

Deferred Run 在 [workflow_runtime.py](../../apps/agentOS/src/runtime/workflow_runtime.py:587) 的 `_materialize_acg_run()` 中构造 Blueprint；内部 `_build_acg_blueprint()`（同文件约 2396 行）创建 `PlanningEngine` 并调用 `PlanningEngine.plan()`。

主动态链为：

```text
create_mission_run
  -> ExecutionRuntime.prepare_run
  -> coordinator.submit
  -> execute_prepared_run
  -> _materialize_acg_run
  -> _build_acg_blueprint
  -> PlanningEngine.plan
  -> IntentParser.parse
  -> SemanticPlanner.plan_profile
  -> TaskDecomposer.decompose
  -> _decompose_staged (outline/detail/relations)
  -> _to_plan
  -> ACGBuilder.build
  -> ACGBuilder.finalize
  -> ACG Runtime
```

静态模板是另一条正式分支：`PlanningEngine.plan()` 先通过 `TemplateMatcher` 命中 Workflow，再调用 `SemanticPlanner.plan_template()` 和 `ACGBuilder.build_template()`。它绕过动态 LLM relations，但仍由 `TaskPlan` 和 Builder 形成执行 Blueprint。

测试辅助入口包括直接实例化 `ExecutionRuntime`、显式 Blueprint 输入和 Planner 单元测试；这些不是生产 HTTP 入口。legacy workflow/template compatibility 入口仍存在，因此不能把动态 Planner 视为仓库唯一可能的 TaskPlan 来源。

## 4. TaskPlan Producers

真实构造点搜索结果：

- `TaskDecomposer._to_plan()` 在 [task_decomposer.py](../../apps/agentOS/src/components/planner/task_decomposer.py:893) 创建动态 `TaskPlan`。
- `SemanticPlanner` 有 compatibility/fallback 计划构造（同文件 `semantic_planner.py` 约 97、124 行），但其结果仍经过 `TaskPlan` 合约。
- `PlanningEngine` 的模板路径消费 `plan_template()` 返回的 TaskPlan，随后由 Builder 投影。
- `apply_task_plan_patch()` 在 [service.py](../../apps/agentOS/src/components/planner/service.py:524) 可基于已有 TaskPlan 产生新版本；这是运行期语义变更路径，不是首次规划路径。
- `WorkflowRuntime` 可读取持久化 `taskPlan`/Blueprint 快照（约 2425 行起），并在 identity lifecycle 下 resolve snapshot；它不应被视为新的 Planner。

生产动态路径中，**TaskDecomposer 是 LLM 计划的主要生产者，但不是全仓库唯一构造点**。模板、fallback 和 patch 都是旁路/兼容生产者。当前没有发现一个独立的 `build_task_plan()` 统一事实源。

## 5. Relation Mutation Lifecycle

动态 staged 路径的真实顺序是：

```text
LLM outline
  -> frozen semantic task identities
LLM detail batches
  -> frozen keys/capabilities restored by _validated_detail_tasks
LLM relations + controlPolicies
  -> _normalize_direct_reversed_required_dependencies
  -> _complete_missing_capability_tasks
  -> _complete_capability_dependencies
  -> _connect_terminal_results
  -> parse VerificationLoopPolicy
  -> TaskPlan construction/validation
  -> ACGBuilder projection
```

具体变化：

- outline/detail 阶段生成或规范化 Task 节点，不处理关系。
- relation 阶段生成 `relations` 和 `controlPolicies`。
- `_to_plan()` 先把原始关系转换为 `TaskPlanRelation`，并按 capability 识别直接反向硬依赖。
- `_complete_capability_dependencies()` 追加 capability catalog 要求的具体 task-instance 边，并在追加前调用 `_find_dependency_path()` 检查是否会形成回路。
- `_connect_terminal_results()` 还会追加 leaf 到 verification/artifact sink 的边。
- `TaskPlan.validate_graph()` 再做节点、父关系、静态 dependency DAG 和 policy 引用校验。
- ACGBuilder 不读取原始模型关系，而消费 `task_plan.relations`，按能力依赖重新构造执行边、parallel/join 控件和 loop 控件。

当前确实存在“修改、添加、删除/过滤、方向变化”的多个阶段，但没有统一的边 provenance 或 mutation log。

## 6. `_to_plan()` Responsibility Audit

`_to_plan()` 不是纯 schema conversion。它同时承担：

1. raw task key/capability/role 规范化；
2. source refs、workset、constraints、acceptance criteria 规范化；
3. 缺失 capability task materialization；
4. 直接反向 required dependency 过滤；
5. capability requirement 到具体 task 的绑定；
6. terminal sink 连接；
7. control policy 解析为 `VerificationLoopPolicy`；
8. 创建 `TaskPlan`，触发最终合约校验。

因此 `_to_plan()` 实际上已经是一个隐式 topology compiler 的一部分。它的边界问题不是“要不要继续负责 topology”，而是当前职责分散在 `_decompose_staged()` 和 `_to_plan()`，且 repair 发生在完整约束编译之前。

## 7. Capability Requirement Resolution

Capability Catalog 的依赖由 catalog descriptor 的 `depends_on` 提供，`_complete_missing_capability_tasks()` 先通过 `expand_dependencies()` 物化缺失 capability task；随后 `_complete_capability_dependencies()` 读取每个节点 capability 的 `depends_on` 并补边。

这表示：

```text
Capability requirement: capability X depends_on capability Y
Concrete binding: selected task instance of Y -> selected task instance of X
```

二者在概念上存在区分，但当前没有独立的 requirement/binding contract 或边对象；补全函数直接把 requirement 变成 `TaskPlanRelation`，来源信息丢失。

## 8. Multi-instance Capability Binding Algorithm

当前算法在 `_complete_capability_dependencies()`（约 1196 行）中：

1. `by_capability[capability]` 按 `nodes` 列表顺序收集候选。
2. 对目标节点，优先选择 `node_positions[candidate] < node_positions[target]` 的 preceding 候选。
3. preceding 候选按 `reversed(preceding)` 排序，即偏好列表中目标之前、位置最靠后的候选。
4. 其余候选随后加入。
5. 已存在边直接接受；否则调用 `_find_dependency_path(relations, start=target, target=candidate)`，若目标到候选已有路径则跳过该候选以避免环。
6. 第一个不形成回路的候选被选中；全部阻断则抛错。

这是确定性的（依赖输入 list 顺序，非 dict 随机顺序），但属于 greedy local selection：没有全局搜索、代价函数、语义匹配或回溯。改变 Task 节点顺序可能改变绑定；多个实例时没有 provenance 记录“为何选该 producer”。

## 9. Dependency Edge Provenance

当前 `TaskPlanRelation` 只有：

```text
sourceKey, targetKey, relationType
```

没有 `origin`、`reason`、`confidence`、`requirement_id`、mutable 标志或 repair history。`_normalize_direct_reversed_required_dependencies()` 会静默过滤一部分被 catalog 证明为反向的模型边；terminal connector 和 capability completion 直接追加普通 `TaskPlanRelation`。

因此 `_find_dependency_cycle()` 只能返回节点路径，不能回答：

- 哪条边来自模型；
- 哪条边来自 capability catalog；
- 哪条边来自用户/安全策略；
- 哪条边是否可删除；
- 为什么存在这条边。

审计上下文目前最多保留 staged stage、prompt audit 和异常字符串，不足以支持安全的自动解环。

## 10. Terminal Connection Audit

`_connect_terminal_results()` 在 `_to_plan()` 内、TaskPlan 构造前运行。它识别 capability 为 `verification` 或 `artifact_generation` 的 sink，对无 outgoing dependency 的 leaf 按位置和 sink 类型排序，尝试追加 `leaf -> sink`；若 sink 已经能到达 leaf，则跳过以避免 cycle，全部候选失败则抛错。

terminal node 是普通 semantic Task，不是这里新建的 synthetic node；ACG Builder 另行创建 `ctrl_start`/`ctrl_end` 等执行控制节点。terminal edges 在 DAG 校验前加入，随后由 `TaskPlan.validate_graph()` 校验。

ACGBuilder 不会再次读取 TaskPlan terminal edges 来决定 semantic dependency；但它会根据 `task_plan.relations` 派生 capability-level `data_dependencies`，再生成执行边、parallel/join 和 end 边。因此“TaskPlan 后没有任何拓扑变化”这一强断言不成立：Builder 不修改 TaskPlan 对象，但会进行一次执行图级拓扑投影。

## 11. Control Policy / Static Dependency Separation

`VerificationLoopPolicy` 在 [planning.py](../../apps/agentOS/src/contracts/planning.py:74) 中是独立 semantic contract，包含 entry、exit、condition source、repeat values、max revisions 和 exhausted behavior。`TaskPlan.validate_graph()` 只验证 policy 引用存在，不把 policy back edge 加入静态 dependency DAG。

ACGBuilder._wire_control_policies()（约 356 行）把 policy 转成 `ControlNode(controlType=LOOP)` 和 `CONTROL_FLOW` edge；Runtime 运行 loop control。当前代码没有发现把 `bodyExit -> bodyEntry` 直接转换为 `DEPENDS_ON` 的逻辑。

因此 separation 在 schema 和 Builder projection 层面基本成立（**CONFIRMED**）。但 planner 只在 prompt 中要求“feedback 用 verification_loop”，没有对“反向关系必须自动转换/禁止”提供结构化 normalization，仍可能由 LLM 返回非法静态边。

## 12. Relations Repair Audit

当前 staged repair 触发点位于 `_decompose_staged()`（约 530 行）：

- relation LLM 调用失败且不是 transport error 时，先做一次 `relations.repair`。
- relation 结果进入 `_to_plan()`。
- 若第一次 `_to_plan()` 因 coverage gap 失败，会做 source-ref repair。
- 若错误字符串被 `_is_dependency_cycle_error()` 识别，则做一次 `relations.cycle-repair`，冻结 detailed tasks，只重生成 relations/controlPolicies。
- repair 后再次 `_to_plan()`；仍失败则整个 staged planning 失败。

当前 repair prompt 能看到：冻结任务 compact 信息、原始 relation prompt、直接 cycle 异常文本，并明确要求避免 dependency cycle、使用 verification_loop。它**看不到完整的 capability completion 候选边及其来源**，因为这些边是在 `_to_plan()` 内逐节点生成的；第二次 capability binding 冲突也不会再次进入 repair 分支。

因此真实 Case B 的路径是：

```text
model relations cycle
 -> _to_plan/_complete_capability_dependencies detects cycle
 -> relations.cycle-repair
 -> repaired model relations pass initial direct-cycle check
 -> capability completion selects candidates
 -> _find_dependency_path detects reverse path
 -> TaskDecompositionError
 -> no second repair
```

## 13. Error Model

拓扑相关真实异常包括：

- `TaskDecompositionError`：staged planning、missing predecessor、cycle、terminal sink 等。
- `ValueError`：`TaskPlan` contract validator 的 duplicate key、unknown relation、parent/dependency cycle 等。
- `ACGPlanningError`：PlanningEngine 层 unresolved capability、entropy budget 或候选方案失败。
- `KeyError`：Builder 找不到 capability/task binding。

当前 cycle repair 通过字符串 `"dependency cycle" in str(error).lower()`（TaskDecomposer 约 650 行附近的 helper）驱动，属于架构风险：异常类型没有结构化 cycle、edge origin、candidate producer 或 attempt 字段。最终 Run 保留包装后的错误文本和 planner audit，但不能可靠地重建完整冲突边集合。

## 14. TaskPlan → Blueprint → ACG Topology Mutation Audit

`ACGBuilder.build()`（约 49 行）要求每个 TaskPlan node 有一个 capability，并把 TaskPlan relation 转成 capability-level `data_dependencies`。随后：

- `_build_steps()` 为每个 TaskPlan node 建立一个 StepNode，并在 metadata 中保存 taskPlanKey。
- `_wire_execution_graph()` 添加 `ctrl_start`/`ctrl_end`、dependency edges、parallel controls、join controls 和 end edges。
- `_wire_data_contracts()` 根据 capability dependencies 添加 communication/support/read edges。
- `_wire_control_policies()` 添加 loop ControlNode 和 control-flow edge。
- `finalize()` 仅做 step 与 TaskPlan 的数量/顺序绑定校验，不重新修改 TaskPlan。

结论：Builder 不产生第二个 semantic TaskPlan，但它确实重新推导执行拓扑。`Validated TaskPlan = 最终静态 semantic graph` 只在 semantic 层成立；`ACG Blueprint = TaskPlan 的一对一节点映射` 不成立，因为 Blueprint 还包含控制节点、communication edges、parallel/join 和 terminal execution edges。

## 15. Existing Parallel / Legacy Planning Paths

没有发现第二套完整 Planner/Runtime。主要并行/旁路路径是：

- `PlanningEngine` 的 static template 与 dynamic generation 两分支。
- `SemanticPlanner` 的 LLM、fallback/compatibility plan。
- `ACGBuilder.build()` 和 `build_template()` 两种 Blueprint 投影。
- `apply_task_plan_patch()` 的运行期 TaskPlan 语义变更。
- legacy execution draft 目录中的旧 executor，不是当前正式 Runtime，测试架构门禁也禁止 scheduler 依赖 DAG。

因此未来引入 `TaskPlanTopologyCompiler` 应挂在 `PlanningEngine -> TaskDecomposer` 内部，服务 dynamic/template/patch 共用的 TaskPlan topology contract；不能再创建 `PlanningEngine2` 或独立 Runtime。

## 16. Test Coverage and Test Results

现有 planner tests 覆盖：

- 直接 TaskPlan dependency cycle 被 `TaskPlan` 拒绝；
- staged outline/detail repair；
- frozen task identity；
- capability dependency completion 的正常路径；
- 多实例 capability 的部分场景；
- source ref coverage；
- prompt 中 verification_loop 约束；
- planning timeout/retry。

本次运行：`47 passed`。

缺口：

- 模型关系无环、加入 catalog 强制边后成环；
- 多 candidate producer 的全局最优/稳定选择；
- edge provenance/mutability；
- terminal edge 与 capability completion 合并后再次成环；
- invalid control policy 到 Builder/Runtime 的端到端投影；
- Builder 是否改变 semantic dependency 的属性测试；
- 真实 Case A/Case B 的持久化 Run 重现测试；
- `StructuredTopologyConflict` 结构化错误契约。

## 17. Failure Case A Reconstruction

输入关系：

```text
recommended-scheme-synthesis
 -> constraint-compliance-recheck
 -> recommended-scheme-synthesis
```

执行路径：

```text
_decompose_staged relation call
 -> _to_plan
 -> _normalize_direct_reversed_required_dependencies
 -> _complete_capability_dependencies/_find_dependency_cycle
 -> TaskDecompositionError("TaskPlan dependency cycle: ...")
 -> relations.cycle-repair
 -> second _to_plan
```

当前 repair 冻结 outline/detail，只重做 relation/controlPolicies。若 repaired payload 在最终 `_to_plan()` 中通过，才进入 `PlanningEngine.plan()` 的 `plan_parsed`，再进入 variant generation 和 `ACGBuilder.build()`。Case A 的根因是把 refinement feedback 当静态 dependency；控制策略 schema 已存在，但 normalization 不是强制的。

## 18. Failure Case B Reconstruction

目标 capability requirement：

```text
process_decomposition -> cost_analysis
```

具体 candidate binding 中系统尝试：

```text
implementation-schedule-30weeks -> storage-sizing-calculation
```

模型关系已有路径：

```text
storage-sizing-calculation
 -> alternative-distributed-storage-design
 -> candidate-economic-comparison
 -> recommended-scheme-synthesis
 -> implementation-schedule-30weeks
```

因此 `_complete_capability_dependencies()` 对 target `storage-sizing-calculation` 检查 `target -> candidate` 反向可达路径，发现添加 required edge 会闭环；候选选择是 greedy，若没有其它不成环 candidate，就抛出：

```text
required capability dependency process_decomposition -> cost_analysis cannot be bound ...
```

该异常虽然包含 capability 和一条 path，但没有标注 path 中每条 edge 的来源；它发生在第一次 cycle repair 之后，当前不会重新调用 relations repair。这正是“局部模型关系校验”和“最终可执行关系校验”不是同一阶段的证据。

## 19. Target Architecture Gap Analysis

目标结构中以下判断得到代码支持：

- `TaskDecomposer` 生成 frozen tasks 和 relation proposal：**CONFIRMED**。
- `TaskPlan` 是 semantic-only contract，禁止 execution identity：**CONFIRMED**。
- `VerificationLoopPolicy` 独立于 static dependency，并由 Builder 转换为 LOOP control：**CONFIRMED**。
- Capability requirement 在 catalog 中定义：**CONFIRMED**。
- 最终拓扑只在一个统一 compiler 中决定：**NOT SUPPORTED BY CURRENT CODE**。
- Concrete binding 与 immutable requirement 分成两层 contract：**PARTIALLY CONFIRMED**，概念存在但数据结构和 provenance 未分离。
- Edge origin/mutability/repair history：**NOT SUPPORTED BY CURRENT CODE**。
- Builder 完全不再推导拓扑：**NOT SUPPORTED BY CURRENT CODE**；它不改 TaskPlan，但会重建执行图拓扑。

## 20. Recommended Minimal Migration Boundary

不建议本阶段重写 Planner。最小边界：

1. 在 `TaskDecomposer` 内先引入内部 proposed-edge 结构（不立即改变公开 TaskPlan schema），记录 `origin`, `mutable`, `reason`, `requirement_id`。
2. 将 `_normalize_direct_reversed_required_dependencies()`、`_complete_capability_dependencies()`、`_connect_terminal_results()` 的结果先放入同一 candidate topology。
3. 在 capability completion 完成后执行一次全局 cycle/coverage/control policy validation。
4. 只有最终 candidate topology 失败时才触发 bounded relation repair；repair prompt 必须包含 immutable/mutable edges 和完整 cycle。
5. repair 后重新从 frozen tasks 构造完整 candidate topology，不能只检查模型 relations。
6. 保留 `TaskPlan` 作为对外 semantic contract；下一阶段再考虑 `TopologyCompiler.compile() -> ValidatedTaskPlan | StructuredTopologyConflict`。
7. ACGBuilder 暂时保持执行图投影职责，但增加不改变 semantic dependency 的断言和 provenance 转移。

## 21. Risks

- 直接把所有 `TaskPlanRelation` 改成带 provenance 的公开 schema 会影响持久化、identity projection 和前端契约，风险较高。
- 自动删除环内模型边可能静默丢失业务语义；当前没有足够 provenance 支持安全删边。
- 依赖补全是按节点顺序的 greedy 选择，修复顺序可能改变具体 producer。
- Builder 按 capability 而非 task instance 聚合 parallel groups，多个同 capability task 的执行拓扑仍需单独审计。
- template/fallback/patch 路径如果不复用统一 topology validation，未来仍可能产生多个事实源。
- 生产错误目前是普通异常字符串，前端无法稳定展示 cycle edge origin 和可修复动作。

## 22. Final Verdict

评级：**B**。

当前基础能力已经存在：Planner、TaskPlan DAG validator、Capability Catalog completion、terminal connection、verification loop schema 和 ACG Builder projection 都是真实代码，而不是设计文档中的假设。问题在于它们被分散在多个阶段，导致“模型关系局部无环”不等于“最终 TaskPlan/ACG 候选图无环”。

对未来 `TaskPlanTopologyCompiler` 的核心审计结论是：它应当是现有 `PlanningEngine -> TaskDecomposer` 内部的单一最终拓扑编译边界，而不是第二套 Planner。原则应保持：

```text
LLM proposes.
Compiler decides.
ACG executes.
```

当前距离这一目标是“职责已部分存在，但最终事实源尚未统一”。
