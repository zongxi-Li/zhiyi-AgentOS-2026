"""无用户内容的审计事件；文本输出事件应另行定义，禁止复用为日志载荷。

TODO(P3)：补齐本机流事件的取消/错误/完成互斥语义。
TODO(P1)：审计只允许事件码、计数和批准的关联ID，不添加任意 metadata。
"""

from typing import Literal

from safe.contracts.base import Identifier, SafeContract


class AuditEvent(SafeContract):
    event: Literal["session_created", "session_closed", "session_failed", "release_refused"]
    correlation_id: Identifier
