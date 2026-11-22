"""ResourceBinder：任务需求到执行绑定的唯一选择权威。

职责链是单向的：``ExecutionRequirement``（任务声明需要什么）→ 硬约束过滤
（谁合法）→ 确定性评分（谁更合适）→ 容量租约（谁当下可用）→ 冻结
``ExecutionBinding``。Planner、Coordinator、语义路由模型都不拥有资源
选择权；``routing_hints`` 只允许作为有界先验参与评分，绝无资格裁决权。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from typing import Awaitable, Callable
from uuid import uuid4

from support.async_tasks import await_settled
from support.work_timeouts import suspended_work_wait
from components.resource.application.resource_plane import ResourcePlane
from components.resource.scheduler.placement_policy import placement_preference
from contracts.resource import (
    NodeProfile,
    ExecutionBinding,
    ExecutionRequirement,
    ModelEndpointBinding,
    NodeHealthStatus,
    Placement,
    RemoteExecutionPolicy,
    RuntimeProfile,
    RuntimeKind,
    RuntimeSnapshot,
    ResourceLease,
)

from .leases import CapacityView, InMemoryLeaseCoordinator, LeaseCoordinator, LeaseRenewalFailedError
from .models import CandidateDecision, FilterReason, ReadyNodeSchedulingResult, RequirementReadiness, SchedulerUnavailable

#: 路由先验的最大评分权重；语义提示永远无法逆转硬约束排序一个数量级。
_ROUTING_HINT_WEIGHT = 0.05


class LeaseKeepAlive:
    """Renew allocated leases independently of the Attempt's event loop work."""

    def __init__(
        self, coordinator: LeaseCoordinator, lease: ResourceLease, *,
        interval: timedelta = timedelta(seconds=20), ttl: timedelta = timedelta(seconds=90),
        on_failure: Callable[[Exception], Awaitable[None] | None] | None = None,
        additional_leases: tuple[ResourceLease, ...] = (),
    ) -> None:
        if interval <= timedelta(0) or ttl <= interval:
            raise ValueError("lease keep-alive requires positive interval below ttl")
        self.coordinator = coordinator
        self.lease = lease
        self.additional_leases = additional_leases
        self.interval = interval
        self.ttl = ttl
        self.on_failure = on_failure
        self.failure: Exception | None = None
        self._task: asyncio.Task[None] | None = None
        self._stopped = Event()
        self._failed = asyncio.Event()

    def start(self) -> None:
        if self._task is None:
            loop = asyncio.get_running_loop()
            done = loop.create_future()

            def renew() -> None:
                try:
                    failure = self._renew_until_stopped()
                except Exception as exc:
                    failure = exc
                loop.call_soon_threadsafe(done.set_result, failure)

            # Binding persistence and Identity projection can block the loop.
            # The worker owns renewal from allocation until stop joins it.
            Thread(target=renew, name=f"lease-renewal:{self.lease.lease_id}", daemon=True).start()
            self._task = loop.create_task(self._observe_worker(done))

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            await await_settled(self._task)

    async def wait_failed(self) -> Exception:
        await self._failed.wait()
        assert self.failure is not None
        return self.failure

    async def _observe_worker(self, done: asyncio.Future[Exception | None]) -> None:
        failure = await done
        if failure is None:
            return
        self.failure = (failure if isinstance(failure, LeaseRenewalFailedError)
                        else LeaseRenewalFailedError(str(failure)))
        self._failed.set()
        if self.on_failure is not None:
            result = self.on_failure(self.failure)
            if isinstance(result, Awaitable):
                await result

    def _renew_until_stopped(self) -> Exception | None:
        interval = self.interval.total_seconds()
        delay = interval
        unavailable = None
        while not self._stopped.is_set():
            expiry = min(lease.expires_at for lease in (self.lease, *self.additional_leases))
            remaining = (expiry - datetime.now(timezone.utc)).total_seconds()
            if remaining <= 0:
                return unavailable or LeaseRenewalFailedError("execution lease expired before renewal")
            if self._stopped.wait(min(delay, remaining / 2)):
                break
            try:
                self._renew_leases()
            except SchedulerUnavailable as exc:
                unavailable = exc
                delay = min(1.0, interval)
            else:
                unavailable = None
                delay = interval
        return None

    def _renew_leases(self) -> None:
        for index, lease in enumerate((self.lease, *self.additional_leases)):
            renewed = self.coordinator.renew(
                lease_id=lease.lease_id, owner_id=lease.owner_id or "",
                version=lease.version, ttl=self.ttl,
            )
            # Keep any confirmed version even if a subsequent renewal fails.
            if index == 0:
                self.lease = renewed
            else:
                self.additional_leases = (*self.additional_leases[:index - 1], renewed,
                                          *self.additional_leases[index:])


