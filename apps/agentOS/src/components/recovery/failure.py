"""Stable failure classification at execution component boundaries."""

from __future__ import annotations

import hashlib
import json

from contracts.recovery import FailureEvent, FailureSource, FailureType
from contracts.tools import safe_tool_failure_details


_CLASSIFICATIONS: dict[str, tuple[FailureSource, FailureType, str, bool]] = {
    "MaterialSourceError": (FailureSource.EXECUTOR, FailureType.CONTRACT, "CONTENT_SOURCE_INVALID", False),
    "ExecutionDeniedError": (FailureSource.AUDIT, FailureType.POLICY, "EXECUTION_AUDIT_DENIED", False),
    "ResourceNotFoundError": (FailureSource.SCHEDULER, FailureType.CAPACITY, "RESOURCE_UNAVAILABLE", True),
    "SchedulerNoEligibleResource": (FailureSource.SCHEDULER, FailureType.CAPACITY, "NO_ELIGIBLE_RESOURCE", False),
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


_TOOL_CLASSIFICATIONS = {
    "NO_ELIGIBLE_RESOURCE": (FailureSource.SCHEDULER, FailureType.CAPACITY, False),
    "NO_MODEL_ENDPOINT": (FailureSource.SCHEDULER, FailureType.CAPACITY, False),
    "EXECUTION_CAPACITY_UNAVAILABLE": (FailureSource.SCHEDULER, FailureType.CAPACITY, False),
    "EXECUTION_RESOURCE_UNAVAILABLE": (FailureSource.SCHEDULER, FailureType.CAPACITY, False),
    "SCHEDULER_UNAVAILABLE": (FailureSource.SCHEDULER, FailureType.TRANSIENT, True),
    "EXECUTION_LEASE_LOST": (FailureSource.SCHEDULER, FailureType.LEASE_EXPIRED, False),
    "EXECUTION_AUTHORIZATION_LOST": (FailureSource.AUDIT, FailureType.POLICY, False),
    "HANDS_OUTCOME_UNKNOWN": (FailureSource.EXECUTOR, FailureType.PERMANENT, False),
    "TOOL_TIMEOUT": (FailureSource.EXECUTOR, FailureType.TRANSIENT, False),
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
    structured_code = getattr(classified, "code", None)
    tool_classification = _TOOL_CLASSIFICATIONS.get(structured_code) if isinstance(structured_code, str) else None
    mapped = _CLASSIFICATIONS.get(type(classified).__name__)
    if tool_classification is not None:
        resolved_source, failure_type, retryable = tool_classification
        reason_code = structured_code
    elif mapped is None:
        resolved_source = source
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
    metadata = getattr(classified, "metadata", None)
    tool_details = safe_tool_failure_details(
        metadata.get("toolFailure", getattr(classified, "details", None))
        if isinstance(metadata, dict) else getattr(classified, "details", None))
    if tool_details:
        details.update(tool_details)
    if type(classified).__name__ == "MaterialSourceError":
        details.update(stepId=classified.step_id, manifestId=classified.manifest_id)
    if type(classified).__name__ == "SchedulerNoEligibleResource":
        structured_reason = getattr(classified, "reason_code", None)
        if structured_reason in {"NO_ELIGIBLE_RESOURCE", "NO_MODEL_ENDPOINT"}:
            reason_code = structured_reason
        details.update(stepId=getattr(classified, "step_id", None),
            candidateReasons=getattr(classified, "candidate_reasons", []))
    message = str(classified).strip() or type(classified).__name__
    identity = ""
    if tool_details:
        identity = "|" + json.dumps(tool_details, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(
        f"{subject_ref}|{resolved_source.value}|{reason_code}|{message}{identity}".encode("utf-8")
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
