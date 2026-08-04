"""资源画像登记的轻量门面。"""

from __future__ import annotations

from contracts.resource import ResourceProfile

from .store import ResourceStore


class ResourceRegistry:
    """集中校验画像注册，避免服务层直接依赖存储字典细节。"""

    def __init__(self, store: ResourceStore) -> None:
        self._store = store

    def get(self, resource_id: str) -> ResourceProfile:
        """按资源标识取得静态画像。"""
        return self._store.get_profile(resource_id)

    def all(self) -> list[ResourceProfile]:
        """取得全部已登记画像。"""
        return self._store.list_profiles()
