"""双时钟端口：TTL用单调时钟，签名时间窗用UTC时间。

TODO(P3)：提供可推进的测试时钟，覆盖时钟回拨、TTL边界和绝对寿命。
TODO(P4)：所有deadline统一来源；不能将进程单调时刻发送给另一台机器比较。
"""

from typing import Protocol


class Clock(Protocol):
    def monotonic(self) -> float:
        """仅供本进程持续时间/过期检查，不落盘恢复旧会话。"""
        ...

    def utc_timestamp(self) -> float:
        """认证时间窗使用的Unix UTC秒；回拨策略由认证实现明确处理。"""
        ...
