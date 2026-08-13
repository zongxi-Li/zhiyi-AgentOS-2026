"""融合 ACG 与历史迁移边界测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from adapters.model.native import register_native_runtime
from runtime.execution_migration import ExecutionEngineMigratingError
from runtime.workflow_runtime import ReviewConflictError
from runtime.workflow_runtime import WorkflowRuntime
from service.agents import AgentRegistry
from components.task_manager.store import WorkflowRegistry
from support.stores.memory_workflow_store import MemoryWorkflowStore


def _prepared_acg_run():
    agents = AgentRegistry()
    workflows = WorkflowRegistry()
    register_native_runtime(agent_registry=agents, workflow_registry=workflows)
    runtime = WorkflowRuntime(
        agent_registry=agents,
        workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(),
    )
    task = runtime.create_task("migration boundary")
    _, run = runtime.prepare_run(task.task_id)
    return runtime, run


def test_prepare_acg_run_persists_blueprint_and_pending_migration_state() -> None:
    runtime, run = _prepared_acg_run()

    persisted = runtime.get_status(run.run_id)

    assert persisted.status.value == "pending"
    assert persisted.acg_blueprint is not None
    assert persisted.runtime_graph is None
    assert persisted.execution_state["engineMigration"] == "langgraph_pending"


def test_legacy_runtime_graph_snapshot_remains_migration_blocked() -> None:
    """缺少新 Blueprint 的历史 runtimeGraph 快照不能误走融合执行入口。"""
    runtime, run = _prepared_acg_run()
    legacy = run.model_copy(deep=True)
    legacy.acg_blueprint = None
    legacy.runtime_graph = {"legacy": True}
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


def test_production_modules_do_not_import_legacy_drafts() -> None:
    production_sources = Path("src").rglob("*.py")

    assert all("drafts.legacy_execution" not in source.read_text(encoding="utf-8") for source in production_sources)


def test_legacy_archive_and_langgraph_attribution_are_present() -> None:
    manifest = Path("drafts/legacy_execution/MANIFEST.md").read_text(encoding="utf-8")
    notices = Path("docs/THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    assert "禁止生产导入" in manifest
    assert "src/components/executor/" in manifest
    assert "d56666f7fbf0d380ad84cdf0cbe5aa48ab0cc086" in notices
    assert "MIT License" in notices


def test_execution_dependencies_do_not_install_langgraph_packages() -> None:
    requirements = Path("requirements.txt").read_text(encoding="utf-8").lower()

    assert "langchain-core==1.4.7" in requirements
    assert "langgraph" not in requirements


def test_fused_files_keep_upstream_attribution_headers() -> None:
    for relative_path in (
        "src/components/executor/graph.py",
        "src/components/executor/compiler.py",
        "src/components/executor/node_runner.py",
        "src/components/recovery/checkpoint.py",
        "src/components/auditor/governance/trace.py",
    ):
        content = Path(relative_path).read_text(encoding="utf-8")
        assert "LangGraph 1.2.10" in content
        assert "d56666f7fbf0d380ad84cdf0cbe5aa48ab0cc086" in content
        assert "MIT" in content
