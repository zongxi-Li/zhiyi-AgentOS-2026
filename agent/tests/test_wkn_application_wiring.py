from __future__ import annotations

from pathlib import Path

from components.auditor.decision_store import SQLiteDecisionStore
from components.communicator.provenance_store import SQLiteProvenanceStore
from components.executor.value_store import SQLiteExecutionValueStore
from components.memory.store import SQLiteMemoryStore
from components.resource.store import SQLiteResourceStore
from components.recovery.checkpoint import ACGCheckpointStore
from components.scheduler.leases import RedisLeaseCoordinator
from adapters.guarded_model import GuardedModelRuntime
from runtime import WorkflowRuntime
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore

from app.execution.wiring import build_default_runtime, close_runtime


class _InjectedToolRuntime:
    def scoped(self, allowed_tools):
        return self


class _InjectedModelRuntime:
    pass


class _InjectedIntentLLM:
    pass


class _InjectedRedis:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _environment(root: Path) -> dict[str, str]:
    return {
        "AGENTOS_WORKFLOW_DB_PATH": str(root / "workflows.sqlite3"),
        "AGENTOS_LANGGRAPH_CHECKPOINT_DB": str(root / "langgraph_checkpoints.sqlite3"),
        "AGENTOS_EXECUTION_VALUE_DB": str(root / "execution_values.sqlite3"),
        "AGENTOS_EXECUTION_MEMORY_DB": str(root / "execution_memory.sqlite3"),
        "AGENTOS_PROVENANCE_DB": str(root / "provenance.sqlite3"),
        "AGENTOS_AUDIT_DB": str(root / "audit_decisions.sqlite3"),
        "AGENTOS_RESOURCE_DB": str(root / "resources.sqlite3"),
    }


def test_application_builds_the_single_wkn_runtime_with_six_stores(tmp_path: Path) -> None:
    tools = _InjectedToolRuntime()
    model = _InjectedModelRuntime()
    intent = _InjectedIntentLLM()
    runtime = build_default_runtime(
        environment=_environment(tmp_path),
        tool_runtime=tools,
        model_runtime=model,
        intent_llm=intent,
    )
    try:
        assert type(runtime) is WorkflowRuntime
        assert isinstance(runtime.workflow_store, SQLiteWorkflowStore)
        assert isinstance(runtime.checkpoint_store, ACGCheckpointStore)
        assert isinstance(runtime.execution_value_store, SQLiteExecutionValueStore)
        assert isinstance(runtime.memory_store, SQLiteMemoryStore)
        assert isinstance(runtime.provenance_store, SQLiteProvenanceStore)
        assert isinstance(runtime.decision_store, SQLiteDecisionStore)
        assert isinstance(runtime.resource_service.store, SQLiteResourceStore)
        assert runtime.tool_runtime is tools
        assert isinstance(runtime._model_runtime, GuardedModelRuntime)
        assert runtime._model_runtime.delegate is model
        assert runtime._intent_llm is intent
        assert runtime.agent_registry.all()
        assert runtime.workflow_registry.all()
        assert {manifest.pack_id for manifest in runtime.plugin_manifests} == {
            "education",
            "kinlin.legal",
            "programmer",
            "writer",
        }
    finally:
        close_runtime(runtime)


def test_production_python_does_not_import_the_removed_agentos_package() -> None:
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for source in [*(root / "app").rglob("*.py"), *(root / "packs").rglob("*.py")]:
        text = source.read_text(encoding="utf-8")
        if "from agentos" in text or "import agentos" in text or "agentos.core" in text:
            offenders.append(str(source.relative_to(root)))
    assert offenders == []


def test_application_wires_an_injected_redis_lease_coordinator(tmp_path: Path) -> None:
    client = _InjectedRedis()
    runtime = build_default_runtime(
        environment=_environment(tmp_path),
        tool_runtime=_InjectedToolRuntime(),
        model_runtime=_InjectedModelRuntime(),
        intent_llm=_InjectedIntentLLM(),
        coordination_client=client,
    )
    try:
        assert isinstance(runtime.scheduler_service.coordinator, RedisLeaseCoordinator)
        assert runtime.scheduler_service.coordinator.client is client
    finally:
        close_runtime(runtime)
    assert client.closed is True
