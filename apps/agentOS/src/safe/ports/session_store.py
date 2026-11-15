"""会话存储端口；所有事务方法都以 owner 作为第一层授权边界。"""

from typing import Callable, Protocol

from safe.contracts.session import ActivationContext, SessionView, StepReceipt, StepRequest
from safe.ports.model_runner import KVHandle

StepRunner = Callable[[StepRequest], tuple[int, bool]]
ContextStepRunner = Callable[[StepRequest, ActivationContext, KVHandle | None], tuple[int, bool]]


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

    def execute_with_context(self, owner_id: str, request: StepRequest, runner: ContextStepRunner) -> StepReceipt:
        """锁内查幂等、核验步骤后，传入存储构造的可信位置和本会话KV句柄。

        KV句柄只供进程内回调，不写入SessionView或任何网络合同。
        """
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


__all__ = ["SessionStore", "StepRunner", "ContextStepRunner"]
