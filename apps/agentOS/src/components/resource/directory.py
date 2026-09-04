"""Compatibility facade over the authoritative :class:`ResourceService`."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from contracts.capability import CapabilityKind, CapabilityManifest
from contracts.resource import ResourceHealthStatus, ResourceProfile, ResourceSnapshot, ResourceType
from service.agents.base import AgentProfile

from .service import ResourceService


class ResourceConflictError(ValueError):
    """The same resource identity was registered with a different profile."""


class ResourceNotFoundError(KeyError):
    """No authoritative resource satisfies the requested projection."""


@dataclass(frozen=True)
class AgentResource:
    """Legacy Agent projection retained for runtime compatibility."""

    agent_id: str
    agent_name: str
    domain: str
    capabilities: tuple[str, ...]
    version: str
    priority: int
    enabled: bool
    resource_id: str | None = None
    labels: tuple[tuple[str, str], ...] = ()


class ResourceDirectory:
    """Legacy lookup API delegating every state read/write to ResourceService."""

    def __init__(self, resource_service: ResourceService | None = None) -> None:
        self.resource_service = resource_service or ResourceService()

    def register_agent(self, profile: AgentProfile) -> AgentResource:
        agent_id = str(profile.agent_id or profile.agent_name).strip()
        agent_name = str(profile.agent_name).strip()
        domain = str(profile.domain).strip().lower()
        if not agent_id or not agent_name or not domain:
            raise ValueError("agentId, agentName and domain are required")
        extra = dict(profile.model_extra or {})
        labels = extra.get("labels", {})
        if not isinstance(labels, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in labels.items()
        ):
            raise ValueError("agent labels must be a string mapping")
        declared_capabilities = {
            item.strip().lower() for item in profile.capabilities if item.strip()
        }
        capabilities = tuple(sorted(declared_capabilities))
        resource = AgentResource(
            agent_id=agent_id,
            agent_name=agent_name,
            domain=domain,
            capabilities=capabilities,
            version=str(profile.plugin_version or "v1"),
            priority=int(profile.binding_priority),
            enabled=bool(profile.enabled),
            resource_id=(str(extra["resourceId"]) if extra.get("resourceId") else None),
            labels=tuple(sorted(labels.items())),
        )
        unified = ResourceProfile(
            resourceId=agent_id,
            resourceType=ResourceType.AGENT,
            capabilities=sorted(declared_capabilities | {f"agent:{agent_name.lower()}"}),
            domains=[domain],
            labels=labels,
            capacity=max(1, int(profile.capacity)),
            enabled=resource.enabled,
            metadata={
                "directoryKind": "agent",
                "agent": {
                    "agent_id": resource.agent_id,
                    "agent_name": resource.agent_name,
                    "domain": resource.domain,
                    "capabilities": list(resource.capabilities),
                    "version": resource.version,
                    "priority": resource.priority,
                    "enabled": resource.enabled,
                    "resource_id": resource.resource_id,
                    "labels": [list(item) for item in resource.labels],
                },
            },
        )
        self._register_profile(unified)
        return resource

    def register_capability(self, manifest: CapabilityManifest) -> CapabilityManifest:
        type_by_kind = {
            CapabilityKind.AGENT: ResourceType.AGENT,
            CapabilityKind.MODEL: ResourceType.MODEL,
            CapabilityKind.SKILL: ResourceType.SKILL,
            CapabilityKind.TOOL: ResourceType.TOOL,
        }
        resource_type = type_by_kind[manifest.kind]
        if manifest.kind is CapabilityKind.MODEL and bool(manifest.metadata.get("embedding")):
            resource_type = ResourceType.EMBEDDING
        unified = ResourceProfile(
            resourceId=manifest.capability_id,
            resourceType=resource_type,
            capabilities=sorted(set(manifest.capabilities) | {manifest.capability_id}),
            metadata={
                "directoryKind": "capability",
                "manifest": manifest.model_dump(by_alias=True, mode="json"),
            },
        )
        self._register_profile(unified)
        return manifest

    def _register_profile(self, profile: ResourceProfile) -> None:
        try:
            existing = self.resource_service.profile(profile.resource_id)
        except KeyError:
            self.resource_service.register(
                profile,
                ResourceSnapshot(
                    resourceId=profile.resource_id,
                    availableSlots=profile.capacity,
                    utilization=0.0,
                    healthStatus=ResourceHealthStatus.ONLINE,
                ),
            )
        else:
            if existing != profile:
                same_identity = existing.model_copy(update={"capacity": profile.capacity}) == profile
                if same_identity:
                    self.resource_service.update_capacity(
                        profile.resource_id,
                        profile.capacity,
                        expected_capacity=existing.capacity,
                    )
                else:
                    raise ResourceConflictError(
                        f"resource conflicts with existing identity: {profile.resource_id}"
                    )
        self.resource_service.heartbeat(profile.resource_id)

    def set_health(self, resource_id: str, *, healthy: bool) -> None:
        try:
            self.resource_service.set_health(resource_id, healthy=healthy)
        except KeyError as exc:
            raise ResourceNotFoundError(f"resource is not registered: {resource_id}") from exc

    def resolve_capability(
        self, capability_id: str, *, kind: CapabilityKind | None = None
    ) -> CapabilityManifest:
        try:
            profile = self.resource_service.profile(capability_id)
            health = self.resource_service.health_monitor.health(capability_id)
        except KeyError as exc:
            raise ResourceNotFoundError(
                f"capability resource is not available: {capability_id}"
            ) from exc
        payload = profile.metadata.get("manifest")
        if not health.healthy or not isinstance(payload, dict):
            raise ResourceNotFoundError(f"capability resource is not available: {capability_id}")
        manifest = CapabilityManifest.model_validate(payload)
        if kind is not None and manifest.kind is not kind:
            raise ResourceNotFoundError(
                f"capability resource kind does not match: {capability_id}"
            )
        return manifest

    def resolve_agent(
        self,
        *,
        domain: str,
        agent_name: str | None = None,
        capability: str | None = None,
        allowed_agent_ids: Iterable[str] | None = None,
    ) -> AgentResource:
        normalized_domain = (domain or "").strip().lower()
        candidates = self._agent_candidates(
            domain=normalized_domain,
            allowed_agent_ids=allowed_agent_ids,
        )
        normalized_name = (agent_name or "").strip().lower()
        if normalized_name:
            named = [item for item in candidates if item.agent_name.lower() == normalized_name]
            if named:
                return self._select(named, normalized_domain)
        normalized_capability = (capability or "").strip().lower()
        if normalized_capability:
            capable = [item for item in candidates if normalized_capability in item.capabilities]
            if capable:
                return self._select(capable, normalized_domain)
        raise ResourceNotFoundError(
            f"agent resource not found: domain={domain}, agentName={agent_name}, capability={capability}"
        )

    def resolve_agent_candidates(
        self,
        *,
        domain: str,
        capability: str,
        allowed_agent_ids: Iterable[str] | None = None,
        excluded_agent_ids: Iterable[str] = (),
    ) -> tuple[AgentResource, ...]:
        normalized_domain = (domain or "").strip().lower()
        normalized_capability = (capability or "").strip().lower()
        candidates = self._agent_candidates(
            domain=normalized_domain,
            allowed_agent_ids=allowed_agent_ids,
            excluded_agent_ids=excluded_agent_ids,
        )
        return tuple(
            sorted(
                (item for item in candidates if normalized_capability in item.capabilities),
                key=lambda item: (
                    0 if item.domain == normalized_domain else 1,
                    -item.priority,
                    item.agent_id,
                ),
            )
        )

    def _agent_candidates(
        self,
        *,
        domain: str,
        allowed_agent_ids: Iterable[str] | None,
        excluded_agent_ids: Iterable[str] = (),
    ) -> list[AgentResource]:
        allowed = {str(item) for item in allowed_agent_ids} if allowed_agent_ids is not None else None
        excluded = {str(item) for item in excluded_agent_ids}
        candidates: list[AgentResource] = []
        for profile in self.resource_service.profiles():
            payload = profile.metadata.get("agent")
            if profile.resource_type is not ResourceType.AGENT or not isinstance(payload, dict):
                continue
            item = AgentResource(**payload)
            health = self.resource_service.health_monitor.health(profile.resource_id)
            if (
                item.enabled
                and health.healthy
                and item.agent_id not in excluded
                and (allowed is None or item.agent_id in allowed)
                and item.domain in (domain, "general")
            ):
                candidates.append(item)
        return candidates

    @staticmethod
    def _select(candidates: list[AgentResource], requested_domain: str) -> AgentResource:
        return sorted(
            candidates,
            key=lambda item: (
                0 if item.domain == requested_domain else 1,
                -item.priority,
                item.agent_id,
            ),
        )[0]


__all__ = ["AgentResource", "ResourceConflictError", "ResourceDirectory", "ResourceNotFoundError"]
