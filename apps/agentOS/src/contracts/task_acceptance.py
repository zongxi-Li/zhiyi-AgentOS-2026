"""Caller-owned document requirements, independent of Planner's mutable TaskPlan."""

import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

Scalar = StrictStr | StrictBool | StrictInt | StrictFloat | None


class AcceptanceCriterion(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    criterion_id: str = Field(alias="criterionId", min_length=1, max_length=128)
    artifact_key: str = Field(default="final", alias="artifactKey", min_length=1, max_length=128)
    task_key: str | None = Field(default=None, alias="taskKey", min_length=1, max_length=128)
    pointer: str = Field(max_length=512)
    operator: Literal["exists", "equals", "at_most", "at_least"]
    expected: Scalar = None

    @model_validator(mode="after")
    def validate_predicate(self):
        if self.pointer and not self.pointer.startswith("/"):
            raise ValueError("acceptance pointer must be empty or begin with /")
        if re.search(r"~(?![01])", self.pointer):
            raise ValueError("acceptance pointer contains an invalid JSON Pointer escape")
        if isinstance(self.expected, str) and len(self.expected) > 2048:
            raise ValueError("acceptance expected string exceeds the bounded requirement size")
        if isinstance(self.expected, float) and not math.isfinite(self.expected):
            raise ValueError("acceptance expected number must be finite")
        if self.operator in {"at_most", "at_least"} and type(self.expected) not in {int, float}:
            raise ValueError("numeric acceptance requires a numeric expected value")
        if self.operator == "exists" and self.expected is not None:
            raise ValueError("exists acceptance does not take an expected value")
        if self.operator != "exists" and "expected" not in self.model_fields_set:
            raise ValueError("comparison acceptance requires an explicit expected value")
        return self


class TaskAcceptanceSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    version: Literal[1] = 1
    criteria: tuple[AcceptanceCriterion, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({c.criterion_id for c in self.criteria}) != len(self.criteria):
            raise ValueError("task acceptance criterion ids must be unique")
        return self


class TaskAcceptanceResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    verifier: Literal["json-document.v1"] = "json-document.v1"
    # This checks document assertions, not the external world described by them.
    scope: Literal["document_requirement"] = "document_requirement"
    criterion_id: str = Field(alias="criterionId")
    outcome: Literal["passed", "failed", "unverified"]
    reason: Literal["matched", "predicate_false", "pointer_missing", "type_mismatch",
                    "artifact_missing", "artifact_ambiguous", "review_pending",
                    "unsupported_media_type", "size_limit", "invalid_json", "parser_limit"]
    source_run_id: str | None = Field(default=None, alias="sourceRunId")
    commit_id: str | None = Field(default=None, alias="commitId")
    manifest_id: str | None = Field(default=None, alias="manifestId")
    checksum: str | None = None


def frozen_task_acceptance(run) -> TaskAcceptanceSpec | None:
    """Read the admission snapshot; model plans cannot change or remove it."""
    raw = run.execution_state.get("taskAcceptance")
    submitted = run.input.get("taskAcceptance")
    if raw is None and submitted is None:
        return None
    if raw is None or submitted is None:
        raise ValueError("task acceptance admission snapshot is missing")
    spec = TaskAcceptanceSpec.model_validate(raw)
    # JSON keeps boolean and numeric predicates distinct (True == 1 in Python).
    if spec.model_dump_json(by_alias=True) != TaskAcceptanceSpec.model_validate(submitted).model_dump_json(by_alias=True):
        raise ValueError("task acceptance changed after Run admission")
    return spec
