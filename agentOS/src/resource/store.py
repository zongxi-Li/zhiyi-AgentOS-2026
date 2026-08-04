"""资源画像和快照的进程内存存储实现。"""

from __future__ import annotations

from typing import Protocol

from contracts.resource import ResourceProfile, ResourceSnapshot

from .models import VersionedResourceSnapshot


class ResourceStore(Protocol):
    """资源服务依赖的最小存储边界，便于后续替换存储介质。"""

    def register(self, profile: ResourceProfile, snapshot: ResourceSnapshot) -> VersionedResourceSnapshot: ...

    def get_profile(self, resource_id: str) -> ResourceProfile: ...

    def get_snapshot(self, resource_id: str) -> VersionedResourceSnapshot: ...

    def list_profiles(self) -> list[ResourceProfile]: ...

    def update_snapshot(
        self, snapshot: ResourceSnapshot, *, expected_version: int | None = None
    ) -> VersionedResourceSnapshot: ...


class InMemoryResourceStore:
    """面向单进程运行的资源存储。

    每次写快照均创建新投影并增加版本，以使调用方能检测到陈旧观测。
    对外返回深拷贝，防止调用方修改 Pydantic 模型后绕过版本控制。
    """

    def __init__(self) -> None:
        self._profiles: dict[str, ResourceProfile] = {}
        self._snapshots: dict[str, VersionedResourceSnapshot] = {}

    def register(self, profile: ResourceProfile, snapshot: ResourceSnapshot) -> VersionedResourceSnapshot:
        """原子登记相互匹配的静态画像和第一份动态快照。"""
        if profile.resource_id != snapshot.resource_id:
            raise ValueError("profile and snapshot resource_id must match")
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
        """写入新观测，并可用版本号执行乐观并发校验。"""
        current = self.get_snapshot(snapshot.resource_id)
        if expected_version is not None and expected_version != current.version:
            raise ValueError(
                f"snapshot version conflict for {snapshot.resource_id}: "
                f"expected {expected_version}, current {current.version}"
            )
        versioned = VersionedResourceSnapshot(
            snapshot=snapshot.model_copy(deep=True), version=current.version + 1
        )
        self._snapshots[snapshot.resource_id] = versioned
        return self._copy_versioned(versioned)

    @staticmethod
    def _copy_versioned(value: VersionedResourceSnapshot) -> VersionedResourceSnapshot:
        return VersionedResourceSnapshot(snapshot=value.snapshot.model_copy(deep=True), version=value.version)


# TODO: 后续接入 SQLite 持久化，以在进程重启后保留资源画像和快照版本。
