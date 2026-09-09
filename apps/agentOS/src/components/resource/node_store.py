"""节点资源表的存储实现（协议 + 进程内存）。"""

from __future__ import annotations

from datetime import datetime
from threading import RLock
from typing import Protocol

from contracts.resource import NodeProfile, NodeSnapshot

from .models import VersionedNodeSnapshot
from .store import ResourceCredentialRecord, StaleResourceObservation, VersionConflict


class NodeStore(Protocol):
    """节点资源表依赖的最小存储边界，便于替换存储介质。"""

    def register(self, profile: NodeProfile, snapshot: NodeSnapshot) -> VersionedNodeSnapshot:
        """登记匹配的节点画像与首份快照；重复登记抛出 ``ValueError``。"""
        ...

    def get_profile(self, node_id: str) -> NodeProfile:
        """读取节点画像副本；未知标识抛出 ``KeyError``。"""
        ...

    def get_snapshot(self, node_id: str) -> VersionedNodeSnapshot:
        """读取当前版本快照副本；未知标识抛出 ``KeyError``。"""
        ...

    def list_profiles(self) -> list[NodeProfile]:
        """返回稳定顺序的节点画像副本列表。"""
        ...

    def update_snapshot(
        self, snapshot: NodeSnapshot, *, expected_version: int | None = None
    ) -> VersionedNodeSnapshot:
        """按可选期望版本原子更新快照；过期版本抛出 ``VersionConflict``。"""
        ...

    def save_credential(self, record: ResourceCredentialRecord) -> None:
        """保存一个节点凭据；同一节点不可静默覆盖已有凭据。"""
        ...

    def rotate_credential(self, record: ResourceCredentialRecord) -> None:
        """原子替换已有节点凭据。"""
        ...

    def get_credential(self, node_id: str) -> ResourceCredentialRecord:
        """读取节点凭据元数据；未登记凭据抛出 ``KeyError``。"""
        ...

    def consume_nonce(
        self, node_id: str, nonce: str, expires_at: datetime, *, now: datetime
    ) -> bool:
        """原子登记 nonce；已使用或已过期返回 False。"""
        ...


class InMemoryNodeStore:
    """面向单进程运行的节点资源存储。"""

    def __init__(self) -> None:
        self._profiles: dict[str, NodeProfile] = {}
        self._snapshots: dict[str, VersionedNodeSnapshot] = {}
        self._credentials: dict[str, ResourceCredentialRecord] = {}
        self._nonces: dict[tuple[str, str], datetime] = {}
        self._lock = RLock()

    def register(self, profile: NodeProfile, snapshot: NodeSnapshot) -> VersionedNodeSnapshot:
        if profile.node_id != snapshot.node_id:
            raise ValueError("profile and snapshot nodeId must match")
        with self._lock:
            if profile.node_id in self._profiles:
                current_profile = self._profiles[profile.node_id]
                current_snapshot = self._snapshots[profile.node_id]
                if current_profile == profile and current_snapshot.snapshot == snapshot:
                    return self._copy(current_snapshot)
                raise ValueError(f"node already registered: {profile.node_id}")
            self._profiles[profile.node_id] = profile.model_copy(deep=True)
            versioned = VersionedNodeSnapshot(snapshot=snapshot.model_copy(deep=True), version=1)
            self._snapshots[profile.node_id] = versioned
            return self._copy(versioned)

    def get_profile(self, node_id: str) -> NodeProfile:
        try:
            return self._profiles[node_id].model_copy(deep=True)
        except KeyError as error:
            raise KeyError(f"unknown node: {node_id}") from error

    def get_snapshot(self, node_id: str) -> VersionedNodeSnapshot:
        try:
            return self._copy(self._snapshots[node_id])
        except KeyError as error:
            raise KeyError(f"unknown node: {node_id}") from error

    def list_profiles(self) -> list[NodeProfile]:
        return [self._profiles[key].model_copy(deep=True) for key in sorted(self._profiles)]

    def update_snapshot(
        self, snapshot: NodeSnapshot, *, expected_version: int | None = None
    ) -> VersionedNodeSnapshot:
        with self._lock:
            try:
                current = self._snapshots[snapshot.node_id]
            except KeyError as error:
                raise KeyError(f"unknown node: {snapshot.node_id}") from error
            if expected_version is not None and expected_version != current.version:
                raise VersionConflict(
                    f"snapshot version conflict for {snapshot.node_id}: "
                    f"expected {expected_version}, current {current.version}"
                )
            if snapshot.observation_sequence < current.snapshot.observation_sequence:
                raise StaleResourceObservation(
                    f"stale observation for {snapshot.node_id}: "
                    f"received {snapshot.observation_sequence}, "
                    f"current {current.snapshot.observation_sequence}"
                )
            versioned = VersionedNodeSnapshot(
                snapshot=snapshot.model_copy(deep=True), version=current.version + 1
            )
            self._snapshots[snapshot.node_id] = versioned
            return self._copy(versioned)

    def save_credential(self, record: ResourceCredentialRecord) -> None:
        with self._lock:
            if record.resource_id not in self._profiles:
                raise KeyError(f"unknown node: {record.resource_id}")
            if record.resource_id in self._credentials:
                raise ValueError(f"node credential already exists: {record.resource_id}")
            self._credentials[record.resource_id] = record

    def rotate_credential(self, record: ResourceCredentialRecord) -> None:
        with self._lock:
            if record.resource_id not in self._profiles:
                raise KeyError(f"unknown node: {record.resource_id}")
            if record.resource_id not in self._credentials:
                raise KeyError(f"node credential not found: {record.resource_id}")
            self._credentials[record.resource_id] = record

    def get_credential(self, node_id: str) -> ResourceCredentialRecord:
        with self._lock:
            try:
                return self._credentials[node_id]
            except KeyError as error:
                raise KeyError(f"node credential not found: {node_id}") from error

    def consume_nonce(
        self, node_id: str, nonce: str, expires_at: datetime, *, now: datetime
    ) -> bool:
        with self._lock:
            self._nonces = {key: expiry for key, expiry in self._nonces.items() if expiry > now}
            key = (node_id, nonce)
            if expires_at <= now or key in self._nonces:
                return False
            self._nonces[key] = expires_at
            return True

    @staticmethod
    def _copy(value: VersionedNodeSnapshot) -> VersionedNodeSnapshot:
        return VersionedNodeSnapshot(snapshot=value.snapshot.model_copy(deep=True), version=value.version)
