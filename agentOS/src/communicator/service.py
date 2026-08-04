"""通信部件的公共 Facade。"""

from contracts.communication import MessageEnvelope

from .assembler import assemble
from .compressor import compress_text


class CommunicatorService:
    """组装可序列化消息，网络投递仍由应用层适配器承担。"""

    def compose(self, message_id: str, topic: str, sender: str, payload: dict[str, object], recipient: str | None = None) -> MessageEnvelope:
        """返回消息信封，不执行 HTTP、队列或 WebSocket 副作用。"""
        return assemble(message_id, topic, sender, payload, recipient)

    def compact(self, text: str, limit: int = 512) -> str:
        """提供本地、可预测的文本缩略服务。"""
        return compress_text(text, limit)

    # TODO: 注入消息总线客户端，以支持 HTTP、队列或 WebSocket 的可靠投递。
