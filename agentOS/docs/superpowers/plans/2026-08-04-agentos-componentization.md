# AgentOS Componentization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 AgentOS 重组为按业务部件划分的可测试实现，并完成可本地运行的记忆、资源、调度、ACG 导出与运行时接入。

**Architecture:** `contracts` 提供不可变跨部件合同；每个业务部件只通过合同协作。现有 `core` 保留为兼容 Facade，随后由 `runtime` 统一编排新部件，外部系统均位于 `adapters`。

**Tech Stack:** Python 3、Pydantic、SQLite、asyncio、pytest；Mermaid/DOT 以纯文本生成，无前端或图形二进制依赖。

---

### Task 1: 建立共享合同与部件包

**Files:**
- Create: `src/contracts/{__init__,task,workflow,execution,communication,memory,resource,governance,recovery}.py`
- Create: `src/{task_manager,planner,resource,scheduler,executor,communicator,memory,auditor,recovery,runtime,acg_tools}/__init__.py`
- Test: `tests/contracts/test_contract_models.py`

- [ ] **Step 1: 编写合同校验失败测试**

```python
from contracts.resource import ResourceProfile

def test_resource_profile_requires_capability():
    with pytest.raises(ValidationError):
        ResourceProfile(resourceId="r1", resourceType="agent", capabilities=[])
```

- [ ] **Step 2: 运行失败测试**

Run: `pytest tests/contracts/test_contract_models.py -v`

Expected: FAIL because `contracts` cannot be imported.

- [ ] **Step 3: 实现最小共享合同**

```python
class ResourceProfile(BaseModel):
    resource_id: str = Field(alias="resourceId")
    resource_type: Literal["agent", "model", "tool", "knowledge"] = Field(alias="resourceType")
    capabilities: list[str] = Field(min_length=1)
```

`contracts` 中的模型全部使用 `populate_by_name=True`、`extra="forbid"` 和别名 camelCase；模型仅定义数据、校验与稳定哈希，不能依赖任何部件。

- [ ] **Step 4: 运行合同测试**

Run: `pytest tests/contracts/test_contract_models.py -v`

Expected: PASS.

### Task 2: 实现资源器与资源算法

**Files:**
- Create: `src/resource/{models,registry,health,algorithms,store,service}.py`
- Test: `tests/resource/test_scheduler_candidates.py`
- Test: `tests/resource/test_resource_health.py`

- [ ] **Step 1: 编写候选过滤和 EMA 失败测试**

```python
def test_unhealthy_or_full_resource_is_not_available():
    registry.register(profile, ResourceSnapshot(resourceId="a", health="unhealthy", availableSlots=1))
    assert service.candidates(capability="analysis") == []

def test_observe_uses_exponential_moving_average():
    snapshot = service.observe("a", success=True, latency_ms=100)
    assert snapshot.reliability > 0.5
```

- [ ] **Step 2: 运行失败测试**

Run: `pytest tests/resource -v`

Expected: FAIL because `resource` does not exist.

- [ ] **Step 3: 实现资源注册与健康计算**

```python
def ema(previous: float, sample: float, alpha: float = 0.2) -> float:
    return round(alpha * sample + (1.0 - alpha) * previous, 6)

def is_available(snapshot: ResourceSnapshot) -> bool:
    return snapshot.health == "healthy" and snapshot.available_slots > 0
```

实现内存 `ResourceStore`、资源 Profile/Snapshot 版本检查和 `ResourceService.observe()`；SQLite 与远程心跳 Adapter 均以中文待实现注释标出所缺外部依赖，不得伪造实现。

- [ ] **Step 4: 运行资源测试**

Run: `pytest tests/resource -v`

Expected: PASS.

### Task 3: 实现调度器与资源租约

**Files:**
- Create: `src/scheduler/{models,binder,scorer,leases,package_builder,algorithms,service}.py`
- Test: `tests/scheduler/test_weighted_schedule.py`
- Test: `tests/scheduler/test_leases.py`

- [ ] **Step 1: 编写评分、稳定并列与租约冲突测试**

