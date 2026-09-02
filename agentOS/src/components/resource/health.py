"""将心跳和执行结果转化为资源健康度。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .algorithms import exponential_moving_average
from .models import ResourceHealth


def _utc(value: datetime) -> datetime:
    """统一时间用于超时比较，拒绝没有时区的歧义输入。"""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


class ResourceHealthMonitor:
    """维护资源运行指标，并在读取时基于心跳年龄计算健康状态。"""

    def __init__(
        self,
        *,
        heartbeat_timeout: timedelta = timedelta(seconds=60),
        alpha: float = 0.2,
        initial_reliability: float = 0.5,
    ) -> None:
        if heartbeat_timeout <= timedelta(0):
            raise ValueError("heartbeat_timeout must be positive")
        if not 0.0 <= initial_reliability <= 1.0:
            raise ValueError("initial_reliability must be in [0, 1]")
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha must be in (0, 1]")
        self.heartbeat_timeout = heartbeat_timeout
        self.alpha = alpha
        self.initial_reliability = initial_reliability
        self._reliability: dict[str, float] = {}
        self._latency_ms: dict[str, float] = {}
        self._heartbeats: dict[str, datetime] = {}
        self._forced_health: dict[str, bool] = {}

    def heartbeat(self, resource_id: str, *, received_at: datetime | None = None) -> ResourceHealth:
        """记录本地接收心跳的时间，并返回新的健康投影。"""
        timestamp = _utc(received_at) if received_at is not None else datetime.now(timezone.utc)
        self._heartbeats[resource_id] = timestamp
        self._forced_health.pop(resource_id, None)
        return self.health(resource_id, now=timestamp)

    def set_health(self, resource_id: str, *, healthy: bool) -> ResourceHealth:
        """Apply an explicit adapter observation without inventing a heartbeat."""
        self._forced_health[resource_id] = healthy
        return self.health(resource_id)

    def observe(
        self,
        resource_id: str,
        *,
        success: bool,
        latency_ms: float,
        observed_at: datetime | None = None,
    ) -> ResourceHealth:
        """根据一次执行结果用 EMA 平滑可靠性和时延，并视为活动信号。"""
        if latency_ms < 0:
            raise ValueError("latency_ms must be non-negative")
        previous_reliability = self._reliability.get(resource_id, self.initial_reliability)
        self._reliability[resource_id] = exponential_moving_average(
            previous_reliability, 1.0 if success else 0.0, self.alpha
        )
        self._latency_ms[resource_id] = exponential_moving_average(
            self._latency_ms.get(resource_id), latency_ms, self.alpha
        )
        return self.heartbeat(resource_id, received_at=observed_at)

    def health(self, resource_id: str, *, now: datetime | None = None) -> ResourceHealth:
        """按调用时刻计算健康状态，因此资源会在没有新心跳时自然过期。"""
        current_time = _utc(now) if now is not None else datetime.now(timezone.utc)
        heartbeat = self._heartbeats.get(resource_id)
        naturally_healthy = heartbeat is not None and current_time - heartbeat <= self.heartbeat_timeout
        healthy = self._forced_health.get(resource_id, naturally_healthy)
        return ResourceHealth(
            resource_id=resource_id,
            healthy=healthy,
            reliability=self._reliability.get(resource_id, self.initial_reliability),
            latency_ms=self._latency_ms.get(resource_id),
            last_heartbeat=heartbeat,
        )

    calculate = health


# TODO: 继续补齐跨进程心跳的签名鉴权、重放保护和持久化；当前由 ResourceService
# 接收远程观测并更新本进程监测器，尚不等同于生产级多节点健康中心。
