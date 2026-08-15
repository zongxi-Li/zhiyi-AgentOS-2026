"""Regression tests for imports required by the default runtime path."""

import importlib


def test_runtime_constructs_the_current_planning_engine() -> None:
    from runtime.workflow_runtime import WorkflowRuntime

    runtime = WorkflowRuntime()

    assert runtime.planning_engine.__class__.__name__ == "PlanningEngine"


def test_retrieval_adapter_does_not_require_the_removed_retrieval_package() -> None:
    adapter = importlib.import_module("adapters.retrieval_adapter")

    assert adapter.__all__ == []
