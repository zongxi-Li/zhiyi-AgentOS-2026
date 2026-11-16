"""Keep the approved directory ownership and inward dependency boundaries explicit."""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest


PROJECT_ROOT = next(
    parent for parent in Path(__file__).resolve().parents
    if (parent / "apps/agentOS/src").is_dir()
)
AGENTOS_ROOT = PROJECT_ROOT / "apps/agentOS"
SRC = AGENTOS_ROOT / "src"
COMPONENTS = {
    "mission", "planner", "resource", "scheduler", "executor", "communicator",
    "memory", "auditor", "recovery", "attachments", "environment", "evolution", "safe",
}
RUNTIME_GROUPS = {"composition", "orchestration", "projections", "events", "compatibility"}
ADAPTER_GROUPS = {"model", "agent", "tool", "retrieval", "transport"}
CACHE_DIRECTORIES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def _directories(path: Path) -> set[str]:
    return {child.name for child in path.iterdir() if child.is_dir() and child.name not in CACHE_DIRECTORIES}


def _python_sources(path: Path):
    if path.exists():
        yield from sorted(
            source for source in path.rglob("*.py")
            if not CACHE_DIRECTORIES.intersection(source.parts) and "node_modules" not in source.parts
        )


def _imports(path: Path):
    """Resolve static relative imports and literal dynamic imports to source module names."""
    relative = path.relative_to(SRC).with_suffix("")
    parts = relative.parts[:-1] if path.name == "__init__.py" else relative.parts
    package = ".".join(parts if path.name == "__init__.py" else parts[:-1])
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = resolve_name("." * node.level + module, package)
            yield node.lineno, module
            for alias in node.names:
                if alias.name != "*":
                    yield node.lineno, module + "." + alias.name
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            argument = node.args[0].value
            function = node.func
            if not isinstance(argument, str):
                continue
            if (isinstance(function, ast.Name) and function.id == "__import__") or (
                isinstance(function, ast.Attribute) and function.attr == "import_module"
            ):
                yield node.lineno, argument


def _source_root(module: str) -> str:
    if module.startswith("apps.agentOS.src."):
        module = module.removeprefix("apps.agentOS.src.")
    return module.split(".", 1)[0]


def test_components_have_exactly_the_thirteen_approved_owners():
    assert _directories(SRC / "components") == COMPONENTS


@pytest.mark.parametrize(
    "name,groups,root_files",
    [
        ("runtime", RUNTIME_GROUPS, {"__init__.py", "workflow_runtime.py"}),
        ("adapters", ADAPTER_GROUPS, {"__init__.py"}),
    ],
)
def test_application_and_adapter_modules_stay_in_their_declared_groups(name, groups, root_files):
    root = SRC / name
    assert _directories(root) == groups
    assert {path.name for path in root.glob("*.py")} == root_files
    for group in sorted(groups):
        assert (root / group / "__init__.py").is_file(), f"Missing native package: {name}/{group}"


@pytest.mark.parametrize("layer", ["contracts", "domain"])
def test_shared_inner_layers_do_not_import_application_or_infrastructure(layer):
    forbidden = {"components", "runtime", "adapters", "storage"}
    violations = [
        f"{path.relative_to(SRC)}:{line}: {module}"
        for path in _python_sources(SRC / layer)
        for line, module in _imports(path)
        if _source_root(module) in forbidden
    ]
    assert not violations, "Shared inner layer has upward source dependencies:\n" + "\n".join(violations)


def test_components_do_not_depend_on_top_level_runtime():
    violations = [
        f"{path.relative_to(SRC)}:{line}: {module}"
        for path in _python_sources(SRC / "components")
        for line, module in _imports(path)
        if _source_root(module) == "runtime"
    ]
    assert not violations, "Component depends on the application runtime:\n" + "\n".join(violations)


def test_retired_service_and_safe_roots_do_not_keep_second_implementations():
    implementations = [
        str(path.relative_to(AGENTOS_ROOT))
        for root in (AGENTOS_ROOT / "service", SRC / "safe")
        for path in _python_sources(root)
    ]
    assert not implementations, "Retired roots retain Python implementations:\n" + "\n".join(implementations)
