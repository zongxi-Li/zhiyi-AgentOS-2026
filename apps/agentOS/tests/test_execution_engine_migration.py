"""融合 ACG 与历史迁移边界测试。"""

from __future__ import annotations

import asyncio

import pytest

from adapters.model.native import GENERAL_EVIDENCE_WORKFLOW_ID, register_native_runtime
from runtime.execution_migration import ExecutionEngineMigratingError
from runtime.workflow_runtime import ReviewConflictError
from runtime.workflow_runtime import ExecutionRuntime
from service.agents import AgentRegistry
from components.mission_manager.store import WorkflowRegistry
from support.stores.memory_workflow_store import MemoryWorkflowStore
from support.acg.models import ACGBlueprint


def _prepared_acg_run():
    agents = AgentRegistry()
    workflows = WorkflowRegistry()
    register_native_runtime(agent_registry=agents, workflow_registry=workflows)
    runtime = ExecutionRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(),
    )
    task = runtime.create_mission("migration boundary")
    _, run = runtime.prepare_run(task.mission_id)
    return runtime, run


def test_prepare_acg_run_persists_blueprint_and_pending_migration_state() -> None:
    runtime, run = _prepared_acg_run()

    persisted = runtime.get_status(run.run_id)

    assert persisted.status.value == "pending"
    assert persisted.acg_blueprint is not None
    assert "runtimeGraph" not in persisted.model_dump(by_alias=True)
    assert persisted.execution_state["engineMigration"] == "langgraph_pending"


def test_core_general_evidence_template_builds_required_dynamic_acg() -> None:
    agents = AgentRegistry()
    workflows = WorkflowRegistry()
    register_native_runtime(agent_registry=agents, workflow_registry=workflows)
    runtime = ExecutionRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(),
    )
    task = runtime.create_mission(
        "Assess a complex technical proposal",
        workflow_id=GENERAL_EVIDENCE_WORKFLOW_ID,
    )

    _, run = runtime.prepare_run(task.mission_id, workflow_id=GENERAL_EVIDENCE_WORKFLOW_ID)

    assert run.acg_blueprint is not None
    blueprint = ACGBlueprint.model_validate(run.acg_blueprint)
    steps = {node.capability: node for node in blueprint.step_nodes()}
    required = {
        "task_understanding",
        "information_extraction",
        "information_retrieval",
        "evidence_analysis",
        "comparative_analysis",
        "verification",
        "artifact_generation",
    }
    assert required <= set(steps)
    assert steps["verification"].review_required is True
    assert steps["verification"].metadata["reviewBarrier"] is True
    assert blueprint.metadata["reviewCapability"] == "verification"
    # Ordinary fan-out remains direct TaskPlan topology; Builder no longer
    # invents PARALLEL/CONSENSUS controls from capability metadata.
    assert blueprint.nodes == blueprint.step_nodes()
    assert run.execution_state["selectedCapabilities"] == [
        node.capability for node in blueprint.step_nodes()
    ]


def test_legacy_runtime_graph_snapshot_remains_migration_blocked() -> None:
    """缺少新 Blueprint 的历史 runtimeGraph 快照不能误走融合执行入口。"""
    runtime, run = _prepared_acg_run()
    payload = run.model_dump(by_alias=True)
    payload["acgBlueprint"] = None
    payload["runtimeGraph"] = {"legacy": True}
    legacy = type(run).model_validate(payload)
    assert "runtimeGraph" not in legacy.model_dump(by_alias=True)
    runtime.workflow_store.save_run(legacy)

    with pytest.raises(ExecutionEngineMigratingError):
        asyncio.run(runtime.execute_prepared_run(legacy.run_id))

    assert runtime.get_status(legacy.run_id).status.value == "pending"


@pytest.mark.parametrize("entry", ["review", "resume"])
def test_acg_recovery_entries_reject_missing_checkpoint_without_transitioning_run(entry: str) -> None:
    """尚未暂停的 ACG run 不能伪造审核或检查点恢复，且不得改变原生命周期。"""
    runtime, run = _prepared_acg_run()

    error_type = ReviewConflictError if entry == "review" else ValueError
    with pytest.raises(error_type):
        if entry == "review":
            from contracts.workflow import ReviewDecision, ReviewDecisionType

            asyncio.run(runtime.apply_review(
                ReviewDecision(
                    runId=run.run_id,
                    stepId="review-step",
                    decision=ReviewDecisionType.APPROVED,
                )
            ))
        else:
            asyncio.run(runtime.resume_from_checkpoint(run_id=run.run_id, checkpoint_id="missing"))

    persisted = runtime.get_status(run.run_id)
    assert persisted.status.value == "pending"
    assert persisted.error is None


def test_cancel_pending_acg_run_remains_available() -> None:
    runtime, run = _prepared_acg_run()

    cancelled = runtime.cancel(run.run_id)

    assert cancelled.status.value == "cancelled"
