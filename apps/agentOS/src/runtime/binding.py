"""READY-before runtime resource eligibility preparation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from components.resource.agent_directory import AgentDirectory
from components.scheduler.service import SchedulerService
from components.scheduler.two_layer_service import TwoLayerSchedulerService
from contracts.authority import RuntimeResourceId
from contracts.compiled_acg import BindingManifest
from contracts.resource import BindingRequirement, DeploymentTier
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
        resource_directory,
        resource_service,
        resource_execution_adapters: Mapping[str, object],
    ) -> None:
        self.agent_registry = agent_registry
        self.resource_directory = resource_directory
        self.resource_service = resource_service
        self.resource_execution_adapters = resource_execution_adapters

    def prepare(
        self,
        *,
        run: RuntimeRunRecord,
        workflow: WorkflowDefinition,
        scope: RunExecutionScope,
        binding_manifest: BindingManifest,
        agent_service,
        scheduler_service: SchedulerService | TwoLayerSchedulerService,
        node_service,
    ) -> None:
        """Register candidates and persist requirements without selecting one."""

        directory = AgentDirectory(agent_service)
        scoped_agent_ids = set(scope.agent_ids)
        local_resource_ids: list[RuntimeResourceId] = []
        for agent in self.agent_registry.all():
            agent_id = self.agent_registry.agent_id(agent)
            if scoped_agent_ids and agent_id not in scoped_agent_ids:
                continue
            self.resource_directory.register_agent(agent.profile)
            directory.register_agent(agent.profile)
            local_resource_ids.append(RuntimeResourceId(str(agent_id)))

        if isinstance(scheduler_service, TwoLayerSchedulerService):
            scheduler_service.agent_service = agent_service
            scheduler_service.node_service = node_service

        candidate_ids = [
            *local_resource_ids,
            *(
                RuntimeResourceId(item)
                for item in sorted(self.known_remote_resource_ids())
            ),
        ]
        requirements: dict[str, dict[str, object]] = {}
        model_bindings: dict[str, dict[str, Any] | None] = {}
        for step in run.steps:
            rule = binding_manifest.for_step(step.step_id)
            required_capabilities = list(rule.required_capabilities)
            if not required_capabilities:
                raise ValueError(
                    f"BindingManifest has no capability requirement: {step.step_id}"
                )
            allowed_resource_ids = list(dict.fromkeys(candidate_ids))
            allowed_manifest_ids = set(rule.allowed_resource_ids)
            if allowed_manifest_ids:
                allowed_resource_ids = [
                    item for item in allowed_resource_ids
                    if item in allowed_manifest_ids
                ]
            requirement = BindingRequirement(
                requiredCapabilities=required_capabilities,
                domain=rule.domain or workflow.domain,
                resourceTypes=[],
                allowedResourceIds=allowed_resource_ids,
                preferences={},
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
        agents_by_step: dict[str, list] = {}
        for binding in blueprint.resource_plan.bindings:
            agents_by_step.setdefault(binding.step_id, []).append(binding)
        for step in blueprint.step_nodes():
            agents = agents_by_step.get(step.node_id, [])
            if len(agents) != 1:
                missing.append(step.node_id)
                continue
            agent = agents[0]
            try:
                self.agent_registry.resolve(
                    domain=domain,
                    agent_name=agent.planned_agent_id,
                    capability=step.capability,
                    allowed_agent_ids=(scope.agent_ids if scope is not None else None),
                )
            except KeyError:
                remote_match = any(
                    self._remote_resource_matches_step(
                        resource_id, step, domain=domain
                    )
                    for resource_id in self.known_remote_resource_ids()
                )
                if not remote_match:
                    missing.append(agent.planned_agent_id or step.node_id)
        if missing:
            raise ValueError(
                "ACG references unregistered Agents: "
                + ", ".join(sorted(set(missing)))
            )

    def known_remote_resource_ids(self) -> set[str]:
        resource_ids = set(self.resource_execution_adapters)
        for profile in self.resource_service.profiles():
            if profile.deployment_tier is not DeploymentTier.LOCAL:
                resource_ids.add(profile.resource_id)
        return resource_ids

    def _remote_resource_matches_step(
        self, resource_id: str, step, *, domain: str
    ) -> bool:
        try:
            profile = self.resource_service.profile(resource_id)
            health = self.resource_service.health_monitor.health(resource_id)
        except KeyError:
            return False
        return (
            profile.enabled
            and health.healthy
            and (
                not profile.domains
                or domain in profile.domains
                or "general" in profile.domains
            )
            and (not step.capability or step.capability in profile.capabilities)
        )


__all__ = ["RuntimeBindingService"]
