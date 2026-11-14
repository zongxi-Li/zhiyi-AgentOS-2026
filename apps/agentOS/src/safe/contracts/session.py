"""公开会话视图与云端 step；不暴露 KV 句柄、锁或模型对象。

TODO(P3)：冻结 prefill/decode 的 token 位置与 EOS/完成回执语义。
TODO(P3)：owner 来自认证上下文，request_id 必须与完整已认证请求摘要绑定。
TODO(P3)：TTL 使用进程内单调时钟，重启全部会话失效；不可从网络恢复 KV。
"""

from enum import Enum
from typing import Literal

from pydantic import Field

from safe.contracts.activation import ActivationEnvelope
from safe.contracts.base import Digest, Identifier, SafeContract


class SessionStatus(str, Enum):
    CREATED = "created"
    ACTIVE = "active"
    CLOSED = "closed"
    FAILED = "failed"
    EXPIRED = "expired"


class SessionView(SafeContract):
    session_id: Identifier
    manifest_digest: Digest
    status: SessionStatus
    next_step: int = Field(ge=0)


class StepRequest(SafeContract):
    request_id: Identifier
    session_id: Identifier
    manifest_digest: Digest
    step: int = Field(ge=0)
    phase: Literal["prefill", "decode"]
    activation: ActivationEnvelope


class StepReceipt(SafeContract):
    request_id: Identifier
    session_id: Identifier
    step: int = Field(ge=0)
    token_id: int = Field(ge=0)
    finished: bool
