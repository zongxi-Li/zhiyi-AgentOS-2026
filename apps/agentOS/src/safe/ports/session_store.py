"""会话存储端口；仅查询接口已列出，原子执行事务合同仍需完善。

TODO(P3)：定义锁内占用request/提交回执/失败终态接口，禁止分离的check-then-set。
TODO(P3)：幂等先查回执再核验step；nonce防重放不属于本端口。
TODO(P3)：所有读写均含owner约束，不暴露其他主体会话是否存在。
"""

from typing import Protocol

from safe.contracts.session import SessionView, StepReceipt


class SessionStore(Protocol):
    def view(self, owner_id: str, session_id: str) -> SessionView:
        """返回owner拥有且未过期的会话视图；未知/越权统一拒绝。"""
        ...

    def receipt(self, owner_id: str, session_id: str, request_id: str) -> StepReceipt | None:
        """只返回同一身份下的已提交回执；None不代表可安全重新计算。"""
        ...