```python
def test_scheduler_prefers_highest_weighted_score():
    assert scheduler.schedule(request).resource_id == "fast-reliable-agent"

def test_second_lease_fails_when_slot_is_reserved():
    leases.reserve("agent-a", "run-1", "step-1", ttl_seconds=30)
    with pytest.raises(LeaseUnavailable):
        leases.reserve("agent-a", "run-2", "step-2", ttl_seconds=30)
```

- [ ] **Step 2: 运行失败测试**

Run: `pytest tests/scheduler -v`

Expected: FAIL because `scheduler` does not exist.

- [ ] **Step 3: 实现多目标评分与租约服务**

```python
score = (
    0.30 * skill_match + 0.20 * reliability + 0.15 * health_score
    + 0.15 * (1 - load) + 0.10 * (1 - latency)
    + 0.05 * (1 - cost) + 0.05 * (1 - network_distance)
)
```

对所有输入归一化到 `[0, 1]`，按 `(-score, priority, resource_id)` 稳定排序；租约用 `asyncio.Lock` 原子创建、到期清理和释放；`package_builder` 只组合合同，不调用 Agent。

- [ ] **Step 4: 运行调度测试**

Run: `pytest tests/scheduler -v`

Expected: PASS.

### Task 4: 实现记忆器与混合召回算法

**Files:**
- Create: `src/memory/{models,store,admission,retrieval,compression,lifecycle,algorithms,service}.py`
- Test: `tests/memory/test_retrieval.py`
- Test: `tests/memory/test_admission.py`
- Test: `tests/memory/test_compression.py`

- [ ] **Step 1: 编写范围、证据、冲突与预算测试**

```python
def test_retrieval_never_crosses_tenant_or_run_scope():
    assert [x.memory_id for x in service.retrieve(query)] == ["same-run"]

def test_semantic_memory_requires_evidence():
    assert admission.accept(batch) is False

def test_budget_selection_keeps_best_value_per_token():
    assert [x.memory_id for x in select_under_budget(records, 10)] == ["small-high-value"]
```

- [ ] **Step 2: 运行失败测试**

Run: `pytest tests/memory -v`

Expected: FAIL because new memory contracts and service do not exist.

- [ ] **Step 3: 实现 MemoryManager**

```python
rank = 0.35 * lexical + 0.20 * evidence + 0.20 * freshness + 0.15 * authority + 0.10 * utility
```

实现 Scope/权限硬过滤、直接引用和关键词召回、`content_hash` 去重、冲突并存、稳定重排以及按 `rank / token_count` 的贪心预算选择。工作/情节记忆可直接写入；语义和程序记忆必须包含有效证据引用。Vector Store 调用在 Adapter 中以中文待实现注释标出。

- [ ] **Step 4: 运行记忆测试**

Run: `pytest tests/memory -v`

Expected: PASS.

### Task 5: 实现 ACG JSON 与绘图工具

**Files:**
- Create: `src/acg_tools/{models,serializer,exporter,labels,mermaid,graphviz,service}.py`
- Test: `tests/acg_tools/test_export.py`
- Test: `tests/acg_tools/test_render.py`

- [ ] **Step 1: 编写 JSON 稳定性与绘图文本测试**

```python
def test_export_is_deterministic(blueprint):
    assert export_json(blueprint) == export_json(blueprint)

def test_render_contains_node_and_dependency_edge(blueprint):
    assert "flowchart TD" in render_mermaid(blueprint)
    assert "digraph ACG" in render_dot(blueprint)
```

- [ ] **Step 2: 运行失败测试**

Run: `pytest tests/acg_tools -v`

Expected: FAIL because `acg_tools` does not exist.

- [ ] **Step 3: 实现无副作用导出器**

```python
payload = {"formatVersion": "acg.v1", "graph": graph, "nodes": nodes, "edges": edges}
return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
```

按节点 ID 和边 ID 排序；为 Step、Agent、Memory、Evidence、Control 节点与依赖/通信/控制边赋予固定 Mermaid/DOT 样式；导出器不得改变 Blueprint 或 RuntimeGraph。

- [ ] **Step 4: 运行工具测试**

Run: `pytest tests/acg_tools -v`

Expected: PASS.