def _non_empty_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def hard_constraint_reasons(
    profile: RuntimeProfile,
    snapshot: RuntimeSnapshot,
    *,
    healthy: bool,
    node_status: NodeHealthStatus | None,
    node: NodeProfile | None = None,
    requirement: ExecutionRequirement,
    check_capabilities: bool = True,
) -> list[FilterReason]:
    """按硬约束判定 Runtime 是否具备本次绑定资格；不产生任何状态变更。"""
    reasons: list[FilterReason] = []
    if profile.draining:
        reasons.append(FilterReason.DRAINING)
    if profile.kind is RuntimeKind.AGENT_INSTANCE:
        reasons.append(FilterReason.AGENT_INSTANCE_NOT_SCHEDULABLE)
    is_remote_runtime = profile.endpoint is not None and profile.endpoint.protocol != "local"
    if node is not None:
        if not node.enabled or node_status in {
            NodeHealthStatus.UNKNOWN, NodeHealthStatus.STALE,
            NodeHealthStatus.OFFLINE, NodeHealthStatus.SUSPICIOUS,
        }:
            reasons.append(FilterReason.NODE_UNHEALTHY)
        if requirement.min_cpu_cores is not None and node.compute.cpu_cores < requirement.min_cpu_cores:
            reasons.append(FilterReason.NODE_CPU_INSUFFICIENT)
        required_memory_mb = (requirement.min_memory_bytes or 0) / (1024 * 1024)
        if requirement.min_memory_bytes is not None and node.compute.memory_mb < required_memory_mb:
            reasons.append(FilterReason.NODE_MEMORY_INSUFFICIENT)
        if requirement.required_gpu_type is not None and node.compute.gpu_type != requirement.required_gpu_type:
            reasons.append(FilterReason.NODE_GPU_TYPE_MISMATCH)
        required_gpu_memory_mb = (requirement.min_gpu_memory_bytes or 0) / (1024 * 1024)
        if requirement.min_gpu_memory_bytes is not None and node.compute.gpu_memory_mb < required_gpu_memory_mb:
            reasons.append(FilterReason.NODE_GPU_MEMORY_INSUFFICIENT)
        if any(node.labels.get(key) != value for key, value in requirement.required_node_labels.items()):
            reasons.append(FilterReason.NODE_LABEL_MISMATCH)
        if requirement.required_data_region and node.data_region != requirement.required_data_region:
            reasons.append(FilterReason.NODE_DATA_REGION_MISMATCH)
        if requirement.allowed_owner_scopes and node.owner_scope not in requirement.allowed_owner_scopes:
            reasons.append(FilterReason.NODE_OWNER_SCOPE_MISMATCH)
        if (
            is_remote_runtime
            and node.remote_execution_policy is RemoteExecutionPolicy.DENY
        ):
            reasons.append(FilterReason.NODE_REMOTE_EXECUTION_DENIED)
        allowlist = node.metadata.get("remoteExecutionAllowlist", [])
        if (
            is_remote_runtime
            and node.remote_execution_policy is RemoteExecutionPolicy.ALLOWLIST_ONLY
            and profile.runtime_id not in allowlist
        ):
            reasons.append(FilterReason.NODE_REMOTE_EXECUTION_DENIED)
    if not profile.enabled:
        reasons.append(FilterReason.DISABLED)
    if not healthy:
        reasons.append(FilterReason.UNHEALTHY)
    if node is None and node_status is not None and node_status in {
        NodeHealthStatus.UNKNOWN, NodeHealthStatus.STALE, NodeHealthStatus.OFFLINE,
        NodeHealthStatus.SUSPICIOUS,
    }:
        reasons.append(FilterReason.NODE_UNHEALTHY)
    if check_capabilities and not set(requirement.required_capabilities).issubset(profile.capabilities):
        reasons.append(FilterReason.CAPABILITY_MISMATCH)
    if requirement.runtime_kinds and profile.kind not in requirement.runtime_kinds:
        reasons.append(FilterReason.RUNTIME_KIND_MISMATCH)
    if requirement.allowed_placements and profile.placement not in requirement.allowed_placements:
        reasons.append(FilterReason.PLACEMENT_MISMATCH)
    if requirement.min_trust is not None and profile.trust.rank < requirement.min_trust.rank:
        reasons.append(FilterReason.TRUST_INSUFFICIENT)
    if requirement.domain and profile.domains and requirement.domain not in profile.domains and "general" not in profile.domains:
        reasons.append(FilterReason.DOMAIN_MISMATCH)
    if not requirement.allow_remote_execution and is_remote_runtime:
        reasons.append(FilterReason.REMOTE_EXECUTION_DISABLED)
    if requirement.allowed_runtime_ids and profile.runtime_id not in requirement.allowed_runtime_ids:
        reasons.append(FilterReason.NOT_ALLOWED)
    if profile.runtime_id in requirement.excluded_runtime_ids:
        reasons.append(FilterReason.EXCLUDED)
    if any(profile.labels.get(key) != value for key, value in requirement.labels.items()):
        reasons.append(FilterReason.LABEL_MISMATCH)
    if requirement.data_zone and profile.data_zone != requirement.data_zone:
        reasons.append(FilterReason.DATA_ZONE_MISMATCH)
    if requirement.owner_scope and profile.owner_scope != requirement.owner_scope:
        reasons.append(FilterReason.OWNER_SCOPE_MISMATCH)
    if requirement.max_cost is not None and profile.cost_metadata.get("unit", 0.0) > requirement.max_cost:
        reasons.append(FilterReason.COST_EXCEEDED)
    if requirement.max_latency_ms is not None and (
        snapshot.latency_ms is None or snapshot.latency_ms > requirement.max_latency_ms
    ):
        reasons.append(FilterReason.LATENCY_EXCEEDED)
    return reasons


