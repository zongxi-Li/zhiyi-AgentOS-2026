"""Architecture gates for the AgentOS competition capability upgrade."""

from __future__ import annotations

import ast
from pathlib import Path

from components.executor.graph import ACGExecutionGraph
from runtime.workflow_runtime import ExecutionRuntime


SRC = Path(__file__).resolve().parents[2] / "src"


def _python_sources(root: Path):
    yield from sorted(root.rglob("*.py"))


def _defined_classes(root: Path) -> set[str]:
    names: set[str] = set()
    for path in _python_sources(root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names.update(node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
    return names


def test_workflow_runtime_and_acg_graph_remain_the_only_execution_truth() -> None:
    """Capability work must not introduce a parallel DAG runtime/state machine."""
    assert ExecutionRuntime.__module__ == "runtime.workflow_runtime"
    assert ACGExecutionGraph.__module__ == "components.executor.graph"
    forbidden = {"RuntimeGraph", "SchedulerGraph", "EvolutionRuntime", "LongTermMemoryRuntime"}
    assert _defined_classes(SRC).isdisjoint(forbidden)


def test_scheduler_has_no_dag_readiness_dependency() -> None:
    """Scheduler may consume READY work but must not import or construct the DAG."""
    scheduler_root = SRC / "components" / "scheduler"
    forbidden_modules = {"components.executor.graph", "components.executor.state_graph"}
    for path in _python_sources(scheduler_root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        assert imports.isdisjoint(forbidden_modules), path


def test_resource_directory_has_no_independent_truth_containers() -> None:
    """The legacy directory is a facade, not a second registry or health store."""
    from components.resource.directory import ResourceDirectory

    directory = ResourceDirectory()
    assert set(vars(directory)) == {"resource_service"}


def test_memory_and_evolution_forbid_runtime_mutation_primitives() -> None:
    """Memory remains a service/store and evolution remains declarative policy data."""
    guarded_roots = (SRC / "components" / "memory", SRC / "components" / "evolution")
    forbidden_calls = {"exec", "eval", "compile"}
    for root in guarded_roots:
        for path in _python_sources(root):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            calls = {
                node.func.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            assert calls.isdisjoint(forbidden_calls), path
