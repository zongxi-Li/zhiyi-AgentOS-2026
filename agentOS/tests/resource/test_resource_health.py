"""资源健康指标的增量计算测试。"""

from resource.health import ResourceHealthMonitor


def test_ema_reliability_increases_after_success():
    """成功观测应按照 EMA 权重提高资源可靠性。"""
    monitor = ResourceHealthMonitor(alpha=0.5, initial_reliability=0.4)

    before = monitor.health("worker").reliability
    after = monitor.observe("worker", success=True, latency_ms=120.0).reliability

    assert after > before
    assert after == 0.7
