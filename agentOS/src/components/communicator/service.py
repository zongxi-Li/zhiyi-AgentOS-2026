"""通信部件的公共 Facade。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TYPE_CHECKING

from contracts.communication import MessageEnvelope

from .assembler import ContextAssembler, assemble
from .contracts import ContextPack
from .compressor import compress_text
from .provenance import ProvenanceLedger

if TYPE_CHECKING:
    from components.executor.value_store import ExecutionValueStore


class CommunicatorService:
    """提供消息装配、保守压缩和字段合同上下文服务。

    实例维护按运行隔离的内存血缘账本，但不执行 HTTP、队列或 WebSocket 投递；
    可靠传输、持久化及跨协程同步仍是应用层适配器的职责。
    """

    def __init__(
        self,
        *,
        run_id: str = "",
        task_id: str = "",
        ledger: ProvenanceLedger | None = None,
    ) -> None:
        """服务使用 run 隔离账本；注入账本时先确认其归属，避免恢复串线。"""
        active_ledger = ledger or ProvenanceLedger(run_id=run_id, task_id=task_id)
        if active_ledger.run_id != run_id or active_ledger.task_id != task_id:
            raise ValueError("provenance ledger ownership does not match communicator run")
        self._assembler = ContextAssembler(active_ledger)
        # 事件按步骤归属领取，而非使用全局游标。并行步骤在 Agent 调用期间会交错
        # 记账；全局游标会把先完成节点之外的事件错误投影到当前节点 Trace。
        self._drained_event_ids: set[str] = set()

    def compose(self, message_id: str, topic: str, sender: str, payload: dict[str, object], recipient: str | None = None) -> MessageEnvelope:
        """把消息标识、主题、发送方和载荷封装为 ``MessageEnvelope``。

        返回新合同对象且不执行网络或队列副作用；字段非法时由合同校验错误上抛。
        输入载荷不在服务内变更，固定字段装配的时间与空间复杂度均为 O(1)。
        """
        return assemble(message_id, topic, sender, payload, recipient)

    def compact(self, text: str, limit: int = 512) -> str:
        """以本地字符上限生成可预测的文本缩略结果。

        返回策略由 ``compress_text`` 定义，不调用模型、不解释语义；调用不修改
        原字符串，时间与空间复杂度随截取长度增长。
        """
        return compress_text(text, limit)

    def assemble_context(self, **kwargs: object) -> ContextPack:
        """将关键字参数转交给字段合同驱动的上下文装配器。

        返回包含白名单数据、缺失字段和血缘统计的 ``ContextPack``，并追加账本
        消费/交互事件；参数不满足装配器约定时错误直接上抛，不作隐式全量透传。
        """
        return self._assembler.assemble(**kwargs)  # type: ignore[arg-type]

    def assemble_execution_context(
        self,
        *,
        run_id: str,
        step_id: str,
        input_spec: Mapping[str, Any],
        upstream_refs: Mapping[str, str],
        value_store: "ExecutionValueStore",
        token_budget: int | None = None,
        task_id: str = "",
        objective: str = "",
        step_goal: str = "",
        operation_id: str = "",
    ) -> ContextPack:
        """按输出引用读取上游受控数据并装配严格合同 ContextPack。

        这里是执行器取得上游正文的唯一入口。每次读取都携带当前 ``run_id``，由
        ``ExecutionValueStore`` 拒绝跨运行引用；随后仍交由既有装配器执行字段白名单、
        必填字段和 Token 预算计算。因此既不会从 State 恢复正文，也不会因便捷而全量
        透传 Agent 输出。
        """
        upstream_outputs = {
            source_step_id: value_store.get_output(run_id=run_id, output_ref=output_ref)
            for source_step_id, output_ref in upstream_refs.items()
        }
        return self.assemble_context(
            run_id=run_id,
            task_id=task_id,
            step_id=step_id,
            input_spec=input_spec,
            upstream_outputs=upstream_outputs,
            objective=objective,
            step_goal=step_goal,
            token_budget=token_budget,
            operation_id=operation_id,
        )

    def record_production(self, step_id: str, output: dict[str, object], **kwargs: object) -> None:
        """为 ``step_id`` 的输出登记字段、Token 与证据血缘。

        该调用会向内部账本追加生产事件而不修改 ``output``；额外参数遵循装配器
        的代理名称、尝试次数等约定。账本错误或无效输入保持原样上抛。
        """
        self._assembler.record_production(step_id, output, **kwargs)  # type: ignore[arg-type]

    @property
    def provenance(self) -> ProvenanceLedger:
        """返回本服务持有的可导出内存血缘账本引用。

        返回的不是副本，调用者可读取事件或验证完整性，但直接修改公开列表可能
        破坏链式不变量；并发读取与写入须由调用方协调。
        """
        return self._assembler.ledger

    def drain_provenance_events(self, *, step_id: str | None = None) -> list[dict[str, Any]]:
        """领取尚未投影且归属当前步骤的安全血缘事件。

        ``step_id`` 存在时，生产事件按生产者归属，消费与交互事件按消费者归属；
        这样并行节点即使交错执行也不会互相吞掉 Trace。省略它仅为兼容旧调用，
        会领取所有尚未投影的事件。
        """
        events = self.provenance.trace_events()
        owned: list[dict[str, Any]] = []
        for event in events:
            payload = event["payload"]
            event_id = payload["eventId"]
            if event_id in self._drained_event_ids:
                continue
            if step_id is not None and not self._belongs_to_step(event, step_id):
                continue
            self._drained_event_ids.add(event_id)
            owned.append(event)
        return owned

    @staticmethod
    def _belongs_to_step(event: dict[str, Any], step_id: str) -> bool:
        """判断安全投影是否归属步骤；只查看投影元数据，不读取正文。"""
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return False
        return payload.get("producerStepId") == step_id or payload.get("consumerStepId") == step_id

    # TODO: 注入消息总线客户端，以支持 HTTP、队列或 WebSocket 的可靠投递。
