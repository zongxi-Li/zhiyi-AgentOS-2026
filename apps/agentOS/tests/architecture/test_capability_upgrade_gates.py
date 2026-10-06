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


def test_resource_plane_is_the_only_resource_state_authority() -> None:
    """资源平面只有一个状态权威；目录/独立注册表门面已随重构删除。"""
    resource_root = SRC / "components" / "resource"
    remaining = {path.name for path in resource_root.glob("*.py")}
    assert remaining.isdisjoint({
        "directory.py", "agent_directory.py", "agent_service.py",
        "agent_store.py", "node_service.py", "registry.py",
    })
    from components.resource.service import ResourcePlane

    plane = ResourcePlane()
    # Node/Runtime/ModelEndpoint 状态都收敛在同一服务实例里。
    assert hasattr(plane, "register_runtime") and hasattr(plane, "register_node")
    assert hasattr(plane, "upsert_model_endpoint") and hasattr(plane, "runtime_candidates")


def test_local_runtime_is_only_a_contract_and_transport_boundary() -> None:
    """Host tools must not create a parallel authority or execute inside AgentOS."""
    local_files = (SRC / "contracts" / "local_runtime.py", SRC / "adapters" / "local_runtime.py")
    forbidden_classes = {"CapabilityRegistry", "ResourceRegistry", "RuntimeEventBroker"}
    forbidden_imports = {
        "service.agents.base", "app.tools.terminal", "app.tools.chat_catalog",
        "subprocess", "httpx", "requests", "socket",
    }
    forbidden_calls = {"exec", "eval", "system", "Popen", "run", "create_subprocess_shell"}
    for path in local_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        classes = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
        imports = {
            alias.name
            for node in ast.walk(tree) if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        )
        calls = {
            node.func.id for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert classes.isdisjoint(forbidden_classes), path
        assert imports.isdisjoint(forbidden_imports), path
        assert calls.isdisjoint(forbidden_calls), path


def test_local_runtime_http_transport_keeps_the_low_level_boundary() -> None:
    """HTTP Local Runtime transport must not become the AgentRun adapter."""
    path = SRC / "adapters" / "local_runtime_http.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "AgentRunContext" not in names
    assert "AgentOutput" not in names
    assert "HttpResourceExecutionAdapter" not in names
    assert "LocalRuntimeExecutionRequest" in names
    assert "LocalRuntimeExecutionResult" in names
    assert "AgentRunContext" not in attributes


def test_local_runtime_process_does_not_introduce_agentos_authorities() -> None:
    """The host process may supervise native children, but owns no AgentOS authority."""
    local_root = SRC.parents[1] / "local-runtime"
    process_sources = []
    for path in local_root.rglob("*.py"):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        classes = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        assert classes.isdisjoint({"CapabilityRegistry", "ResourceRegistry", "RuntimeEventBroker"})
        if "process" in path.parts:
            process_sources.append(path)
        else:
            assert imported.isdisjoint({"subprocess", "service.agents.base"})
    assert process_sources
    assert all(path.is_relative_to(local_root / "process") for path in process_sources)


def test_agentos_does_not_host_native_process_execution() -> None:
    """Native subprocess and Windows Job Object code stay in local-runtime."""
    for path in SRC.rglob("*.py"):
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
        assert "subprocess" not in imports, path
        assert "ProcessExecutionService" not in path.read_text(encoding="utf-8"), path


def test_windows_isolation_is_local_runtime_only() -> None:
    """OS identity, ACL, and Job Object code cannot cross into AgentOS."""
    agentos_source = "\n".join(
        path.read_text(encoding="utf-8") for path in SRC.rglob("*.py")
    )
    assert "WindowsWorkspaceSecurityLease" not in agentos_source
    assert "CreateAppContainerToken" not in agentos_source
    assert "CreateRestrictedToken" not in agentos_source
    assert "CreateJobObjectW" not in agentos_source

    local_root = SRC.parents[1] / "local-runtime"
    local_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in local_root.rglob("*.py")
        if "tests" not in path.parts
    )
    assert "WindowsWorkspaceSecurityLease" in local_source
    assert "ProcessSupervisor" in local_source


def test_acg_does_not_expose_shell_execution_in_pr6() -> None:
    """PR-6 supplies the host primitive only; ACG remains unchanged."""
    acg_root = SRC / "components" / "executor"
    source = "\n".join(path.read_text(encoding="utf-8") for path in _python_sources(acg_root))
    assert "shell.exec" not in source
    assert "ProcessExecutionService" not in source


