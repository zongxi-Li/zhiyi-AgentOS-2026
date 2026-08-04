"""跨部件合同的公共行为测试。"""

from datetime import datetime, timedelta, timezone
from enum import Enum

import pytest
from pydantic import ValidationError

from contracts import (
    MemoryRecord,
    MemoryType,
    ResourceLease,
    ResourceProfile,
    SchedulingDecision,
    stable_json_dumps,
)
from core.data_contracts import ContextContractError, validate_contract_payload


def test_resource_profile_requires_at_least_one_capability():
    """资源不能在没有能力声明时进入调度候选集。"""
    with pytest.raises(ValidationError, match="capabilities"):
        ResourceProfile(resourceId="worker-1", capabilities=[])


def test_memory_record_accepts_known_type_and_rejects_invalid_type():
    """记忆记录只接受稳定的枚举类型，优先级也有明确范围。"""
    record = MemoryRecord(
        memoryId="mem-1",
        memoryType=MemoryType.SEMANTIC,
        content={"fact": "稳定事实"},
        importance=0.8,
    )

    assert record.memory_type is MemoryType.SEMANTIC
    assert record.importance == 0.8

    with pytest.raises(ValidationError, match="memoryType"):
        MemoryRecord(memoryId="mem-2", memoryType="unknown", content={})
    with pytest.raises(ValidationError, match="importance"):
        MemoryRecord(
            memoryId="mem-3",
            memoryType="episodic",
            content={},
            importance=1.1,
        )


def test_resource_lease_expiry_must_follow_creation_time():
    """租约结束时间必须晚于创建时间，防止立即失效的分配。"""
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValidationError, match="expiresAt"):
        ResourceLease(
            leaseId="lease-1",
            resourceId="worker-1",
            createdAt=created_at,
            expiresAt=created_at,
        )

    lease = ResourceLease(
        leaseId="lease-2",
        resourceId="worker-1",
        createdAt=created_at,
        expiresAt=created_at + timedelta(minutes=5),
    )
    assert lease.expires_at > lease.created_at


def test_stable_json_dump_uses_aliases_and_deterministic_key_order():
    """合同序列化可用于跨部件签名，键顺序和别名必须稳定。"""
    profile = ResourceProfile(
        resourceId="worker-1",
        capabilities=["summarize"],
        labels={"zone": "east", "tier": "gold"},
    )

    assert stable_json_dumps(profile) == (
        '{"capabilities":["summarize"],"labels":{"tier":"gold","zone":"east"},'
        '"resourceId":"worker-1"}'
    )


def test_stable_json_dump_normalizes_sets_and_rejects_unknown_objects():
    """集合按规范化后的稳定键排序，任意对象不能被静默转为字符串。"""
    class SampleKind(str, Enum):
        FIRST = "first"

    payload = {
        "when": datetime(2026, 1, 1, 8, tzinfo=timezone(timedelta(hours=8))),
        "values": {"z", "a"},
        "kind": SampleKind.FIRST,
        "pair": (2, 1),
    }

    assert stable_json_dumps(payload) == (
        '{"kind":"first","pair":[2,1],"values":["a","z"],'
        '"when":"2026-01-01T00:00:00+00:00"}'
    )
    with pytest.raises(TypeError, match="not JSON-normalizable"):
        stable_json_dumps({"invalid": object()})


def test_resource_lease_requires_timezone_aware_utc_ordered_times():
    """租约拒绝朴素时间，并将带时区时间统一转换为 UTC。"""
    with pytest.raises(ValidationError, match="timezone-aware"):
        ResourceLease(
            leaseId="lease-naive",
            resourceId="worker-1",
            createdAt=datetime(2026, 1, 1),
            expiresAt=datetime(2026, 1, 1, 0, 1),
        )

    lease = ResourceLease(
        leaseId="lease-zone",
        resourceId="worker-1",
        createdAt=datetime(2026, 1, 1, 8, tzinfo=timezone(timedelta(hours=8))),
        expiresAt=datetime(2026, 1, 1, 8, 5, tzinfo=timezone(timedelta(hours=8))),
    )
    assert lease.created_at == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert lease.expires_at == datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)


def test_scheduling_decision_enforces_allocation_field_combinations():
    """调度决定不能产生无资源的分配或在非分配状态泄漏租约。"""
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    lease = ResourceLease(
        leaseId="lease-3",
        resourceId="worker-1",
        createdAt=created_at,
        expiresAt=created_at + timedelta(minutes=5),
    )

    with pytest.raises(ValidationError, match="allocated"):
        SchedulingDecision(requestId="request-1", decision="allocated")
    with pytest.raises(ValidationError, match="resourceId"):
        SchedulingDecision(requestId="request-2", decision="allocated", resourceId="worker-2", lease=lease)
    with pytest.raises(ValidationError, match="must not"):
        SchedulingDecision(requestId="request-3", decision="queued", resourceId="worker-1")

    decision = SchedulingDecision(
        requestId="request-4", decision="allocated", resourceId="worker-1", lease=lease
    )
    assert decision.lease is lease


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        ({"type": "string", "minLength": 2}, "x"),
        ({"type": "string", "maxLength": 1}, "xy"),
        ({"type": "array", "minItems": 2}, ["x"]),
        ({"type": "array", "maxItems": 1}, ["x", "y"]),
        ({"type": "unknown"}, "x"),
    ],
)
def test_forced_fallback_rejects_declared_bounds_and_unknown_types(monkeypatch, schema, payload):
    """无依赖回退模式必须执行长度边界，且不能忽略未知 JSON 类型。"""
    import core.data_contracts as data_contracts

    monkeypatch.setattr(data_contracts, "_HAS_JSONSCHEMA", False)
    with pytest.raises(ContextContractError):
        validate_contract_payload(payload, schema, step_id="step-1", direction="input")
