"""Strategic decisions over durable ACG facts, separate from executable plans."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from contracts.artifacts import ArtifactEvidence
from contracts.planning import TaskPlanPatch
from contracts.task_acceptance import TaskAcceptanceSpec, TaskAcceptanceResult
from contracts.resource import ExecutionRequirement, ModelDemand


def requirement_fingerprint(requirement: ExecutionRequirement) -> str:
    return hashlib.sha256(json.dumps(requirement.model_dump(by_alias=True, mode="json"),
        sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


class PlanningContract(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)


class RuntimeWaitCondition(PlanningContract):
    """Finite readiness predicates; neither callbacks nor execution approval."""

    kind: Literal["until", "node_available", "requirement_available"]
    not_before: AwareDatetime | None = Field(default=None, alias="notBefore")
    node_id: str | None = Field(default=None, alias="nodeId", min_length=1, max_length=128)
    step_id: str | None = Field(default=None, alias="stepId", min_length=1, max_length=128)
    requirement_id: str | None = Field(default=None, alias="requirementId", min_length=64, max_length=64)
    expires_at: AwareDatetime | None = Field(default=None, alias="expiresAt")

    @model_validator(mode="after")
    def exact_condition(self):
        if self.kind == "requirement_available":
            if (not self.step_id or not self.requirement_id or self.expires_at is None
                    or self.node_id is not None or self.not_before is not None):
                raise ValueError("requirement_available requires only stepId, requirementId and expiresAt")
        elif any(value is not None for value in (self.step_id, self.requirement_id, self.expires_at)):
            raise ValueError("only requirement_available can carry a frozen requirement and deadline")
        if self.kind == "until" and (self.not_before is None or self.node_id is not None):
            raise ValueError("until requires only a timezone-aware notBefore")
        if self.kind == "node_available" and (self.node_id is None or self.not_before is not None):
            raise ValueError("node_available requires only a nodeId")
        return self


class RuntimeConditionWake(PlanningContract):
    observation_id: str = Field(alias="observationId")
    condition: RuntimeWaitCondition
    checked_at: AwareDatetime = Field(alias="checkedAt")
    node_snapshot_version: int | None = Field(default=None, alias="nodeSnapshotVersion")
    node_observation_sequence: int | None = Field(default=None, alias="nodeObservationSequence")
    node_health: Literal["online"] | None = Field(default=None, alias="nodeHealth")
    outcome: Literal["ready", "expired"] | None = None
    runtime_versions: dict[str, int] = Field(default_factory=dict, alias="runtimeVersions")
    node_versions: dict[str, int] = Field(default_factory=dict, alias="nodeVersions")
    model_endpoint_versions: dict[str, int] = Field(default_factory=dict, alias="modelEndpointVersions")

    @model_validator(mode="after")
    def resource_proof(self):
        if self.condition.kind == "requirement_available":
            if self.outcome is None or (self.outcome == "ready" and not self.runtime_versions):
                raise ValueError("resource wake requires readiness evidence or explicit expiry")
        return self


class RuntimePlanningWait(PlanningContract):
    observation_id: str = Field(alias="observationId")
    condition: RuntimeWaitCondition
    armed_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc), alias="armedAt")
    wake: RuntimeConditionWake | None = None

    @model_validator(mode="after")
    def wake_ownership(self):
        if self.wake and (self.wake.observation_id != self.observation_id or self.wake.condition != self.condition):
            raise ValueError("planning wake must belong to its original wait")
        return self


class RuntimeQuestion(PlanningContract):
    prompt: str = Field(min_length=1, max_length=2000)
    choices: tuple[str, ...] = Field(default=(), max_length=5)

    @model_validator(mode="after")
    def valid_choices(self):
        if not self.prompt.strip() or any(not c.strip() or len(c) > 200 for c in self.choices):
            raise ValueError("question and choices must contain bounded text")
        return self


class RuntimeHumanAnswer(PlanningContract):
    question_id: str = Field(alias="questionId")
    source_run_id: str = Field(alias="sourceRunId")
    prompt: str
    answer: str = Field(min_length=1, max_length=2000)
    operation_id: str = Field(alias="operationId")
    answered_at: AwareDatetime = Field(alias="answeredAt")


class StepObservation(PlanningContract):
    step_id: str = Field(alias="stepId")
    task_key: str = Field(alias="taskKey")
    status: str
    output_ref: str | None = Field(default=None, alias="outputRef")
    commit_id: str | None = Field(default=None, alias="commitId")
    audit_ref: str | None = Field(default=None, alias="auditRef")
    audit_outcome: str | None = Field(default=None, alias="auditOutcome")
    # A contract-valid verifier report is an observation, not independent proof.
    verification_report: Literal["passed", "partial", "failed"] | None = Field(
        default=None, alias="verificationReport"
    )
    artifact_refs: tuple[str, ...] = Field(default=(), alias="artifactRefs")
    artifact_evidence: tuple[ArtifactEvidence, ...] = Field(default=(), alias="artifactEvidence")


class RuntimeUserInput(PlanningContract):
    source_run_id: str = Field(alias="sourceRunId")
    operation_id: str = Field(alias="operationId")
    content: str = Field(min_length=1, max_length=4000)
    submitted_at: AwareDatetime = Field(alias="submittedAt")


class RuntimeResourceCandidate(PlanningContract):
    runtime_id: str = Field(alias="runtimeId")
    accepted: bool
    reasons: tuple[str, ...] = ()
    snapshot_version: int = Field(alias="snapshotVersion")


class RuntimeResourceObservation(PlanningContract):
    step_id: str = Field(alias="stepId")
    requirement_id: str = Field(alias="requirementId")
    required_capabilities: tuple[str, ...] = Field(alias="requiredCapabilities")
    runtime_kinds: tuple[str, ...] = Field(alias="runtimeKinds")
    allowed_placements: tuple[str, ...] = Field(alias="allowedPlacements")
    min_trust: str | None = Field(default=None, alias="minTrust")
    domain: str | None = None
    max_cost: float | None = Field(default=None, alias="maxCost")
    max_latency_ms: float | None = Field(default=None, alias="maxLatencyMs")
    allow_remote_execution: bool = Field(default=True, alias="allowRemoteExecution")
    model_demand: ModelDemand | None = Field(default=None, alias="modelDemand")
    ready: bool
    reason: str | None = None
    candidates: tuple[RuntimeResourceCandidate, ...] = Field(default=(), max_length=16)
    candidate_count: int = Field(alias="candidateCount", ge=0)
    node_versions: dict[str, int] = Field(default_factory=dict, alias="nodeVersions")
    model_endpoint_versions: dict[str, int] = Field(default_factory=dict, alias="modelEndpointVersions")


class RuntimeResourceFailover(PlanningContract):
    step_id: str = Field(alias="stepId")
    runtime_id: str = Field(alias="runtimeId")


class RuntimePlanningObservation(PlanningContract):
    mission_id: str = Field(alias="missionId")
    run_id: str = Field(alias="runId")
    graph_id: str = Field(alias="graphId")
    graph_version: int = Field(alias="graphVersion")
    plan_version: int = Field(alias="planVersion")
    checkpoint_id: str | None = Field(default=None, alias="checkpointId")
    wake_reason: Literal["verification", "exhausted", "failure", "resume", "restart", "condition", "user_input"] = Field(alias="wakeReason")
    goal: str
    steps: tuple[StepObservation, ...]
    remaining_step_ids: tuple[str, ...] = Field(alias="remainingStepIds")
    failure_id: str | None = Field(default=None, alias="failureId")
    failure_type: str | None = Field(default=None, alias="failureType")
    failure_reason: str | None = Field(default=None, alias="failureReason")
    failure_source: str | None = Field(default=None, alias="failureSource")
    failure_step_id: str | None = Field(default=None, alias="failureStepId")
    recovery_action: str | None = Field(default=None, alias="recoveryAction")
    failed_step_ids: tuple[str, ...] = Field(default=(), alias="failedStepIds")
    completion_blockers: tuple[str, ...] = Field(default=(), alias="completionBlockers")
    # Resource truth comes from the existing directory/health services, never a model.
    resources: tuple[tuple[str, str], ...] = ()
    resource_requirements: tuple[RuntimeResourceObservation, ...] = Field(default=(), alias="resourceRequirements", max_length=16)
    resource_failovers: tuple[RuntimeResourceFailover, ...] = Field(default=(), alias="resourceFailovers", max_length=16)
    task_acceptance: TaskAcceptanceSpec | None = Field(default=None, alias="taskAcceptance")
    task_acceptance_results: tuple[TaskAcceptanceResult, ...] = Field(default=(), alias="taskAcceptanceResults")
    condition_wake: RuntimeConditionWake | None = Field(default=None, alias="conditionWake")
    human_answers: tuple[RuntimeHumanAnswer, ...] = Field(default=(), alias="humanAnswers", max_length=32)
    user_inputs: tuple[RuntimeUserInput, ...] = Field(default=(), alias="userInputs", max_length=32)

    def fingerprint(self) -> str:
        payload = self.model_dump(by_alias=True, mode="json")
        for key in ("failureReason", "failureSource", "failureStepId", "resourceRequirements", "resourceFailovers"):
            if not payload[key]:
                del payload[key]
        if payload["conditionWake"] is not None:
            for key in ("outcome", "runtimeVersions", "nodeVersions", "modelEndpointVersions"):
                if not payload["conditionWake"][key]:
                    del payload["conditionWake"][key]
            for key in ("stepId", "requirementId", "expiresAt"):
                if payload["conditionWake"]["condition"][key] is None:
                    del payload["conditionWake"]["condition"][key]
        if not payload["humanAnswers"]:
            del payload["humanAnswers"]
        if not payload["userInputs"]:
            del payload["userInputs"]
        if payload["conditionWake"] is None:
            del payload["conditionWake"]
        if payload["taskAcceptance"] is None:
            del payload["taskAcceptance"]
        if not payload["taskAcceptanceResults"]:
            del payload["taskAcceptanceResults"]
        # Preserve fingerprints of existing reference-only rounds on restart.
        for step in payload["steps"]:
            if not step["artifactEvidence"]:
                del step["artifactEvidence"]
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


class RuntimePlanningDecision(PlanningContract):
    observation_id: str = Field(alias="observationId", min_length=1)
    action: Literal["continue", "recover", "revise", "wait", "complete", "abort"]
    reason: str = Field(min_length=1, max_length=1000)
    task_plan_patch: TaskPlanPatch | None = Field(default=None, alias="taskPlanPatch")
    wait_for: RuntimeWaitCondition | None = Field(default=None, alias="waitFor")
    question: RuntimeQuestion | None = None

    @model_validator(mode="after")
    def semantic_patch_only_for_revision(self):
        if (self.action == "revise") != (self.task_plan_patch is not None):
            raise ValueError("revise requires a TaskPlanPatch; other actions cannot carry one")
        if self.wait_for is not None and self.action != "wait":
            raise ValueError("only wait can declare waitFor")
        if self.question is not None and (self.action != "wait" or self.wait_for is not None):
            raise ValueError("a user question requires wait without an automatic condition")
        return self


class RuntimePlanningRound(PlanningContract):
    observation_id: str = Field(alias="observationId")
    observation: RuntimePlanningObservation
    decision: RuntimePlanningDecision | None = None
    status: Literal["observed", "decided", "applied", "rejected"] = "observed"
    rejection: str | None = None


class RuntimePlanningState(PlanningContract):
    version: Literal[1] = 1
    # Mission lineage budget: inherited on both semantic replacement and retry.
    rounds_used: int = Field(default=0, alias="roundsUsed", ge=0)
    max_rounds: int = Field(default=12, alias="maxRounds", ge=1, le=32)
    current: RuntimePlanningRound | None = None
    last_verification_refs: tuple[str, ...] = Field(default=(), alias="lastVerificationRefs")
    restart_pending: bool = Field(default=False, alias="restartPending")
    parent_observation_id: str | None = Field(default=None, alias="parentObservationId")
    waiting: RuntimePlanningWait | None = None
    human_answers: tuple[RuntimeHumanAnswer, ...] = Field(default=(), alias="humanAnswers", max_length=32)
    user_input_pending: bool = Field(default=False, alias="userInputPending")
    user_inputs: tuple[RuntimeUserInput, ...] = Field(default=(), alias="userInputs", max_length=32)


def successor_planning_state(raw: dict, pending_inputs: tuple | list = ()) -> dict:
    """Carry control budget and lineage, never stale run-local observations."""
    state = RuntimePlanningState.model_validate(raw)
    known = {(i.source_run_id, i.operation_id) for i in state.user_inputs}
    pending = tuple(RuntimeUserInput.model_validate(i) for i in pending_inputs
                    if (i["sourceRunId"], i["operationId"]) not in known)
    return RuntimePlanningState(
        roundsUsed=state.rounds_used, maxRounds=state.max_rounds,
        parentObservationId=state.current.observation_id if state.current else state.parent_observation_id,
        humanAnswers=state.human_answers,
        userInputs=(*state.user_inputs, *pending),
        userInputPending=state.user_input_pending or bool(pending),
    ).model_dump(by_alias=True, mode="json")
