import pytest

from components.recovery import (
    RecoveryRecipeRegistry,
    RecoveryService,
    failure_event_from_exception,
)
from components.communicator.reliable import CommunicationBackpressureError
from adapters.model_adapter import StructuredGenerationError
from contracts.tools import HostToolExecutionError
from contracts.recovery import (
    FailureEvent,
    FailureSource,
    FailureType,
    RecoveryAction,
    RecoveryNodeTemplate,
    RecoveryRecipe,
)


def _recipe(recipe_id: str, reason: str) -> RecoveryRecipe:
    return RecoveryRecipe(
        recipeId=recipe_id,
        version="1",
        triggerFailureTypes=["output_contract_violation"],
        triggerReasonCodes=[reason],
        requiredCapabilities=["contract_adapter"],
        nodeTemplates=[
            RecoveryNodeTemplate(
                logicalName="repair",
                name="Lossless contract repair",
                capability="contract_adapter",
            )
        ],
    )


def test_recipe_registry_selects_stably_and_returns_a_copy() -> None:
    registry = RecoveryRecipeRegistry([_recipe("z-repair", "*"), _recipe("a-repair", "MISSING")])
    failure = FailureEvent(
        failureId="failure-1",
        subjectRef="step:report",
        failureType="output_contract_violation",
        message="required property missing",
        details={"reasonCode": "MISSING"},
    )

    selected = RecoveryService(registry).select_recipe(failure)

    assert selected is not None
    assert selected.recipe_id == "a-repair"
    selected.required_capabilities.append("mutated")
    assert registry.get("a-repair").required_capabilities == ["contract_adapter"]
    assert RecoveryService(registry).select_recipe(
        failure,
        application_counts={"a-repair@1": 1, "z-repair@1": 1},
    ) is None


def test_failure_boundary_produces_stable_event_and_recovery_action() -> None:
    failure = failure_event_from_exception(
        CommunicationBackpressureError("channel queue is full"),
        subject_ref="run:run-1:step:writer",
    )
    replay = failure_event_from_exception(
        CommunicationBackpressureError("channel queue is full"),
        subject_ref="run:run-1:step:writer",
    )

    assert failure.failure_id == replay.failure_id
    assert failure.source is FailureSource.COMMUNICATION
    assert failure.failure_type is FailureType.COMMUNICATION
    assert failure.reason_code == "COMMUNICATION_BACKPRESSURE"
    assert RecoveryService().propose(failure).strategy is RecoveryAction.RETRY


def test_failure_boundary_preserves_structured_output_contract_reason() -> None:
    failure = failure_event_from_exception(
        StructuredGenerationError(
            "OUTPUT_CONTRACT_VIOLATION",
            "success_criteria exceeds maxItems",
        ),
        subject_ref="run:run-1:step:understand",
    )

    assert failure.failure_type is FailureType.CONTRACT
    assert failure.reason_code == "OUTPUT_CONTRACT_VIOLATION"
    assert failure.retryable is False


@pytest.mark.parametrize("code,source,kind,action,retryable", [
    ("NO_ELIGIBLE_RESOURCE", FailureSource.SCHEDULER, FailureType.CAPACITY, RecoveryAction.REBIND, False),
    ("EXECUTION_CAPACITY_UNAVAILABLE", FailureSource.SCHEDULER, FailureType.CAPACITY, RecoveryAction.REBIND, False),
    ("EXECUTION_RESOURCE_UNAVAILABLE", FailureSource.SCHEDULER, FailureType.CAPACITY, RecoveryAction.REBIND, False),
    ("SCHEDULER_UNAVAILABLE", FailureSource.SCHEDULER, FailureType.TRANSIENT, RecoveryAction.RETRY, True),
    ("EXECUTION_LEASE_LOST", FailureSource.SCHEDULER, FailureType.LEASE_EXPIRED, RecoveryAction.REBIND, False),
    ("EXECUTION_AUTHORIZATION_LOST", FailureSource.AUDIT, FailureType.POLICY, RecoveryAction.REVIEW, False),
    ("HANDS_OUTCOME_UNKNOWN", FailureSource.EXECUTOR, FailureType.PERMANENT, RecoveryAction.ABORT, False),
])
def test_host_tool_failure_preserves_diagnostic_identity_and_recovery_semantics(code, source, kind, action, retryable):
    details = {"stepId": "reader", "attemptId": "attempt:1", "commitId": "commit:1", "tool": "fs.read",
        "resourceId": "hands", "operationKey": "read:1", "phase": "tool_scheduling",
        "schedulingReason": "NO_ELIGIBLE_RESOURCE",
        "candidateReasons": [{"resourceId": "hands", "reasons": ["DISABLED"], "raw": "private provider body"}],
        "arguments": {"path": "private-path"}, "command": "private-command"}
    error = StructuredGenerationError(code, "Host tool failure", retryable=True)
    error.metadata = {"toolFailure": details, "raw": "private provider body"}
    event = failure_event_from_exception(error, subject_ref="run:run-1")
    assert event.source is source and event.failure_type is kind and event.retryable is retryable
    assert RecoveryService().propose(event).strategy is action
    assert event.details["stepId"] == "reader" and event.details["tool"] == "fs.read"
    assert event.details["candidateReasons"] == [{"resourceId": "hands", "reasons": ["DISABLED"]}]
    assert "private" not in event.model_dump_json()


def test_distinct_failed_tool_operations_have_distinct_stable_failure_identities():
    def failure(operation):
        return failure_event_from_exception(HostToolExecutionError("NO_ELIGIBLE_RESOURCE", "No eligible tool resource",
            details={"stepId": "reader", "operationKey": operation}), subject_ref="run:run-1")

    assert failure("read:1").failure_id == failure("read:1").failure_id
    assert failure("read:1").failure_id != failure("read:2").failure_id
