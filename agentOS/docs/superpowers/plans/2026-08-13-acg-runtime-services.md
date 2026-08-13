# ACG 运行时自研服务实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以 AgentOS 自研的通信、记忆、审计和外部能力适配服务补齐融合执行底座，使 ACG 能在不泄漏完整数据到执行 State 的前提下安全执行、审核、暂停和续跑。

**Architecture:** `ACGExecutionGraph` 只调度引用型状态；`ExecutionValueStore` 作为 run 内输出和 ContextPack 的唯一引用解析点。通信服务负责 slot 白名单与熵预算，记忆服务负责权限范围内的读写，审计服务负责 Trace、证据和审核决策，适配层负责把受控上下文交给 Agent/Model/Tool。`WorkflowRuntime` 仅装配这些服务和投影生命周期。

**Tech Stack:** Python 3.10、Pydantic 2、SQLite、AgentOS ACG、融合 LangGraph 1.2.10 执行语义、`langchain-core==1.4.7`（仅 Runnable/config/callback 基础依赖）。

---

## 一、固定边界与交付顺序

| 顺序 | 自研服务 | 解决的问题 | 不允许承担的职责 | 前置条件 |
| --- | --- | --- | --- | --- |
| 1 | 执行值存储 | 以引用保存/读取受控输出、ContextPack 和节点结果 | 图调度、记忆召回、审计决策 | 已有 `ACGExecutionState` |
| 2 | 通信服务 | slot 白名单、输入合同、EVENT 通知、熵预算和血缘 | 全量上游透传、持久化执行状态 | 执行值存储 |
| 3 | 记忆服务 | run/scope 权限过滤、召回、受控写入与记忆引用 | 直接读取 WorkflowRun 全量步骤输出 | 执行值存储、通信 ContextPack |
| 4 | 审计服务 | Trace 投影、证据引用、策略决定、审核请求 | 调 Agent、改图、改写输出正文 | 通信/记忆/节点结果引用 |
| 5 | 适配服务 | Agent/Model/Tool 受控调用、scope、超时与错误归一化 | 规划 ACG、绕过合同写入输出 | 通信/记忆/审计上下文 |
| 6 | Runtime 接线 | 组装并执行图、持久化 checkpoint、生命周期投影 | 实现上述任一领域算法 | 前 1–5 项 |

所有阶段遵守以下不可变规则：

- `ACGExecutionState` 和 SQLite checkpoint 只能保存摘要、ID、URI、checksum、版本和引用；不得保存完整 slot 输入、完整 Agent 输出、记忆正文、模型 prompt/response 或 LangGraph callback/chunk。
- 所有跨部件输入输出使用 `contracts/` 中的 JSON 兼容模型或明确的内部引用对象；不得把 SDK 对象传入 contracts。
- `STRICT_CONTRACT` 和 `EVENT` 是首期唯一可运行模式；`BLACKBOARD`、`DEBATE` 必须在编译期报错。
- `runId` 是执行值、记忆 scope、Trace、checkpoint thread ID 的第一隔离键；任何跨 run 读取必须失败而不是回退查询。
- 每个任务必须先写失败测试，再执行最小实现并运行对应测试；完成一个任务后单独提交。

## 二、通信服务计划

### Task 1：建立执行值引用仓库

**Files:**

- Create: `src/components/executor/value_store.py`
- Modify: `src/components/executor/node_runner.py`
- Test: `tests/components/executor/test_value_store.py`

- [ ] **Step 1: 写入跨 run 隔离的失败测试。**

```python
def test_value_store_rejects_cross_run_reference() -> None:
    store = InMemoryExecutionValueStore()
    ref = store.put_output(run_id="run-a", step_id="extract", payload={"text": "safe"})

    with pytest.raises(ExecutionValueAccessError, match="run-a"):
        store.get_output(run_id="run-b", output_ref=ref)
```

- [ ] **Step 2: 运行失败测试。**

Run: `pytest tests/components/executor/test_value_store.py::test_value_store_rejects_cross_run_reference -q`

Expected: FAIL，因为 `InMemoryExecutionValueStore` 和 `ExecutionValueAccessError` 尚不存在。

- [ ] **Step 3: 实现最小引用接口和内存实现。**

