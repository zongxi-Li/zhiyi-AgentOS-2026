"""跨部件合同的公共行为测试。"""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from contracts import (
    MemoryRecord,
    MemoryType,
    ResourceLease,
    ResourceProfile,
    stable_json_dumps,
)


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
