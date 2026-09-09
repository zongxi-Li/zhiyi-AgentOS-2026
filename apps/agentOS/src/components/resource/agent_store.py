"""Agent 注册表的存储实现（协议 + 进程内存）。"""

from __future__ import annotations

from threading import RLock
from typing import Protocol

from contracts.resource import AgentProfile, AgentSnapshot

from .models import VersionedAgentSnapshot
from .store import StaleResourceObservation, VersionConflict


class AgentStore(Protocol):
    """Agent 注册表依赖的最小存储边界，便于替换存储介质。"""

    def register(self, profile: AgentProfile, snapshot: AgentSnapshot) -> VersionedAgentSnapshot:
        """登记匹配的 Agent 画像与首份快照；重复登记抛出 ``ValueError``。"""
        ...

    def get_profile(self, agent_id: str) -> AgentProfile:
        """读取 Agent 画像副本；未知标识抛出 ``KeyError``。"""
        ...

    def get_snapshot(self, agent_id: str) -> VersionedAgentSnapshot:
        """读取当前版本快照副本；未知标识抛出 ``KeyError``。"""
        ...

    def list_profiles(self) -> list[AgentProfile]:
        """返回稳定顺序的 Agent 画像副本列表。"""
        ...

    def update_snapshot(
        self, snapshot: AgentSnapshot, *, expected_version: int | None = None
    ) -> VersionedAgentSnapshot:
        """按可选期望版本原子更新快照；过期版本抛出 ``VersionConflict``。"""
        ...


class InMemoryAgentStore:
    """面向单进程运行的 Agent 注册存储。"""

    def __init__(self) -> None:
        self._profiles: dict[str, AgentProfile] = {}
        self._snapshots: dict[str, VersionedAgentSnapshot] = {}
        self._lock = RLock()

    def register(self, profile: AgentProfile, snapshot: AgentSnapshot) -> VersionedAgentSnapshot:
        if profile.agent_id != snapshot.agent_id:
            raise ValueError("profile and snapshot agentId must match")
        with self._lock:
            if profile.agent_id in self._profiles:
                current_profile = self._profiles[profile.agent_id]
                current_snapshot = self._snapshots[profile.agent_id]
                if current_profile == profile and current_snapshot.snapshot == snapshot:
                    return self._copy(current_snapshot)
                raise ValueError(f"agent already registered: {profile.agent_id}")
            self._profiles[profile.agent_id] = profile.model_copy(deep=True)
            versioned = VersionedAgentSnapshot(snapshot=snapshot.model_copy(deep=True), version=1)
            self._snapshots[profile.agent_id] = versioned
            return self._copy(versioned)

    def get_profile(self, agent_id: str) -> AgentProfile:
        try:
            return self._profiles[agent_id].model_copy(deep=True)
        except KeyError as error:
            raise KeyError(f"unknown agent: {agent_id}") from error

    def get_snapshot(self, agent_id: str) -> VersionedAgentSnapshot:
        try:
            return self._copy(self._snapshots[agent_id])
        except KeyError as error:
            raise KeyError(f"unknown agent: {agent_id}") from error

    def list_profiles(self) -> list[AgentProfile]:
        return [self._profiles[key].model_copy(deep=True) for key in sorted(self._profiles)]

    def update_snapshot(
        self, snapshot: AgentSnapshot, *, expected_version: int | None = None
    ) -> VersionedAgentSnapshot:
        with self._lock:
            try:
                current = self._snapshots[snapshot.agent_id]
            except KeyError as error:
                raise KeyError(f"unknown agent: {snapshot.agent_id}") from error
            if expected_version is not None and expected_version != current.version:
                raise VersionConflict(
                    f"snapshot version conflict for {snapshot.agent_id}: "
                    f"expected {expected_version}, current {current.version}"
                )
            if snapshot.observation_sequence < current.snapshot.observation_sequence:
                raise StaleResourceObservation(
                    f"stale observation for {snapshot.agent_id}: "
                    f"received {snapshot.observation_sequence}, "
                    f"current {current.snapshot.observation_sequence}"
                )
            versioned = VersionedAgentSnapshot(
                snapshot=snapshot.model_copy(deep=True), version=current.version + 1
            )
            self._snapshots[snapshot.agent_id] = versioned
            return self._copy(versioned)

    @staticmethod
    def _copy(value: VersionedAgentSnapshot) -> VersionedAgentSnapshot:
        return VersionedAgentSnapshot(snapshot=value.snapshot.model_copy(deep=True), version=value.version)
