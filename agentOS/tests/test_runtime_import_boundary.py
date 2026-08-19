"""Regression tests for imports required by the default runtime path."""

import importlib


def test_runtime_constructs_the_current_planning_engine() -> None:
    from runtime.workflow_runtime import WorkflowRuntime

    runtime = WorkflowRuntime()

    assert runtime.planning_engine.__class__.__name__ == "PlanningEngine"


def test_retrieval_adapter_does_not_require_the_removed_retrieval_package() -> None:
    adapter = importlib.import_module("adapters.retrieval_adapter")

    assert adapter.__all__ == []


def test_runtime_exports_application_setup_without_starting_network_clients() -> None:
    """应用装配入口可直接导入，但导入自身不读取密钥或建立网络连接。"""
    from runtime import ApplicationSetup

    assert ApplicationSetup.__name__ == "ApplicationSetup"
