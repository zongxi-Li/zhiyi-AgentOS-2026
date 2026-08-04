"""消息与上下文包的跨部件传输合同。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictStr


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ContextPackRef(BaseModel):
    """上下文包的可校验存储引用。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    context_id: StrictStr = Field(alias="contextId", min_length=1, description="上下文包唯一标识。")
    uri: StrictStr = Field(min_length=1, description="上下文包在交换层或存储层的位置。")
    checksum: StrictStr = Field(min_length=1, description="上下文内容的稳定校验和。")
    content_type: StrictStr = Field(default="application/json", alias="contentType", min_length=1, description="上下文包媒体类型。")


class MessageEnvelope(BaseModel):
    """部件间投递的一条消息信封，负载仅为通用 JSON 值。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    message_id: StrictStr = Field(alias="messageId", min_length=1, description="消息唯一标识。")
    topic: StrictStr = Field(min_length=1, description="稳定的消息主题。")
    sender: StrictStr = Field(min_length=1, description="发送方部件标识。")
    recipient: StrictStr | None = Field(default=None, description="可选的指定接收方部件标识。")
    correlation_id: StrictStr | None = Field(default=None, alias="correlationId", description="关联同一处理链的标识。")
    payload: dict[str, Any] = Field(default_factory=dict, description="经协议约定的消息负载。")
    context: ContextPackRef | None = Field(default=None, description="随消息传递的上下文包引用。")
    sent_at: datetime = Field(default_factory=_utc_now, alias="sentAt", description="消息创建的 UTC 时间。")
