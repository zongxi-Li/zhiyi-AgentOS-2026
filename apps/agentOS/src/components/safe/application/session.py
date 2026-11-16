"""会话创建、步骤事务、回执查询、关闭与过期清理用例。"""

from __future__ import annotations

from components.safe.contracts.session import SessionView, StepReceipt, StepRequest
from components.safe.ports.session_store import ContextStepRunner, SessionStore, StepRunner


class SessionService:
    """应用层门面；认证 owner 由上层传入，本类不解析 HTTP 或 token。"""

    def __init__(self, store: SessionStore) -> None:
        self._store = store

    def create(self, owner_id: str, manifest_digest: str, *, session_id: str | None = None) -> SessionView:
        return self._store.create(owner_id, manifest_digest, session_id=session_id)

    def view(self, owner_id: str, session_id: str) -> SessionView:
        return self._store.view(owner_id, session_id)

    def receipt(self, owner_id: str, session_id: str, request_id: str) -> StepReceipt | None:
        return self._store.receipt(owner_id, session_id, request_id)

    def execute(self, owner_id: str, request: StepRequest, runner: StepRunner) -> StepReceipt:
        return self._store.execute(owner_id, request, runner)

    def execute_with_context(self, owner_id: str, request: StepRequest, runner: ContextStepRunner) -> StepReceipt:
        """可信上下文只能由存储在会话锁内构造，不能从请求复制。"""
        return self._store.execute_with_context(owner_id, request, runner)

    def close(self, owner_id: str, session_id: str) -> SessionView:
        return self._store.close(owner_id, session_id)

    def fail(self, owner_id: str, session_id: str) -> SessionView:
        return self._store.fail(owner_id, session_id)

    def cleanup_expired(self) -> int:
        return self._store.cleanup_expired()


__all__ = ["SessionService"]
