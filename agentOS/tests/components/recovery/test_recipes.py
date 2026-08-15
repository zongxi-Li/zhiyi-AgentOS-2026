from components.recovery import RecoveryRecipeRegistry, RecoveryService
from contracts.recovery import FailureEvent, RecoveryNodeTemplate, RecoveryRecipe


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
