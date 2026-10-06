"""ResourceBinder：任务需求到执行绑定的唯一选择权威。

职责链是单向的：``ExecutionRequirement``（任务声明需要什么）→ 硬约束过滤
（谁合法）→ 确定性评分（谁更合适）→ 容量租约（谁当下可用）→ 冻结
``ExecutionBinding``。Planner、Coordinator、语义路由模型都不拥有资源
选择权；``routing_hints`` 只允许作为有界先验参与评分，绝无资格裁决权。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from components.resource.models import RuntimeCandidate, RuntimeHealth
from components.resource.node_health import NodeHealthMonitor
from components.resource.service import ResourcePlane
from contracts.resource import (
    ExecutionBinding,
    ExecutionRequirement,
    ModelEndpointBinding,
    NodeHealthStatus,
    Placement,
    RuntimeProfile,
    RuntimeSnapshot,
    TrustLevel,
)

from .leases import InMemoryLeaseCoordinator, LeaseCoordinator
from .models import CandidateDecision, FilterReason, ReadyNodeSchedulingResult, RequirementReadiness, SchedulerUnavailable

#: 路由先验的最大评分权重；语义提示永远无法逆转硬约束排序一个数量级。
_ROUTING_HINT_WEIGHT = 0.05


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
    requirement: ExecutionRequirement,
) -> list[FilterReason]:
    """按硬约束判定 Runtime 是否具备本次绑定资格；不产生任何状态变更。"""
    reasons: list[FilterReason] = []
    if not profile.enabled:
        reasons.append(FilterReason.DISABLED)
    if not healthy:
        reasons.append(FilterReason.UNHEALTHY)
    if node_status is not None and node_status in {NodeHealthStatus.STALE, NodeHealthStatus.OFFLINE}:
        reasons.append(FilterReason.NODE_UNHEALTHY)
    if not set(requirement.required_capabilities).issubset(profile.capabilities):
        reasons.append(FilterReason.CAPABILITY_MISMATCH)
    if requirement.runtime_kinds and profile.kind not in requirement.runtime_kinds:
        reasons.append(FilterReason.RUNTIME_KIND_MISMATCH)
    if requirement.allowed_placements and profile.placement not in requirement.allowed_placements:
        reasons.append(FilterReason.PLACEMENT_MISMATCH)
    if requirement.min_trust is not None and profile.trust.rank < requirement.min_trust.rank:
        reasons.append(FilterReason.TRUST_INSUFFICIENT)
    if requirement.domain and profile.domains and requirement.domain not in profile.domains and "general" not in profile.domains:
        reasons.append(FilterReason.DOMAIN_MISMATCH)
    if not requirement.allow_remote_execution and profile.placement is not Placement.DEVICE:
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
    if snapshot.available_slots < 1:
        reasons.append(FilterReason.NO_CAPACITY)
    if requirement.max_cost is not None and profile.cost_metadata.get("unit", 0.0) > requirement.max_cost:
        reasons.append(FilterReason.COST_EXCEEDED)
    if requirement.max_latency_ms is not None and (
        snapshot.latency_ms is None or snapshot.latency_ms > requirement.max_latency_ms
    ):
        reasons.append(FilterReason.LATENCY_EXCEEDED)
    return reasons


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
        "routingPrior": routing_prior,
    }
    score = (
        0.35 * factors["reliability"]
        + 0.20 * factors["capacity"]
        + 0.15 * factors["idle"]
        + 0.10 * factors["latency"]
        + 0.05 * factors["cost"]
        + 0.05 * factors["preference"]
        + _ROUTING_HINT_WEIGHT * factors["routingPrior"]
    )
    return round(score, 9), {key: round(value, 9) for key, value in factors.items()}


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

    def evaluate(
        self,
        requirement: ExecutionRequirement,
        *,
        now: datetime | None = None,
    ) -> list[CandidateDecision]:
        """只读评估全部 Runtime 的资格与分数；不获取租约。"""
        current = now or datetime.now(timezone.utc)
        decisions: list[CandidateDecision] = []
        for profile in self.plane.runtimes():
            versioned = self.plane.runtime_snapshot(profile.runtime_id)
            health = self.plane.health_monitor.health(profile.runtime_id, now=current)
            node_status = self._host_node_status(profile, now=current)
            reasons = hard_constraint_reasons(
                profile,
                versioned.snapshot,
                healthy=health.healthy,
                node_status=node_status,
                requirement=requirement,
            )
            if reasons:
                decisions.append(CandidateDecision(
                    resourceId=profile.runtime_id,
                    accepted=False,
                    reasons=reasons,
                ))
                continue
            score, _ = placement_score(
                profile,
                versioned.snapshot,
                reliability=health.reliability,
                latency_ms=health.latency_ms,
                requirement=requirement,
            )
            decisions.append(CandidateDecision(
                resourceId=profile.runtime_id,
                accepted=True,
                reasons=[],
                score=score,
            ))
        decisions.sort(key=lambda item: (not item.accepted, -(item.score or 0.0), item.resource_id))
        return decisions

    def assess(self, requirement: ExecutionRequirement, *, now: datetime | None = None) -> RequirementReadiness:
        """Inspect runtime, model and lease capacity through the existing authorities.

        Reading active slots may expire old leases, but never acquires a lease.
        This is a readiness hint: bind_ready must still perform atomic allocation.
        """
        current = now or datetime.now(timezone.utc)
        candidates = self.evaluate(requirement, now=current)
        eligible = [c for c in candidates if not set(c.reasons) - {FilterReason.NO_CAPACITY}]
        endpoints = self.plane.model_candidates(requirement.model, now=current) if requirement.model else []
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
                available = tuple(c.resource_id for c in eligible if c.accepted
                    and self.coordinator.active_slots(c.resource_id, now=current)
                    < self.plane.runtime(c.resource_id).capacity)
                if not available:
                    reason = "NO_CAPACITY"
            except SchedulerUnavailable:
                reason = "COORDINATION_UNAVAILABLE"
        return RequirementReadiness(ready=reason is None, reason=reason, candidates=candidates,
            runtimeVersions=runtime_versions, nodeVersions=node_versions, modelEndpointVersions=model_versions,
            availableRuntimeIds=available)

    def bind_ready(
        self,
        *,
        run_id: str,
        step_id: str,
        attempt_id: str,
        requirement: ExecutionRequirement,
        now: datetime | None = None,
    ) -> ReadyNodeSchedulingResult:
        """为 READY 步骤选择 Runtime、授予租约并冻结执行绑定。"""
        current = now or datetime.now(timezone.utc)
        assessment = self.assess(requirement, now=current)
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
                )
        if assessment.reason in {"NO_MODEL_ENDPOINT", "NO_ELIGIBLE_RESOURCE"}:
            # 有可执行后端但模型端点缺失是配置缺口，不是容量问题。
            return ReadyNodeSchedulingResult(
                status="queued",
                candidates=evaluations,
                reason=assessment.reason,
            )
        for decision in evaluations:
            if not decision.accepted:
                continue
            profile = self.plane.runtime(decision.resource_id)
            versioned = self.plane.runtime_snapshot(profile.runtime_id)
            lease_id = f"lease:{run_id}:{step_id}:{attempt_id}:{profile.runtime_id}"
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
            confirmed = self.plane.runtime_snapshot(profile.runtime_id)
            if confirmed.version != versioned.version:
                self.coordinator.release(lease.lease_id)
                continue
            health = self.plane.health_monitor.health(profile.runtime_id, now=current)
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
                metadata={
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
            return ReadyNodeSchedulingResult(
                status="allocated",
                binding=binding,
                lease=lease,
                candidates=evaluations,
            )
        return ReadyNodeSchedulingResult(
            status="queued",
            candidates=evaluations,
            reason="NO_CAPACITY",
        )

    def release(self, lease_id: str) -> bool:
        return self.coordinator.release(lease_id)

    def _host_node_status(self, profile: RuntimeProfile, *, now: datetime) -> NodeHealthStatus | None:
        monitor: NodeHealthMonitor = self.plane.node_health_monitor
        if not isinstance(monitor, NodeHealthMonitor):
            return None
        try:
            return monitor.health(profile.node_id, now=now).status
        except Exception:
            return None


__all__ = ["ResourceBinder", "hard_constraint_reasons", "placement_score"]