def test_local_runtime_integration_does_not_route_chat_acg_or_tauri() -> None:
    """Chat may use the AgentOS Local Runtime seam without creating a parallel authority."""
    chat_api = SRC.parents[1] / "agent" / "app" / "api" / "chat.py"
    chat_catalog = SRC.parents[1] / "agent" / "app" / "tools" / "chat_catalog.py"
    chat_executor = SRC.parents[1] / "agent" / "app" / "tools" / "local_runtime.py"
    assert "get_chat_tool_runtime" in chat_api.read_text(encoding="utf-8")
    assert "ResourceService(" not in chat_api.read_text(encoding="utf-8")
    assert "FilesystemCapabilities" not in chat_catalog.read_text(encoding="utf-8")
    assert "LocalRuntimeExecutor" not in chat_catalog.read_text(encoding="utf-8")
    assert "LocalRuntimeToolExecutor" in chat_catalog.read_text(encoding="utf-8")
    catalog_source = chat_catalog.read_text(encoding="utf-8")
    assert "run_command" in catalog_source
    assert "ProcessExecutionService" not in catalog_source
    assert "subprocess" not in catalog_source
    assert "AgentRunContext" not in chat_executor.read_text(encoding="utf-8")

    tauri_root = SRC.parents[1] / "desktop"
    if tauri_root.exists():
        tauri_source = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in tauri_root.rglob("*.rs"))
        assert "LocalRuntime" not in tauri_source


def test_chat_terminal_keeps_its_existing_composition() -> None:
    """Chat routes file work through the existing AgentOS Local Runtime adapter."""
    chat_api = SRC.parents[1] / "agent" / "app" / "api" / "chat.py"
    catalog = SRC.parents[1] / "agent" / "app" / "tools" / "chat_catalog.py"
    runtime = SRC.parents[1] / "agent" / "app" / "tools" / "runtime.py"
    assert "get_chat_tool_runtime" in chat_api.read_text(encoding="utf-8")
    assert "LocalRuntimeToolExecutor" in catalog.read_text(encoding="utf-8")
    assert all(name in runtime.read_text(encoding="utf-8") for name in (
        "read_file", "list_files", "write_file", "patch_file"
    ))
    config = SRC.parents[1] / "agent" / "app" / "config.py"
    assert "CHAT_LEGACY_CONTAINER_TERMINAL_ENABLED: bool = False" in config.read_text(encoding="utf-8")


def test_chat_permission_policy_does_not_create_a_second_execution_authority() -> None:
    """Approval is a Chat gate; AgentOS Resource/Capability remains execution truth."""
    permission = SRC.parents[1] / "agent" / "app" / "tools" / "permissions.py"
    catalog = SRC.parents[1] / "agent" / "app" / "tools" / "chat_catalog.py"
    runtime = SRC.parents[1] / "agent" / "app" / "tools" / "runtime.py"
    permission_source = permission.read_text(encoding="utf-8")
    catalog_source = catalog.read_text(encoding="utf-8")
    runtime_source = runtime.read_text(encoding="utf-8")

    assert "ChatPermissionService" in catalog_source
    assert "LocalRuntimeToolExecutor" in catalog_source
    assert "CapabilityRegistry" not in permission_source + catalog_source
    assert "ResourceRegistry" not in permission_source + catalog_source
    assert "RuntimeEventBroker" not in permission_source + catalog_source
    assert "ResourceService(" not in permission_source + catalog_source
    assert "subprocess" not in permission_source
    assert "allowedRoot" not in permission_source
    assert "AgentRunContext" not in permission_source + runtime_source
    assert "APPROVAL_REQUIRED" in runtime_source
    assert "APPROVAL_RESOLVED" in runtime_source
    assert "allow_session" in permission_source
    assert "shell.exec" in permission_source


def test_chat_approval_contract_exposes_only_safe_display_fields() -> None:
    """Approval SSE/API data must not become a grant, credential, or host-root channel."""
    permission = SRC.parents[1] / "agent" / "app" / "tools" / "permissions.py"
    source = permission.read_text(encoding="utf-8")
    approval_block = source[source.index("class ApprovalRequest"):source.index("class ApprovalResolutionError")]
    assert "approvalId" in approval_block
    assert "toolCallId" in approval_block
    assert "capabilityId" in approval_block
    assert "relativePath" in approval_block
    assert "allowedRoot" not in approval_block
    assert "resourceId" not in approval_block
    assert "credentialId" not in approval_block


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


def test_v2_planner_core_contains_no_case_specific_domain_steps() -> None:
    """Golden scenarios belong in evals or Packs, never in the generic planner."""
    planner_root = SRC / "components" / "planner"
    source = "\n".join(path.read_text(encoding="utf-8") for path in _python_sources(planner_root))
    forbidden_case_terms = {
        "源网荷储", "医院智慧门诊", "法律合同审查", "工业园区能源优化",
    }
    assert forbidden_case_terms.isdisjoint(source)