```python
class ExecutionValueStore(Protocol):
    def put_output(self, *, run_id: str, step_id: str, payload: dict[str, Any]) -> str: ...
    def get_output(self, *, run_id: str, output_ref: str) -> dict[str, Any]: ...
    def put_context_pack(self, *, run_id: str, step_id: str, payload: dict[str, Any]) -> str: ...
    def get_context_pack(self, *, run_id: str, context_ref: str) -> dict[str, Any]: ...

class InMemoryExecutionValueStore:
    def put_output(self, *, run_id: str, step_id: str, payload: dict[str, Any]) -> str:
        ref = f"output:{run_id}:{step_id}:{uuid4().hex}"
        self._outputs[ref] = (run_id, deepcopy(payload))
        return ref

    def get_output(self, *, run_id: str, output_ref: str) -> dict[str, Any]:
        owner_run_id, payload = self._outputs[output_ref]
        if owner_run_id != run_id:
            raise ExecutionValueAccessError(output_ref, owner_run_id, run_id)
        return deepcopy(payload)
```

- [ ] **Step 4: 增加不可变副本、缺失引用和 ContextPack 隔离测试并运行。**

Run: `pytest tests/components/executor/test_value_store.py -q`

Expected: PASS；修改读取结果不会篡改仓库，未知引用抛出明确错误，ContextPack 不能跨 run 读取。

- [ ] **Step 5: 将 `ACGNodeRunner` 的 `output_ref_factory` 改为依赖注入的 `ExecutionValueStore`。**

```python
controlled = {key: value for key, value in payload.items() if key in allowed}
output_ref = self.value_store.put_output(
    run_id=state.run_id,
    step_id=step_id,
    payload=controlled,
)
```

- [ ] **Step 6: 提交本任务。**

```bash
git add src/components/executor/value_store.py src/components/executor/node_runner.py tests/components/executor/test_value_store.py
git commit -m "feat: add run-isolated execution value store"
```

### Task 2：让 STRICT_CONTRACT 按引用装配上游 slots

**Files:**

- Modify: `src/components/executor/node_runner.py`
- Modify: `src/components/communicator/service.py`
- Test: `tests/components/communicator/test_execution_context.py`

- [ ] **Step 1: 写入输入字段白名单的失败测试。**

```python
def test_strict_contract_reads_only_declared_upstream_fields() -> None:
    store = InMemoryExecutionValueStore()
    source_ref = store.put_output(
        run_id="run-1", step_id="extract",
        payload={"title": "A", "secret": "must-not-pass"},
    )

    pack = assemble_execution_context(
        run_id="run-1",
        step_id="summarize",
        input_spec={"from": {"extract": ["title"]}},
        upstream_refs={"extract": source_ref},
        value_store=store,
    )

    assert pack.data == {"title": "A"}
```

- [ ] **Step 2: 运行失败测试。**

Run: `pytest tests/components/communicator/test_execution_context.py::test_strict_contract_reads_only_declared_upstream_fields -q`

Expected: FAIL，因为 `assemble_execution_context` 尚不存在。

- [ ] **Step 3: 在 `CommunicatorService` 添加受控装配入口。**

```python
def assemble_execution_context(
    self,
    *,
    run_id: str,
    step_id: str,
    input_spec: Mapping[str, Any],
    upstream_refs: Mapping[str, str],
    value_store: ExecutionValueStore,
    token_budget: int | None,
) -> ContextPack:
    upstream_outputs = {
        source_step_id: value_store.get_output(run_id=run_id, output_ref=output_ref)
        for source_step_id, output_ref in upstream_refs.items()
    }
    return self.assemble_context(
        run_id=run_id,
        step_id=step_id,
        input_spec=input_spec,
        upstream_outputs=upstream_outputs,
        token_budget=token_budget,
    )
```

- [ ] **Step 4: 在节点运行器中从 State 的 `output_refs` 映射读取上游引用，而不是读取摘要。**

需要先在 `ACGExecutionState` 增加 `output_refs: dict[str, str]`；该字段只保存 `outputRef`，不保存内容。

- [ ] **Step 5: 增加缺字段、schema 违例和熵超限测试并运行。**

Run: `pytest tests/components/communicator/test_execution_context.py tests/test_acg_execution_graph.py -q`

Expected: PASS；缺少必填字段在 Adapter 调用前失败，超限不读取无关字段，违例产生 `ContextContractError`。

