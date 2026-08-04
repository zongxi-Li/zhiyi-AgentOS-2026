"""资源租约创建器。"""

from datetime import datetime, timedelta, timezone

from contracts.resource import ResourceLease


def issue_lease(lease_id: str, resource_id: str, owner_id: str, seconds: int = 60) -> ResourceLease:
    """生成短时 UTC 租约；持久化释放仍由外部资源适配器负责。"""
    created_at = datetime.now(timezone.utc)
    return ResourceLease(leaseId=lease_id, resourceId=resource_id, ownerId=owner_id, createdAt=created_at, expiresAt=created_at + timedelta(seconds=max(1, seconds)))
