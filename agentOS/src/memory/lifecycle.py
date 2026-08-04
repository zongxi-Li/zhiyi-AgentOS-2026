"""记忆生命周期判断。"""

from datetime import datetime, timezone

from contracts.memory import MemoryRecord


def is_expired(record: MemoryRecord, now: datetime | None = None) -> bool:
    """仅在显式设置且已过期时返回真。"""
    now = now or datetime.now(timezone.utc)
    return record.expires_at is not None and record.expires_at <= now
