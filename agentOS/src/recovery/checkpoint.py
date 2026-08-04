"""轻量恢复检查点。"""

from typing import Any


class CheckpointStore:
    """进程内检查点实现，适合单次运行和测试。"""

    def __init__(self) -> None:
        self._snapshots: dict[str, dict[str, Any]] = {}

    def save(self, checkpoint_id: str, state: dict[str, Any]) -> None:
        """按检查点标识保存状态浅副本；同名覆盖仅限本进程，调用方负责并发互斥。"""
        self._snapshots[checkpoint_id] = dict(state)

    def load(self, checkpoint_id: str) -> dict[str, Any] | None:
        """返回检查点状态副本；不存在时返回 ``None``，不会暴露内部可变字典。"""
        state = self._snapshots.get(checkpoint_id)
        return dict(state) if state is not None else None

    # TODO: 接入持久化检查点存储，并对快照做版本校验和加密。
