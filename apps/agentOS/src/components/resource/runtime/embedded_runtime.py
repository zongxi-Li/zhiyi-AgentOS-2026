"""进程内逻辑 Agent 运行时：作为 EXECUTION_BACKEND 注册进资源平面。

宿主提供聚合容量和环境；具体实例由既有 Binder 在 READY 边界选择。
聚合事实来自当前进程的全部本地实例，不受某个 Run 的授权范围影响。
"""

from __future__ import annotations

from types import SimpleNamespace

from contracts.resource import (
    HealthStatus,
    Placement,
    RuntimeKind,
    RuntimeProfile,
    RuntimeSnapshot,
    TrustLevel,
)

from .local_runtime import DEFAULT_LOCAL_RUNTIME_NODE_ID
from ..application.resource_plane import ResourcePlane

EMBEDDED_AGENTS_RUNTIME_ID = "runtime:embedded-agents"
EMBEDDED_AGENTS_BASE_CAPABILITY = "exec.agents"


def register_embedded_agents_runtime(
    plane: ResourcePlane,
    agents,
) -> RuntimeProfile:
    """把当前进程内 Agent 注册表投影为一个 Device 执行后端。

    能力集是全部可见逻辑 Agent 能力的并集，容量是各 Agent 声明容量之和；
    每个逻辑 Agent 同时以 ``agent:<role>`` 能力暴露，与 BindingManifest
    对单 Agent 步骤的角色锚点（``agent:<planned_agent_id>``）对接。注册表
    变化时重复调用即可完成同步（引导路径允许更新）。
    """
    # 基础能力标识让调度器能够选择整个嵌入式执行后端。
    capabilities: set[str] = {EMBEDDED_AGENTS_BASE_CAPABILITY}
    capacity = 0
    for agent in agents:
        profile = getattr(agent, "profile", None)
        if profile is None or not getattr(profile, "enabled", True):
            continue
        capabilities.update(
            str(item).strip().lower()
            for item in (profile.capabilities or [])
            if str(item).strip()
        )
        agent_id = str(
            getattr(profile, "agent_id", "") or getattr(profile, "agent_name", "") or ""
        ).strip()
        if agent_id:
            capabilities.add(f"agent:{agent_id.lower()}")
        # 容量至少为一，兼容未声明容量的旧 Agent 画像。
        capacity += max(1, int(getattr(profile, "capacity", 1) or 1))
    profile = RuntimeProfile(
        runtimeId=EMBEDDED_AGENTS_RUNTIME_ID,
        kind=RuntimeKind.EXECUTION_BACKEND,
        displayName="进程内 Agent 运行时",
        nodeId=DEFAULT_LOCAL_RUNTIME_NODE_ID,
        placement=Placement.DEVICE,
        capabilities=sorted(capabilities),
        trust=TrustLevel.HOST_TRUSTED,
        capacity=max(1, capacity),
        enabled=capacity > 0,
        metadata={"managedBy": "bootstrap", "runtime": "embedded-agents"},
    )
    plane.ensure_node(
        DEFAULT_LOCAL_RUNTIME_NODE_ID,
        placement=Placement.DEVICE,
        display_name="本机设备节点",
        trust=TrustLevel.HOST_TRUSTED,
    )
    # 进程存活即设备节点存活：每次注册同步刷新节点心跳。
    plane.heartbeat_node(DEFAULT_LOCAL_RUNTIME_NODE_ID)
    snapshot = RuntimeSnapshot(
        runtimeId=EMBEDDED_AGENTS_RUNTIME_ID,
        availableSlots=profile.capacity,
        utilization=0.0,
        healthStatus=HealthStatus.UNKNOWN,
    )
    plane.register_runtime(profile, snapshot)
    return profile


def refresh_embedded_agents_runtime(plane: ResourcePlane, registry) -> RuntimeProfile:
    """Project global local-instance facts, preserving instance administration."""
    agents = []
    for registration in registry.registrations():
        if not registry.is_enabled(registration.ref.agent_id):
            continue
        profile = registration.implementation.profile
        try:
            resource = plane.runtime(registration.ref.resource_id)
        except KeyError:
            capacity = profile.capacity
        else:
            if resource.host_runtime_id != EMBEDDED_AGENTS_RUNTIME_ID:
                continue
            if not resource.enabled or resource.draining or resource.metadata.get("outcomeUnknown"):
                continue
            capacity = resource.capacity
        agents.append(SimpleNamespace(profile=profile.model_copy(update={"capacity": capacity})))
    return register_embedded_agents_runtime(plane, agents)


__all__ = [
    "EMBEDDED_AGENTS_BASE_CAPABILITY",
    "EMBEDDED_AGENTS_RUNTIME_ID",
    "register_embedded_agents_runtime",
    "refresh_embedded_agents_runtime",
]