def _reason_details(reasons: list[FilterReason]) -> list[dict[str, str]]:
    """Compatibility projection for APIs that need explainable rejection data."""
    return [
        {
            "level": "node" if reason.value.startswith("NODE_") else "runtime",
            "code": reason.value,
            "message": reason.value.replace("_", " ").lower(),
        }
        for reason in reasons
    ]


def placement_score(
    profile: RuntimeProfile,
    snapshot: RuntimeSnapshot,
    *,
    reliability: float,
    latency_ms: float | None,
    requirement: ExecutionRequirement,
) -> tuple[float, dict[str, float]]:
    """计算可解释的确定性软分数；硬约束由 ``hard_constraint_reasons`` 负责。"""
    capacity = snapshot.available_slots / max(profile.capacity, 1)
    snapshot_penalty = 0.5 if snapshot.health_status.value in {"degraded", "unknown"} else 1.0
    latency = 1.0 if latency_ms is None else 1.0 / (1.0 + latency_ms / 1000.0)
    cost = 1.0 / (1.0 + profile.cost_metadata.get("unit", 0.0))
    preferred = 1.0 if requirement.preferences.get("preferredRuntimeId") == profile.runtime_id else 0.0
    routing_prior = _routing_hint_factor(profile, requirement.routing_hints)
    factors = {
        "reliability": reliability,
        "capacity": capacity,
        "idle": 1.0 - snapshot.utilization,
        "latency": latency,
        "cost": cost,
        "preference": preferred,
        "placementTier": placement_preference(profile.placement),
        "routingPrior": routing_prior,
    }
    score = (
        0.30 * factors["reliability"]
        + 0.17 * factors["capacity"]
        + 0.12 * factors["idle"]
        + 0.07 * factors["latency"]
        + 0.05 * factors["cost"]
        + 0.04 * factors["preference"]
        + 0.15 * factors["placementTier"]
        + _ROUTING_HINT_WEIGHT * factors["routingPrior"]
    )
    return round(score * snapshot_penalty, 9), {
        **{key: round(value, 9) for key, value in factors.items()},
        "snapshotPenalty": snapshot_penalty,
    }


