"""PR-S01-01: Unified Planner 最小类型化动作协议合同。

设计边界（与 S00-S03 权威划分一致）：

- 本合同只描述“模型侧请求”与“Runtime 侧结果”。权威标识（sessionId、
  actionId、proposalId、候选 semantic key）一律由 Runtime 分配，模型请求中
  出现任何身份字段都会因 ``extra="forbid"`` 被拒绝。
- READ 是封闭投影的只读查询；PROPOSE 只登记候选（candidate tasks、方法建议、
  TaskPlan 修订草案），不创建持久化任务身份、资源绑定、执行图或正式工作承诺。
  登记回执的 ``status`` 恒为 ``registered``，正式落库仍走既有
  RuntimePlanningDecision → SemanticRevisionService（S02 权威）链路。
- 请求/提案里的全部文本都是不可信数据：合同层只做类型与边界校验，结果合同
  只回显指纹，不把不可信内容拼接进任何指令通道。

该协议默认关闭：没有任何生产装配引用本合同（见 components.planner.unified_actions）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from contracts.identity import SemanticTaskKey
from contracts.planning import TaskPlanPatch
from contracts.runtime_planning import RuntimePlanningDecision


PLANNER_ACTION_PROTOCOL_VERSION = 1

ReadTarget = Literal["run_state", "capability_catalog", "evidence_refs"]
ProposalKind = Literal["candidate_tasks", "plan_revision", "method"]

RejectionCode = Literal[
    "PROTOCOL_VERSION_UNSUPPORTED",
    "INVALID_PAYLOAD",
    "UNKNOWN_SESSION",
    "SESSION_REVOKED",
    "BUDGET_EXHAUSTED",
    "DUPLICATE_ACTION",
    "BINDING_MISMATCH",
    "PLAN_VERSION_MISMATCH",
    "STALE_OBSERVATION",
    "UNAUTHORIZED_TARGET",
    "TOOL_TIMEOUT",
    "TOOL_FAILED",
]


def _canonical_fingerprint(payload: dict) -> str:
    import hashlib
    import json

    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PlannerActionContract(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)


# ---------------------------------------------------------------- model side


class PlannerReadQuery(PlannerActionContract):
    """封闭只读查询；v1 没有参数，投影由 Runtime 单方面定义。"""

    target: ReadTarget


class PlannedTaskDraft(PlannerActionContract):
    """不可信候选任务语义。刻意无 key：候选身份由 Runtime 分配。"""

    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=2000)
    capability_id: str = Field(min_length=1, max_length=128, alias="capabilityId")
    rationale: str = Field(default="", max_length=1000)
    acceptance_criteria: tuple[str, ...] = Field(
        default=(), max_length=8, alias="acceptanceCriteria"
    )
    produced_artifacts: tuple[str, ...] = Field(
        default=(), max_length=8, alias="producedArtifacts"
    )
    source_refs: tuple[str, ...] = Field(default=(), max_length=8, alias="sourceRefs")

    @model_validator(mode="after")
    def bounded_text(self):
        if not self.title.strip() or not self.objective.strip():
            raise ValueError("draft title and objective must not be blank")
        for field in ("acceptance_criteria", "produced_artifacts", "source_refs"):
            for item in getattr(self, field):
                if not str(item).strip() or len(str(item)) > 500:
                    raise ValueError(f"draft {field} entries must be non-blank and bounded")
        return self


class PlannerCandidateTasksProposal(PlannerActionContract):
    kind: Literal["candidate_tasks"] = "candidate_tasks"
    tasks: tuple[PlannedTaskDraft, ...] = Field(min_length=1, max_length=16)


class PlannerPlanRevisionProposal(PlannerActionContract):
    """TaskPlan 修订草案。仅复用既有 TaskPlanPatch 合同；登记不等于应用。"""

    kind: Literal["plan_revision"] = "plan_revision"
    patch: TaskPlanPatch


class PlannerMethodProposal(PlannerActionContract):
    """针对既有语义任务的方法建议；capability 必须在可见目录中解析。"""

    kind: Literal["method"] = "method"
    target_key: SemanticTaskKey = Field(alias="targetKey")
    capability_id: str = Field(min_length=1, max_length=128, alias="capabilityId")
    rationale: str = Field(default="", max_length=2000)


class PlannerActionRequest(PlannerActionContract):
    """模型侧唯一输入形态：无任何身份/版本字段，绑定全部来自 Runtime 签发的会话。"""

    request_ref: str = Field(min_length=1, max_length=128, alias="requestRef")
    query: PlannerReadQuery | None = None
    # 判别联合按 kind 收窄；字符串字段里的伪造 JSON 永远只是字符串。
    proposal: (
        PlannerCandidateTasksProposal | PlannerPlanRevisionProposal | PlannerMethodProposal
    ) | None = None

    @model_validator(mode="after")
    def exactly_one_operation(self):
        if (self.query is None) == (self.proposal is None):
            raise ValueError("exactly one of query or proposal is required")
        if not self.request_ref.strip() or any(ch.isspace() for ch in self.request_ref):
            raise ValueError("requestRef must be a single non-whitespace token")
        return self


# -------------------------------------------------------------- runtime side


class PlannerActionEnvelope(PlannerActionContract):
    """Runtime 构造并持有的动作信封；actionId 由 Runtime 分配，绝不来自模型。"""

    protocol_version: Literal[1] = Field(default=1, alias="protocolVersion")
    action_id: str = Field(alias="actionId")
    session_id: str = Field(alias="sessionId")
    request: PlannerActionRequest
    received_at: AwareDatetime = Field(default_factory=utc_now, alias="receivedAt")


class PlannerActionRejection(PlannerActionContract):
    action_id: str = Field(alias="actionId")
    request_ref: str | None = Field(default=None, alias="requestRef")
    code: RejectionCode
    reason: str = Field(min_length=1, max_length=500)
    retryable: bool = True
    replayed: bool = False


class RunStepProjection(PlannerActionContract):
    step_id: str = Field(alias="stepId")
    task_key: str = Field(alias="taskKey")
    status: str
    audit_outcome: str | None = Field(default=None, alias="auditOutcome")
    verification_report: str | None = Field(default=None, alias="verificationReport")
    artifact_count: int = Field(default=0, alias="artifactCount")


class RunStateProjection(PlannerActionContract):
    mission_id: str = Field(alias="missionId")
    run_id: str = Field(alias="runId")
    run_status: str = Field(alias="runStatus")
    graph_id: str = Field(alias="graphId")
    graph_version: int = Field(alias="graphVersion")
    plan_version: int = Field(alias="planVersion")
    observation_id: str = Field(alias="observationId")
    wake_reason: str = Field(alias="wakeReason")
    steps: tuple[RunStepProjection, ...] = ()
    remaining_step_ids: tuple[str, ...] = Field(default=(), alias="remainingStepIds")
    completion_blockers: tuple[str, ...] = Field(default=(), alias="completionBlockers")
    truncated: bool = False


class CapabilityProjection(PlannerActionContract):
    capability_id: str = Field(alias="capabilityId")
    display_name: str = Field(alias="displayName")
    description: str = ""
    planning_stage: str = Field(default="analysis", alias="planningStage")
    depends_on: tuple[str, ...] = Field(default=(), alias="dependsOn")
    optional_dependencies: tuple[str, ...] = Field(default=(), alias="optionalDependencies")
    produces_artifact: bool = Field(default=False, alias="producesArtifact")
    requires_evidence: bool = Field(default=False, alias="requiresEvidence")
    requires_review: bool = Field(default=False, alias="requiresReview")
    risk_level_hint: str = Field(default="normal", alias="riskLevelHint")
    domain_hints: tuple[str, ...] = Field(default=(), alias="domainHints")


class CapabilityCatalogProjection(PlannerActionContract):
    capabilities: tuple[CapabilityProjection, ...] = ()
    count: int = 0
    truncated: bool = False


class EvidenceCheckProjection(PlannerActionContract):
    check: str
    outcome: str


class EvidenceItemProjection(PlannerActionContract):
    step_id: str = Field(alias="stepId")
    task_key: str = Field(alias="taskKey")
    commit_id: str | None = Field(default=None, alias="commitId")
    audit_ref: str | None = Field(default=None, alias="auditRef")
    audit_outcome: str | None = Field(default=None, alias="auditOutcome")
    artifact_refs: tuple[str, ...] = Field(default=(), alias="artifactRefs")
    checks: tuple[EvidenceCheckProjection, ...] = ()


class EvidenceProjection(PlannerActionContract):
    items: tuple[EvidenceItemProjection, ...] = ()
    truncated: bool = False


class PlannerReadResult(PlannerActionContract):
    action_id: str = Field(alias="actionId")
    request_ref: str = Field(alias="requestRef")
    target: ReadTarget
    as_of: AwareDatetime = Field(alias="asOf", default_factory=utc_now)
    replayed: bool = False
    run_state: RunStateProjection | None = Field(default=None, alias="runState")
    capability_catalog: CapabilityCatalogProjection | None = Field(
        default=None, alias="capabilityCatalog"
    )
    evidence: EvidenceProjection | None = None


class RegisteredProposal(PlannerActionContract):
    proposal_id: str = Field(alias="proposalId")
    kind: ProposalKind
    content_fingerprint: str = Field(alias="contentFingerprint")
    assigned_keys: tuple[str, ...] = Field(default=(), alias="assignedKeys")


class PlannerProposalReceipt(PlannerActionContract):
    """登记回执：候选已被记录，未产生任何 TaskPlan/绑定/图/Run 写入。"""

    action_id: str = Field(alias="actionId")
    request_ref: str = Field(alias="requestRef")
    status: Literal["registered"] = "registered"
    replayed: bool = False
    proposals: tuple[RegisteredProposal, ...] = ()


PlannerActionOutcome = PlannerReadResult | PlannerProposalReceipt | PlannerActionRejection


class PlannerToolFeedback(PlannerActionContract):
    """一次工具动作的有界反馈投影；作为不可信数据进入下一轮提示。

    只携带封闭投影、指纹与拒绝码/理由，不携带提案原文、密钥或内部凭证。
    """

    request_ref: str = Field(min_length=1, max_length=128, alias="requestRef")
    outcome: Literal["read", "registered", "rejected"]
    replayed: bool = False
    target: ReadTarget | None = None
    run_state: RunStateProjection | None = Field(default=None, alias="runState")
    capability_catalog: CapabilityCatalogProjection | None = Field(
        default=None, alias="capabilityCatalog"
    )
    evidence: EvidenceProjection | None = None
    registered: tuple[RegisteredProposal, ...] = ()
    rejection_code: RejectionCode | None = Field(default=None, alias="rejectionCode")
    rejection_reason: str | None = Field(default=None, max_length=400, alias="rejectionReason")


class PlannerLoopTurn(PlannerActionContract):
    """PR-S01-02：受限 ReAct 循环中模型每一轮的输出——恰好一个工具动作或最终决策。"""

    turn_kind: Literal["use_tool", "decide"] = Field(alias="turnKind")
    action_request: PlannerActionRequest | None = Field(default=None, alias="actionRequest")
    final_decision: RuntimePlanningDecision | None = Field(default=None, alias="finalDecision")

    @model_validator(mode="after")
    def exactly_one_turn(self):
        if self.turn_kind == "use_tool":
            if self.action_request is None or self.final_decision is not None:
                raise ValueError("use_tool requires exactly one actionRequest and no finalDecision")
        else:
            if self.final_decision is None or self.action_request is not None:
                raise ValueError("decide requires exactly one finalDecision and no actionRequest")
        return self


def proposal_fingerprint(proposal: object) -> str:
    """不可信提案内容的规范指纹；回执与审计只携带指纹，不携带原文。"""

    if isinstance(proposal, PlannerCandidateTasksProposal):
        payload = {"kind": "candidate_tasks", "tasks": [t.model_dump(by_alias=True, mode="json") for t in proposal.tasks]}
    elif isinstance(proposal, PlannerPlanRevisionProposal):
        payload = {"kind": "plan_revision", "patch": proposal.patch.model_dump(by_alias=True, mode="json")}
    elif isinstance(proposal, PlannerMethodProposal):
        payload = {"kind": "method", **proposal.model_dump(by_alias=True, mode="json")}
    else:  # pragma: no cover - closed union
        raise TypeError(f"unsupported proposal type: {type(proposal).__name__}")
    return _canonical_fingerprint(payload)


__all__ = [
    "PLANNER_ACTION_PROTOCOL_VERSION",
    "CapabilityCatalogProjection",
    "CapabilityProjection",
    "EvidenceCheckProjection",
    "EvidenceItemProjection",
    "EvidenceProjection",
    "PlannerActionEnvelope",
    "PlannerActionOutcome",
    "PlannerActionRejection",
    "PlannerActionRequest",
    "PlannerCandidateTasksProposal",
    "PlannerLoopTurn",
    "PlannerMethodProposal",
    "PlannerPlanRevisionProposal",
    "PlannerProposalReceipt",
    "PlannerReadQuery",
    "PlannerReadResult",
    "PlannerToolFeedback",
    "PlannedTaskDraft",
    "RegisteredProposal",
    "RejectionCode",
    "RunStateProjection",
    "RunStepProjection",
    "proposal_fingerprint",
    "utc_now",
]
