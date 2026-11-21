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


class RuntimeToolOutcome(PlanningContract):
    """Safe committed call metadata, never proof supplied by an Agent itself."""

    tool: str = Field(min_length=1, max_length=128)
    status: str = Field(max_length=64)
    error_code: str | None = Field(default=None, alias="errorCode", max_length=128)
    receipt_ref: str | None = Field(default=None, alias="receiptRef", max_length=256)


class PlanningResultField(PlanningContract):
    """A complete field address and size, without its generated contents."""

    name: str
    present: bool
    value_type: str = Field(alias="valueType")
    byte_length: int = Field(alias="byteLength", ge=0)
    estimated_tokens: int = Field(alias="estimatedTokens", ge=0)
    item_count: int | None = Field(default=None, alias="itemCount", ge=0)
    purpose: Literal["result", "evidence", "unresolved"] = "result"


class PlanningResultIndexEntry(PlanningContract):
    """An observation's frozen, audited address for one completed Step output."""

    step_id: str = Field(alias="stepId")
    task_key: str = Field(alias="taskKey")
    title: str
    objective: str
    logical_role: str | None = Field(default=None, alias="logicalRole")
    output_ref: str = Field(alias="outputRef")
    commit_id: str = Field(alias="commitId")
    audit_ref: str = Field(alias="auditRef")
    audit_outcome: str = Field(alias="auditOutcome")
    source_run_id: str = Field(alias="sourceRunId")
    source_output_ref: str = Field(alias="sourceOutputRef")
    output_checksum: str = Field(alias="outputChecksum")
    byte_length: int = Field(alias="byteLength", ge=0)
    estimated_tokens: int = Field(alias="estimatedTokens", ge=0)
    fields: tuple[PlanningResultField, ...]
    evidence_refs: tuple[str, ...] = Field(default=(), alias="evidenceRefs")
    unresolved_fields: tuple[str, ...] = Field(default=(), alias="unresolvedFields")
    artifact_refs: tuple[str, ...] = Field(default=(), alias="artifactRefs")
    readable: bool = True
    unavailable_reason: str | None = Field(default=None, alias="unavailableReason")


