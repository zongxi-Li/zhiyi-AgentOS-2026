"""资源画像和快照的进程内存存储实现。"""

from __future__ import annotations

from threading import RLock
from typing import Protocol

from contracts.resource import ResourceProfile, ResourceSnapshot

from .models import VersionedResourceSnapshot


class VersionConflict(ValueError):
    """调用方基于过期快照版本提交更新时抛出的乐观锁冲突。"""


class ResourceStore(Protocol):
    """资源服务依赖的最小存储边界，便于替换存储介质。

    实现必须返回调用方不可变更内部状态的投影；若支持并发，版本读取、校验和写入
    必须具有原子语义，未知资源和版本冲突不得被静默吞掉。
    """

    def register(self, profile: ResourceProfile, snapshot: ResourceSnapshot) -> VersionedResourceSnapshot:
        """登记匹配画像与首份快照并返回版本投影；重复或标识不一致时抛出 ``ValueError``。"""
        ...

    def get_profile(self, resource_id: str) -> ResourceProfile:
        """读取资源画像副本；未知标识应抛出 ``KeyError``。"""
        ...

    def get_snapshot(self, resource_id: str) -> VersionedResourceSnapshot:
        """读取当前版本快照副本；未知标识应抛出 ``KeyError``。"""
        ...

    def list_profiles(self) -> list[ResourceProfile]:
        """返回稳定顺序的画像副本列表，不暴露实现内部容器。"""
        ...

    def update_snapshot(
        self, snapshot: ResourceSnapshot, *, expected_version: int | None = None
    ) -> VersionedResourceSnapshot:
        """按可选期望版本原子更新快照；过期版本应抛出 ``VersionConflict``。"""
        ...


class InMemoryResourceStore:
    """面向单进程运行的资源存储。

    每次写快照均创建新投影并增加版本，以使调用方能检测到陈旧观测。
    对外返回深拷贝，防止调用方修改 Pydantic 模型后绕过版本控制。
    """

    def __init__(self) -> None:
        self._profiles: dict[str, ResourceProfile] = {}
        self._snapshots: dict[str, VersionedResourceSnapshot] = {}
        # 注册和快照更新共享同一把可重入锁，保证版本读取、校验、写入不可穿插。
        self._lock = RLock()

    def register(self, profile: ResourceProfile, snapshot: ResourceSnapshot) -> VersionedResourceSnapshot:
        """原子登记相互匹配的静态画像和第一份动态快照。"""
        if profile.resource_id != snapshot.resource_id:
            raise ValueError("profile and snapshot resource_id must match")
        with self._lock:
            if profile.resource_id in self._profiles:
                raise ValueError(f"resource already registered: {profile.resource_id}")
            resource_id = profile.resource_id
            self._profiles[resource_id] = profile.model_copy(deep=True)
            versioned = VersionedResourceSnapshot(snapshot=snapshot.model_copy(deep=True), version=1)
            self._snapshots[resource_id] = versioned
            return self._copy_versioned(versioned)

    def get_profile(self, resource_id: str) -> ResourceProfile:
        """读取资源画像；未知资源被明确视为调用错误。"""
        try:
            return self._profiles[resource_id].model_copy(deep=True)
        except KeyError as error:
            raise KeyError(f"unknown resource: {resource_id}") from error

    def get_snapshot(self, resource_id: str) -> VersionedResourceSnapshot:
        """读取当前最新版快照及其版本号。"""
        try:
            return self._copy_versioned(self._snapshots[resource_id])
        except KeyError as error:
            raise KeyError(f"unknown resource: {resource_id}") from error

    def list_profiles(self) -> list[ResourceProfile]:
        """按注册顺序返回画像副本，保证相同输入下结果稳定。"""
        return [profile.model_copy(deep=True) for profile in self._profiles.values()]

    def update_snapshot(
        self, snapshot: ResourceSnapshot, *, expected_version: int | None = None
    ) -> VersionedResourceSnapshot:
        """在单一临界区内校验版本并写入，避免并发更新同时通过校验。"""
        with self._lock:
            try:
                current = self._snapshots[snapshot.resource_id]
            except KeyError as error:
                raise KeyError(f"unknown resource: {snapshot.resource_id}") from error
            if expected_version is not None and expected_version != current.version:
                raise VersionConflict(
                    f"snapshot version conflict for {snapshot.resource_id}: "
                    f"expected {expected_version}, current {current.version}"
                )
            # 版本派生和字典写回也在锁内，令一次更新成为不可分割的状态转换。
            versioned = VersionedResourceSnapshot(
                snapshot=snapshot.model_copy(deep=True), version=current.version + 1
            )
            self._snapshots[snapshot.resource_id] = versioned
            return self._copy_versioned(versioned)

    @staticmethod
    def _copy_versioned(value: VersionedResourceSnapshot) -> VersionedResourceSnapshot:
        return VersionedResourceSnapshot(snapshot=value.snapshot.model_copy(deep=True), version=value.version)


# TODO: 后续接入 SQLite 持久化，以在进程重启后保留资源画像和快照版本。
