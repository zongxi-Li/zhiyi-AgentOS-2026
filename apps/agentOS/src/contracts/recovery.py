"""Failure, recovery plan, and immutable ACG graph patch contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from .planning import TaskBindingPatch, TaskPlanPatch
from support.acg.planning import ACGResourcePlan
from .workflow import GraphRef


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FailureSource(str, Enum):
    SCHEDULER = "scheduler"
    EXECUTOR = "executor"
    COMMUNICATION = "communication"
    MEMORY = "memory"
    EVIDENCE = "evidence"
    AUDIT = "audit"
    CONTROL = "control"
    STORAGE = "storage"


class FailureType(str, Enum):
    TRANSIENT = "transient"
    CAPACITY = "capacity"
    LEASE_EXPIRED = "lease_expired"
    CONTRACT = "contract"
    POLICY = "policy"
    COMMUNICATION = "communication"
    CONTROL = "control"
    STORAGE = "storage"
    PERMANENT = "permanent"


class RecoveryAction(str, Enum):
    RETRY = "retry"
    REBIND = "rebind"
    RESUME = "resume"
    REVIEW = "review"
    ROLLBACK = "rollback"
    PATCH_GRAPH = "patch_graph"
    ABORT = "abort"


class FailureEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    failure_id: StrictStr = Field(alias="failureId", min_length=1)
    subject_ref: StrictStr = Field(alias="subjectRef", min_length=1)
    failure_type: FailureType = Field(alias="failureType")
    source: FailureSource = FailureSource.EXECUTOR
    reason_code: StrictStr = Field(default="UNSPECIFIED", alias="reasonCode", min_length=1)
    message: StrictStr = Field(min_length=1)
    retryable: bool = False
    occurred_at: datetime = Field(default_factory=_utc_now, alias="occurredAt")
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_failure_type(cls, value: Any) -> Any:
        """Keep the wire contract stable while accepting pre-classification reason names."""
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        raw = payload.get("failureType", payload.get("failure_type"))
        if raw is None:
            return payload
        try:
            FailureType(raw)
        except (TypeError, ValueError):
            details = dict(payload.get("details") or {})
            details.setdefault("legacyFailureType", str(raw))
            payload["details"] = details
            payload.setdefault(
                "reasonCode",
                str(details.get("reasonCode") or details.get("reason_code") or raw),
            )
            payload["failureType"] = FailureType.CONTRACT.value
        return payload


class GraphPatchRef(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    patch_id: StrictStr = Field(alias="patchId", min_length=1)
    graph: GraphRef
    uri: StrictStr = Field(min_length=1)
    checksum: StrictStr = Field(min_length=1)


class GraphPatch(BaseModel):
    """A bounded mutation that always creates a new immutable graph revision."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    patch_id: StrictStr = Field(alias="patchId", min_length=1)
    idempotency_key: StrictStr = Field(alias="idempotencyKey", min_length=1)
    run_id: StrictStr = Field(alias="runId", min_length=1)
    graph_id: StrictStr = Field(alias="graphId", min_length=1)
    base_graph_version: int = Field(alias="baseGraphVersion", ge=1)
    add_nodes: list[dict[str, Any]] = Field(default_factory=list, alias="addNodes")
    add_edges: list[dict[str, Any]] = Field(default_factory=list, alias="addEdges")
    remove_edge_ids: list[StrictStr] = Field(default_factory=list, alias="removeEdgeIds")
    retire_node_ids: list[StrictStr] = Field(default_factory=list, alias="retireNodeIds")
    replace_nodes: dict[StrictStr, dict[str, Any]] = Field(default_factory=dict, alias="replaceNodes")
    task_plan_patch: TaskPlanPatch | None = Field(default=None, alias="taskPlanPatch")
    task_binding_patch: TaskBindingPatch | None = Field(default=None, alias="taskNodeBindingPatch")
    resource_plan_patch: ACGResourcePlan | None = Field(default=None, alias="resourcePlanPatch")
    reason: str = ""
    created_at: datetime = Field(default_factory=_utc_now, alias="createdAt")

    def checksum(self) -> str:
        payload = self.model_dump(by_alias=True, mode="json")
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class GraphPatchResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    applied: bool
    idempotent_replay: bool = Field(default=False, alias="idempotentReplay")
    graph_version: int = Field(alias="graphVersion", ge=1)
    run_id: str | None = Field(default=None, alias="runId")
    patch_ref: GraphPatchRef = Field(alias="patchRef")


class RecoveryNodeTemplate(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    logical_name: StrictStr = Field(alias="logicalName", min_length=1)
    name: StrictStr = Field(min_length=1)
    capability: StrictStr = Field(min_length=1)
    input_spec: dict[str, Any] = Field(default_factory=dict, alias="inputSpec")
    output_spec: dict[str, Any] = Field(default_factory=dict, alias="outputSpec")


class RecoveryRecipe(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    recipe_id: StrictStr = Field(alias="recipeId", min_length=1)
    version: StrictStr = Field(min_length=1)
    trigger_failure_types: list[StrictStr] = Field(alias="triggerFailureTypes", min_length=1)
    trigger_reason_codes: list[StrictStr] = Field(default_factory=list, alias="triggerReasonCodes")
    required_capabilities: list[StrictStr] = Field(alias="requiredCapabilities", min_length=1)
    max_applications_per_run: int = Field(default=1, alias="maxApplicationsPerRun", ge=1)
    node_templates: list[RecoveryNodeTemplate] = Field(alias="nodeTemplates", min_length=1)

    def matches(self, failure: FailureEvent) -> bool:
        kinds = {item.strip().lower() for item in self.trigger_failure_types}
        reasons = {item.strip().upper() for item in self.trigger_reason_codes}
        reason = failure.reason_code.upper()
        legacy = str(failure.details.get("legacyFailureType", "")).lower()
        kind_match = failure.failure_type.value in kinds or legacy in kinds
        return kind_match and (
            not reasons or "*" in reasons or reason in reasons
        )


class RecoveryPlan(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    plan_id: StrictStr = Field(alias="planId", min_length=1)
    failure_id: StrictStr = Field(alias="failureId", min_length=1)
    strategy: RecoveryAction
    graph_patch: GraphPatchRef | None = Field(default=None, alias="graphPatch")
    steps: list[StrictStr] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now, alias="createdAt")


__all__ = [
    "FailureEvent", "FailureSource", "FailureType", "GraphPatch", "GraphPatchRef",
    "GraphPatchResult", "RecoveryAction", "RecoveryNodeTemplate", "RecoveryPlan",
    "RecoveryRecipe",
]