class PlanningContextIndexEntry(PlanningContract):
    """A frozen address for diagnostic context; status never grants completion."""

    context_ref: str = Field(alias="contextRef")
    context_kind: str = Field(alias="contextKind")
    title: str
    source_run_id: str = Field(alias="sourceRunId")
    step_id: str | None = Field(default=None, alias="stepId")
    attempt_id: str | None = Field(default=None, alias="attemptId")
    operation_id: str | None = Field(default=None, alias="operationId")
    original_ref: str | None = Field(default=None, alias="originalRef")
    status: str
    trust: str
    checksum: str
    byte_length: int = Field(alias="byteLength", ge=0)
    estimated_tokens: int = Field(alias="estimatedTokens", ge=0)
    fields: tuple[PlanningResultField, ...]


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
    # Reports can request review/replanning; only independently checked receipts
    # satisfy an execution-evidence requirement. No arguments/body enter here.
    tool_outcomes: tuple[RuntimeToolOutcome, ...] = Field(default=(), alias="toolOutcomes", max_length=64)


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
    mission_intent_basis_ref: dict | None = Field(default=None, alias="missionIntentBasisRef")
    mission_id: str = Field(alias="missionId")
    run_id: str = Field(alias="runId")
    graph_id: str = Field(alias="graphId")
    graph_version: int = Field(alias="graphVersion")
    plan_version: int = Field(alias="planVersion")
    checkpoint_id: str | None = Field(default=None, alias="checkpointId")
    wake_reason: Literal["verification", "exhausted", "failure", "resume", "restart", "condition", "user_input"] = Field(alias="wakeReason")
    goal: str
    steps: tuple[StepObservation, ...]
    committed_results: tuple[PlanningResultIndexEntry, ...] = Field(default=(), alias="committedResults",
        exclude_if=lambda value: not value)
    context_catalog: tuple[PlanningContextIndexEntry, ...] = Field(default=(), alias="contextCatalog",
        exclude_if=lambda value: not value)
    remaining_step_ids: tuple[str, ...] = Field(alias="remainingStepIds")
    protected_task_keys: tuple[str, ...] = Field(default=(), alias="protectedTaskKeys",
        exclude_if=lambda value: not value)
    failure_id: str | None = Field(default=None, alias="failureId")
    failure_type: str | None = Field(default=None, alias="failureType")
    failure_reason: str | None = Field(default=None, alias="failureReason")
    failure_message: str | None = Field(default=None, alias="failureMessage", max_length=500)
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
    # Host-generated bounded progress; paths are workspace-relative and bodies
    # never enter the strategic planning snapshot.
    workspace_observations: tuple[dict, ...] = Field(default=(), alias="workspaceObservations")
    # Only immutable context references enter the planning journal. Source
    # bodies are loaded separately for the model's admitted planning request.
    workspace_discovery: dict | None = Field(default=None, alias="workspaceDiscovery", exclude_if=lambda value: value is None)
    # Host-owned feedback from a rejected semantic revision.  This is a fact
    # for the next Planner round, never an execution or approval instruction.
    planning_commit_rejection: dict | None = Field(default=None, alias="planningCommitRejection")
    readonly_recovery_proof: dict | None = Field(default=None, alias="readonlyRecoveryProof")
    condition_wake: RuntimeConditionWake | None = Field(default=None, alias="conditionWake")
    human_answers: tuple[RuntimeHumanAnswer, ...] = Field(default=(), alias="humanAnswers")
    user_inputs: tuple[RuntimeUserInput, ...] = Field(default=(), alias="userInputs")

    def decision_error(self, decision: RuntimePlanningDecision) -> tuple[str, str] | None:
        """Share pure decision rules with model correction and final authority.

        Passing this check never applies a decision or accepts an artifact.
        The Runtime still rechecks resource eligibility and current state.
        """
        if decision.observation_id != self.fingerprint():
            return "observationId", "Planner decision observation does not match the current snapshot"
        if decision.action == "complete" and (self.remaining_step_ids or self.completion_blockers):
            return "action", "Planner cannot complete unresolved work"
        if decision.action == "complete" and self.task_acceptance is not None:
            results = {result.criterion_id: result for result in self.task_acceptance_results}
            if any(criterion.criterion_id not in results or results[criterion.criterion_id].outcome != "passed"
                   for criterion in self.task_acceptance.criteria):
                return "action", "Planner cannot complete unverified task acceptance requirements"
        if decision.action == "continue":
            if error := self.continuation_error():
                return "action", error
        if decision.wait_for is not None and decision.wait_for.kind == "node_available":
            if decision.wait_for.node_id not in {node_id for node_id, _ in self.resources}:
                return "waitFor", "Planner wait targets an unobserved node"
        if decision.wait_for is not None and decision.wait_for.kind == "requirement_available":
            condition = decision.wait_for
            fact = next((item for item in self.resource_requirements if item.step_id == condition.step_id), None)
            if (condition.step_id not in self.remaining_step_ids or fact is None
                    or fact.requirement_id != condition.requirement_id or fact.ready):
                return "waitFor", "Planner wait must target a current observed blocked requirement"
        if decision.action == "recover":
            if self.recovery_action not in {"retry", "rebind"} or len(self.failed_step_ids) != 1:
                return "action", "Recovery authority has no supported retry for this failure"
        if decision.action == "revise":
            if self.failure_type in {"policy", "storage"}:
                return "taskPlanPatch", "Semantic revision cannot bypass integrity or policy failures"
            patch = decision.task_plan_patch
            if patch.mission_id != self.mission_id or patch.base_plan_version != self.plan_version:
                return "taskPlanPatch", "Planner revision targets a stale or different TaskPlan"
            if reason := self.revision_error(patch):
                return "taskPlanPatch", reason
        return None

    def continuation_error(self) -> str | None:
        """Keep scheduled corrective work separate from terminal acceptance.

        A failed verification report can be repaired by an already-declared
        downstream task. Integrity, review and failed execution still require
        their existing authorities before the graph can advance.
        """
        if self.wake_reason == "failure" or not self.remaining_step_ids:
            return "Planner cannot continue an exhausted or invalid execution"
        if self.failed_step_ids:
            return "Planner must use Recovery for failed steps"
        if self.failure_type in {"policy", "storage"}:
            return "Planner cannot continue integrity or policy failures"
        if any(blocker.startswith("review_unresolved:") for blocker in self.completion_blockers):
            return "Planner cannot continue unresolved review"
        if any(blocker.startswith(("artifact_unsealed:", "artifact_content_integrity:"))
               for blocker in self.completion_blockers):
            return "Planner cannot continue untrusted artifact evidence"
        repairable = ("verification_failed:", "verification_partial:", "verification_unverified:", "artifact_missing:",
            "artifact_nonempty_content:", "artifact_utf8_text:", "artifact_json_syntax:",
            "expected_artifact_missing:", "task_acceptance_failed:", "task_acceptance_unverified:",
            "workspace_observation_incomplete:")
        if any(not blocker.startswith(repairable) for blocker in self.completion_blockers):
            return "Planner cannot continue unresolved execution evidence"
        return None

    def revision_error(self, patch: TaskPlanPatch) -> str | None:
        if patch.changed_task_keys().intersection(self.protected_task_keys):
            return "started or settled work cannot be changed"
        if self.protected_task_keys and self.failed_step_ids:
            return ("Resolve the failed execution before graph activation. Choose recover when supported, "
                    "otherwise report the blocking failure.")
        return None

    def fingerprint(self) -> str:
        payload = self.model_dump(by_alias=True, mode="json")
        for key in ("failureReason", "failureMessage", "failureSource", "failureStepId", "resourceRequirements", "resourceFailovers"):
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
        if not payload["workspaceObservations"]:
            del payload["workspaceObservations"]
        if payload["planningCommitRejection"] is None:
            del payload["planningCommitRejection"]
        if payload["readonlyRecoveryProof"] is None:
            del payload["readonlyRecoveryProof"]
        # Preserve fingerprints of existing reference-only rounds on restart.
        for step in payload["steps"]:
            if not step["artifactEvidence"]:
                del step["artifactEvidence"]
            if not step["toolOutcomes"]:
                del step["toolOutcomes"]
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


