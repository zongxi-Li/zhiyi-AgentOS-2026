from components.recovery import (
    RecoveryRecipeRegistry,
    RecoveryService,
    failure_event_from_exception,
)
from components.communicator.reliable import CommunicationBackpressureError
from adapters.model_adapter import StructuredGenerationError
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
