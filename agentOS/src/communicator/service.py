"""通信部件的公共 Facade。"""

from contracts.communication import MessageEnvelope

from .assembler import ContextAssembler, assemble
from .contracts import ContextPack
from .compressor import compress_text
from .provenance import ProvenanceLedger


class CommunicatorService:
    """组装可序列化消息，网络投递仍由应用层适配器承担。"""

    def __init__(self, *, run_id: str = "", task_id: str = "") -> None:
        """服务拥有一份按运行隔离的血缘账本，不向旧运行时索取状态。"""
        self._assembler = ContextAssembler(ProvenanceLedger(run_id=run_id, task_id=task_id))

    def compose(self, message_id: str, topic: str, sender: str, payload: dict[str, object], recipient: str | None = None) -> MessageEnvelope:
        """返回消息信封，不执行 HTTP、队列或 WebSocket 副作用。"""
        return assemble(message_id, topic, sender, payload, recipient)

    def compact(self, text: str, limit: int = 512) -> str:
        """提供本地、可预测的文本缩略服务。"""
        return compress_text(text, limit)

    def assemble_context(self, **kwargs: object) -> ContextPack:
        """字段合同驱动的上下文装配入口。"""
        return self._assembler.assemble(**kwargs)  # type: ignore[arg-type]

    def record_production(self, step_id: str, output: dict[str, object], **kwargs: object) -> None:
        """生产方调用此入口登记字段、Token 与证据血缘。"""
        self._assembler.record_production(step_id, output, **kwargs)  # type: ignore[arg-type]

    @property
    def provenance(self) -> ProvenanceLedger:
        """返回可导出的链式血缘账本。"""
        return self._assembler.ledger

    # TODO: 注入消息总线客户端，以支持 HTTP、队列或 WebSocket 的可靠投递。