- [ ] **Step 6: 提交本任务。**

```bash
git add src/components/executor/node_runner.py src/components/executor/graph.py src/components/communicator/service.py tests/components/communicator/test_execution_context.py tests/test_acg_execution_graph.py
git commit -m "feat: assemble strict-contract inputs from output references"
```

### Task 3：实现 EVENT 的通知引用语义

**Files:**

- Modify: `src/components/executor/compiler.py`
- Modify: `src/components/executor/node_runner.py`
- Test: `tests/components/executor/test_event_mode.py`

- [ ] **Step 1: 写入 EVENT 不读取上游正文的失败测试。**

```python
def test_event_step_receives_event_reference_without_upstream_payload() -> None:
    result = run_event_node(upstream_ref="output:run-1:source:1")

    assert result.context_pack.data == {}
    assert result.context_pack.source_step_ids == ["source"]
    assert result.context_pack.evidence_refs == ["event:output:run-1:source:1"]
```

- [ ] **Step 2: 运行失败测试。**

Run: `pytest tests/components/executor/test_event_mode.py::test_event_step_receives_event_reference_without_upstream_payload -q`

Expected: FAIL，因为节点运行器尚未按 `communication_mode` 分支。

- [ ] **Step 3: 在 `ACGNodeRunner` 添加 EVENT 分支。**

```python
if node_spec.communication_mode == "EVENT":
    pack = ContextPack(
        runId=state.run_id,
        stepId=step_id,
        sourceStepIds=list(upstream_refs),
        evidenceRefs=[f"event:{ref}" for ref in upstream_refs.values()],
    )
else:
    pack = self.communicator.assemble_execution_context(...)
```

- [ ] **Step 4: 增加“EVENT 不允许声明 inputSpec.from 字段”的编译失败测试并实现校验。**

Run: `pytest tests/components/executor/test_event_mode.py -q`

Expected: PASS；EVENT 只能声明通知依赖，不能用作数据传输通道。

- [ ] **Step 5: 提交本任务。**

```bash
git add src/components/executor/compiler.py src/components/executor/node_runner.py tests/components/executor/test_event_mode.py
git commit -m "feat: enforce event-only communication mode"
```

## 三、记忆服务计划

### Task 4：定义 run-scoped 记忆策略和节点召回入口

**Files:**

- Modify: `src/contracts/memory.py`
- Modify: `src/components/memory/service.py`
- Modify: `src/components/executor/node_runner.py`
- Test: `tests/components/memory/test_execution_memory.py`

- [ ] **Step 1: 写入跨 run 记忆不可见的失败测试。**

```python
def test_recall_for_step_never_returns_memory_from_another_run() -> None:
    memory = MemoryService()
    memory.remember(record(run_id="run-a", memory_id="m-a"))
    memory.remember(record(run_id="run-b", memory_id="m-b"))

    records = memory.recall_for_step(run_id="run-a", step_id="analysis", query="contract")

    assert [item.memory_id for item in records] == ["m-a"]
```

- [ ] **Step 2: 运行失败测试。**

Run: `pytest tests/components/memory/test_execution_memory.py::test_recall_for_step_never_returns_memory_from_another_run -q`

Expected: FAIL，因为 `recall_for_step` 尚不存在。

- [ ] **Step 3: 扩展 `MemoryPolicy` 的 scope 约束并实现召回入口。**

```python
def recall_for_step(
    self,
    *,
    run_id: str,
    step_id: str,
    query: str,
    memory_types: list[MemoryType] | None = None,
    limit: int = 10,
) -> list[MemoryRecord]:
    return self.search(MemoryQuery(
        query=query,
        scope=run_id,
        memoryTypes=memory_types or [],
        limit=limit,
    ))
```

- [ ] **Step 4: 在节点运行器中用 `recall_for_step` 替代直接 `search`，并生成仅含 ID 的 `memoryRef`。**

```python
memories = self.memory.recall_for_step(
    run_id=state.run_id,
    step_id=step_id,
    query=step.goal or step.name,
)
memory_ref = self.value_store.put_memory_refs(
    run_id=state.run_id,
    step_id=step_id,
    memory_ids=[record.memory_id for record in memories],
)
```

- [ ] **Step 5: 增加 MemoryPolicy 拒绝写入、过期过滤和 Adapter 只收到受限记录的测试。**

