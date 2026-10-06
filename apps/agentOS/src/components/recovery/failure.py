"""Stable failure classification at execution component boundaries."""

from __future__ import annotations

import hashlib

from contracts.recovery import FailureEvent, FailureSource, FailureType


_CLASSIFICATIONS: dict[str, tuple[FailureSource, FailureType, str, bool]] = {
    "ExecutionDeniedError": (FailureSource.AUDIT, FailureType.POLICY, "EXECUTION_AUDIT_DENIED", False),
    "ResourceNotFoundError": (FailureSource.SCHEDULER, FailureType.CAPACITY, "RESOURCE_UNAVAILABLE", True),
    "SchedulerNoEligibleResource": (FailureSource.SCHEDULER, FailureType.CAPACITY, "NO_ELIGIBLE_RESOURCE", False),
    "SchedulerAllocationTimeout": (FailureSource.SCHEDULER, FailureType.CAPACITY, "SCHEDULER_CAPACITY_TIMEOUT", True),
    "CommunicationBackpressureError": (FailureSource.COMMUNICATION, FailureType.COMMUNICATION, "COMMUNICATION_BACKPRESSURE", True),
    "CommunicationAccessError": (FailureSource.COMMUNICATION, FailureType.POLICY, "COMMUNICATION_NOT_AUTHORIZED", False),
    "EntropyBudgetExceededError": (FailureSource.COMMUNICATION, FailureType.POLICY, "COMMUNICATION_BUDGET_EXHAUSTED", False),
    "BlackboardConflictError": (FailureSource.COMMUNICATION, FailureType.COMMUNICATION, "BLACKBOARD_CAS_CONFLICT", True),
    "ConditionEvaluationError": (FailureSource.CONTROL, FailureType.CONTROL, "CONTROL_CONDITION_INVALID", False),
    "ACGChannelError": (FailureSource.CONTROL, FailureType.CONTROL, "CONTROL_CHANNEL_CONFLICT", False),
    "ACGSuperstepError": (FailureSource.CONTROL, FailureType.CONTROL, "SUPERSTEP_FAILED", True),
    "ExecutionValueAccessError": (FailureSource.STORAGE, FailureType.STORAGE, "ARTIFACT_REFERENCE_INVALID", False),
    "DecisionAccessError": (FailureSource.AUDIT, FailureType.POLICY, "AUDIT_DECISION_INVALID", False),
    "TimeoutError": (FailureSource.EXECUTOR, FailureType.TRANSIENT, "EXECUTION_TIMEOUT", True),
}


def failure_event_from_exception(
    exc: BaseException,
    *,
    subject_ref: str,
    source: FailureSource = FailureSource.EXECUTOR,
) -> FailureEvent:
    """Convert an exception into the shared, reference-only failure contract."""
    cause = getattr(exc, "cause", None)
    classified = cause if isinstance(cause, BaseException) else exc
    mapped = _CLASSIFICATIONS.get(type(classified).__name__)
    if mapped is None:
        resolved_source = source
        structured_code = getattr(classified, "code", None)
        if isinstance(structured_code, str) and structured_code:
            reason_code = structured_code
            failure_type = (
                FailureType.CONTRACT
                if structured_code == "OUTPUT_CONTRACT_VIOLATION"
                else FailureType.PERMANENT
            )
            retryable = bool(getattr(classified, "retryable", False))
        else:
            failure_type = FailureType.PERMANENT
            reason_code = "UNCLASSIFIED_EXECUTION_FAILURE"
            retryable = False
    else:
        resolved_source, failure_type, reason_code, retryable = mapped
    details = {"exceptionType": type(classified).__name__}
    if type(classified).__name__ in {"SchedulerNoEligibleResource", "SchedulerAllocationTimeout"}:
        structured_reason = getattr(classified, "reason_code", None)
        if structured_reason in {"NO_ELIGIBLE_RESOURCE", "NO_MODEL_ENDPOINT", "SCHEDULER_CAPACITY_TIMEOUT"}:
            reason_code = structured_reason
        details.update(stepId=getattr(classified, "step_id", None),
            candidateReasons=getattr(classified, "candidate_reasons", []))
    message = str(classified).strip() or type(classified).__name__
    digest = hashlib.sha256(
        f"{subject_ref}|{resolved_source.value}|{reason_code}|{message}".encode("utf-8")
    ).hexdigest()[:24]
    return FailureEvent(
        failureId=f"failure_{digest}",
        subjectRef=subject_ref,
        failureType=failure_type,
        source=resolved_source,
        reasonCode=reason_code,
        message=message[:500],
        retryable=retryable,
        details=details,
    )


__all__ = ["failure_event_from_exception"]
