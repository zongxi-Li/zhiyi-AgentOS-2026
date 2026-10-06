"""READY-before runtime resource eligibility preparation.

职责边界：把编译期 ``BindingManifest``（任务声明需要什么）冻结为每个步骤
的 ``ExecutionRequirement``，并保证嵌入式 Agent 运行时投影进入资源平面。
本服务绝不选择具体资源——选择权威在 ``ResourceBinder``。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from components.resource.embedded_runtime import register_embedded_agents_runtime
from components.resource.service import ResourcePlane
from contracts.authority import RuntimeResourceId
from contracts.compiled_acg import BindingManifest
from contracts.resource import ExecutionRequirement, RuntimeKind
from contracts.workflow import (
    RunExecutionScope,
    RuntimeRunRecord,
    WorkflowDefinition,
)
from service.agents import AgentRegistry
from support.acg.schema import RuntimeBlueprintSpec


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
        非权威偏好（agentRole），由执行器在嵌入式后端内解析角色。
        """
        scoped_agent_ids = set(scope.agent_ids) if scope.agent_ids else None
        visible_agents = [
            agent for agent in self.agent_registry.all()
            if scoped_agent_ids is None
            or self.agent_registry.agent_id(agent) in scoped_agent_ids
        ]
        register_embedded_agents_runtime(self.resource_plane, visible_agents)

        requirements: dict[str, dict[str, object]] = {}
        model_bindings: dict[str, dict[str, Any] | None] = {}
        for step in run.steps:
            rule = binding_manifest.for_step(step.step_id)
            required_capabilities = list(rule.required_capabilities)
            if not required_capabilities:
                raise ValueError(
                    f"BindingManifest has no capability requirement: {step.step_id}"
                )
            role_hint = str(rule.agent_node_ids[0]) if rule.agent_node_ids else None
            requirement = ExecutionRequirement(
                requiredCapabilities=required_capabilities,
                runtimeKinds=[RuntimeKind.EXECUTION_BACKEND],
                domain=rule.domain or workflow.domain,
                preferences=({"agentRole": role_hint} if role_hint else {}),
                policyMetadata={
                    "source": "compiled-binding-manifest",
                    "stepId": step.step_id,
                    "agentNodeIds": list(rule.agent_node_ids),
                    "maxConcurrency": rule.max_concurrency,
                },
            )
            requirements[step.step_id] = requirement.model_dump(
                by_alias=True, mode="json"
            )
            model_bindings[step.step_id] = None

        run.execution_state["resourceBindings"] = {}
        run.execution_state.pop("nodeAgentBindings", None)
        run.execution_state["bindingRequirements"] = requirements
        run.execution_state["modelBindings"] = model_bindings

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


__all__ = ["RuntimeBindingService"]