class RuntimePlanningFailure(PlanningContract):
    """Host-recorded diagnostics, never a model proposal or an external wait."""
    error_code: str = Field(alias="errorCode", pattern=r"^[A-Z][A-Z0-9_]{0,127}$")
    error_type: str = Field(alias="errorType")
    retryable: bool = False
    stage: str = "runtime_decision"
    validation_failures: tuple[dict, ...] = Field(default=(), alias="validationFailures")


class RuntimePlanningRound(PlanningContract):
    observation_id: str = Field(alias="observationId")
    observation: RuntimePlanningObservation
    decision: RuntimePlanningDecision | None = None
    status: Literal["observed", "decided", "applied", "rejected"] = "observed"
    rejection: str | None = None
    failure: RuntimePlanningFailure | None = None


class RuntimePlanningState(PlanningContract):
    version: Literal[1] = 1
    # Counters are execution history, never a task-completion condition.
    rounds_used: int = Field(default=0, alias="roundsUsed", ge=0)
    max_rounds: int | None = Field(default=None, alias="maxRounds", ge=1)
    current: RuntimePlanningRound | None = None
    last_verification_refs: tuple[str, ...] = Field(default=(), alias="lastVerificationRefs")
    restart_pending: bool = Field(default=False, alias="restartPending")
    parent_observation_id: str | None = Field(default=None, alias="parentObservationId")
    waiting: RuntimePlanningWait | None = None
    human_answers: tuple[RuntimeHumanAnswer, ...] = Field(default=(), alias="humanAnswers")
    user_input_pending: bool = Field(default=False, alias="userInputPending")
    user_inputs: tuple[RuntimeUserInput, ...] = Field(default=(), alias="userInputs")


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