Run: `pytest tests/components/memory/test_execution_memory.py tests/test_acg_execution_graph.py -q`

Expected: PASS；拒绝项不写入、过期项不召回、Agent 不可获得其它 run 的记忆。

- [ ] **Step 6: 提交本任务。**

```bash
git add src/contracts/memory.py src/components/memory/service.py src/components/executor/node_runner.py tests/components/memory/test_execution_memory.py tests/test_acg_execution_graph.py
git commit -m "feat: add run-scoped execution memory recall"
```

### Task 5：将受控节点产物写入情节记忆

**Files:**

- Modify: `src/components/memory/service.py`
- Modify: `src/components/executor/node_runner.py`
- Test: `tests/components/memory/test_execution_memory.py`

- [ ] **Step 1: 写入只有白名单输出会进入情节记忆的失败测试。**

```python
def test_node_memory_write_uses_controlled_output_only() -> None:
    result = run_node_with_output({"answer": "safe", "internal": "secret"})

    record = result.memory_record
    assert record.content == {"answer": "safe"}
    assert "internal" not in record.content
```

- [ ] **Step 2: 运行失败测试。**

Run: `pytest tests/components/memory/test_execution_memory.py::test_node_memory_write_uses_controlled_output_only -q`

Expected: FAIL，因为节点完成后尚未写入情节记忆。

- [ ] **Step 3: 实现 `remember_step_output`。**

```python
def remember_step_output(
    self,
    *,
    run_id: str,
    step_id: str,
    output: dict[str, Any],
    policy: MemoryPolicy,
) -> MemoryRecord | None:
    record = MemoryRecord(
        memoryId=f"memory:{run_id}:{step_id}",
        memoryType=MemoryType.EPISODIC,
        content=dict(output),
        scope=run_id,
        tags=["execution", step_id],
    )
    return record if self.remember(record, policy) else None
```

- [ ] **Step 4: 在输出合同通过和审计 Trace 生成后调用该入口。**

- [ ] **Step 5: 运行完整记忆测试。**

Run: `pytest tests/components/memory/test_execution_memory.py -q`

Expected: PASS；仅受控输出写入，策略拒绝不会产生记忆引用。

- [ ] **Step 6: 提交本任务。**

```bash
git add src/components/memory/service.py src/components/executor/node_runner.py tests/components/memory/test_execution_memory.py
git commit -m "feat: persist controlled node output as episodic memory"
```

## 四、审计服务计划

### Task 6：建立节点审计请求、发现和策略决定

**Files:**

- Create: `src/components/auditor/execution_audit.py`
- Modify: `src/components/auditor/service.py`
- Modify: `src/components/executor/node_runner.py`
- Test: `tests/components/auditor/test_execution_audit.py`

- [ ] **Step 1: 写入高风险输出要求审核的失败测试。**

```python
def test_high_risk_node_output_returns_review_decision() -> None:
    decision = ExecutionAuditService().assess_node(
        request=AuditRequest(
            requestId="audit-1",
            subjectRef="output:run-1:legal",
            auditType="node_output",
            evidenceRefs=["trace:legal"],
        ),
        severity_counts={"high": 1},
    )

    assert decision.outcome == "review"
```

- [ ] **Step 2: 运行失败测试。**

Run: `pytest tests/components/auditor/test_execution_audit.py::test_high_risk_node_output_returns_review_decision -q`

Expected: FAIL，因为 `ExecutionAuditService` 尚不存在。

- [ ] **Step 3: 实现纯规则的节点审计服务。**

```python
class ExecutionAuditService:
    def assess_node(self, *, request: AuditRequest, severity_counts: dict[str, int]) -> PolicyDecision:
        score = audit_score(severity_counts)
        outcome = "review" if severity_counts.get("high", 0) or severity_counts.get("critical", 0) else "allow"
        return PolicyDecision(
            decisionId=f"decision:{request.request_id}",
            subjectRef=request.subject_ref,
            outcome=outcome,
            policyRefs=["execution-risk.v1"],
            rationale=f"audit score={score}",
        )
```

- [ ] **Step 4: 在节点执行器中把输出合同、证据引用和风险发现投影为 `AuditRequest`。**

