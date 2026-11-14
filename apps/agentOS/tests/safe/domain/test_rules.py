"""验证失败默认拒绝与终态不可恢复的协议规则。"""

import pytest

from safe.contracts.errors import ErrorCode, SafeError
from safe.contracts.session import SessionStatus
from safe.domain.idempotency import require_same_request
from safe.domain.session_state import require_next_step, transition


def test_terminal_session_cannot_be_reopened():
    assert transition(SessionStatus.CREATED, SessionStatus.ACTIVE) == SessionStatus.ACTIVE
    assert transition(SessionStatus.ACTIVE, SessionStatus.FAILED) == SessionStatus.FAILED
    for status in (SessionStatus.FAILED, SessionStatus.CLOSED, SessionStatus.EXPIRED):
        with pytest.raises(SafeError):
            transition(status, SessionStatus.ACTIVE)


def test_step_order_and_idempotency_identity():
    require_next_step(expected=0, received=0)
    with pytest.raises(SafeError) as error:
        require_next_step(expected=1, received=0)
    assert error.value.code == ErrorCode.STEP_OUT_OF_ORDER
    key = ("owner", "session", "request", "a" * 64)
    require_same_request(key, key)
    for index in range(4):
        different = list(key)
        different[index] += "x"
        with pytest.raises(SafeError):
            require_same_request(key, tuple(different))
