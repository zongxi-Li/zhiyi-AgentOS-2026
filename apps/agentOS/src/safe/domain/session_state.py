"""纯状态迁移表；IO、锁、KV 释放与回执持久化由用例/端口负责。

TODO(P3)：状态提交与模型前向之间发生异常时一律 FAILED，不能回滚为可用 KV。
TODO(P3)：终态允许重复查询回执；不得重新执行步骤或延长寿命。
"""

from safe.contracts.errors import ErrorCode, SafeError
from safe.contracts.session import SessionStatus

_ALLOWED = {
    SessionStatus.CREATED: frozenset({SessionStatus.ACTIVE, SessionStatus.CLOSED, SessionStatus.FAILED, SessionStatus.EXPIRED}),
    SessionStatus.ACTIVE: frozenset({SessionStatus.CLOSED, SessionStatus.FAILED, SessionStatus.EXPIRED}),
}


def transition(current: SessionStatus, target: SessionStatus) -> SessionStatus:
    if target not in _ALLOWED.get(current, frozenset()):
        raise SafeError(ErrorCode.SESSION_INVALID)
    return target


def require_next_step(*, expected: int, received: int) -> None:
    if type(expected) is not int or type(received) is not int or expected < 0 or received != expected:
        raise SafeError(ErrorCode.STEP_OUT_OF_ORDER)