节点运行器只接收 `PolicyDecision` 的引用和是否需要审核，不能直接修改 Workflow 状态。

- [ ] **Step 5: 增加 allow/deny/review、证据引用透传、未知严重度的测试。**

Run: `pytest tests/components/auditor/test_execution_audit.py -q`

Expected: PASS；决定稳定可重放，所有 finding 都带来源证据引用。

- [ ] **Step 6: 提交本任务。**

```bash
git add src/components/auditor/execution_audit.py src/components/auditor/service.py src/components/executor/node_runner.py tests/components/auditor/test_execution_audit.py
git commit -m "feat: add execution-node audit decisions"
```

### Task 7：将执行事件、审计决定和检查点串成连续 Trace

**Files:**

- Modify: `src/components/auditor/governance/trace.py`
- Modify: `src/components/executor/graph.py`
- Modify: `src/components/recovery/checkpoint.py`
- Test: `tests/components/auditor/test_execution_trace.py`

- [ ] **Step 1: 写入审核暂停前 Trace 顺序的失败测试。**

```python
def test_review_interrupt_trace_is_ordered_before_checkpoint() -> None:
    events = execute_until_review()

    assert [event.event_type.value for event in events[-3:]] == [
        "step_succeeded", "review_required", "checkpoint_created",
    ]
```

- [ ] **Step 2: 运行失败测试。**

Run: `pytest tests/components/auditor/test_execution_trace.py::test_review_interrupt_trace_is_ordered_before_checkpoint -q`

Expected: FAIL，因为 runtime 尚未消费完整图事件并保存检查点。

- [ ] **Step 3: 扩展执行事件投影词表。**

```python
projection = {
    "nodes_scheduled": TraceEventType.STEP_SCHEDULED,
    "node_started": TraceEventType.STEP_STARTED,
    "node_completed": TraceEventType.STEP_SUCCEEDED,
    "interrupted": TraceEventType.REVIEW_REQUIRED,
    "checkpoint_created": TraceEventType.CHECKPOINT_CREATED,
}
```

- [ ] **Step 4: 规定 checkpoint payload 仅含 `checkpointId`、`runId`、`graphId`、`completedStepIds` 和引用哈希。**

- [ ] **Step 5: 增加恢复后 Trace 连续、重复恢复幂等和跨 run Trace 隔离测试。**

Run: `pytest tests/components/auditor/test_execution_trace.py -q`

Expected: PASS；恢复后事件继续追加到同一 run，未写入完整 ContextPack 或输出正文。

- [ ] **Step 6: 提交本任务。**

```bash
git add src/components/auditor/governance/trace.py src/components/executor/graph.py src/components/recovery/checkpoint.py tests/components/auditor/test_execution_trace.py
git commit -m "feat: trace audit and checkpoint execution events"
```

## 五、适配服务计划

### Task 8：实现作用域内的 Agent 调用适配器

**Files:**

- Create: `src/adapters/agent_invocation.py`
- Modify: `src/components/executor/node_runner.py`
- Modify: `src/support/agents/registry.py`
- Test: `tests/adapters/test_agent_invocation.py`

- [ ] **Step 1: 写入 scope 外 Agent 不能被调用的失败测试。**

```python
def test_agent_invoker_rejects_agent_outside_frozen_scope() -> None:
    invoker = AgentInvocationAdapter(registry=registry.scoped(["allowed-agent"]))

    with pytest.raises(AgentInvocationError, match="not available in run scope"):
        asyncio.run(invoker.invoke(step=step_for("blocked-agent"), context=context))
```

- [ ] **Step 2: 运行失败测试。**

Run: `pytest tests/adapters/test_agent_invocation.py::test_agent_invoker_rejects_agent_outside_frozen_scope -q`

Expected: FAIL，因为 `AgentInvocationAdapter` 尚不存在。

- [ ] **Step 3: 实现统一 Agent 调用与错误归一化。**

```python
class AgentInvocationAdapter:
    async def invoke(self, *, step: WorkflowStep, context: AgentRunContext) -> AgentOutput:
        try:
            agent = self.registry.resolve(
                domain=context.workflow.domain,
                agent_name=step.agent_name,
                capability=step.capability,
            )
        except KeyError as exc:
            raise AgentInvocationError("AGENT_NOT_IN_SCOPE", step.step_id) from exc
        return await agent.run(context)
```

