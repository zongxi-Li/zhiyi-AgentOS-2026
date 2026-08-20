"""Composition root for the single wkn AgentOS runtime."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from adapters.model.native import register_native_runtime
from components.auditor.decision_store import SQLiteDecisionStore
from components.communicator.provenance_store import SQLiteProvenanceStore
from components.executor.value_store import SQLiteExecutionValueStore
from components.memory.store import SQLiteMemoryStore
from components.resource.service import ResourceService
from components.resource.store import SQLiteResourceStore
from components.recovery.checkpoint import ACGCheckpointStore
from components.task_manager.store import WorkflowRegistry
from runtime import WorkflowRuntime
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


def configure_runtime(
    runtime: WorkflowRuntime,
    *,
    intent_llm: object | None = None,
    model_runtime: object | None = None,
) -> WorkflowRuntime:
    runtime.set_intent_llm(intent_llm or GatewayIntentLLM())
    runtime.set_model_runtime(model_runtime or GatewayStructuredGenerationRuntime())
    return runtime


def build_default_runtime(
    *,
    environment: Mapping[str, str] | None = None,
    intent_llm: object | None = None,
    model_runtime: object | None = None,
    tool_runtime: object | None = None,
) -> WorkflowRuntime:
    """Construct all registries, stores, and external adapters in the application."""
    env = environment or os.environ
    workflow_path = _workflow_db_path(env)
    acquire_workflow_instance_lock(str(workflow_path))

    runtime = WorkflowRuntime(
        agent_registry=AgentRegistry(),
        workflow_registry=WorkflowRegistry(),
        workflow_store=SQLiteWorkflowStore(workflow_path),
        checkpoint_store=ACGCheckpointStore(db_path=_database_path(env, "AGENTOS_LANGGRAPH_CHECKPOINT_DB")),
        execution_value_store=SQLiteExecutionValueStore(db_path=_database_path(env, "AGENTOS_EXECUTION_VALUE_DB")),
        memory_store=SQLiteMemoryStore(db_path=_database_path(env, "AGENTOS_EXECUTION_MEMORY_DB")),
        resource_service=ResourceService(
            store=SQLiteResourceStore(
                Path(str(env.get("AGENTOS_RESOURCE_DB") or workflow_path.with_name("resources.sqlite3")))
            )
        ),
        provenance_store=SQLiteProvenanceStore(db_path=_database_path(env, "AGENTOS_PROVENANCE_DB")),
        decision_store=SQLiteDecisionStore(db_path=_database_path(env, "AGENTOS_AUDIT_DB")),
        tool_runtime=tool_runtime or get_tool_runtime(),
    )
    register_native_runtime(agent_registry=runtime.agent_registry, workflow_registry=runtime.workflow_registry)
    runtime.plugin_manifests = register_installed_packs(
        agent_registry=runtime.agent_registry,
        workflow_registry=runtime.workflow_registry,
        capability_catalog=runtime.capability_catalog,
    )
    return configure_runtime(runtime, intent_llm=intent_llm, model_runtime=model_runtime)


def close_runtime(runtime: WorkflowRuntime) -> None:
    """Close resources created by this composition root without changing workflow state."""
    resources = (
        runtime.workflow_store,
        runtime.checkpoint_store,
        runtime.execution_value_store,
        runtime.memory_store,
        runtime.resource_service.store,
        runtime.provenance_store,
        runtime.decision_store,
        getattr(runtime, "_model_runtime", None),
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


__all__ = ["GatewayIntentLLM", "build_default_runtime", "close_runtime", "configure_runtime"]
