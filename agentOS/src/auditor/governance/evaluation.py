"""AgentOS Core 的 evaluation 模块，提供运行时控制、状态、Trace、审核或治理能力。"""


from collections import Counter
from typing import Iterable, Optional

from contracts.workflow import EvaluationRun, TraceEventType, WorkflowMetric, WorkflowRun, WorkflowStatus


class WorkflowEvaluator:
    """计算工作流级治理指标。"""

    def evaluate(
        self,
        runs: Iterable[WorkflowRun],
        *,
        domain: Optional[str] = None,
        workflow_id: Optional[str] = None,
        source: Optional[str] = None,
    ) -> EvaluationRun:
        items = list(runs)
        total = len(items)
        if total == 0:
            return EvaluationRun(
                domain=domain,
                workflowId=workflow_id,
                source=source,
                metrics=WorkflowMetric(),
            )

        completed = sum(1 for run in items if run.status == WorkflowStatus.COMPLETED)
        failed = sum(1 for run in items if run.status == WorkflowStatus.FAILED)
        cancelled = sum(1 for run in items if run.status == WorkflowStatus.CANCELLED)
        waiting_review = sum(1 for run in items if run.status == WorkflowStatus.WAITING_REVIEW)
        retrying = sum(1 for run in items if run.status == WorkflowStatus.RETRYING)
        recovered = sum(1 for run in items if run.recovery_count > 0 and run.status == WorkflowStatus.COMPLETED)
        recovery_attempts = sum(1 for run in items if run.recovery_count > 0)
        status_breakdown = Counter(run.status.value for run in items)
        review_count = sum(
            1
            for run in items
            for event in run.trace
            if event.event_type == TraceEventType.REVIEW_DECIDED
        )

        metrics = WorkflowMetric(
            totalRuns=total,
            completedRuns=completed,
            failedRuns=failed,
            cancelledRuns=cancelled,
            waitingReviewRuns=waiting_review,
            retryingRuns=retrying,
            completionRate=round(completed / total, 4),
            failureRate=round(failed / total, 4),
            recoverySuccessRate=round(recovered / recovery_attempts, 4) if recovery_attempts else 0.0,
            averageRecoveryCount=round(sum(run.recovery_count for run in items) / total, 4),
            averageTraceEvents=round(sum(len(run.trace) for run in items) / total, 4),
            reviewCount=review_count,
            statusBreakdown=dict(status_breakdown),
        )
        return EvaluationRun(domain=domain, workflowId=workflow_id, source=source, metrics=metrics)