- [ ] **Step 4: 修改节点运行器：不再直接从映射调用 `agent.run`，而是调用适配器。**

- [ ] **Step 5: 增加 Agent 不存在、超时异常映射、输出不合同时不写 value store 的测试。**

Run: `pytest tests/adapters/test_agent_invocation.py tests/test_acg_execution_graph.py -q`

Expected: PASS；scope、错误码和输出提交顺序稳定。

- [ ] **Step 6: 提交本任务。**

```bash
git add src/adapters/agent_invocation.py src/components/executor/node_runner.py src/support/agents/registry.py tests/adapters/test_agent_invocation.py tests/test_acg_execution_graph.py
git commit -m "feat: invoke agents through frozen execution scope"
```

### Task 9：实现 Tool 调用审计包装器

**Files:**

- Create: `src/adapters/audited_tool_runtime.py`
- Modify: `src/adapters/tool_adapter.py`
- Modify: `src/components/executor/node_runner.py`
- Test: `tests/adapters/test_audited_tool_runtime.py`

- [ ] **Step 1: 写入未授权工具在真实调用前被拒绝的失败测试。**

```python
def test_audited_tool_runtime_blocks_unapproved_tool_before_delegate() -> None:
    delegate = RecordingToolRuntime()
    runtime = AuditedToolRuntime(delegate=delegate, allowed_tools={"search"}, trace=trace)

    with pytest.raises(ToolAuthorizationError):
        asyncio.run(runtime.execute("shell", {"command": "whoami"}))

    assert delegate.calls == []
```

- [ ] **Step 2: 运行失败测试。**

Run: `pytest tests/adapters/test_audited_tool_runtime.py::test_audited_tool_runtime_blocks_unapproved_tool_before_delegate -q`

Expected: FAIL，因为包装器尚不存在。

- [ ] **Step 3: 实现权限、Trace 和错误映射包装器。**

```python
class AuditedToolRuntime:
    async def execute(self, name: str, arguments: dict[str, Any], **kwargs: Any) -> Any:
        if name not in self.allowed_tools:
            raise ToolAuthorizationError(name)
        self.trace.append(..., event_type=TraceEventType.TOOL_CALLED, payload={"tool": name})
        return await self.delegate.execute(name, arguments, **kwargs)
```

- [ ] **Step 4: 增加成功、失败、超时、取消和迟到结果不提交到 value store 的测试。**

Run: `pytest tests/adapters/test_audited_tool_runtime.py -q`

Expected: PASS；每次调用存在唯一审计事件，禁止工具不会触发外部副作用。

- [ ] **Step 5: 提交本任务。**

```bash
git add src/adapters/audited_tool_runtime.py src/adapters/tool_adapter.py src/components/executor/node_runner.py tests/adapters/test_audited_tool_runtime.py
git commit -m "feat: add audited scoped tool runtime"
```

### Task 10：接入模型调用元数据而不记录敏感正文

**Files:**

- Modify: `src/adapters/model_adapter.py`
- Modify: `src/components/executor/node_runner.py`
- Test: `tests/adapters/test_model_audit_metadata.py`

- [ ] **Step 1: 写入模型审计元数据不含 prompt 和响应正文的失败测试。**

```python
def test_model_audit_record_excludes_prompt_and_generated_data() -> None:
    record = StructuredGenerationResult(
        data={"answer": "secret"}, provider="local", model="test", usage={"tokens": 3}
    ).audit_record()

    assert record == {"provider": "local", "model": "test", "latencyMs": 0,
                      "promptVersion": "native-capability.v1", "usage": {"tokens": 3}}
```

- [ ] **Step 2: 运行失败测试。**

Run: `pytest tests/adapters/test_model_audit_metadata.py::test_model_audit_record_excludes_prompt_and_generated_data -q`

Expected: FAIL 或暴露当前节点执行器未投影模型调用元数据的缺口。

- [ ] **Step 3: 在节点审计 payload 中记录 `AgentOutput.model_invocations` 的 `audit_record` 投影。**

```python
trace_payload = {
    "outputRef": output_ref,
    "modelInvocations": [dict(item) for item in output.model_invocations],
}
```

- [ ] **Step 4: 增加多个模型调用、供应商错误和无模型调用的测试。**

Run: `pytest tests/adapters/test_model_audit_metadata.py -q`

