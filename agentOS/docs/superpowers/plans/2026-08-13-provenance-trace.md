# 通信血缘 Trace 投影 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将低熵通信的生产、消费和交互血缘投影为持久 Trace，供审计、记忆策略和后续轨迹演化消费。

**Architecture:** `CommunicatorService` 继续在 run 内维护 `ProvenanceLedger`；节点运行器从账本取得新事件并返回安全投影；执行图将投影附带在 `node_completed` 事件；Runtime 映射为既有 `DATA_PRODUCED` 与 `DATA_CONSUMED` Trace。投影只包含字段名、校验和、事件 ID、引用、token 统计和节省率，绝不包含 slot 正文、ContextPack 正文或模型输出。

**Tech Stack:** Python 3.10、Pydantic 2、pytest、现有 CommunicatorService / TraceStore / ACG Runtime。

---

### Task 1: 提供账本安全投影

**Files:**

- Modify: `src/components/communicator/provenance.py`
- Test: `tests/components/communicator/test_provenance_trace.py`

- [ ] **Step 1: 写失败测试。**

```python
def test_ledger_trace_projection_excludes_payload_body() -> None:
    ledger.record_production("extract", {"title": "secret"}, 2)
    event = ledger.trace_events()[0]
    assert event["fieldNames"] == ["title"]
    assert "title" not in str(event)
    assert "secret" not in str(event)
```

- [ ] **Step 2: 运行失败测试。**

Run: `$env:PYTHONPATH='src;.'; pytest -q tests/components/communicator/test_provenance_trace.py`

Expected: FAIL，账本尚无 `trace_events`。

- [ ] **Step 3: 实现安全投影。**

```python
def trace_events(self) -> list[dict[str, object]]:
    return [self._trace_event(item) for item in self._events_since(0)]
```

生产事件投影为 `data_produced`，消费和交互事件投影为 `data_consumed`；仅使用合同已有元数据字段。

- [ ] **Step 4: 重跑测试。**

Run: `$env:PYTHONPATH='src;.'; pytest -q tests/components/communicator/test_provenance_trace.py`

Expected: PASS。

### Task 2: 将节点通信事件附带到 ACG 流

**Files:**

- Modify: `src/components/communicator/service.py`
- Modify: `src/components/executor/node_runner.py`
- Modify: `src/components/executor/graph.py`
- Test: `tests/test_acg_execution_graph.py`

- [ ] **Step 1: 写失败测试。**

```python
async def execute(step_id, state):
    result = await runner(step_id, state)
    assert result["provenanceEvents"]
```

- [ ] **Step 2: 运行失败测试。**

Run: `$env:PYTHONPATH='src;.'; pytest -q tests/test_acg_execution_graph.py -k provenance`

Expected: FAIL，节点结果没有 `provenanceEvents`。

- [ ] **Step 3: 实现增量读取。**

`CommunicatorService` 保存已投影事件游标；`ACGNodeRunner` 在 ContextPack 装配、产物记录后取本节点新增投影，并附加到节点结果；`ACGExecutionGraph` 原样放入 `node_completed`。

- [ ] **Step 4: 重跑图层测试。**

Run: `$env:PYTHONPATH='src;.'; pytest -q tests/test_acg_execution_graph.py -k provenance`

Expected: PASS。

### Task 3: Runtime 持久化血缘 Trace

**Files:**

- Modify: `src/runtime/workflow_runtime.py`
- Test: `tests/runtime/test_acg_run.py`

- [ ] **Step 1: 写失败测试。**

```python
result = asyncio.run(runtime.execute_prepared_run(run.run_id))
events = [event for event in result.trace if event.event_type in {
    TraceEventType.DATA_PRODUCED, TraceEventType.DATA_CONSUMED,
}]
assert events
assert "AgentOS" not in str([event.payload for event in events])
```

- [ ] **Step 2: 运行失败测试。**

Run: `$env:PYTHONPATH='src;.'; pytest -q tests/runtime/test_acg_run.py -k provenance`

Expected: FAIL，Runtime 尚未投影通信账本事件。

- [ ] **Step 3: 追加受控 Trace。**

```python
for item in event.get("provenanceEvents", []):
    self.trace_store.append(run, item["eventType"], step_id=event.get("stepId"), payload=item["payload"])
```

- [ ] **Step 4: 运行完整验证。**

Run: `$env:PYTHONPATH='src;.'; pytest -q; $files = @(); $files += rg --files src -g '*.py'; $files += rg --files service -g '*.py'; python -m py_compile $files; git diff --check`

Expected: 全部测试与编译通过，差异检查通过。
