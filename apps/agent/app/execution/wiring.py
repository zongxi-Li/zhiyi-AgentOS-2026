"""Composition root for the single AgentOS execution runtime."""

from __future__ import annotations

import os
import asyncio
import json
from datetime import timedelta
from pathlib import Path
from threading import Thread
from typing import Any, Mapping

from adapters.model.native import register_native_runtime
from adapters.local_runtime import LocalRuntimeClient
from adapters.local_runtime_http import HttpLocalRuntimeTransport
from components.auditor.decision_store import SQLiteDecisionStore
from components.communicator.provenance_store import SQLiteProvenanceStore
from components.executor.value_store import SQLiteExecutionValueStore
from components.evolution.service import EvolutionService
from components.evolution.store import SQLiteEvolutionStore
from components.memory.store import SQLiteMemoryStore
from components.content import SQLiteContentManifestStore
from components.attachments import (
    AttachmentLimits,
    DocumentTextExtractorRegistry,
    DocxTextExtractor,
    InputAttachmentService,
    LocalAttachmentStorage,
    PdfTextExtractor,
    PlainTextExtractor,
)
from components.resource.service import ResourceService
from components.resource.local_runtime import (
    LOCAL_RUNTIME_RESOURCE_CAPABILITIES,
    LocalRuntimeHealthProjector,
    LocalRuntimeResourceConfig,
    ensure_local_runtime_resource,
)
from contracts.local_runtime import LocalRuntimeAuthorizationRef
from components.resource.health import ResourceHealthMonitor
from components.resource.health_store import SQLiteResourceHealthStore
from components.resource.store import SQLiteResourceStore
from components.resource.agent_service import AgentService
from components.resource.agent_directory import AgentDirectory
from components.resource.agent_store import SQLiteAgentStore
from components.resource.node_service import NodeService
from components.resource.node_store import SQLiteNodeStore
from components.recovery.checkpoint import ACGCheckpointStore
from components.scheduler.leases import RedisLeaseCoordinator
from components.scheduler.service import SchedulerService
from components.scheduler.two_layer_service import TwoLayerSchedulerService
from components.mission_manager.store import WorkflowRegistry
from runtime import ApplicationSetup, ExecutionRuntime
from adapters.guarded_model import GuardedModelRuntime
from adapters.model_runtime import RegisteredModelRuntime
from runtime.v2 import (
    AcgIdentityLifecycleService,
    IdentityProjectionReconciler,
    IdentityProjectionBridge,
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
    "AGENTOS_CONTENT_MANIFEST_DB": "data/content_manifests.sqlite3",
    "AGENTOS_EXECUTION_MEMORY_DB": "data/execution_memory.sqlite3",
    "AGENTOS_PROVENANCE_DB": "data/provenance.sqlite3",
    "AGENTOS_AUDIT_DB": "data/audit_decisions.sqlite3",
    "AGENTOS_RESOURCE_DB": "data/resources.sqlite3",
    "AGENTOS_NODE_DB": "data/nodes.sqlite3",
    "AGENTOS_AGENT_DB": "data/agents.sqlite3",
    "AGENTOS_RESOURCE_HEALTH_DB": "data/resource_health.sqlite3",
    "AGENTOS_EVOLUTION_DB": "data/evolution.sqlite3",
}