Expected: PASS；Trace 有足够成本/时延元数据，但不包含敏感正文。

- [ ] **Step 5: 提交本任务。**

```bash
git add src/adapters/model_adapter.py src/components/executor/node_runner.py tests/adapters/test_model_audit_metadata.py
git commit -m "feat: project safe model invocation metadata"
```

## 六、Runtime 接线、暂停续跑和最终验收

### Task 11：将自研服务组合接入首次 ACG 执行

**Files:**

- Modify: `src/runtime/workflow_runtime.py`
- Modify: `src/components/executor/node_runner.py`
- Test: `tests/runtime/test_fused_acg_execution.py`

- [ ] **Step 1: 写入线性 ACG 从 `prepare_run` 执行到 completed 的失败测试。**

```python
def test_runtime_executes_prepared_acg_with_reference_state() -> None:
    runtime, run = prepared_runtime_with_two_step_acg()

    result = asyncio.run(runtime.execute_prepared_run(run.run_id))

    assert result.status is WorkflowStatus.COMPLETED
    assert result.execution_state["engineMigration"] == "langgraph_fused_v1"
    assert result.runtime_graph is None
    assert result.output["outputRef"].startswith("output:")
```

- [ ] **Step 2: 运行失败测试。**

Run: `pytest tests/runtime/test_fused_acg_execution.py::test_runtime_executes_prepared_acg_with_reference_state -q`

Expected: FAIL，当前入口会抛 `ACG_EXECUTION_ENGINE_MIGRATING`。

- [ ] **Step 3: 在 `WorkflowRuntime` 注入自研服务并实现 ACG 分支。**

```python
graph = self.acg_graph_compiler.compile(ACGBlueprint.model_validate(run.acg_blueprint))
state = ACGExecutionState(runId=run.run_id, graphId=graph_id)
runner = self._build_node_runner(task=task, run=run, workflow=workflow, state=state)
async for event in graph.astream(state, runner):
    self.trace_store.append_execution_event(run, event)
    self._persist_execution_projection(run, state)
```

- [ ] **Step 4: 在成功路径解除 `execute_prepared_run` 的迁移错误拦截，并保持其它非 ACG adapter 不变。**

- [ ] **Step 5: 增加并行分支、IF 分支、取消、输出引用和 Trace 导出的端到端测试。**

Run: `pytest tests/runtime/test_fused_acg_execution.py -q`

Expected: PASS；每个 run 的状态只含引用，完整输出可从 `ExecutionValueStore` 按 runId 读取。

- [ ] **Step 6: 提交本任务。**

```bash
git add src/runtime/workflow_runtime.py src/components/executor/node_runner.py tests/runtime/test_fused_acg_execution.py
git commit -m "feat: execute acg through fused runtime services"
```

### Task 12：接入审核暂停和 SQLite 恢复

**Files:**

- Modify: `src/runtime/workflow_runtime.py`
- Modify: `src/components/recovery/checkpoint.py`
- Test: `tests/runtime/test_fused_acg_recovery.py`

- [ ] **Step 1: 写入审核中断后重建 runtime 仍可恢复的失败测试。**

```python
def test_runtime_resumes_review_checkpoint_after_recreation(tmp_path) -> None:
    runtime, run = prepared_review_runtime(tmp_path)
    asyncio.run(runtime.execute_prepared_run(run.run_id))
    recreated = recreate_runtime_with_same_databases(tmp_path)

    result = asyncio.run(recreated.apply_review(approved_decision(run)))

    assert result.status is WorkflowStatus.COMPLETED
    assert completed_steps(result) == ["review", "deliver"]
```

- [ ] **Step 2: 运行失败测试。**

Run: `pytest tests/runtime/test_fused_acg_recovery.py::test_runtime_resumes_review_checkpoint_after_recreation -q`

Expected: FAIL，当前 `apply_review` 仍处于迁移保护态。

- [ ] **Step 3: 捕获 `ExecutionInterrupt`，按以下顺序持久化。**

```python
checkpoint_id = self.acg_checkpoint_store.save(
    run_id=run.run_id,
    state=state.model_dump(by_alias=True, mode="json"),
)
run.execution_state["checkpointId"] = checkpoint_id
run.execution_state["reviewPayload"] = dict(interrupt.payload)
run = self._set_run_lifecycle(run, status=WorkflowStatus.WAITING_REVIEW)
self.trace_store.append_execution_event(run, {"type": "interrupted", **interrupt.payload})
self.workflow_store.save_run(run)
```

