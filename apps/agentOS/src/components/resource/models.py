"""资源部件内部使用的只读投影模型。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from contracts.resource import AgentSnapshot, NodeHealthStatus, NodeSnapshot, ResourceProfile, ResourceSnapshot


@dataclass(frozen=True)
class VersionedResourceSnapshot:
    """附带单调递增版本号的资源快照。

    合同层的 ``ResourceSnapshot`` 描述一次观测值，而版本属于本地存储语义。
    将两者分开可避免把持久化实现细节泄漏到跨部件合同中。
    """

    snapshot: ResourceSnapshot
    version: int


@dataclass(frozen=True)
class ResourceHealth:
    """由心跳和执行观测推导出的资源健康投影。"""

    resource_id: str
    healthy: bool
    reliability: float
    latency_ms: float | None
    last_heartbeat: datetime | None


@dataclass(frozen=True)
class ResourceCandidate:
    """提供给调度器的候选资源及其当下观测依据。"""

    profile: ResourceProfile
    snapshot: VersionedResourceSnapshot
    health: ResourceHealth
    score: float


@dataclass(frozen=True)
class VersionedNodeSnapshot:
    """附带单调递增版本号的节点快照。"""

    snapshot: NodeSnapshot
    version: int


@dataclass(frozen=True)
class VersionedAgentSnapshot:
    """附带单调递增版本号的 Agent 快照。"""

    snapshot: AgentSnapshot
    version: int


@dataclass(frozen=True)
class NodeHealth:
    """节点健康投影：分级状态 + 最后心跳 + 连续失败次数。"""

    node_id: str
    status: NodeHealthStatus
    last_heartbeat: datetime | None
    consecutive_failures: int
