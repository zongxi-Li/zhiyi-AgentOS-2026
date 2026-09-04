from __future__ import annotations

import re

import pytest
from pydantic import BaseModel, ValidationError

from contracts.identity import (
    AttemptId,
    BlueprintId,
    RunId,
    StepExecutionId,
    TaskId,
    MissionId,
    generate_identity,
)


class IdentityEnvelope(BaseModel):
    mission_id: MissionId
    task_id: TaskId
    blueprint_id: BlueprintId
    run_id: RunId
    attempt_id: AttemptId
    step_execution_id: StepExecutionId


@pytest.mark.parametrize(
    ("prefix", "pattern"),
    [
        ("task", r"task_[0-9a-f]{12}"),
        ("mission", r"mission_[0-9a-f]{12}"),
        ("blueprint", r"blueprint_[0-9a-f]{12}"),
        ("run", r"run_[0-9a-f]{12}"),
        ("attempt", r"attempt_[0-9a-f]{12}"),
        ("binding", r"binding_[0-9a-f]{12}"),
        ("step_execution", r"step_execution_[0-9a-f]{12}"),
    ],
)
def test_generate_identity_uses_canonical_format(prefix: str, pattern: str) -> None:
    assert re.fullmatch(pattern, generate_identity(prefix))


@pytest.mark.parametrize(
    "field,value",
    [
        ("mission_id", "run_0123456789ab"),
        ("task_id", "task_0123456789a"),
        ("blueprint_id", "blueprint_0123456789ag"),
        ("run_id", "run_0123456789AB"),
        ("attempt_id", "run-clean"),
        ("step_execution_id", "run_test"),
    ],
)
def test_identity_validator_rejects_wrong_prefix_length_and_non_hex(field: str, value: str) -> None:
    valid = {
        "mission_id": "mission_0123456789ab",
        "task_id": "task_0123456789ab",
        "blueprint_id": "blueprint_0123456789ab",
        "run_id": "run_0123456789ab",
        "attempt_id": "attempt_0123456789ab",
        "step_execution_id": "step_execution_0123456789ab",
    }
    valid[field] = value
    with pytest.raises(ValidationError):
        IdentityEnvelope(**valid)
