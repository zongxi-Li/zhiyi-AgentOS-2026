"""AgentOS Core 的 review 模块，提供运行时控制、状态、Trace、审核或治理能力。"""


from typing import List

from contracts.workflow import ReviewDecision, ReviewDecisionType, ReviewRecord, TraceEventType, WorkflowRun
from components.auditor.governance.trace import TraceStore


class ReviewManager:
    """把人工审核决策写入运行 Trace，并可从 Trace 重建审核记录。

    实例依赖注入的 ``TraceStore``；它不维护独立持久化索引，因此同一运行的
    并发追加与底层 Trace 可见性由调用者及 TraceStore 协调。
    """

    def __init__(self, trace_store: TraceStore):
        self.trace_store = trace_store

    def record(self, run: WorkflowRun, decision: ReviewDecision) -> ReviewRecord:
        """把 ``decision`` 追加为审核 Trace 并返回对应的审核记录。

        返回记录与刚写入事件共享运行、步骤和时间信息；写入 ``run.trace`` 是
        唯一副作用。TraceStore 或合同校验错误会直接上抛，方法不尝试重试。
        """
        event = self.trace_store.append(
            run=run,
            event_type=TraceEventType.REVIEW_DECIDED,
            step_id=decision.step_id,
            observation=f"Review decision: {decision.decision.value}",
            payload=decision.model_dump(by_alias=True, mode="json"),
        )
        return ReviewRecord(
            runId=run.run_id,
            stepId=decision.step_id,
            decision=decision.decision,
            reviewer=decision.reviewer,
            comment=decision.comment,
            operationId=decision.operation_id,
            traceEventId=event.event_id,
            createdAt=event.created_at,
        )

    def list(self, run: WorkflowRun) -> List[ReviewRecord]:
        """从 ``run.trace`` 重建并稳定排序全部人工审核记录。

        仅处理 ``REVIEW_DECIDED`` 事件，缺省载荷字段按兼容默认值填充；返回新
        列表且不修改 Trace。时间复杂度 O(n log n)，额外空间 O(k)。
        """
        records: List[ReviewRecord] = []
        for event in sorted(run.trace, key=lambda item: (item.created_at, item.event_id)):
            if event.event_type != TraceEventType.REVIEW_DECIDED:
                continue
            payload = event.payload or {}
            records.append(
                ReviewRecord(
                    reviewId=payload.get("reviewId") or f"review_{event.event_id}",
                    runId=payload.get("runId") or run.run_id,
                    stepId=payload.get("stepId") or event.step_id or "",
                    decision=ReviewDecisionType(payload.get("decision", ReviewDecisionType.APPROVED.value)),
                    reviewer=payload.get("reviewer") or "system",
                    comment=payload.get("comment") or "",
                    operationId=payload.get("operationId"),
                    traceEventId=event.event_id,
                    createdAt=payload.get("createdAt") or event.created_at,
                )
            )
        return records
