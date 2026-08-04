"""消息信封构建器。"""

from contracts.communication import MessageEnvelope


def assemble(message_id: str, topic: str, sender: str, payload: dict[str, object], recipient: str | None = None) -> MessageEnvelope:
    """将通用 JSON 负载封装为 contracts 定义的消息信封。"""
    return MessageEnvelope(messageId=message_id, topic=topic, sender=sender, recipient=recipient, payload=payload)
