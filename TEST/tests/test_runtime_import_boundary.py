"""Regression tests for imports required by the default runtime path."""

import ast
import importlib
from pathlib import Path

import pytest


RUNTIME_SOURCE = Path(__file__).parents[1] / "src" / "runtime"


def test_runtime_constructs_the_current_planning_engine() -> None:
    from runtime.workflow_runtime import ExecutionRuntime

    runtime = ExecutionRuntime()

    assert runtime.planning_engine.__class__.__name__ == "PlanningEngine"


def test_retrieval_adapter_does_not_require_the_removed_retrieval_package() -> None:
    adapter = importlib.import_module("adapters.retrieval_adapter")

    assert adapter.__all__ == []


@pytest.mark.parametrize(
    "module_name",
    [
        "acg_execution.py",
        "binding.py",
        "ports.py",
        "review.py",
        "runtime_recovery.py",
        "semantic_revision.py",
        "state_persistence.py",
    ],
)
def test_extracted_runtime_services_do_not_import_the_runtime_facade(
    module_name: str,
) -> None:
    source = (RUNTIME_SOURCE / module_name).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert "runtime.workflow_runtime" not in imported_modules
    assert "ExecutionRuntime" not in imported_names
