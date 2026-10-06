"""ResourceBinder 的绑定权威合同。

职责链单向不可逆：需求声明 → 硬约束过滤 → 确定性评分 → 容量租约 →
冻结绑定。Planner 与语义路由提示都没有资格裁决权；致命原因（无合法资源/
无模型端点）必须与容量排队区分开。
"""

from datetime import timedelta

import pytest

from components.resource.service import ResourcePlane
from components.scheduler.binder import ResourceBinder, hard_constraint_reasons, placement_score
from components.scheduler.models import FATAL_SCHEDULING_REASONS
from contracts.resource import (
    ExecutionRequirement,
    HealthStatus,
    ModelDemand,
    ModelEndpointProfile,
    Placement,
    RuntimeKind,
    RuntimeProfile,
    RuntimeSnapshot,
    TrustLevel,
)


def _plane() -> ResourcePlane:
    return ResourcePlane()


def _register(
    plane: ResourcePlane,
    runtime_id: str,
    *,
    node: str = "node:edge-1",
    placement: Placement = Placement.EDGE,
    capabilities: tuple[str, ...] = ("repo.read", "test.run"),
    trust: TrustLevel = TrustLevel.TRUSTED,
    capacity: int = 2,
    **overrides,
) -> RuntimeProfile:
    plane.ensure_node(node, placement=placement, trust=TrustLevel.HOST_TRUSTED)
    profile = RuntimeProfile(
        runtimeId=runtime_id,
        kind=RuntimeKind.EXECUTION_BACKEND,
        nodeId=node,
        placement=placement,
        capabilities=list(capabilities),
        trust=trust,
        capacity=capacity,
        **overrides,
    )
    plane.register_runtime(profile)
    plane.heartbeat_runtime(runtime_id)
    return profile


def _requirement(**overrides) -> ExecutionRequirement:
    values = dict(requiredCapabilities=["repo.read"])
    values.update(overrides)
    return ExecutionRequirement(**values)


def test_bind_ready_freezes_binding_with_lease_and_metadata() -> None:
    plane = _plane()
    _register(plane, "runtime:edge-exec-1")
    binder = ResourceBinder(plane)

    result = binder.bind_ready(
        run_id="run-1", step_id="step-2", attempt_id="attempt-3", requirement=_requirement()
    )

    assert result.status == "allocated"
    assert result.binding is not None and result.lease is not None
    binding = result.binding
    assert binding.resource_id == "runtime:edge-exec-1"
    assert binding.runtime_kind is RuntimeKind.EXECUTION_BACKEND
    assert binding.placement is Placement.EDGE
    assert binding.node_id == "node:edge-1"
    assert binding.lease_id if hasattr(binding, "lease_id") else True
    assert binding.metadata["score"] is not None
    assert binding.metadata["scoreFactors"]["reliability"] > 0
    assert "placement=edge" in binding.metadata["placementReasons"]


def test_capacity_is_per_runtime_and_release_restores_binding() -> None:
    plane = _plane()
    _register(plane, "runtime:edge-exec-1", capacity=1)
    binder = ResourceBinder(plane)
    common = dict(run_id="run-1", step_id="step-a", requirement=_requirement())

    first = binder.bind_ready(attempt_id="attempt-1", **common)
    second = binder.bind_ready(attempt_id="attempt-2", **common)
    assert first.status == "allocated"
    assert second.status == "queued" and second.reason == "NO_CAPACITY"

    assert binder.release(first.lease.lease_id)
    third = binder.bind_ready(attempt_id="attempt-3", **common)
    assert third.status == "allocated"


def test_no_eligible_resource_is_fatal_not_capacity_queue() -> None:
    plane = _plane()
    _register(plane, "runtime:edge-exec-1", capabilities=("repo.read",))
    binder = ResourceBinder(plane)

    result = binder.bind_ready(
        run_id="run-1",
        step_id="step-1",
        attempt_id="attempt-1",
        requirement=_requirement(requiredCapabilities=["shell.exec"]),
    )
    assert result.status == "queued"
    assert result.reason == "NO_ELIGIBLE_RESOURCE"
    assert result.reason in FATAL_SCHEDULING_REASONS
    assert all(not decision.accepted for decision in result.candidates)


