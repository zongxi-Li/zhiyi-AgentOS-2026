"""面向调度器的资源登记、观测和候选查询服务。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from contracts.resource import (
    BindingRequirement,
    DeploymentTier,
    ResourceHealthStatus,
    ResourceProfile,
    ResourceSnapshot,
)

from .algorithms import health_score, is_resource_available
from .health import ResourceHealthMonitor
from .models import ResourceCandidate, ResourceHealth, VersionedResourceSnapshot
from .registry import ResourceRegistry
from .store import InMemoryResourceStore, ResourceStore


class ResourceService:
    """以单个协调入口向调度器暴露可立即分配的资源候选。"""

    def __init__(
        self,
        store: ResourceStore | None = None,
        health_monitor: ResourceHealthMonitor | None = None,
        *,
        heartbeat_timeout: timedelta = timedelta(seconds=60),
    ) -> None:
        self.store = store or InMemoryResourceStore()
        self.registry = ResourceRegistry(self.store)
        self.health_monitor = health_monitor or ResourceHealthMonitor(
            heartbeat_timeout=heartbeat_timeout
        )

    def register(self, profile: ResourceProfile, snapshot: ResourceSnapshot) -> VersionedResourceSnapshot:
        """登记一个可调度资源及其首个负载快照。"""
        return self.store.register(profile, snapshot)

    register_resource = register

    def update_snapshot(
        self, snapshot: ResourceSnapshot, *, expected_version: int | None = None
    ) -> VersionedResourceSnapshot:
        """更新动态负载观测；版本冲突交给存储层显式报告。"""
        return self.store.update_snapshot(snapshot, expected_version=expected_version)

    def update_capacity(
        self, resource_id: str, capacity: int, *, expected_capacity: int
    ) -> VersionedResourceSnapshot:
        """以 CAS 同步已登记资源的声明容量和动态空闲槽位。"""
        return self.store.update_capacity(
            resource_id,
            capacity,
            expected_capacity=expected_capacity,
        )

    def snapshot(self, resource_id: str) -> VersionedResourceSnapshot:
        """读取调度决策所需的最新版本快照。"""
        return self.store.get_snapshot(resource_id)

    def profile(self, resource_id: str) -> ResourceProfile:
        """Read the authoritative static profile."""
        return self.store.get_profile(resource_id)

    def profiles(self) -> list[ResourceProfile]:
        """List authoritative profiles in stable order."""
        return self.store.list_profiles()

    def heartbeat(
        self,
        resource_id: str,
        *,
        received_at: datetime | None = None,
        source: Literal["local", "external"] = "local",
    ) -> ResourceHealth:
        """记录已登记资源的存活信号，远程资源必须由外部节点主动上报。"""
        profile = self.registry.get(resource_id)
        if profile.deployment_tier is not DeploymentTier.LOCAL and source != "external":
            raise ValueError("remote resource heartbeat must come from an external heartbeat")
        return self.health_monitor.heartbeat(resource_id, received_at=received_at)

    def observe(
        self,
        resource_id: str,
        *,
        success: bool,
        latency_ms: float,
        observed_at: datetime | None = None,
    ) -> ResourceHealth:
        """记录执行结果，供后续调度在可靠性和时延上作出更好选择。"""
        self.registry.get(resource_id)
        return self.health_monitor.observe(
            resource_id,
            success=success,
            latency_ms=latency_ms,
            observed_at=observed_at,
        )

    def observe_remote(
        self,
        resource_id: str,
        *,
        available_slots: int,
        utilization: float,
        latency_ms: float | None = None,
        observed_at: datetime | None = None,
    ) -> ResourceHealth:
        """接收远程资源的一次完整观测，并同步快照与存活信号。"""
        profile = self.registry.get(resource_id)
        if profile.deployment_tier is DeploymentTier.LOCAL:
            raise ValueError("remote observation requires a non-local resource")
        current = self.store.get_snapshot(resource_id)
        timestamp = observed_at or datetime.now().astimezone()
        updated = ResourceSnapshot(
            resourceId=resource_id,
            observedAt=timestamp,
            availableSlots=available_slots,
            utilization=utilization,
            healthStatus=ResourceHealthStatus.ONLINE,
            latencyMs=latency_ms,
        )
        self.store.update_snapshot(updated, expected_version=current.version)
        if latency_ms is None:
            return self.heartbeat(resource_id, received_at=timestamp, source="external")
        return self.health_monitor.observe(
            resource_id,
            success=True,
            latency_ms=latency_ms,
            observed_at=timestamp,
        )

    def set_health(self, resource_id: str, *, healthy: bool) -> ResourceHealth:
        """Record a compatibility adapter's explicit health observation."""
        self.registry.get(resource_id)
        return self.health_monitor.set_health(resource_id, healthy=healthy)

    def candidates(
        self,
        required_capabilities: list[str] | tuple[str, ...] | set[str],
        *,
        labels: dict[str, str] | None = None,
        now: datetime | None = None,
    ) -> list[ResourceCandidate]:
        """返回具备所需能力、健康且仍有槽位的稳定排序候选集。"""
        candidates: list[ResourceCandidate] = []
        for profile in self.registry.all():
            versioned = self.store.get_snapshot(profile.resource_id)
            health = self.health_monitor.health(profile.resource_id, now=now)
            if not is_resource_available(
                profile, versioned.snapshot, health, required_capabilities, labels
            ):
                continue
            candidates.append(
                ResourceCandidate(
                    profile=profile,
                    snapshot=versioned,
                    health=health,
                    score=health_score(health, versioned.snapshot.utilization),
                )
            )
        return sorted(candidates, key=lambda candidate: (-candidate.score, candidate.profile.resource_id))

    get_candidates = candidates

    def find_candidates(
        self, requirement: BindingRequirement, *, now: datetime | None = None
    ) -> list[ResourceCandidate]:
        """Resolve a frozen requirement without creating a concrete binding."""
        allowed = set(requirement.allowed_resource_ids)
        excluded = set(requirement.excluded_resource_ids)
        selected = self.candidates(
            requirement.required_capabilities,
            labels=requirement.labels,
            now=now,
        )
        return [
            candidate
            for candidate in selected
            if (not allowed or candidate.profile.resource_id in allowed)
            and candidate.profile.resource_id not in excluded
            and (not requirement.resource_types or candidate.profile.resource_type in requirement.resource_types)
            and (requirement.domain is None or not candidate.profile.domains or requirement.domain in candidate.profile.domains or "general" in candidate.profile.domains)
            and (requirement.data_zone is None or candidate.profile.data_zone == requirement.data_zone)
            and (requirement.owner_scope is None or candidate.profile.owner_scope == requirement.owner_scope)
            and (
                requirement.max_cost is None
                or candidate.profile.cost_metadata.get("unit", 0.0) <= requirement.max_cost
            )
        ]
