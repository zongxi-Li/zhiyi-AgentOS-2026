"""持久化存储的适配器边界。"""

from typing import Protocol


class BlobStore(Protocol):
    """以稳定键读取和写入文本化数据的最小存储协议。"""

    def get(self, key: str) -> str | None:
        """读取不存在时返回空值。"""
        ...

    def put(self, key: str, value: str) -> None:
        """写入值，具体事务语义由实现声明。"""
        ...


# TODO: 接入 SQLite/对象存储实现，并处理迁移、事务、加密与保留策略。

__all__ = ["BlobStore"]