def _routing_hint_factor(profile: RuntimeProfile, hints: dict) -> float:
    """把上游语义先验投影到 [0, 1]；未知提示一律忽略。"""
    if not isinstance(hints, dict):
        return 0.0
    preferred_placement = hints.get("preferredPlacement")
    preferred_kind = hints.get("preferredRuntimeKind")
    preferred_runtime = hints.get("preferredRuntimeId")
    if preferred_placement in {item.value for item in Placement}:
        if profile.placement.value == preferred_placement:
            return 1.0
    elif preferred_kind in {"execution_backend", "model_server", "tool_service"}:
        if profile.kind.value == preferred_kind:
            return 1.0
    elif _non_empty_string(preferred_runtime):
        return 1.0 if profile.runtime_id == preferred_runtime else 0.0
    return 0.0


class ResourceBinder:
    """从资源平面为 READY 步骤完成一次可审计的执行绑定。"""

    def __init__(
        self,
        plane: ResourcePlane,
        *,
        coordinator: LeaseCoordinator | None = None,
        lease_ttl: timedelta = timedelta(seconds=60),
    ) -> None:
        self.plane = plane
        self.coordinator = coordinator or InMemoryLeaseCoordinator()
        self.lease_ttl = lease_ttl
        self._capacity_waiters: dict[asyncio.Event, asyncio.AbstractEventLoop] = {}
        self.capacity_metrics: dict[str, int] = {
            "capacity_conflict_total": 0,
            "snapshot_stale_total": 0,
        }

    def _eligible_agents(self, profiles, requirement, *, host_id, now):
        preferred = str(requirement.preferences.get("agentRole") or "").strip().lower()
        eligible = []
        for candidate in profiles:
            profile = self.plane.runtime(candidate.runtime_id)
            if (profile.kind is not RuntimeKind.AGENT_INSTANCE or profile.agent_registration != candidate.agent_registration
                    or profile.host_runtime_id != host_id or not profile.enabled or profile.draining
                    or profile.runtime_id in requirement.excluded_runtime_ids
                    or not set(requirement.required_capabilities).issubset(profile.capabilities)
                    or (requirement.domain and profile.domains and requirement.domain not in profile.domains
                        and "general" not in profile.domains)
                    or not self.plane.health_monitor.health(profile.runtime_id, now=now).healthy):
                continue
            eligible.append(profile)
        eligible.sort(key=lambda item: (
            preferred not in {item.agent_registration.agent_id.lower(), (item.display_name or "").strip().lower()},
            -int(item.metadata.get("bindingPriority", 0)), item.runtime_id,
        ))
        return eligible

    def _has_binding_capacity(self, runtime_id, requirement, *, agent_candidates, now):
        """Check every resource needed by the binding, without reserving it."""
        if not self.capacity_view(runtime_id, now=now).has_local_capacity:
            return False
        if agent_candidates is None or runtime_id not in agent_candidates:
            return True
        return any(
            self.capacity_view(instance.runtime_id, now=now).has_local_capacity
            for instance in self._eligible_agents(
                agent_candidates[runtime_id], requirement, host_id=runtime_id, now=now,
            )
        )

    def evaluate(
        self,
        requirement: ExecutionRequirement,
        *,
        now: datetime | None = None,
        agent_candidates: dict[str, tuple[RuntimeProfile, ...]] | None = None,
    ) -> list[CandidateDecision]:
        """只读评估全部 Runtime 的资格与分数；不获取租约。"""
        current = now or datetime.now(timezone.utc)
        decisions: list[CandidateDecision] = []
        for profile in self.plane.runtimes():
            versioned = self.plane.runtime_snapshot(profile.runtime_id)
            health = self.plane.health_monitor.health(profile.runtime_id, now=current)
            node = self.plane.node(profile.node_id)
            node_status = self.plane.get_node_health(profile.node_id, now=current).status
            reasons = hard_constraint_reasons(
                profile,
                versioned.snapshot,
                healthy=health.healthy,
                node_status=node_status,
                node=node,
                requirement=requirement,
                check_capabilities=agent_candidates is None or profile.runtime_id not in agent_candidates,
            )
            # The current remote Step protocol carries no model route/quota.
            # Only locally callable instances can consume this injected model.
            if (requirement.model is not None and agent_candidates is not None
                    and profile.kind is RuntimeKind.EXECUTION_BACKEND and profile.runtime_id not in agent_candidates):
                reasons.append(FilterReason.MODEL_DEMAND_UNSUPPORTED_REMOTE)
            if agent_candidates is not None and profile.runtime_id in agent_candidates and not self._eligible_agents(
                agent_candidates[profile.runtime_id], requirement, host_id=profile.runtime_id, now=current,
            ):
                reasons.append(FilterReason.NO_ELIGIBLE_AGENT)
            if reasons:
                decisions.append(CandidateDecision(
                    resourceId=profile.runtime_id,
                    accepted=False,
                    reasons=reasons,
                    reasonDetails=_reason_details(reasons),
                ))
                continue
            score, _ = placement_score(
                profile,
                versioned.snapshot,
                reliability=health.reliability,
                latency_ms=health.latency_ms,
                requirement=requirement,
            )
            # 心跳健康是准入依据；陈旧快照只降权，不允许压过新鲜健康资源。
            if (current - versioned.snapshot.observed_at.astimezone(timezone.utc)) > timedelta(seconds=60):
                score = round(score * 0.5, 9)
            decisions.append(CandidateDecision(
                resourceId=profile.runtime_id,
                accepted=True,
                reasons=[],
                score=score,
            ))
        decisions.sort(key=lambda item: (not item.accepted, -(item.score or 0.0), item.resource_id))
        return decisions

    def assess(self, requirement: ExecutionRequirement, *, now: datetime | None = None,
               agent_candidates: dict[str, tuple[RuntimeProfile, ...]] | None = None) -> RequirementReadiness:
        """Inspect runtime, model and lease capacity through the existing authorities.

        Reading active slots may expire old leases, but never acquires a lease.
        This is a readiness hint: bind_ready must still perform atomic allocation.
        """
        current = now or datetime.now(timezone.utc)
        candidates = self.evaluate(requirement, now=current, agent_candidates=agent_candidates)
        eligible = [c for c in candidates if c.accepted]
        endpoints = (
            self.plane.model_candidates(
                requirement.model,
                owner_scope=requirement.owner_scope,
                now=current,
            )
            if requirement.model
            else []
        )
        runtime_versions = {c.resource_id: self.plane.runtime_snapshot(c.resource_id).version for c in candidates}
        node_ids = {self.plane.runtime(c.resource_id).node_id for c in candidates}
        node_versions = {node_id: self.plane.node_snapshot(node_id).version for node_id in node_ids}
        model_versions = {c.endpoint.endpoint_id: c.endpoint.version for c in endpoints}
        reason = None
        available = ()
        if not eligible:
            reason = "NO_ELIGIBLE_RESOURCE"
        elif requirement.model and not endpoints:
            reason = "NO_MODEL_ENDPOINT"
        else:
            try:
                available = tuple(
                    c.resource_id for c in eligible
                    if self._has_binding_capacity(c.resource_id, requirement,
                        agent_candidates=agent_candidates, now=current)
                )
                if not available:
                    reason = "NO_CAPACITY"
            except SchedulerUnavailable:
                reason = "COORDINATION_UNAVAILABLE"
        return RequirementReadiness(ready=reason is None, reason=reason, candidates=candidates,
            runtimeVersions=runtime_versions, nodeVersions=node_versions, modelEndpointVersions=model_versions,
            availableRuntimeIds=available)

    def capacity_view(self, runtime_id: str, *, now: datetime | None = None) -> CapacityView:
        """Return the declared capacity, Redis occupancy, and telemetry separately."""
        profile = self.plane.runtime(runtime_id)
        snapshot = self.plane.runtime_snapshot(runtime_id).snapshot
        current = now or datetime.now(timezone.utc)
        age = current - snapshot.observed_at.astimezone(timezone.utc)
        snapshot_state = (
            "UNKNOWN" if snapshot.health_status.value == "unknown"
            else "STALE" if age > timedelta(seconds=60) else "FRESH"
        )
        active_leases = self.coordinator.active_slots(runtime_id, now=current)
        view = CapacityView(
            static_capacity=profile.capacity,
            active_leases=active_leases,
            remote_available_slots=snapshot.available_slots,
            snapshot_state=snapshot_state,
        )
        if snapshot_state == "STALE":
            self.capacity_metrics["snapshot_stale_total"] += 1
        if (
            snapshot.available_slots is not None
            and snapshot.available_slots != max(0, profile.capacity - active_leases)
        ):
            self.capacity_metrics["capacity_conflict_total"] += 1
        return view

    def bind_ready(
        self,
        *,
        run_id: str,
        step_id: str,
        attempt_id: str,
        requirement: ExecutionRequirement,
        now: datetime | None = None,
        agent_candidates: dict[str, tuple[RuntimeProfile, ...]] | None = None,
        existing_binding: ExecutionBinding | None = None,
        fresh_reservation: bool = False,
    ) -> ReadyNodeSchedulingResult:
        """为 READY 步骤选择 Runtime、授予租约并冻结执行绑定。"""
        if existing_binding is not None and (
            existing_binding.run_id, existing_binding.step_id, existing_binding.attempt_id
        ) != (run_id, step_id, attempt_id):
            raise ValueError("existing binding belongs to another Attempt")
        current = now or datetime.now(timezone.utc)
        assessment = self.assess(requirement, now=current, agent_candidates=agent_candidates)
        evaluations = assessment.candidates
        model_binding = None
        if requirement.model is not None:
            if assessment.model_endpoint_versions:
                best = self.plane.model_endpoint(next(iter(assessment.model_endpoint_versions)))
                model_binding = ModelEndpointBinding(
                    endpointId=best.endpoint_id,
                    provider=best.provider,
                    model=best.model,
                    version=best.model_version,
                    quota=best.quota,
                )
        if assessment.reason in {"NO_MODEL_ENDPOINT", "NO_ELIGIBLE_RESOURCE"}:
            # 这些是永久性配置缺口；不能进入容量等待队列。
            return ReadyNodeSchedulingResult(
                status="rejected",
                candidates=evaluations,
                reason=assessment.reason,
            )
        choices = []
        for decision in evaluations:
            if not decision.accepted:
                continue
            instances = (self._eligible_agents(agent_candidates[decision.resource_id], requirement,
                         host_id=decision.resource_id, now=current)
                         if agent_candidates is not None and decision.resource_id in agent_candidates else [None])
            choices.extend((decision, instance) for instance in instances)
        if existing_binding is not None:
            choices = [(decision, instance) for decision, instance in choices
                       if decision.resource_id == existing_binding.resource_id and instance is not None
                       and instance.agent_registration == existing_binding.agent_registration]
            if not choices:
                return ReadyNodeSchedulingResult(status="rejected", candidates=evaluations, reason="PINNED_AGENT_UNAVAILABLE")
        for decision, instance in choices:
            profile = self.plane.runtime(decision.resource_id)
            if existing_binding is not None:
                self.assert_binding(existing_binding, now=current)
                return ReadyNodeSchedulingResult(status="allocated", binding=existing_binding,
                    lease=self.coordinator.get(existing_binding.lease_id, now=current),
                    agentLease=self.coordinator.get(existing_binding.agent_lease_id, now=current), candidates=evaluations)
            versioned = self.plane.runtime_snapshot(profile.runtime_id)
            lease_id = f"lease:{run_id}:{step_id}:{attempt_id}:{profile.runtime_id}"
            if fresh_reservation or instance is not None:
                # Provisional reservations are single-use. A compensated pair
                # must not reuse a released lease identity on the next poll.
                lease_id += ":" + uuid4().hex
            lease = self.coordinator.acquire(
                lease_id=lease_id,
                resource_id=profile.runtime_id,
                capacity=profile.capacity,
                run_id=run_id,
                step_id=step_id,
                attempt_id=attempt_id,
                slot_count=1,
                ttl=self.lease_ttl,
                now=current,
            )
            if lease is None:
                continue
            agent_lease = None
            allocated = False
            try:
                if instance is not None:
                    agent_lease = self.coordinator.acquire(
                        lease_id=f"{lease_id}:agent", resource_id=instance.runtime_id, capacity=instance.capacity,
                        run_id=run_id, step_id=step_id, attempt_id=attempt_id, slot_count=1,
                        ttl=self.lease_ttl, now=current,
                    )
                    if agent_lease is None or self.plane.runtime(instance.runtime_id) != instance:
                        continue
                confirmed = self.plane.runtime_snapshot(profile.runtime_id)
                if confirmed.version != versioned.version or self.plane.runtime(profile.runtime_id) != profile:
                    continue
                health = self.plane.health_monitor.health(profile.runtime_id, now=current)
                if not health.healthy:
                    continue
                confirmed_health = self.plane.get_node_health(profile.node_id, now=current)
                if confirmed_health.status in {NodeHealthStatus.UNKNOWN, NodeHealthStatus.STALE,
                                                NodeHealthStatus.OFFLINE, NodeHealthStatus.SUSPICIOUS}:
                    continue
                _, score_factors = placement_score(
                    profile,
                    confirmed.snapshot,
                    reliability=health.reliability,
                    latency_ms=health.latency_ms,
                    requirement=requirement,
                )
                binding = ExecutionBinding(
                    bindingId=f"binding:{run_id}:{step_id}:{attempt_id}",
                    runId=run_id,
                    stepId=step_id,
                    attemptId=attempt_id,
                    resourceId=profile.runtime_id,
                    runtimeKind=profile.kind,
                    nodeId=profile.node_id,
                    placement=profile.placement,
                    trust=profile.trust,
                    modelBinding=model_binding,
                    snapshotVersion=confirmed.version,
                    leaseId=lease.lease_id,
                    leaseVersion=lease.version,
                    agentRegistration=instance.agent_registration if instance is not None else None,
                    agentLeaseId=agent_lease.lease_id if agent_lease is not None else None,
                    agentLeaseVersion=agent_lease.version if agent_lease is not None else None,
                    metadata={
                        **({"modelDemand": requirement.model.model_dump(by_alias=True, mode="json")} if requirement.model is not None else {}),
                        "score": decision.score,
                        "deploymentTier": profile.placement.value,
                        "runtimeKind": profile.kind.value,
                        "placementReasons": [
                            f"placement={profile.placement.value}",
                            f"runtimeKind={profile.kind.value}",
                            f"trust={profile.trust.value}",
                            f"latencyMs={confirmed.snapshot.latency_ms}",
                        ],
                        "scoreFactors": score_factors,
                    },
                )
                result = ReadyNodeSchedulingResult(
                    status="allocated",
                    binding=binding,
                    lease=lease,
                    agentLease=agent_lease,
                    candidates=evaluations,
                )
                allocated = True
                return result
            finally:
                if not allocated:
                    try:
                        if agent_lease is not None:
                            self.coordinator.release(agent_lease.lease_id)
                    finally:
                        self.coordinator.release(lease.lease_id)
        return ReadyNodeSchedulingResult(
            status="queued",
            candidates=evaluations,
            reason="NO_CAPACITY",
        )

    async def wait_ready(
        self, *, run_id: str, step_id: str, attempt_id: str,
        requirement: ExecutionRequirement,
        agent_candidates: dict[str, tuple[RuntimeProfile, ...]]
        | Callable[[], dict[str, tuple[RuntimeProfile, ...]]] | None = None,
        existing_binding: ExecutionBinding | None = None,
        before_attempt: Callable[[], Awaitable[ReadyNodeSchedulingResult | None] | ReadyNodeSchedulingResult | None] | None = None,
        on_queued: Callable[[ReadyNodeSchedulingResult], Awaitable[None]] | None = None,
        timeout: float | None = None,
    ) -> ReadyNodeSchedulingResult:
        """Wait for lease contention or explicit caller readiness, retaining the binding authority.

        Local releases wake queued work immediately. A capped polling interval
        also observes remote releases, lease expiry and resource changes. There
        is no retry count; an optional caller-owned queue deadline returns the
        final queued decision. Cancellation owns no provisional reservation.
        """
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + max(0, timeout)
        changed = asyncio.Event()
        self._capacity_waiters[changed] = loop
        delay = .05
        announced_reason = None
        try:
            while True:
                changed.clear()  # Register before assessing, avoiding lost releases.
                # Health/authority refresh and queue publication are scheduler
                # work too. A remote health round-trip during contention must
                # not exhaust the waiting Agent's active execution budget.
                decision = None
                with suspended_work_wait():
                    if before_attempt is not None:
                        prepared = before_attempt()
                        decision = await prepared if isinstance(prepared, Awaitable) else prepared
                if decision is None:
                    decision = self.bind_ready(
                        run_id=run_id, step_id=step_id, attempt_id=attempt_id,
                        requirement=requirement, existing_binding=existing_binding,
                        agent_candidates=agent_candidates() if callable(agent_candidates) else agent_candidates,
                        fresh_reservation=True,
                    )
                    if decision.reason != "NO_CAPACITY":
                        return decision
                if decision.status != "queued":
                    return decision
                remaining = None if deadline is None else deadline - loop.time()
                if remaining is not None and remaining <= 0:
                    return decision
                if announced_reason != decision.reason and on_queued is not None:
                    with suspended_work_wait():
                        await on_queued(decision)
                    announced_reason = decision.reason
                with suspended_work_wait():
                    try:
                        await asyncio.wait_for(changed.wait(), min(delay, remaining) if remaining is not None else delay)
                    except TimeoutError:
                        pass
                delay = min(1.0, delay * 2)
        finally:
            self._capacity_waiters.pop(changed, None)

    def release(self, lease_id: str) -> bool:
        released = self.coordinator.release(lease_id)
        if released:
            for changed, loop in tuple(self._capacity_waiters.items()):
                if not loop.is_closed():
                    loop.call_soon_threadsafe(changed.set)
        return released

    def release_binding(self, binding: ExecutionBinding) -> bool:
        try:
            return self.release(binding.lease_id) if binding.lease_id else False
        finally:
            if binding.agent_lease_id:
                self.release(binding.agent_lease_id)

    def assert_binding(self, binding: ExecutionBinding, *, now: datetime | None = None) -> None:
        """Renewal versions may advance; resource/owner/Attempt identity may not."""
        current = now or datetime.now(timezone.utc)
        pairs = [(binding.lease_id, binding.resource_id)]
        if binding.agent_registration is not None:
            pairs.append((binding.agent_lease_id, binding.agent_registration.resource_id))
        for lease_id, resource_id in pairs:
            lease = self.coordinator.get(lease_id, now=current) if lease_id else None
            if (lease is None or lease.status != "active" or lease.expires_at <= current
                    or (lease.resource_id, lease.run_id, lease.step_id, lease.attempt_id, lease.owner_id)
                    != (resource_id, binding.run_id, binding.step_id, binding.attempt_id, binding.attempt_id)):
                raise LeaseRenewalFailedError("execution binding no longer owns its resource leases")

__all__ = ["LeaseKeepAlive", "ResourceBinder", "hard_constraint_reasons", "placement_score"]
