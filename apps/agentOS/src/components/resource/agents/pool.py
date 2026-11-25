"""Registered executor facts and lifecycle, without Step selection or leases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from contracts.agents import AgentDefinition, AgentRegistrationRef
from contracts.resource import NodeProfile, RuntimeKind, RuntimeProfile
from components.resource.application.resource_plane import ResourcePlane
from components.resource.domain.models import RuntimeHealth

from contracts.agent_runtime import AgentNotFound, AgentRegistration, AgentRegistryPort, BaseAgent


@dataclass(frozen=True)
class RegisteredAgentInstance:
    """A view, not contracts.task.AgentInstance (a task execution statistic)."""

    ref: AgentRegistrationRef
    definition: AgentDefinition
    resource: RuntimeProfile
    host: RuntimeProfile
    host_node: NodeProfile
    host_health: RuntimeHealth
    health: RuntimeHealth
    logical_enabled: bool

    @property
    def capacity(self) -> int:
        return self.resource.capacity

    @property
    def draining(self) -> bool:
        return self.resource.draining


class AgentPool:
    """Join implementation registrations with ResourcePlane-owned instance facts.

    There is no busy/available ledger, scheduler, or instance factory here.
    Binder consumes these facts to reserve an instance and its host together.
    """

    def __init__(self, *, registry: AgentRegistryPort, resource_plane: ResourcePlane, host_runtime_id: str) -> None:
        self.registry = registry
        self.resource_plane = resource_plane
        self.host_runtime_id = host_runtime_id

    def synchronize(self) -> None:
        for registration in self.registry.registrations():
            try:
                existing = self.resource_plane.runtime(registration.ref.resource_id)
            except KeyError:
                existing = None
            if existing is not None:
                if existing.agent_registration != registration.ref:
                    raise ValueError("Agent instance resource does not match its registration")
                continue
            self.resource_plane.register_agent_instance(
                registration.ref, registration.definition,
                host_runtime_id=self.host_runtime_id,
                capacity=registration.implementation.profile.capacity,
                enabled=registration.implementation.profile.enabled,
            )

    def prune_previous_registries(self, coordinator) -> tuple[str, ...]:
        """Delete idle local instance facts from earlier process epochs only."""
        current = self.registry.registrations()
        if not current:
            return ()  # No verified current epoch: never guess which facts are stale.
        epochs = {item.ref.registry_id for item in current}
        removed = []
        for profile in self.resource_plane.runtimes():
            ref = profile.agent_registration
            if (profile.kind is not RuntimeKind.AGENT_INSTANCE or ref is None
                    or ref.registry_id in epochs or profile.host_runtime_id != self.host_runtime_id
                    or profile.metadata.get("managedBy") != "agent-pool"):
                continue
            if profile.metadata.get("outcomeUnknown") or coordinator.active_slots(profile.runtime_id) > 0:
                continue
            self.resource_plane.set_agent_instance_state(
                ref, expected_version=profile.version, enabled=False, draining=True,
            )
            self.resource_plane.unregister_agent_instance(ref)
            removed.append(profile.runtime_id)
        return tuple(removed)

    def register_instance(self, agent: BaseAgent, *, instance_id: str, expected_generation: int | None = None,
                          host_runtime_id: str | None = None, enabled: bool | None = None) -> AgentRegistrationRef:
        if enabled is not None and type(enabled) is not bool:
            raise ValueError("Agent instance enabled must be boolean")
        host_id = host_runtime_id or self.host_runtime_id
        if self.resource_plane.runtime(host_id).kind is not RuntimeKind.EXECUTION_BACKEND:
            raise ValueError("Agent instance requires an execution backend host")

        def publish(registration: AgentRegistration) -> None:
            self.resource_plane.register_agent_instance(
                registration.ref, registration.definition, host_runtime_id=host_id,
                capacity=agent.profile.capacity,
                enabled=(agent.profile.enabled and self.registry.is_enabled(registration.ref.agent_id)
                         and enabled is not False),
            )

        return self.registry.register_instance(
            agent, instance_id=instance_id, expected_generation=expected_generation,
            publish_facts=publish,
        )

    def describe(self, ref: AgentRegistrationRef, *, now: datetime | None = None) -> RegisteredAgentInstance:
        registration = self.registry.get_registration(ref)
        resource = self.resource_plane.runtime(ref.resource_id)
        if resource.agent_registration != ref:
            raise ValueError("Agent instance resource does not match its registration")
        host = self.resource_plane.runtime(resource.host_runtime_id)
        return RegisteredAgentInstance(
            ref=ref, definition=registration.definition, resource=resource,
            host=host, host_node=self.resource_plane.node(host.node_id),
            host_health=self.resource_plane.health_monitor.health(host.runtime_id, now=now),
            health=self.resource_plane.health_monitor.health(ref.resource_id, now=now),
            logical_enabled=self.registry.is_enabled(ref.agent_id),
        )

    def instances(self, *, now: datetime | None = None) -> tuple[RegisteredAgentInstance, ...]:
        return tuple(self.describe(item.ref, now=now) for item in self.registry.registrations())

    def local_candidates(self, allowed_agent_ids: Iterable[str] | None = None) -> dict[str, tuple[RuntimeProfile, ...]]:
        """Project locally callable, current registrations for the existing Binder."""
        self.synchronize()
        allowed = set(allowed_agent_ids) if allowed_agent_ids is not None else None
        grouped: dict[str, list[RuntimeProfile]] = {self.host_runtime_id: []}
        for registration in self.registry.registrations():
            resource = self.resource_plane.runtime(registration.ref.resource_id)
            host = self.resource_plane.runtime(resource.host_runtime_id)
            if host.endpoint is not None and host.endpoint.protocol != "local":
                continue  # A local Python object is not a remote Worker registration.
            candidates = grouped.setdefault(host.runtime_id, [])
            if allowed is not None and registration.ref.agent_id not in allowed:
                continue
            if not self.registry.is_enabled(registration.ref.agent_id):
                continue
            try:
                if self.registry.registration_for(registration.implementation) != registration.ref:
                    continue
            except AgentNotFound:
                continue
            self.resource_plane.heartbeat_agent_instance(registration.ref)
            candidates.append(resource)
        return {host_id: tuple(items) for host_id, items in grouped.items()}

    def heartbeat(self, ref: AgentRegistrationRef) -> RuntimeHealth:
        self.registry.get_registration(ref)
        return self.resource_plane.heartbeat_agent_instance(ref)

    def update(self, ref: AgentRegistrationRef, *, expected_version: int,
               enabled: bool | None = None, draining: bool | None = None,
               capacity: int | None = None) -> RegisteredAgentInstance:
        self.registry.get_registration(ref)
        self.resource_plane.set_agent_instance_state(
            ref, expected_version=expected_version, enabled=enabled,
            draining=draining, capacity=capacity,
        )
        return self.describe(ref)

    def unregister(self, ref: AgentRegistrationRef, *, expected_version: int) -> None:
        self.registry.get_registration(ref)
        self.resource_plane.set_agent_instance_state(
            ref, expected_version=expected_version, enabled=False, draining=True,
        )
        self.registry.unregister_instance(
            ref, withdraw_facts=lambda: self.resource_plane.unregister_agent_instance(ref),
        )

    def scoped(self, allowed_agent_ids: Iterable[str]) -> ScopedAgentPool:
        return ScopedAgentPool(self, frozenset(allowed_agent_ids))


class ScopedAgentPool:
    """Read-only scope view; knowing an instance ID never broadens visibility."""

    def __init__(self, pool: AgentPool, allowed_agent_ids: frozenset[str]) -> None:
        self._pool = pool
        self._allowed_agent_ids = allowed_agent_ids

    def instances(self, *, now: datetime | None = None) -> tuple[RegisteredAgentInstance, ...]:
        return tuple(self._pool.describe(item.ref, now=now)
                     for item in self._pool.registry.registrations(allowed_agent_ids=self._allowed_agent_ids))

    def describe(self, ref: AgentRegistrationRef, *, now: datetime | None = None) -> RegisteredAgentInstance:
        self._pool.registry.get_registration(ref, allowed_agent_ids=self._allowed_agent_ids)
        return self._pool.describe(ref, now=now)

    def scoped(self, allowed_agent_ids: Iterable[str]) -> ScopedAgentPool:
        return ScopedAgentPool(self._pool, self._allowed_agent_ids.intersection(allowed_agent_ids))


__all__ = ["AgentPool", "RegisteredAgentInstance", "ScopedAgentPool"]