- [ ] **Step 4: 实现 `apply_review` 和 `resume_from_checkpoint` 的新路径。**

审核批准创建 `ExecutionResumeCommand(runId=run.run_id, payload=...)`；恢复前必须校验 Blueprint 版本、插件 scope 和 checkpoint 的 runId，随后调用 `graph.resume`。

- [ ] **Step 5: 增加 reject/cancel、重复 operationId、跨 run checkpoint 和 Trace 连续性测试。**

Run: `pytest tests/runtime/test_fused_acg_recovery.py -q`

Expected: PASS；审核步骤不重复执行，跨 run 访问被拒绝，恢复事件接在原 Trace 后。

- [ ] **Step 6: 提交本任务。**

```bash
git add src/runtime/workflow_runtime.py src/components/recovery/checkpoint.py tests/runtime/test_fused_acg_recovery.py
git commit -m "feat: resume fused acg review checkpoints"
```

### Task 13：迁移收敛与全量验收

**Files:**

- Modify: `src/runtime/execution_migration.py`
- Modify: `docs/langgraph_execution_integration_plan.md`
- Modify: `docs/TODOS.md`
- Test: `tests/test_execution_engine_migration.py`

- [ ] **Step 1: 写入新的 ACG run 不再返回迁移错误、历史不兼容 run 返回明确迁移错误的失败测试。**

```python
def test_fused_acg_run_executes_but_legacy_runtime_graph_run_is_migration_blocked() -> None:
    assert execute_new_fused_run().status is WorkflowStatus.COMPLETED
    with pytest.raises(ExecutionEngineMigratingError):
        execute_legacy_runtime_graph_run()
```

- [ ] **Step 2: 运行失败测试。**

Run: `pytest tests/test_execution_engine_migration.py::test_fused_acg_run_executes_but_legacy_runtime_graph_run_is_migration_blocked -q`

Expected: FAIL，直到 Runtime 新路径已覆盖全部 ACG 执行入口。

- [ ] **Step 3: 收窄迁移错误的适用范围。**

新 Blueprint 的 `engineMigration` 为 `langgraph_fused_v1` 时执行新路径；仅旧 `runtimeGraph` 历史快照或缺少必需 scope/checkpoint 元数据时抛迁移错误。

- [ ] **Step 4: 执行完整验证。**

Run:

```bash
pytest -q
python -m py_compile $(rg --files src -g '*.py')
```

PowerShell 等价命令：

```powershell
$files = rg --files src -g '*.py'
python -m py_compile $files
```

Expected: 全部测试通过，所有生产模块可导入，`drafts/legacy_execution` 未被收集或导入。

- [ ] **Step 5: 提交本任务。**

```bash
git add src/runtime/execution_migration.py docs/langgraph_execution_integration_plan.md docs/TODOS.md tests/test_execution_engine_migration.py
git commit -m "chore: finalize fused acg execution migration"
```

## 七、验收矩阵

| 领域 | 必测成功路径 | 必测拒绝路径 | 关键证据 |
| --- | --- | --- | --- |
| 通信 | 多上游白名单 slot 装配、EVENT 通知 | 缺字段、schema 违例、熵超限、EVENT 正文 | ContextPack 引用、血缘 Trace |
| 记忆 | run 内召回、受控输出写情节记忆 | 跨 run、策略拒绝、过期记录 | memoryRef、MemoryRecord scope |
| 审计 | allow/review 决定、Trace 导出 | 无证据高风险、未知事件 | AuditRequest、PolicyDecision、Trace 连续性 |
| 适配 | scope 内 Agent/工具/模型调用 | scope 外 Agent、未授权工具、模型错误 | 稳定错误码、无副作用证明、调用元数据 |
| 执行 | 线性、并行、IF、审核恢复 | BLACKBOARD/DEBATE、环、runId 不匹配 | ACGExecutionState、checkpoint、Trace |
| 持久化 | 重启后 checkpoint 恢复 | 跨 run checkpoint、历史 RuntimeGraph 恢复 | SQLite 数据、版本/scope 校验 |
