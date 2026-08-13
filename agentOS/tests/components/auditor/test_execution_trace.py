"""融合执行事件到既有审计 Trace 的投影测试。"""

from __future__ import annotations

from components.auditor.governance.trace import TraceStore
from contracts.workflow import WorkflowRun


def test_trace_projects_scheduled_nodes_without_exposing_engine_objects() -> None:
    """调度事件只保留步骤标识等紧凑字段，Trace 合同不承载执行器内部对象。"""
    run = WorkflowRun(taskId="task-1", workflowId="workflow-1", domain="general", runtimeEngine="acg")

    event = TraceStore().append_execution_event(
        run,
        {"type": "nodes_scheduled", "stepIds": ["left", "right"]},
    )

    assert event.event_type.value == "step_scheduled"
    assert event.payload == {"stepIds": ["left", "right"]}
