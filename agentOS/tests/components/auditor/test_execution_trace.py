"""融合执行事件到既有审计 Trace 的投影测试。"""

from __future__ import annotations

from components.auditor.governance.trace import TraceStore
from contracts.workflow import TraceEventType, WorkflowRun


def test_persisted_degraded_run_event_remains_readable() -> None:
    assert TraceEventType("run_degraded") is TraceEventType.RUN_DEGRADED


def test_trace_projects_scheduled_nodes_without_exposing_engine_objects() -> None:
    """调度事件只保留步骤标识等紧凑字段，Trace 合同不承载执行器内部对象。"""
    run = WorkflowRun(taskId="task-1", workflowId="workflow-1", domain="general", runtimeEngine="acg")

    event = TraceStore().append_execution_event(
        run,
        {"type": "nodes_scheduled", "stepIds": ["left", "right"]},
    )

    assert event.event_type.value == "step_scheduled"
    assert event.payload == {"stepIds": ["left", "right"]}


def test_trace_store_appends_prebuilt_node_trace_as_one_batch() -> None:
    """节点的多个审计事实应先构造再整体写入，避免半批 Trace 被恢复标记误认完成。"""
    store = TraceStore()
    run = WorkflowRun(taskId="task-1", workflowId="workflow-1", domain="general", runtimeEngine="acg")
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
