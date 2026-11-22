"""READY-before runtime resource eligibility preparation.

职责边界：把编译期 ``BindingManifest``（任务声明需要什么）冻结为每个步骤
的 ``ExecutionRequirement``，并保证嵌入式 Agent 运行时投影进入资源平面。
本服务绝不选择具体资源——选择权威在 ``ResourceBinder``。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from components.resource.runtime.embedded_runtime import refresh_embedded_agents_runtime, EMBEDDED_AGENTS_RUNTIME_ID
from components.resource.application.resource_plane import ResourcePlane
from components.resource.scheduler.models import RequirementReadiness
from contracts.authority import RuntimeResourceId
from contracts.compiled_acg import BindingManifest
from contracts.resource import ExecutionRequirement, NodeHealthStatus, RuntimeKind, RuntimeProfile
from contracts.tools import HOST_TOOL_FAILURE_CODES, hands_tools, safe_tool_failure_details
from contracts.workflow import (
    RunExecutionScope,
    RuntimeRunRecord,
    StepStatus,
    WorkflowDefinition,
)
from adapters.agent import AgentRegistry
from components.resource.agents.pool import AgentPool
from contracts.acg.schema import RuntimeBlueprintSpec
from runtime.composition.ports import CollaboratorAccess


_HANDS_CAPABILITIES = frozenset(tool.name for tool in hands_tools())
_HOST_DEPENDENCY_FAILURE_CODES = HOST_TOOL_FAILURE_CODES | {"HANDS_OUTCOME_UNKNOWN"}


def execution_requirements_for(binding_manifest: BindingManifest, step_ids, *, domain: str | None):
    """Derive eligibility-only requirements from one immutable compiled manifest."""
    requirements: dict[str, dict[str, object]] = {}
    for step_id in step_ids:
        rule = binding_manifest.for_step(step_id)
        required_capabilities = list(rule.required_capabilities)
        if not required_capabilities:
            raise ValueError(f"BindingManifest has no capability requirement: {step_id}")
        role_hint = str(rule.agent_node_ids[0]) if rule.agent_node_ids else None
        requirement = ExecutionRequirement(
            requiredCapabilities=required_capabilities,
            runtimeKinds=[RuntimeKind.EXECUTION_BACKEND],
            domain=rule.domain or domain,
            model=rule.model_demand,
            preferences=({"agentRole": role_hint} if role_hint else {}),
            policyMetadata={
                "source": "compiled-binding-manifest",
                "stepId": step_id,
                "agentNodeIds": list(rule.agent_node_ids),
                "maxConcurrency": rule.max_concurrency,
            },
        )
        requirements[step_id] = requirement.model_dump(by_alias=True, mode="json")
    return requirements


def requirements_match_manifest(actual, expected) -> bool:
    """Compare authority-bearing requirements; role preferences remain hints.

    Existing Recovery may update ``agentRole`` after a reviewed rebind. That
    preference affects ranking only. Failure isolation can add excluded resource
    identities; it can never erase a compiled exclusion or relax another field.
    """
    if not isinstance(actual, dict) or set(actual) != set(expected):
        return False
    for step_id, expected_payload in expected.items():
        actual_payload = actual.get(step_id)
        if not isinstance(actual_payload, dict):
            return False
        actual_contract = dict(actual_payload)
        expected_contract = dict(expected_payload)
        actual_contract.pop("preferences", None)
        expected_contract.pop("preferences", None)
        excluded = set(actual_contract.pop("excludedRuntimeIds", ()))
        if not set(expected_contract.pop("excludedRuntimeIds", ())) <= excluded:
            return False
        if actual_contract != expected_contract:
            return False
    return True


def queued_step_attempts(run: RuntimeRunRecord) -> dict[str, str]:
    """Current queue identities; scheduling metadata never proves execution."""
    state = run.execution_state
    attempts = state.get("attemptIds", {})
    scheduling = state.get("schedulingStates", {})
    current = {}
    for step in run.steps:
        queued = scheduling.get(step.step_id)
        if (step.status not in {StepStatus.PENDING, StepStatus.RETRYING}
                or not isinstance(queued, dict) or queued.get("status") != "queued"):
            continue
        path = state.get("loopPaths", {}).get(step.step_id, ())
        loop_key = ".".join(str(item) for item in path) or "root"
        key = f"{step.step_id}:{max(step.attempt, step.retry_count) + 1}:{loop_key}"
        attempt_id = queued.get("attemptId")
        if isinstance(attempt_id, str) and attempts.get(key) == attempt_id:
            current[step.step_id] = attempt_id
    return current


def effective_recovery_requirement(run: RuntimeRunRecord, step_id: str) -> ExecutionRequirement:
    """Observe the actual blocked dependency without changing the Step contract.

    A callable Agent does not prove its Hands backend is available. Only a host
    failure belonging to the current, unsettled execution may supply that tool
    dependency; old attempts and unrelated failures keep the compiled demand.
    This is readiness evidence, never an execution or replay authorization.
    """
    state = run.execution_state
    original = ExecutionRequirement.model_validate(state["bindingRequirements"][step_id])
    step = run.get_step(step_id)
    settled = set(state.get("completedStepIds", ())) | set(state.get("skippedStepIds", ()))
    failures = state.get("failureEvents") or []
    if step.status != StepStatus.FAILED or step_id in settled or not failures:
        return original
    failure = failures[-1]
    if (not isinstance(failure, dict) or failure.get("source") not in {"scheduler", "executor"}
            or failure.get("reasonCode") not in _HOST_DEPENDENCY_FAILURE_CODES):
        return original
    details = safe_tool_failure_details(failure.get("details"))
    binding = (state.get("executionBindings") or {}).get(step_id)
    if (not isinstance(binding, dict) or details.get("stepId") != step_id
            or not details.get("attemptId") or details["attemptId"] != binding.get("attemptId")
            or binding.get("runId") != run.run_id or binding.get("stepId") != step_id
            or details.get("tool") not in _HANDS_CAPABILITIES
            or not details.get("resourceId")):
        return original
    from components.executor.node_runner import ACGNodeRunner
    commit_id = ACGNodeRunner._commit_id(run.run_id, step_id, step.attempt,
        loop_path=tuple((state.get("loopPaths") or {}).get(step_id, ())),
        execution_generation=state.get("executionGeneration"))
    if details.get("commitId") != commit_id:
        return original
    return ExecutionRequirement(requiredCapabilities=[details["tool"]],
        runtimeKinds=[RuntimeKind.EXECUTION_BACKEND], allowedRuntimeIds=[details["resourceId"]])


def recovery_requires_resource_readiness(observation) -> bool:
    """Gate scheduler failures and attributed executor tool dependencies only."""
    if observation.failure_source == "scheduler":
        return True
    if (observation.failure_source != "executor" or len(observation.failed_step_ids) != 1
            or observation.failure_step_id != observation.failed_step_ids[0]
            or observation.failure_reason not in _HOST_DEPENDENCY_FAILURE_CODES):
        return False
    fact = next((r for r in observation.resource_requirements
        if r.step_id == observation.failure_step_id), None)
    return bool(fact is not None and len(fact.required_capabilities) == 1
        and fact.required_capabilities[0] in _HANDS_CAPABILITIES)


class RuntimeBindingService:
    """Translate a BindingManifest into eligibility requirements only."""

    def __init__(
        self,
        *,
        agent_registry: AgentRegistry,
        resource_plane: ResourcePlane,
        resource_execution_adapters: Mapping[str, object],
    ) -> None:
        self.agent_registry = agent_registry
        self.resource_plane = resource_plane
        self.resource_execution_adapters = resource_execution_adapters
        self.agent_pool = AgentPool(
            registry=agent_registry, resource_plane=resource_plane,
            host_runtime_id=EMBEDDED_AGENTS_RUNTIME_ID,
        )

    def prepare(
        self,
        *,
        run: RuntimeRunRecord,
        workflow: WorkflowDefinition,
        scope: RunExecutionScope,
        binding_manifest: BindingManifest,
    ) -> None:
        """Project callable agents into the plane and persist requirements.

        步骤需求只声明能力与约束；Planner 的 Agent 绑定意图降级为
        非权威偏好（agentRole），在 READY 时由 Binder 匹配实例及其宿主。
        """
        refresh_embedded_agents_runtime(self.resource_plane, self.agent_registry)
        self.agent_pool.synchronize()

        requirements = execution_requirements_for(
            binding_manifest, (step.step_id for step in run.steps), domain=workflow.domain
        )
        model_bindings: dict[str, dict[str, Any] | None] = {}
        for step in run.steps:
            model_bindings[step.step_id] = None

        run.execution_state["resourceBindings"] = {}
        run.execution_state.pop("nodeAgentBindings", None)
        run.execution_state["bindingRequirements"] = requirements
        run.execution_state["modelBindings"] = model_bindings

    def refresh_embedded_runtime(self) -> None:
        """The local process owns this liveness signal, including while idle."""
        refresh_embedded_agents_runtime(self.resource_plane, self.agent_registry)
        self.agent_pool.synchronize()
        self.resource_plane.heartbeat_runtime(EMBEDDED_AGENTS_RUNTIME_ID, source="local")

    def local_candidates(self, run: RuntimeRunRecord | None = None) -> dict[str, tuple[RuntimeProfile, ...]]:
        """Publish this process's liveness before planning or READY assessment.

        An existing host's administrative profile is not a heartbeat. Preserve
        its enabled/capacity/draining facts, and let Binder evaluate them along
        with the current, scoped implementation registrations. Old process
        registrations and remote endpoints supply no local liveness evidence.
        """
        try:
            host = self.resource_plane.runtime(EMBEDDED_AGENTS_RUNTIME_ID)
        except KeyError:
            host = refresh_embedded_agents_runtime(self.resource_plane, self.agent_registry)
        if (host.kind is RuntimeKind.EXECUTION_BACKEND and host.endpoint is None
                and host.metadata.get("managedBy") == "bootstrap"
                and host.metadata.get("runtime") == "embedded-agents"):
            self.resource_plane.heartbeat_runtime(host.runtime_id, source="local")
            if self.resource_plane.node_health(host.node_id).status in {
                    NodeHealthStatus.UNKNOWN, NodeHealthStatus.STALE, NodeHealthStatus.OFFLINE}:
                # Fresh node observations already prove this deployment alive.
                # Do not manufacture a new snapshot version on each read: it
                # would invalidate persisted Planner rounds without new work.
                self.resource_plane.heartbeat_node(host.node_id)
        return self.agent_pool.local_candidates(
            run.execution_scope.agent_ids if run is not None and run.execution_scope is not None else None)

    def validate_blueprint_agents(
        self,
        blueprint: RuntimeBlueprintSpec,
        *,
        domain: str,
        scope: RunExecutionScope | None = None,
    ) -> None:
        """Ensure each Step has one eligible logical or remote executor."""

        missing: list[str] = []
        bindings_by_step: dict[str, list] = {}
        for binding in blueprint.resource_plan.bindings:
            bindings_by_step.setdefault(binding.step_id, []).append(binding)
        for step in blueprint.step_nodes():
            bindings = bindings_by_step.get(step.node_id, [])
            if len(bindings) != 1:
                missing.append(step.node_id)
                continue
            agent = bindings[0]
            try:
                self.agent_registry.resolve(
                    domain=domain,
                    agent_name=agent.planned_agent_id,
                    capability=step.capability,
                    allowed_agent_ids=(scope.agent_ids if scope is not None else None),
                )
            except KeyError:
                remote_match = any(
                    self._remote_runtime_matches_step(
                        runtime_id, step, domain=domain
                    )
                    for runtime_id in self.known_remote_runtime_ids()
                )
                if not remote_match:
                    missing.append(agent.planned_agent_id or step.node_id)
        if missing:
            raise ValueError(
                "ACG references unregistered Agents: "
                + ", ".join(sorted(set(missing)))
            )

    def known_remote_runtime_ids(self) -> set[str]:
        runtime_ids = set(self.resource_execution_adapters)
        for profile in self.resource_plane.runtimes():
            if profile.endpoint is not None:
                runtime_ids.add(profile.runtime_id)
        return {RuntimeResourceId(item) for item in runtime_ids}

    def _remote_runtime_matches_step(
        self, runtime_id: str, step, *, domain: str
    ) -> bool:
        try:
            profile = self.resource_plane.runtime(runtime_id)
            health = self.resource_plane.health_monitor.health(runtime_id)
        except KeyError:
            return False
        return (
            profile.enabled
            and profile.kind is RuntimeKind.EXECUTION_BACKEND
            and health.healthy
            and (
                not profile.domains
                or domain in profile.domains
                or "general" in profile.domains
            )
            and (not step.capability or step.capability in profile.capabilities)
        )


def assess_run_requirement(services: CollaboratorAccess, run: RuntimeRunRecord,
                           requirement: ExecutionRequirement, *, now: datetime | None = None) -> RequirementReadiness:
    """Assess the same current implementation facts consumed by READY binding."""
    binding = RuntimeBindingService(
        agent_registry=services.agent_registry,
        resource_plane=services.resource_plane,
        resource_execution_adapters=services.resource_execution_adapters,
    )
    return services.resource_binder.assess(
        requirement, now=now, agent_candidates=binding.local_candidates(run))


__all__ = ["RuntimeBindingService", "assess_run_requirement", "effective_recovery_requirement",
    "recovery_requires_resource_readiness", "queued_step_attempts"]
