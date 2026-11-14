"""仅结构化白名单事件的审计端口，禁止任意内容dict。

TODO(P1)：固定失败策略、背压与保留期限；限制关联ID中的可识别信息。
TODO(P6)：用敏感标记测试所有错误和审计路径，避免异常隐式泄露。
"""

from typing import Protocol

from safe.contracts.events import AuditEvent


class AuditSink(Protocol):
    def emit(self, event: AuditEvent) -> None:
        """输出已脱敏合同；sink失败不能改发原始异常或用户内容。"""
        ...