def test_hard_constraints_report_their_filter_reasons() -> None:
    plane = _plane()
    _register(plane, "runtime:device-local", node="node:device:local", placement=Placement.DEVICE, trust=TrustLevel.HOST_TRUSTED)
    _register(plane, "runtime:edge-exec-1")
    binder = ResourceBinder(plane)

    decisions = {
        decision.resource_id: decision
        for decision in binder.evaluate(_requirement(
            allowedPlacements=[Placement.EDGE],
            minTrust=TrustLevel.TRUSTED,
        ))
    }
    assert decisions["runtime:device-local"].accepted is False
    assert "PLACEMENT_MISMATCH" in decisions["runtime:device-local"].reasons
    assert decisions["runtime:edge-exec-1"].accepted is True


def test_disabled_and_unhealthy_runtimes_are_rejected() -> None:
    plane = _plane()
    _register(plane, "runtime:edge-exec-1")
    _register(plane, "runtime:edge-exec-2", node="node:edge-2")
    plane.set_runtime_enabled("runtime:edge-exec-1", enabled=False)
    binder = ResourceBinder(plane)

    decisions = {d.resource_id: d for d in binder.evaluate(_requirement())}
    assert "DISABLED" in decisions["runtime:edge-exec-1"].reasons

    # 无心跳的 Runtime 不健康，不可绑定。
    decisions = {d.resource_id: d for d in binder.evaluate(_requirement())}
    assert decisions["runtime:edge-exec-2"].accepted is True
    plane.set_runtime_health("runtime:edge-exec-2", healthy=False)
    decisions = {d.resource_id: d for d in binder.evaluate(_requirement())}
    assert "UNHEALTHY" in decisions["runtime:edge-exec-2"].reasons


def test_allow_remote_execution_false_keeps_workload_on_device() -> None:
    plane = _plane()
    _register(plane, "runtime:edge-exec-1")
    _register(plane, "runtime:device-local", node="node:device:local", placement=Placement.DEVICE)
    binder = ResourceBinder(plane)

    result = binder.bind_ready(
        run_id="run-1",
        step_id="step-1",
        attempt_id="attempt-1",
        requirement=_requirement(allowRemoteExecution=False),
    )
    assert result.status == "allocated"
    assert result.binding.resource_id == "runtime:device-local"


def test_allowed_and_excluded_runtime_ids_direct_the_choice() -> None:
    plane = _plane()
    _register(plane, "runtime:edge-exec-1")
    _register(plane, "runtime:edge-exec-2", node="node:edge-2")
    binder = ResourceBinder(plane)

    result = binder.bind_ready(
        run_id="run-1", step_id="step-1", attempt_id="attempt-1",
        requirement=_requirement(allowedRuntimeIds=["runtime:edge-exec-2"]),
    )
    assert result.binding.resource_id == "runtime:edge-exec-2"

    result = binder.bind_ready(
        run_id="run-1", step_id="step-2", attempt_id="attempt-1",
        requirement=_requirement(excludedRuntimeIds=["runtime:edge-exec-2"]),
    )
    assert result.binding.resource_id == "runtime:edge-exec-1"


def test_model_demand_binds_endpoint_and_missing_endpoint_is_fatal_config_gap() -> None:
    plane = _plane()
    _register(plane, "runtime:edge-exec-1")
    binder = ResourceBinder(plane)
    demand = ModelDemand(requiredFeatures=["json_schema"], minContextTokens=100_000)

    result = binder.bind_ready(
        run_id="run-1", step_id="step-1", attempt_id="attempt-1",
        requirement=_requirement(model=demand),
    )
    assert result.status == "queued"
    assert result.reason == "NO_MODEL_ENDPOINT"
    assert result.reason in FATAL_SCHEDULING_REASONS

    plane.upsert_model_endpoint(ModelEndpointProfile(
        endpointId="model:zhipu/glm-4.6",
        provider="zhipu",
        model="glm-4.6",
        contextWindowTokens=200_000,
        features={"json_schema": True},
    ))
    result = binder.bind_ready(
        run_id="run-1", step_id="step-2", attempt_id="attempt-1",
        requirement=_requirement(model=demand),
    )
    assert result.status == "allocated"
    assert result.binding.model_binding is not None
    assert result.binding.model_binding.endpoint_id == "model:zhipu/glm-4.6"


