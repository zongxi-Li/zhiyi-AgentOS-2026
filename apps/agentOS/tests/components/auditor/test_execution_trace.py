"""融合执行事件到既有审计 Trace 的投影测试。"""

from __future__ import annotations

from datetime import timedelta

from components.auditor.governance.trace import TraceStore
from contracts.workflow import TraceEvent, TraceEventType, RuntimeRunRecord, utc_now


def test_workspace_trace_keeps_lifecycle_and_full_export_preserves_stream() -> None:
    store = TraceStore()
    run = RuntimeRunRecord(missionId="task-1", workflowId="workflow-1", domain="general", runtimeEngine="acg")
    # Windows 时钟粒度会让快速连续事件共享 created_at，而导出按 (createdAt, eventId) 排序，
    # 随机 eventId 会把同刻事件的顺序变成掷硬币；固定单调时间戳，断言只约束过滤语义。
    base = utc_now()
    events = [
        TraceEvent(
            runId=run.run_id,
            eventType=TraceEventType("runtime_event_classified"),
            observation=name,
            payload={"runtimeEvent": name},
            createdAt=base + timedelta(microseconds=index),
        )
        for index, name in enumerate(
            ["model.output.delta", "model.activity", "model.completed", "model.stream.failure"]
        )
    ]
    store.append_batch(run, events)
    compact = store.export_json(run, workspace=True)
    assert compact["eventCount"] == 4
    assert [event["observation"] for event in compact["events"]] == ["model.completed", "model.stream.failure"]
    assert len(store.export_json(run)["events"]) == 4
    assert len(run.trace) == 4


def test_persisted_degraded_run_event_remains_readable() -> None:
    assert TraceEventType("run_degraded") is TraceEventType.RUN_DEGRADED


def test_trace_projects_scheduled_nodes_without_exposing_engine_objects() -> None:
    """调度事件只保留步骤标识等紧凑字段，Trace 合同不承载执行器内部对象。"""
    run = RuntimeRunRecord(missionId="task-1", workflowId="workflow-1", domain="general", runtimeEngine="acg")

    event = TraceStore().append_execution_event(
        run,
        {"type": "nodes_scheduled", "stepIds": ["left", "right"]},
    )

    assert event.event_type.value == "step_scheduled"
    assert event.payload == {"stepIds": ["left", "right"]}


def test_trace_store_appends_prebuilt_node_trace_as_one_batch() -> None:
    """节点的多个审计事实应先构造再整体写入，避免半批 Trace 被恢复标记误认完成。"""
    store = TraceStore()
    run = RuntimeRunRecord(missionId="task-1", workflowId="workflow-1", domain="general", runtimeEngine="acg")
    success = store.build_execution_event(
        run,
        {"type": "node_completed", "stepId": "extract", "commitId": "commit:run-1:extract:0"},
    )
    memory = store.build_event(
        run,
        event_type=TraceEventType.DATA_CONSUMED,
        step_id="extract",
        observation="Step memory policy applied",
        payload={"written": True},
    )

    stored = store.append_batch(run, [success, memory])

    assert [event.event_type.value for event in stored] == ["step_succeeded", "data_consumed"]
    assert run.trace == stored
