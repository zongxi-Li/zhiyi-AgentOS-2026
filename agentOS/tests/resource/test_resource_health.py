"""资源健康指标的增量计算测试。"""

from components.resource.health import ResourceHealthMonitor


def test_ema_reliability_increases_after_success():
    """成功观测应按照 EMA 权重提高资源可靠性。"""
    monitor = ResourceHealthMonitor(alpha=0.5, initial_reliability=0.4)

    before = monitor.health("worker").reliability
    after = monitor.observe("worker", success=True, latency_ms=120.0).reliability

    assert after > before
    assert after == 0.7


def test_ema_latency_changes_after_consecutive_observations():
    """连续时延观测应按 EMA 系数平滑到新的精确值。"""
    monitor = ResourceHealthMonitor(alpha=0.5)

    monitor.observe("worker", success=True, latency_ms=100.0)
    health = monitor.observe("worker", success=True, latency_ms=300.0)

    assert health.latency_ms == 200.0