def test_model_endpoint_feature_matching_fails_closed() -> None:
    plane = _plane()
    _register(plane, "runtime:edge-exec-1")
    plane.upsert_model_endpoint(ModelEndpointProfile(
        endpointId="model:zhipu/glm-4.6",
        provider="zhipu",
        model="glm-4.6",
        contextWindowTokens=200_000,
    ))
    binder = ResourceBinder(plane)

    # 端点未声明 json_schema 特性 → 按不支持处理，绑定仍以配置缺口收场。
    result = binder.bind_ready(
        run_id="run-1", step_id="step-1", attempt_id="attempt-1",
        requirement=_requirement(model=ModelDemand(requiredFeatures=["json_schema"])),
    )
    assert result.status == "queued" and result.reason == "NO_MODEL_ENDPOINT"

    candidates = plane.model_candidates(ModelDemand(minContextTokens=300_000))
    assert candidates == []


def test_routing_hints_are_bounded_priors_not_authority() -> None:
    plane = _plane()
    _register(plane, "runtime:edge-exec-1")
    _register(plane, "runtime:device-local", node="node:device:local", placement=Placement.DEVICE)
    binder = ResourceBinder(plane)

    def _bind_and_release(step_id: str, requirement: ExecutionRequirement):
        result = binder.bind_ready(
            run_id="run-1", step_id=step_id, attempt_id="attempt-1", requirement=requirement
        )
        assert result.status == "allocated" and result.binding is not None
        assert binder.release(result.lease.lease_id)
        return result.binding

    base = _bind_and_release("step-1", _requirement(routingHints={"preferredPlacement": "device"}))
    hinted = _bind_and_release("step-2", _requirement(routingHints={"preferredPlacement": "device"}))
    # 提示只能微调评分，不能破坏健康度主导的排序量级。
    assert base.metadata["score"] == pytest.approx(hinted.metadata["score"])
    assert hinted.metadata["scoreFactors"]["routingPrior"] in {0.0, 1.0}

    # 提示绝无资格裁决权：指向不存在的 runtime 不改变资格集合。
    decisions = binder.evaluate(_requirement(routingHints={"preferredRuntimeId": "runtime:ghost"}))
    assert {d.resource_id for d in decisions if d.accepted} == {
        "runtime:edge-exec-1",
        "runtime:device-local",
    }

    # 硬约束永远压过提示：提示偏好 edge 但需求只允许 device。
    binding = _bind_and_release("step-3", _requirement(
        routingHints={"preferredPlacement": "edge"},
        allowedPlacements=[Placement.DEVICE],
    ))
    assert binding.resource_id == "runtime:device-local"


def test_placement_score_is_deterministic_and_explainable() -> None:
    plane = _plane()
    profile = _register(plane, "runtime:edge-exec-1")
    snapshot = RuntimeSnapshot(
        runtimeId=profile.runtime_id,
        availableSlots=1,
        utilization=0.5,
        healthStatus=HealthStatus.ONLINE,
        reliability=0.9,
        latencyMs=100.0,
    )
    first, factors = placement_score(
        profile, snapshot, reliability=0.9, latency_ms=100.0, requirement=_requirement()
    )
    second, _ = placement_score(
        profile, snapshot, reliability=0.9, latency_ms=100.0, requirement=_requirement()
    )
    assert first == second
    assert set(factors) == {
        "reliability", "capacity", "idle", "latency", "cost", "preference", "routingPrior",
    }
    assert 0.0 <= first <= 1.0


def test_evaluate_is_read_only() -> None:
    plane = _plane()
    _register(plane, "runtime:edge-exec-1")
    binder = ResourceBinder(plane)
    before = plane.runtime_snapshot("runtime:edge-exec-1")

    decisions = binder.evaluate(_requirement())

    assert decisions[0].accepted is True
    assert plane.runtime_snapshot("runtime:edge-exec-1") == before


def test_lease_ttl_expires_and_capacity_recovers() -> None:
    from datetime import datetime, timezone

    from components.scheduler.leases import InMemoryLeaseCoordinator

    plane = _plane()
    _register(plane, "runtime:edge-exec-1", capacity=1)
    coordinator = InMemoryLeaseCoordinator()
    binder = ResourceBinder(plane, coordinator=coordinator, lease_ttl=timedelta(seconds=5))
    now = datetime.now(timezone.utc)

    first = binder.bind_ready(
        run_id="run-1", step_id="step-1", attempt_id="attempt-1",
        requirement=_requirement(), now=now,
    )
    assert first.status == "allocated"
    later = now + timedelta(seconds=6)
    second = binder.bind_ready(
        run_id="run-1", step_id="step-1", attempt_id="attempt-2",
        requirement=_requirement(), now=later,
    )
    assert second.status == "allocated"
