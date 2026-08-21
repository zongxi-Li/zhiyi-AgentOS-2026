"""Composition root for the single wkn AgentOS runtime."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from adapters.model.native import register_native_runtime
from components.auditor.decision_store import SQLiteDecisionStore
from components.communicator.provenance_store import SQLiteProvenanceStore
from components.executor.value_store import SQLiteExecutionValueStore
from components.evolution.service import EvolutionService
from components.evolution.store import SQLiteEvolutionStore
from components.memory.store import SQLiteMemoryStore
from components.resource.service import ResourceService
from components.resource.store import SQLiteResourceStore
from components.recovery.checkpoint import ACGCheckpointStore
from components.scheduler.leases import RedisLeaseCoordinator
from components.scheduler.service import SchedulerService
from components.task_manager.store import WorkflowRegistry
from runtime import ApplicationSetup, WknWorkflowRuntime
from runtime.v2 import (
    AcgIdentityLifecycleService,
    IdentityProjectionReconciler,
    WknIdentityLifecycleAdapter,
)
from service.agents import AgentRegistry
from support.packs.registry import register_installed_packs
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore

from app.execution.instance_lock import acquire_workflow_instance_lock, release_workflow_instance_lock
from app.execution.model_runtime import GatewayStructuredGenerationRuntime
from app.tools import get_tool_runtime


_DEFAULT_DATABASES = {
    "AGENTOS_LANGGRAPH_CHECKPOINT_DB": "data/langgraph_checkpoints.sqlite3",
    "AGENTOS_EXECUTION_VALUE_DB": "data/execution_values.sqlite3",
    "AGENTOS_EXECUTION_MEMORY_DB": "data/execution_memory.sqlite3",
    "AGENTOS_PROVENANCE_DB": "data/provenance.sqlite3",
    "AGENTOS_AUDIT_DB": "data/audit_decisions.sqlite3",
    "AGENTOS_RESOURCE_DB": "data/resources.sqlite3",
    "AGENTOS_EVOLUTION_DB": "data/evolution.sqlite3",
}


class GatewayIntentLLM:
    def generate_json(self, prompt: str, schema: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        from app.llm.gateway import get_llm_gateway

        return get_llm_gateway().generate_json(prompt, schema, **kwargs)


def _workflow_db_path(environment: Mapping[str, str]) -> Path:
    configured = str(environment.get("AGENTOS_WORKFLOW_DB_PATH") or "").strip()
    if not configured:
        raise RuntimeError("AGENTOS_WORKFLOW_DB_PATH is required outside test mode")
    return Path(configured)


def _database_path(environment: Mapping[str, str], name: str) -> Path:
    return Path(str(environment.get(name) or _DEFAULT_DATABASES[name]).strip())


def _read_optional_secret(environment: Mapping[str, str], name: str) -> str | None:
    direct = str(environment.get(name) or "").strip()
    if direct:
        return direct
    secret_path = str(environment.get(f"{name}_FILE") or "").strip()
    if not secret_path:
        return None
    return Path(secret_path).read_text(encoding="utf-8").strip() or None


def _build_coordination_client(environment: Mapping[str, str]):
    from redis import Redis

    return Redis.from_url(
        str(environment["AGENTOS_COORDINATION_REDIS_URL"]),
        password=_read_optional_secret(environment, "REDIS_PASSWORD"),
        decode_responses=False,
    )


def configure_runtime(
    runtime: WknWorkflowRuntime,
    *,
    intent_llm: object | None = None,
    model_runtime: object | None = None,
) -> WknWorkflowRuntime:
    runtime.set_intent_llm(intent_llm or GatewayIntentLLM())
    runtime.set_model_runtime(model_runtime or GatewayStructuredGenerationRuntime())
    return runtime


def build_model_setup(
    runtime: WknWorkflowRuntime,
    *,
    environment: Mapping[str, str] | None = None,
) -> ApplicationSetup:
    """Bind configured adapters to the Runtime-owned model registry."""
    return ApplicationSetup.from_environment(
        os.environ if environment is None else environment,
        model_registry=runtime.model_registry,
    )


def build_default_runtime(
    *,
    environment: Mapping[str, str] | None = None,
    intent_llm: object | None = None,
    model_runtime: object | None = None,
    tool_runtime: object | None = None,
    coordination_client: object | None = None,
) -> WknWorkflowRuntime:
    """Construct all registries, stores, and external adapters in the application."""
    env = environment or os.environ
    workflow_path = _workflow_db_path(env)
    acquire_workflow_instance_lock(str(workflow_path))

    resource_service = ResourceService(
        store=SQLiteResourceStore(
            Path(str(env.get("AGENTOS_RESOURCE_DB") or workflow_path.with_name("resources.sqlite3")))
        )
    )
    coordination_url = str(env.get("AGENTOS_COORDINATION_REDIS_URL") or "").strip()
    scheduler_service = None
    if coordination_client is not None or coordination_url:
        coordinator = RedisLeaseCoordinator(
            coordination_client or _build_coordination_client(env)
        )
        scheduler_service = SchedulerService(
            resource_service=resource_service,
            coordinator=coordinator,
        )
    identity_service = AcgIdentityLifecycleService.from_sqlite(
        Path(str(
            env.get("AGENTOS_IDENTITY_DB")
            or workflow_path.with_name("identity_v2.sqlite3")
        ))
    )
    identity_adapter = WknIdentityLifecycleAdapter(
        identity_service,
        identity_service.repositories,
    )
    runtime = WknWorkflowRuntime(
        agent_registry=AgentRegistry(),
        workflow_registry=WorkflowRegistry(),
        workflow_store=SQLiteWorkflowStore(workflow_path),
        checkpoint_store=ACGCheckpointStore(db_path=_database_path(env, "AGENTOS_LANGGRAPH_CHECKPOINT_DB")),
        execution_value_store=SQLiteExecutionValueStore(db_path=_database_path(env, "AGENTOS_EXECUTION_VALUE_DB")),
        memory_store=SQLiteMemoryStore(db_path=_database_path(env, "AGENTOS_EXECUTION_MEMORY_DB")),
        resource_service=resource_service,
        scheduler_service=scheduler_service,
        evolution_service=EvolutionService(
            store=SQLiteEvolutionStore(db_path=_database_path(env, "AGENTOS_EVOLUTION_DB")),
            proposal_threshold=1,
        ),
        provenance_store=SQLiteProvenanceStore(db_path=_database_path(env, "AGENTOS_PROVENANCE_DB")),
        decision_store=SQLiteDecisionStore(db_path=_database_path(env, "AGENTOS_AUDIT_DB")),
        tool_runtime=tool_runtime or get_tool_runtime(),
        identity_lifecycle=identity_adapter,
        require_planner_identity=True,
    )
    reconciliation = IdentityProjectionReconciler(
        identity_adapter
    ).reconcile_workflow_store(runtime.workflow_store)
    runtime.identity_reconciliation_report = reconciliation
    register_native_runtime(agent_registry=runtime.agent_registry, workflow_registry=runtime.workflow_registry)
    runtime.plugin_manifests = register_installed_packs(
        agent_registry=runtime.agent_registry,
        workflow_registry=runtime.workflow_registry,
        capability_catalog=runtime.capability_catalog,
    )
    return configure_runtime(runtime, intent_llm=intent_llm, model_runtime=model_runtime)


def close_runtime(runtime: WknWorkflowRuntime) -> None:
    """Close resources created by this composition root without changing workflow state."""
    resources = (
        runtime.workflow_store,
        runtime.checkpoint_store,
        runtime.execution_value_store,
        runtime.memory_store,
        runtime.resource_service.store,
        runtime.scheduler_service.coordinator,
        runtime.evolution_service.store,
        runtime.provenance_store,
        runtime.decision_store,
        getattr(runtime, "_model_runtime", None),
        getattr(
            getattr(runtime, "identity_lifecycle", None),
            "lifecycle_service",
            None,
        ),
    )
    seen: set[int] = set()
    for resource in resources:
        if resource is None or id(resource) in seen:
            continue
        seen.add(id(resource))
        close = getattr(resource, "close", None)
        if callable(close):
            close()
    release_workflow_instance_lock()


__all__ = [
    "GatewayIntentLLM",
    "build_default_runtime",
    "build_model_setup",
    "close_runtime",
    "configure_runtime",
]
