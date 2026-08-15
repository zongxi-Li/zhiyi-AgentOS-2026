"""记忆生命周期判断。"""

from datetime import datetime, timezone

from contracts.memory import MemoryRecord


def is_expired(record: MemoryRecord, now: datetime | None = None) -> bool:
    """判断记录是否存在过期时间且不晚于 ``now``。

    未传 ``now`` 时使用当前 UTC 时间；没有 ``expires_at`` 的记录永不过期。函数
    不删除记录，也不处理时间戳时区不匹配错误，时间与空间复杂度均为 O(1)。
    """
    now = now or datetime.now(timezone.utc)
    return record.expires_at is not None and record.expires_at <= now