class GatewayIntentLLM:
    def generate_json(self, prompt: str, schema: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        from app.llm.gateway import get_llm_gateway

        return get_llm_gateway().generate_json(prompt, schema, **kwargs)


def _run_coroutine_sync(factory):
    """Bridge the legacy synchronous planner boundary to the async model runtime."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    result: dict[str, Any] = {}
    failure: list[BaseException] = []

    def runner() -> None:
        try:
            result["value"] = asyncio.run(factory())
        except BaseException as exc:  # pragma: no cover - only reached in nested-loop hosts
            failure.append(exc)

    thread = Thread(target=runner, name="agentos-planner-model-bridge", daemon=True)
    thread.start()
    thread.join()
    if failure:
        raise failure[0]
    return result.get("value")


class RegisteredPlannerLLM:
    """Bridge planner calls to the Runtime-owned model registry."""

    def __init__(self, runtime: ExecutionRuntime, binding: dict[str, Any] | None = None) -> None:
        self._runtime = runtime
        self._binding = dict(binding) if binding is not None else None

    def copilot_models(self):
        from app.llm.capabilities import provider_model_capabilities
        return tuple({**route, "reasoningEfforts": list(caps.reasoning_efforts or []),
            "defaultReasoningEffort": caps.default_reasoning_effort}
            for route in self._runtime.model_registry.list_models()
            for caps in [provider_model_capabilities(route["model"], "", route["provider"])])

    def for_model(self, provider: str, model: str):
        self._runtime.model_registry.resolve(provider, model)
        return RegisteredPlannerLLM(self._runtime, {"provider": provider, "model": model})

    @property
    def binding(self):
        return self._binding if self._binding is not None else self._runtime.default_model_binding or {}

    @property
    def _model_runtime(self) -> RegisteredModelRuntime:
        binding = self.binding
        return RegisteredModelRuntime(
            registry=self._runtime.model_registry,
            provider=str(binding.get("provider") or ""),
            model=str(binding.get("model") or ""),
            version=binding.get("version"),
        )

    @property
    def provider(self) -> str:
        return str(self.binding.get("provider") or "")

    @property
    def model(self) -> str:
        return str(self.binding.get("model") or "")

    def is_available(self) -> bool:
        if not self.provider or not self.model:
            return False
        return self._model_runtime.is_available()

    def describe_model(self):
        return self._model_runtime.describe_model()

    def stream_generate_json(self, **kwargs):
        return self._model_runtime.stream_generate_json(**kwargs)

    def generate_json(self, prompt: str, schema: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        call_kwargs = dict(kwargs)
        if "max_tokens" in call_kwargs:
            call_kwargs["max_output_tokens"] = call_kwargs.pop("max_tokens")
        # Legacy planner audit identity is separate from model request parameters.
        template_hash = call_kwargs.pop("prompt_template_hash", None)
        result = _run_coroutine_sync(lambda: self._model_runtime.generate_json(
            prompt=prompt, schema=schema, **call_kwargs,
        ))
        return {
            **result.audit_record(), "data": result.data,
            "latency_ms": result.latency_ms,
            **({"prompt_template_hash": template_hash} if template_hash else {}),
        }


def bind_registered_planner_llm(runtime: ExecutionRuntime) -> bool:
    """Switch the production planner to the same registry used by node runtime."""
    current = getattr(runtime, "_intent_llm", None)
    if not isinstance(current, GatewayIntentLLM):
        return False
    if not getattr(runtime, "default_model_binding", None):
        return False
    candidate = RegisteredPlannerLLM(runtime)
    if not candidate.is_available():
        return False
    runtime.set_intent_llm(candidate)
    return True


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
    runtime: ExecutionRuntime,
    *,
    intent_llm: object | None = None,
    model_runtime: object | None = None,
) -> ExecutionRuntime:
    runtime.set_intent_llm(intent_llm or GatewayIntentLLM())
    runtime.set_model_runtime(model_runtime or GatewayStructuredGenerationRuntime())
    return runtime


def sync_agent_registry_to_ledger(runtime: ExecutionRuntime) -> None:
    """Project callable application Agents into the persistent Agent ledger."""
    directory = AgentDirectory(runtime.agent_service)
    for agent in runtime.agent_registry.all():
        directory.register_agent(agent.profile)


def build_model_setup(
    runtime: ExecutionRuntime,
    *,
    environment: Mapping[str, str] | None = None,
) -> ApplicationSetup:
    """Bind configured adapters to the Runtime-owned model registry."""
    values = dict(os.environ if environment is None else environment)
    if not str(values.get("AGENTOS_MODELS") or "").strip():
        # The application historically configured the same provider through the
        # legacy gateway variables. Promote that route into the Runtime registry
        # so Planner never silently falls back to a synchronous provider call.
        from app.llm.gateway import get_llm_gateway

        gateway = get_llm_gateway()
        config = gateway.config
        if (
            gateway.provider_name not in {"", "mock", "unavailable"}
            and gateway.model
            and config.base_url
            and config.api_key
        ):
            key_env = "AGENTOS_RUNTIME_MODEL_API_KEY"
            values[key_env] = config.api_key
            values["AGENTOS_MODELS"] = json.dumps([{
                "capabilityId": f"model.gateway.{gateway.provider_name}",
                "provider": gateway.provider_name,
                "models": [gateway.model],
                "baseUrl": config.base_url,
                "apiKeyEnv": key_env,
                "version": "1.0.0",
                "priority": 100,
                "requestTimeoutSeconds": config.timeout_seconds,
            }])
    setup = ApplicationSetup.from_environment(
        values,
        model_registry=runtime.model_registry,
    )
    runtime.default_model_binding = setup.default_model_binding
    return setup


def build_default_runtime(
    *,
    environment: Mapping[str, str] | None = None,
    intent_llm: object | None = None,
    model_runtime: object | None = None,
    tool_runtime: object | None = None,
    coordination_client: object | None = None,
) -> ExecutionRuntime:
    """Construct all registries, stores, and external adapters in the application."""
    env = environment or os.environ
    environment_name = str(env.get("ENVIRONMENT") or "development").strip().lower()
    resource_credential_key = _read_optional_secret(env, "AGENTOS_RESOURCE_CREDENTIAL_KEY")
    if environment_name in {"prod", "production"} and not resource_credential_key:
        raise RuntimeError(
            "AGENTOS_RESOURCE_CREDENTIAL_KEY is required in production"
        )
    workflow_path = _workflow_db_path(env)
    acquire_workflow_instance_lock(str(workflow_path))

    node_service = NodeService(
        store=SQLiteNodeStore(_database_path(env, "AGENTOS_NODE_DB")),
        credential_key=resource_credential_key,
    )
    agent_service = AgentService(
        store=SQLiteAgentStore(_database_path(env, "AGENTOS_AGENT_DB")),
    )
    resource_health_store = SQLiteResourceHealthStore(
        _database_path(env, "AGENTOS_RESOURCE_HEALTH_DB")
    )
    resource_service = ResourceService(
        store=SQLiteResourceStore(_database_path(env, "AGENTOS_RESOURCE_DB")),
        health_monitor=ResourceHealthMonitor(
            store=resource_health_store,
            heartbeat_timeout=timedelta(seconds=float(env.get("AGENTOS_RESOURCE_HEARTBEAT_TIMEOUT_SECONDS") or 60)),
        ),
        credential_key=resource_credential_key,
    )
    coordination_url = str(env.get("AGENTOS_COORDINATION_REDIS_URL") or "").strip()
    scheduler_service = None
    legacy_scheduler_service = None
    if coordination_client is not None or coordination_url:
        coordinator = RedisLeaseCoordinator(
            coordination_client or _build_coordination_client(env)
        )
        scheduler_service = TwoLayerSchedulerService(
            node_service=node_service,
            agent_service=agent_service,
            coordinator=coordinator,
        )
        legacy_scheduler_service = SchedulerService(
            coordinator=coordinator,
        )
    else:
        scheduler_service = TwoLayerSchedulerService(
            node_service=node_service,
            agent_service=agent_service,
        )
    identity_service = AcgIdentityLifecycleService.from_sqlite(
        Path(str(
            env.get("AGENTOS_IDENTITY_DB")
            or workflow_path.with_name("identity_v2.sqlite3")
        ))
    )
    # The identity projection and the single ExecutionRuntime must observe the
    # same ContentManifest store.  Artifact is only a V2 identity projection of
    # sealed manifests; it is not a second content database.
    content_manifest_store = SQLiteContentManifestStore(
        _database_path(env, "AGENTOS_CONTENT_MANIFEST_DB")
    )
    identity_adapter = IdentityProjectionBridge(
        identity_service,
        identity_service.repositories,
        content_manifest_store,
    )
    attachment_limits = AttachmentLimits(
        max_file_bytes=int(env["AGENTOS_ATTACHMENT_MAX_FILE_BYTES"]) if env.get("AGENTOS_ATTACHMENT_MAX_FILE_BYTES") else None,
        max_total_bytes=int(env["AGENTOS_ATTACHMENT_MAX_TOTAL_BYTES"]) if env.get("AGENTOS_ATTACHMENT_MAX_TOTAL_BYTES") else None,
        max_context_characters=int(env.get("AGENTOS_ATTACHMENT_MAX_CONTEXT_CHARACTERS") or 120_000),
    )
    attachment_service = InputAttachmentService(
        repository=identity_service.repositories.input_attachments,
        storage=LocalAttachmentStorage(
            Path(str(env.get("AGENTOS_ATTACHMENT_STORAGE_DIR") or workflow_path.parent / "attachments"))
        ),
        extractors=DocumentTextExtractorRegistry((
            PlainTextExtractor(),
            PdfTextExtractor(max_pages=int(env.get("AGENTOS_ATTACHMENT_PDF_MAX_PAGES") or 500)),
            DocxTextExtractor(
                max_uncompressed_bytes=int(
                    env.get("AGENTOS_ATTACHMENT_DOCX_MAX_UNCOMPRESSED_BYTES") or 50 * 1024 * 1024
                )
            ),
        )),
        content_store=content_manifest_store,
        limits=attachment_limits,
    )
    runtime = ExecutionRuntime(
        agent_registry=AgentRegistry(),
        workflow_registry=WorkflowRegistry(),
        workflow_store=SQLiteWorkflowStore(workflow_path),
        checkpoint_store=ACGCheckpointStore(db_path=_database_path(env, "AGENTOS_LANGGRAPH_CHECKPOINT_DB")),
        execution_value_store=SQLiteExecutionValueStore(db_path=_database_path(env, "AGENTOS_EXECUTION_VALUE_DB")),
        content_manifest_store=content_manifest_store,
        memory_store=SQLiteMemoryStore(db_path=_database_path(env, "AGENTOS_EXECUTION_MEMORY_DB")),
        node_service=node_service,
        agent_service=agent_service,
        resource_service=resource_service,
        scheduler_service=scheduler_service,
        legacy_scheduler_service=legacy_scheduler_service,
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
    runtime.attachment_service = attachment_service
    runtime.attachment_context_builder = attachment_service.context_builder
    reconciliation = IdentityProjectionReconciler(
        identity_adapter
    ).reconcile_workflow_store(runtime.workflow_store, audit_existing=False)
    runtime.identity_reconciliation_report = reconciliation
    local_runtime_endpoint = str(env.get("AGENTOS_LOCAL_RUNTIME_ENDPOINT") or "").strip()
    if local_runtime_endpoint:
        configured_capabilities = tuple(
            item.strip()
            for item in str(env.get("AGENTOS_LOCAL_RUNTIME_CAPABILITIES") or "").split(",")
            if item.strip()
        )
        local_runtime_config = LocalRuntimeResourceConfig(
            resource_id=str(env.get("AGENTOS_LOCAL_RUNTIME_RESOURCE_ID") or "zhiyi-local-runtime"),
            owner_scope=str(env.get("AGENTOS_LOCAL_RUNTIME_OWNER_SCOPE") or "desktop-user"),
            execution_endpoint=local_runtime_endpoint,
            version=int(env.get("AGENTOS_LOCAL_RUNTIME_VERSION") or 1),
            capacity=int(env.get("AGENTOS_LOCAL_RUNTIME_CAPACITY") or 1),
            credential_id=str(env.get("AGENTOS_LOCAL_RUNTIME_CREDENTIAL_ID") or "").strip() or None,
            credential_secret=_read_optional_secret(env, "AGENTOS_LOCAL_RUNTIME_CREDENTIAL_SECRET"),
            capabilities=configured_capabilities or LOCAL_RUNTIME_RESOURCE_CAPABILITIES,
            shell_exec_enabled=str(env.get("AGENTOS_LOCAL_RUNTIME_SHELL_ENABLED") or "false").strip().lower()
            in {"1", "true", "yes", "on"},
        )
        registered_local_runtime = ensure_local_runtime_resource(
            resource_service, local_runtime_config
        )
        local_runtime_transport = HttpLocalRuntimeTransport(
            resource_id=registered_local_runtime.profile.resource_id,
            address=registered_local_runtime.profile.execution_endpoint.address,
            credential_provider=resource_service,
            timeout_seconds=float(env.get("AGENTOS_LOCAL_RUNTIME_TIMEOUT_SECONDS") or 120),
        )
        runtime.local_runtime_resource = registered_local_runtime
        runtime.local_runtime_transport = local_runtime_transport
        runtime.local_runtime_client = LocalRuntimeClient(local_runtime_transport)
        runtime.local_runtime_health_projector = LocalRuntimeHealthProjector(
            resource_service, registered_local_runtime.profile.resource_id
        )
        workspace_id = str(env.get("AGENTOS_LOCAL_RUNTIME_WORKSPACE_ID") or "").strip()
        grant_id = str(env.get("AGENTOS_LOCAL_RUNTIME_GRANT_ID") or "").strip()
        runtime.local_runtime_authorization = (
            LocalRuntimeAuthorizationRef(
                grantId=grant_id,
                workspaceId=workspace_id,
            )
            if workspace_id and grant_id
            else None
        )
    register_native_runtime(agent_registry=runtime.agent_registry, workflow_registry=runtime.workflow_registry)
    runtime.plugin_manifests = register_installed_packs(
        agent_registry=runtime.agent_registry,
        workflow_registry=runtime.workflow_registry,
        capability_catalog=runtime.capability_catalog,
    )
    sync_agent_registry_to_ledger(runtime)
    return configure_runtime(runtime, intent_llm=intent_llm, model_runtime=model_runtime)


def close_runtime(runtime: ExecutionRuntime) -> None:
    """Close resources created by this composition root without changing workflow state."""
    legacy_resource_service = getattr(runtime, "legacy_resource_service", None)
    legacy_scheduler_service = getattr(runtime, "legacy_scheduler_service", None)
    resources = (
        runtime.workflow_store,
        runtime.checkpoint_store,
        runtime.execution_value_store,
        runtime.content_manifest_store,
        runtime.memory_store,
        getattr(legacy_resource_service, "store", None),
        getattr(getattr(legacy_resource_service, "health_monitor", None), "store", None),
        runtime.node_service.store,
        runtime.agent_service.store,
        getattr(legacy_scheduler_service, "coordinator", None),
        getattr(runtime.scheduler_service, "coordinator", None),
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
    "RegisteredPlannerLLM",
    "bind_registered_planner_llm",
    "build_default_runtime",
    "build_model_setup",
    "close_runtime",
    "configure_runtime",
    "sync_agent_registry_to_ledger",
]