### Task 6: 将通信器与执行器收敛为部件

**Files:**
- Create: `src/communicator/{models,contracts,assembler,compressor,provenance,algorithms,service}.py`
- Create: `src/executor/{graph,dispatcher,barrier,algorithms,service,fault_injection}.py`
- Modify: `src/core/execution/acg_executor.py`
- Modify: `src/core/communication/assembler.py`
- Test: `tests/communicator/test_context_pack.py`
- Test: `tests/executor/test_resource_lease_integration.py`

- [ ] **Step 1: 编写执行包包含记忆和租约的失败测试**

```python
assert outcome.resolved_input["memoryContext"]
assert resource_service.active_lease_count("native_general_agent") == 0
```

- [ ] **Step 2: 运行失败测试**

Run: `pytest tests/communicator tests/executor -v`

Expected: FAIL because new component services are not wired to the executor.

- [ ] **Step 3: 接入新部件 Interface**

在 `ACGExecutor._make_package()` 中请求记忆上下文；在调度前申请租约，在屏障提交后释放租约并反馈执行指标；旧 `ContextAssembler` 和执行器改为调用新服务的兼容 Facade，不改变既有公共方法签名。

- [ ] **Step 4: 运行执行集成与既有回归测试**

Run: `pytest tests/communicator tests/executor tests/test_runtime_graph_execution.py -v`

Expected: PASS.

### Task 7: 迁移任务、规划、审计、恢复与运行时 Facade

**Files:**
- Create: `src/task_manager/{models,state_machine,algorithms,scheduler,store,service}.py`
- Create: `src/planner/{models,intent_analyzer,task_structurer,cognitive_router,template_matcher,acg_builder,algorithms,service}.py`
- Create: `src/auditor/{models,structural,evidence,risk,quality,policy,algorithms,service}.py`
- Create: `src/recovery/{models,classifier,checkpoint,planner,validator,algorithms,service}.py`
- Create: `src/runtime/{bootstrap,workflow_runtime,dependencies,compatibility}.py`
- Modify: `src/core/runtime.py`
- Test: `tests/runtime/test_component_runtime.py`

- [ ] **Step 1: 编写新运行时端到端失败测试**

```python
run = await ComponentRuntime(...).run_task(task)
assert run.status.value == "completed"
assert run.execution_state["componentArchitectureVersion"] == "v1"
```

- [ ] **Step 2: 运行失败测试**

Run: `pytest tests/runtime/test_component_runtime.py -v`

Expected: FAIL because `ComponentRuntime` does not exist.

- [ ] **Step 3: 逐部件建立兼容 Facade**

每个新部件首先复用已验证的 `core` 逻辑并保持旧 API；`runtime.WorkflowRuntime` 仅注入 TaskManager、Planner、Scheduler、Executor、Communicator、Memory、Auditor、Recovery 和 ACGTools，不持有算法实现。未能迁移的远程 Agent、API、厂商模型适配位置保留中文待实现注释并附缺少的外部依赖说明。

- [ ] **Step 4: 运行全量测试**

Run: `pytest -q`

Expected: PASS.

### Task 8: 清理旧路径并完成交付验证

**Files:**
- Modify: `design.md`
- Modify: `src/core/{__init__,runtime}.py`
- Modify: `src/{communication,governance,recovery,infrastructure}/__init__.py`
- Test: `tests/test_component_import_boundaries.py`

- [ ] **Step 1: 编写禁止跨部件内部导入测试**

```python
def test_component_imports_use_contracts_or_public_service_only():
    assert violations == []
```

- [ ] **Step 2: 运行失败测试**

Run: `pytest tests/test_component_import_boundaries.py -v`

Expected: FAIL until component imports are normalized.

- [ ] **Step 3: 归档兼容层与更新文档**

保留 `core` 的过渡导出；移除空壳模块仅在无调用引用时进行。`design.md` 标注已完成部件与外部 Adapter 的中文待实现注释；不得删除用户已有业务文件。

- [ ] **Step 4: 最终验证**

Run: `pytest -q && python -m compileall -q src`

Expected: all tests pass and compilation exits with code 0.
