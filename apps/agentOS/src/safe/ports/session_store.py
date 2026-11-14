"""会话存储端口；所有事务方法都以 owner 作为第一层授权边界。"""

from typing import Callable, Protocol

from safe.contracts.session import SessionView, StepReceipt, StepRequest

StepRunner = Callable[[StepRequest], tuple[int, bool]]


class SessionStore(Protocol):
    def create(self, owner_id: str, manifest_digest: str, *, session_id: str | None = None) -> SessionView:
        """创建绑定 owner/manifest 的短时会话。"""
        ...

    def view(self, owner_id: str, session_id: str) -> SessionView:
        """返回 owner 拥有的会话视图；过期会话以 EXPIRED 终态返回。"""
        ...

    def receipt(self, owner_id: str, session_id: str, request_id: str) -> StepReceipt | None:
        """只返回同一身份下的已提交回执；None 不代表可安全重新计算。"""
        ...

    def execute(self, owner_id: str, request: StepRequest, runner: StepRunner) -> StepReceipt:
        """原子检查、执行和提交一步；相同请求只执行一次。"""
        ...

    def close(self, owner_id: str, session_id: str) -> SessionView:
        """关闭尚未终止的会话。"""
        ...

    def fail(self, owner_id: str, session_id: str) -> SessionView:
        """把尚未终止的会话置为 FAILED。"""
        ...

    def cleanup_expired(self) -> int:
        """标记当前已超过 TTL 的会话并返回数量。"""
        ...


__all__ = ["SessionStore", "StepRunner"]
