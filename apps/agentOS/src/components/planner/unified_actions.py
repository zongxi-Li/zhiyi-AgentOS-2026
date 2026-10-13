"""Unified Planner 类型化动作网关（S01-02/03 受控 opt-in 装配）。

本模块实现最小动作协议的 Runtime 侧权威：

- 会话（session）由 Runtime 签发，绑定可信的 Mission/Run/Observation/PlanVersion；
  模型侧请求没有任何身份字段，伪造身份、跨 Mission/Run 引用在合同层就不存在。
- READ 走封闭投影（运行状态 / 能力目录 / 证据引用），只暴露必要字段，不携带
  输出载荷、摘录、密钥或内部凭证。
- PROPOSE 只在会话内登记候选（候选任务、方法建议、TaskPlan 修订草案），由
  Runtime 分配 proposalId 与候选 semantic key；不写 taskPlan、taskBindings、
  图或 Run，正式落库仍归 S02 的 SemanticRevisionService 链路。
- 每个失败都以封闭拒绝码显式返回并写入审计Sink，绝不构造虚假成功。

确定性检查顺序（submit 内固定不变）：

1. 协议版本 → ``PROTOCOL_VERSION_UNSUPPORTED``
2. 载荷严格校验 → ``INVALID_PAYLOAD``
3. 会话存在 → ``UNKNOWN_SESSION``
4. 会话未撤销 → ``SESSION_REVOKED``
5. 预算（动作数/截止期）→ ``BUDGET_EXHAUSTED``
6. 重复 request_ref：同指纹幂等重放，异指纹 → ``DUPLICATE_ACTION``
7. 持久绑定 CAS（Run 存在、Mission 一致、非终态、observationId、planVersion）
   → ``BINDING_MISMATCH`` / ``PLAN_VERSION_MISMATCH`` / ``STALE_OBSERVATION``
8. READ 目标授权 → ``UNAUTHORIZED_TARGET``
9. 执行（超出单动作时限 → ``TOOL_TIMEOUT``，结果丢弃）

步骤 7 发现的世界变化会顺带撤销会话；其后提交统一得到 ``SESSION_REVOKED``。
预算按“每个非重放提交计一次”扣减，拒绝同样计数。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Iterable
from threading import Lock
from time import monotonic as default_monotonic
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from contracts.planner_actions import (
    PLANNER_ACTION_PROTOCOL_VERSION,
    CapabilityCatalogProjection,
    CapabilityProjection,
    EvidenceCheckProjection,
    EvidenceItemProjection,
    EvidenceProjection,
    PlannerActionRejection,
    PlannerActionRequest,
    PlannerActionOutcome,
    PlannerCandidateTasksProposal,
    PlannerMethodProposal,
    PlannerPlanRevisionProposal,
    PlannerProposalReceipt,
    PlannerReadResult,
    RegisteredProposal,
    RunStateProjection,
    RunStepProjection,
    proposal_fingerprint,
)
from contracts.planning import TaskPlan
from contracts.mission_semantic import run_intent_basis
from components.planner.htn import HTNError, htn_planning_enabled
from components.planner.horizon import HorizonError, horizon_planning_enabled
from contracts.horizon import HorizonSelection
from contracts.runtime_planning import RuntimePlanningState
from contracts.workflow import RuntimeRunRecord, WorkflowStatus
from support.acg.capabilities import CapabilityCatalog
from support.stores.workflow_store import WorkflowStore


ALL_READ_TARGETS: frozenset[str] = frozenset({"run_state", "capability_catalog", "evidence_refs", "method_catalog", "planning_frontier", "candidate_horizon"})
_HORIZON_READS = frozenset({"planning_frontier", "candidate_horizon"})
_TERMINAL_RUN_STATUSES = frozenset(
    {WorkflowStatus.FAILED, WorkflowStatus.COMPLETED, WorkflowStatus.CANCELLED, WorkflowStatus.SUPERSEDED}
)
_MAX_STEPS = 256
_MAX_BLOCKERS = 64
_MAX_CAPABILITIES = 256
_MAX_EVIDENCE_ITEMS = 128
_MAX_ARTIFACT_REFS = 16
_MAX_CHECKS = 16


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class RegisteredProposalRecord:
    """会话内登记的候选数据；仅供未来 ReAct/HTN 循环按数据读取。"""

    __slots__ = ("action_id", "proposal", "assigned_keys", "fingerprint", "expansion", "horizon")

    def __init__(self, *, action_id: str, proposal: Any, assigned_keys: tuple[str, ...], fingerprint: str, expansion=None, horizon=None):
        self.action_id = action_id
        self.proposal = proposal
        self.assigned_keys = assigned_keys
        self.fingerprint = fingerprint
        self.expansion = expansion
        self.horizon = horizon


class PlannerActionSession:
    """Runtime 签发的可信会话；模型侧只见到 sessionId 字符串。"""

    def __init__(
        self,
        *,
        session_id: str,
        mission_id: str,
        run_id: str,
        graph_id: str,
        graph_version: int,
        plan_version: int,
        observation_id: str,
        allowed_reads: frozenset[str],
        max_actions: int,
        expires_at_monotonic: float,
    ):
        self.session_id = session_id
        self.mission_id = mission_id
        self.run_id = run_id
        self.graph_id = graph_id
        self.graph_version = graph_version
        self.plan_version = plan_version
        self.observation_id = observation_id
        self.allowed_reads = allowed_reads
        self.max_actions = max_actions
        self.expires_at_monotonic = expires_at_monotonic
        self.actions_used = 0
        self.revoked = False
        self.revoke_reason: str | None = None
        self.htn_catalog_revision: str | None = None
        self.htn_context_fingerprint: str | None = None
        self.htn_used = False
        self.horizon_used = False
        self.horizon_policy_revision: str | None = None
        # request_ref -> (payload fingerprint, terminal outcome)
        self.journal: dict[str, tuple[str, PlannerActionOutcome]] = {}
        self.registered_proposals: list[RegisteredProposalRecord] = []
        # 串行化同一会话的提交/撤销：预算与幂等日志的 check-then-act 必须原子。
        self.lock = Lock()

    @property
    def active(self) -> bool:
        return not self.revoked


class PlannerActionGateway:
    """动作协议入口。默认关闭，仅经 ReAct opt-in 缝隙装配；HTN 独立门控。"""

    def __init__(
        self,
        *,
        workflow_store: WorkflowStore,
        capability_catalog: CapabilityCatalog,
        audit_sink: Callable[[dict[str, Any]], None] | None = None,
        monotonic_clock: Callable[[], float] = default_monotonic,
        per_action_timeout_seconds: float = 5.0,
        default_max_actions: int = 16,
        default_ttl_seconds: float = 600.0,
        htn_selector: Any = None,
        horizon_selector: Any = None,
        cancellation_requested: Callable[[str], bool] | None = None,
    ):
        self.workflow_store = workflow_store
        self.capability_catalog = capability_catalog
        self.audit_sink = audit_sink
        self.monotonic = monotonic_clock
        self.per_action_timeout_seconds = max(0.0, float(per_action_timeout_seconds))
        self.default_max_actions = max(1, int(default_max_actions))
        self.default_ttl_seconds = max(0.001, float(default_ttl_seconds))
        self._sessions: dict[str, PlannerActionSession] = {}
        self._registry_lock = Lock()
        self.htn_selector = htn_selector
        self.horizon_selector = horizon_selector
        self.cancellation_requested = cancellation_requested or (lambda _run_id: False)

    # ------------------------------------------------------------- session

    def open_session(
        self,
        run_id: str,
        *,
        allowed_reads: Iterable[str] | None = None,
        max_actions: int | None = None,
        ttl_seconds: float | None = None,
    ) -> PlannerActionSession:
        """为持久的规划边界签发会话；Run 缺失、终态或无当前轮次时抛 ValueError。"""
        run = self._load_run(run_id)
        if run.status in _TERMINAL_RUN_STATUSES:
            raise ValueError(f"planning action session requires a non-terminal run, got {run.status.value}")
        loop = self._load_loop(run)
        if loop.current is None:
            raise ValueError("planning action session requires a persisted current planning round")
        default_reads = ALL_READ_TARGETS - {"method_catalog"} - _HORIZON_READS
        if self.htn_selector is not None and htn_planning_enabled():
            default_reads = default_reads | {"method_catalog"}
        if self.horizon_selector is not None and horizon_planning_enabled():
            default_reads = default_reads | _HORIZON_READS
        targets = frozenset(allowed_reads) if allowed_reads is not None else default_reads
        unknown = targets - ALL_READ_TARGETS
        if unknown:
            raise ValueError("unknown read targets: " + ", ".join(sorted(unknown)))
        session = PlannerActionSession(
            session_id=_new_id("psess"),
            mission_id=run.mission_id,
            run_id=run.run_id,
            graph_id=loop.current.observation.graph_id,
            graph_version=loop.current.observation.graph_version,
            plan_version=loop.current.observation.plan_version,
            observation_id=loop.current.observation_id,
            allowed_reads=targets,
            max_actions=self.default_max_actions if max_actions is None else max(1, int(max_actions)),
            expires_at_monotonic=self.monotonic() + (
                self.default_ttl_seconds if ttl_seconds is None else max(0.001, float(ttl_seconds))
            ),
        )
        session.htn_catalog_revision = self.htn_selector.catalog.revision if self.htn_selector is not None else None
        if ((self.htn_selector is not None and htn_planning_enabled())
                or (self.horizon_selector is not None and horizon_planning_enabled())):
            session.htn_context_fingerprint = self._htn_context_fingerprint(run)
        if self.horizon_selector is not None:
            session.horizon_policy_revision = self.horizon_selector.policy_revision
        with self._registry_lock:
            self._sessions[session.session_id] = session
        self._audit({"runtimeEvent": "planner.action.session_opened", "sessionId": session.session_id,
                     "runId": session.run_id, "observationId": session.observation_id,
                     "planVersion": session.plan_version, "allowedReads": sorted(targets),
                     "maxActions": session.max_actions})
        return session

    def get_session(self, session_id: str) -> PlannerActionSession | None:
        with self._registry_lock:
            return self._sessions.get(session_id)

    def verify_binding(self, session: PlannerActionSession) -> PlannerActionRejection | None:
        """决策交付前的绑定复核：世界已变则返回拒绝（并撤销会话），否则 None。"""
        with self._registry_lock:
            issued = self._sessions.get(session.session_id) is session
        with session.lock:
            code = None
            if not issued:
                code = "UNKNOWN_SESSION"
            elif session.revoked:
                code = "SESSION_REVOKED"
            elif self.monotonic() > session.expires_at_monotonic:
                self._revoke(session, "session deadline exceeded before decision hand-off")
                code = "BUDGET_EXHAUSTED"
            if code is not None:
                return PlannerActionRejection(
                    actionId=f"pact_verify_{session.session_id}", code=code,
                    reason="planning session is no longer valid for decision hand-off",
                    retryable=False,
                )
            if session.htn_used:
                if not htn_planning_enabled() or self.htn_selector is None:
                    return PlannerActionRejection(actionId=f"pact_verify_{session.session_id}",
                        code="HTN_DISABLED", reason="HTN was disabled before hand-off", retryable=False)
                if session.htn_catalog_revision != self.htn_selector.catalog.revision:
                    return PlannerActionRejection(actionId=f"pact_verify_{session.session_id}",
                        code="HTN_CATALOG_CHANGED", reason="HTN catalog changed before hand-off", retryable=False)
            outcome = self._check_binding(session, f"pact_verify_{session.session_id}", "")
            if session.horizon_used:
                problem = self._check_horizon_result(session, f"pact_verify_{session.session_id}", None, self.monotonic())
                if problem is not None:
                    return problem
            if ((session.htn_used or session.horizon_used) and not isinstance(outcome, PlannerActionRejection)
                    and not self._htn_observation_current(*outcome)):
                self._revoke(session, "HTN observation changed before hand-off")
                return PlannerActionRejection(actionId=f"pact_verify_{session.session_id}",
                    code="STALE_OBSERVATION", reason="HTN observation changed before hand-off", retryable=False)
            return outcome if isinstance(outcome, PlannerActionRejection) else None

    def revoke_session(self, session_id: str, reason: str) -> bool:
        with self._registry_lock:
            session = self._sessions.get(session_id)
        if session is None:
            return False
        with session.lock:
            if session.revoked:
                return False
            self._revoke(session, f"revoked by runtime: {reason[:200]}")
            return True

    # -------------------------------------------------------------- submit

    def submit(
        self,
        session_id: str,
        raw_request: Mapping[str, Any],
        *,
        protocol_version: int = PLANNER_ACTION_PROTOCOL_VERSION,
    ) -> PlannerActionOutcome:
        action_id = _new_id("pact")
        started = self.monotonic()

        def reject(code: str, reason: str, *, retryable: bool = True, request_ref: str | None = None) -> PlannerActionRejection:
            return PlannerActionRejection(actionId=action_id, requestRef=request_ref, code=code,
                                          reason=reason[:500], retryable=retryable)  # type: ignore[arg-type]

        # 1. protocol version
        if protocol_version != PLANNER_ACTION_PROTOCOL_VERSION:
            outcome = reject("PROTOCOL_VERSION_UNSUPPORTED",
                             f"unsupported protocol version {protocol_version}", retryable=False)
            self._finish(action_id, None, "rejected", outcome, started)
            return outcome
        # 2. strict payload validation
        try:
            request = PlannerActionRequest.model_validate(dict(raw_request))
        except (ValidationError, TypeError, ValueError) as exc:
            errors = exc.errors()[:3] if isinstance(exc, ValidationError) else []
            detail = "; ".join(
                f"{'.'.join(str(p) for p in e.get('loc', ()))}: {e.get('msg')}" for e in errors
            ) or f"{type(exc).__name__}: {str(exc)[:200]}"
            best_effort_ref = raw_request.get("requestRef") if isinstance(raw_request, Mapping) else None
            ref = best_effort_ref if isinstance(best_effort_ref, str) and best_effort_ref.strip() else None
            outcome = reject("INVALID_PAYLOAD", f"request failed strict validation: {detail}", retryable=True,
                             request_ref=ref[:128] if ref else None)
            self._finish(action_id, None, "rejected", outcome, started)
            return outcome
        # 3. known session
        with self._registry_lock:
            session = self._sessions.get(session_id)
        if session is None:
            outcome = reject("UNKNOWN_SESSION", "session id was not issued by this runtime", retryable=False,
                             request_ref=request.request_ref)
            self._finish(action_id, None, "rejected", outcome, started)
            return outcome
        # 4-9 run under the session lock: budget, journal and revocation are
        # check-then-act sequences that must stay atomic across threads.
        with session.lock:
            return self._submit_locked(action_id, session, request, started)

    def _submit_locked(
        self, action_id: str, session: PlannerActionSession, request: PlannerActionRequest, started: float,
    ) -> PlannerActionOutcome:
        def reject(code: str, reason: str, *, retryable: bool = True) -> PlannerActionRejection:
            return PlannerActionRejection(actionId=action_id, requestRef=request.request_ref, code=code,
                                          reason=reason[:500], retryable=retryable)  # type: ignore[arg-type]

        # 4. revoked
        if session.revoked:
            outcome = reject("SESSION_REVOKED", f"session revoked: {session.revoke_reason}", retryable=False)
            self._finish(action_id, session, "rejected", outcome, started)
            return outcome
        # 5. budget (count + deadline): once exhausted the session is closed,
        #    idempotent replays included; replays themselves never consume budget
        fingerprint = self._request_fingerprint(request)
        recorded = session.journal.get(request.request_ref)
        replay = recorded is not None and recorded[0] == fingerprint
        if session.actions_used >= session.max_actions:
            outcome = reject("BUDGET_EXHAUSTED",
                             f"action budget exhausted: {session.actions_used}/{session.max_actions}",
                             retryable=False)
            self._finish(action_id, session, "rejected", outcome, started)
            return outcome
        if self.monotonic() > session.expires_at_monotonic:
            self._revoke(session, "session deadline exceeded")
            outcome = reject("BUDGET_EXHAUSTED", "session deadline exceeded", retryable=False)
            self._finish(action_id, session, "rejected", outcome, started)
            return outcome
        is_htn = ((request.query is not None and request.query.target == "method_catalog")
                  or (isinstance(request.proposal, PlannerMethodProposal) and request.proposal.method_id is not None))
        is_horizon = ((request.query is not None and request.query.target in _HORIZON_READS)
                      or isinstance(request.proposal, HorizonSelection))
        if is_horizon or session.horizon_used:
            problem = self._check_horizon_result(session, action_id, request, started)
            if problem is None and is_horizon and any(
                    isinstance(r.proposal, PlannerPlanRevisionProposal) for r in session.registered_proposals):
                problem = reject("PROPOSAL_ONLY", "Horizon cannot share a revision-commit session", retryable=False)
            if problem is not None:
                session.actions_used += 1
                self._finish(action_id, session, "rejected", problem, started)
                return problem
            session.horizon_used = True
        if is_htn or session.htn_used:
            # HTN replay rechecks bindings, feature and catalog before cached results.
            problem = None
            if not htn_planning_enabled() or self.htn_selector is None:
                problem = reject("HTN_DISABLED", "HTN feature is disabled", retryable=False)
            elif session.htn_catalog_revision != self.htn_selector.catalog.revision:
                self._revoke(session, "HTN catalog changed")
                problem = reject("HTN_CATALOG_CHANGED", "HTN catalog changed", retryable=False)
            elif request.query is not None and request.query.target not in session.allowed_reads:
                problem = reject("UNAUTHORIZED_TARGET", "read target is no longer granted", retryable=False)
            elif is_htn and any(isinstance(r.proposal, PlannerPlanRevisionProposal) for r in session.registered_proposals):
                problem = reject("PROPOSAL_ONLY", "HTN cannot share a revision-commit session", retryable=False)
            else:
                binding = self._check_binding(session, action_id, request.request_ref)
                if isinstance(binding, PlannerActionRejection):
                    problem = binding
                elif not self._htn_observation_current(*binding):
                    self._revoke(session, "HTN observation no longer matches persisted facts")
                    problem = reject("STALE_OBSERVATION", "HTN observation no longer matches persisted facts", retryable=False)
            if problem is not None:
                session.actions_used += 1
                self._finish(action_id, session, "rejected", problem, started)
                return problem
            session.htn_used = True
        # 6. duplicate / idempotent replay
        if recorded is not None:
            if replay:
                if session.htn_used:
                    problem = self._check_htn_result(session, action_id, request, started)
                    if problem is not None:
                        self._finish(action_id, session, "rejected", problem, started)
                        return problem
                if session.horizon_used:
                    problem = self._check_horizon_result(session, action_id, request, started)
                    if problem is not None:
                        self._finish(action_id, session, "rejected", problem, started)
                        return problem
                outcome = recorded[1].model_copy(update={"replayed": True})
                self._finish(action_id, session, "replayed", outcome, started)
                return outcome
            session.actions_used += 1
            outcome = reject("DUPLICATE_ACTION",
                             "requestRef was already used with different content", retryable=False)
            self._finish(action_id, session, "rejected", outcome, started)
            return outcome
        session.actions_used += 1
        # 7. durable binding CAS
        binding = self._check_binding(session, action_id, request.request_ref)
        if isinstance(binding, PlannerActionRejection):
            self._finish(action_id, session, "rejected", binding, started)
            return binding
        run, loop = binding
        # 8-9. authorize + execute
        if request.query is not None:
            if request.query.target not in session.allowed_reads:
                outcome = reject("UNAUTHORIZED_TARGET",
                                 f"read target not granted to this session: {request.query.target}",
                                 retryable=False)
                self._finish(action_id, session, "rejected", outcome, started)
                return outcome
            outcome = self._execute_read(action_id, request, run, loop, started)
        else:
            outcome = self._execute_proposal(action_id, request, run, loop, session, started)
        if isinstance(outcome, PlannerActionRejection):
            self._finish(action_id, session, "rejected", outcome, started)
            return outcome
        if session.htn_used:
            # The provider may have taken time or observed a concurrent state change.
            # Recheck before publishing feedback, journaling or registering proposals.
            problem = self._check_htn_result(session, action_id, request, started)
            if problem is not None:
                self._finish(action_id, session, "rejected", problem, started)
                return problem
        if session.horizon_used:
            problem = self._check_horizon_result(session, action_id, request, started)
            if problem is not None:
                self._finish(action_id, session, "rejected", problem, started)
                return problem
        if isinstance(outcome, PlannerProposalReceipt):
            for entry in outcome.proposals:
                session.registered_proposals.append(RegisteredProposalRecord(
                    action_id=action_id, proposal=request.proposal, assigned_keys=entry.assigned_keys,
                    fingerprint=entry.content_fingerprint, expansion=outcome.expansion, horizon=outcome.horizon))
        session.journal[request.request_ref] = (fingerprint, outcome)
        self._finish(action_id, session, "read" if isinstance(outcome, PlannerReadResult) else "registered",
                     outcome, started)
        return outcome

    # -------------------------------------------------------------- checks

    def _check_horizon_result(self, session, action_id, request, started):
        """Revalidate before cache reuse and after computation, with the lock held."""
        def reject(code, reason):
            return PlannerActionRejection(actionId=action_id,
                requestRef=request.request_ref if request else None, code=code,
                reason=reason, retryable=code == "TOOL_TIMEOUT")

        def permissions():
            if self.cancellation_requested(session.run_id):
                self._revoke(session, "Runtime cancellation requested")
                return reject("BINDING_MISMATCH", "Runtime cancellation requested before Horizon publication")
            if not horizon_planning_enabled() or self.horizon_selector is None:
                return reject("HORIZON_DISABLED", "Horizon feature is disabled")
            if session.horizon_policy_revision != self.horizon_selector.policy_revision:
                self._revoke(session, "Horizon policy or capability catalog changed")
                return reject("HORIZON_POLICY_CHANGED", "Horizon policy or capability catalog changed")
            target = request.query.target if request and request.query else "candidate_horizon"
            if target not in session.allowed_reads:
                return reject("UNAUTHORIZED_TARGET", "Horizon read/selection permission withdrawn")
            return None

        if session.revoked:
            return reject("SESSION_REVOKED", "session revoked before Horizon publication")
        problem = permissions()
        if problem is not None:
            return problem
        binding = self._check_binding(session, action_id, request.request_ref if request else "")
        if isinstance(binding, PlannerActionRejection):
            return binding
        if (session.htn_context_fingerprint != self._htn_context_fingerprint(binding[0])
                or not self._horizon_observation_current(*binding)):
            self._revoke(session, "Horizon input snapshot changed")
            return reject("STALE_OBSERVATION", "Horizon input snapshot changed")
        problem = permissions()
        if problem is not None:
            return problem
        if self.monotonic() > session.expires_at_monotonic:
            self._revoke(session, "session expired before Horizon publication")
            return reject("BUDGET_EXHAUSTED", "session expired before Horizon publication")
        if self.monotonic() > started + self.per_action_timeout_seconds:
            return reject("TOOL_TIMEOUT", "Horizon verification exceeded the action deadline")
        # Policy serialization and persistence reads above can yield to cancel().
        # Sample the sticky signal once more after all potentially blocking work.
        if self.cancellation_requested(session.run_id):
            self._revoke(session, "Runtime cancellation requested")
            return reject("BINDING_MISMATCH", "Runtime cancellation requested before Horizon publication")
        return None

    def _check_htn_result(self, session, action_id, request, started):
        """Session lock is already held; this does not acquire it recursively."""
        def reject(code, reason):
            return PlannerActionRejection(actionId=action_id, requestRef=request.request_ref,
                code=code, reason=reason, retryable=code == "TOOL_TIMEOUT")

        if session.revoked:
            return reject("SESSION_REVOKED", "session revoked before result publication")
        if not htn_planning_enabled() or self.htn_selector is None:
            return reject("HTN_DISABLED", "HTN disabled before result publication")
        if session.htn_catalog_revision != self.htn_selector.catalog.revision:
            self._revoke(session, "HTN catalog changed before result publication")
            return reject("HTN_CATALOG_CHANGED", "HTN catalog changed before result publication")
        if request.query is not None and request.query.target not in session.allowed_reads:
            return reject("UNAUTHORIZED_TARGET", "read target withdrawn before result publication")
        binding = self._check_binding(session, action_id, request.request_ref)
        if isinstance(binding, PlannerActionRejection):
            return binding
        if not self._htn_observation_current(*binding):
            self._revoke(session, "HTN observation changed before result publication")
            return reject("STALE_OBSERVATION", "HTN observation changed before result publication")
        # Persistence reads above may have blocked; sample volatile grants/catalog again.
        if not htn_planning_enabled() or self.htn_selector is None:
            return reject("HTN_DISABLED", "HTN disabled before result publication")
        if session.htn_catalog_revision != self.htn_selector.catalog.revision:
            self._revoke(session, "HTN catalog changed before result publication")
            return reject("HTN_CATALOG_CHANGED", "HTN catalog changed before result publication")
        if request.query is not None and request.query.target not in session.allowed_reads:
            return reject("UNAUTHORIZED_TARGET", "read target withdrawn before result publication")
        if self.monotonic() > session.expires_at_monotonic:
            self._revoke(session, "session expired before result publication")
            return reject("BUDGET_EXHAUSTED", "session expired before result publication")
        if self.monotonic() > started + self.per_action_timeout_seconds:
            return reject("TOOL_TIMEOUT", "HTN result verification exceeded the action deadline")
        return None

    def _check_binding(
        self, session: PlannerActionSession, action_id: str, request_ref: str,
    ) -> tuple[RuntimeRunRecord, RuntimePlanningState] | PlannerActionRejection:
        def rejection(code: str, reason: str) -> PlannerActionRejection:
            return PlannerActionRejection(actionId=action_id, code=code, reason=reason[:500],
                                          retryable=False, requestRef=request_ref)  # type: ignore[arg-type]

        try:
            run = self.workflow_store.get_run(session.run_id)
        except KeyError:
            self._revoke(session, "run record no longer exists")
            return rejection("BINDING_MISMATCH", "bound run record no longer exists")
        if run.mission_id != session.mission_id:
            self._revoke(session, "run mission changed")
            return rejection("BINDING_MISMATCH", "run belongs to a different Mission than the session")
        if run.status in _TERMINAL_RUN_STATUSES:
            self._revoke(session, f"run reached terminal status {run.status.value}")
            return rejection("BINDING_MISMATCH", f"run reached terminal status {run.status.value}")
        try:
            loop = self._load_loop(run)
        except ValueError as exc:
            self._revoke(session, "planning loop disappeared")
            return rejection("STALE_OBSERVATION", str(exc))
        if loop.current is None:
            self._revoke(session, "planning round cleared")
            return rejection("STALE_OBSERVATION", "current planning round was cleared")
        if loop.current.observation_id != session.observation_id:
            self._revoke(session, "a newer planning observation exists")
            return rejection("STALE_OBSERVATION",
                             "session observation is no longer the current planning boundary")
        raw_plan = run.execution_state.get("taskPlan")
        try:
            plan = TaskPlan.model_validate(raw_plan) if isinstance(raw_plan, dict) else None
        except ValidationError:
            plan = None
        if plan is None or plan.plan_version != session.plan_version:
            self._revoke(session, "task plan version changed")
            return rejection("PLAN_VERSION_MISMATCH",
                             f"task plan version changed from {session.plan_version}")
        if (session.htn_used or session.horizon_used) and session.htn_context_fingerprint != self._htn_context_fingerprint(run):
            self._revoke(session, "HTN planning context changed")
            return rejection("STALE_OBSERVATION", "HTN planning context changed without a new bound session")
        return run, loop

    @staticmethod
    def _htn_context_fingerprint(run) -> str:
        """Ephemeral content fence, not a persisted planning state or commit token."""
        return _canonical({
            "plan": run.execution_state.get("taskPlan"), "graph": run.acg_blueprint,
            "bindings": run.execution_state.get("taskBindings"),
            "basis": run.execution_state.get("missionIntentBasis"),
            "scope": run.execution_scope.model_dump(mode="json") if run.execution_scope is not None else None,
            "runtimeRevision": run.runtime_revision, "runStatus": run.status.value,
            "steps": [s.model_dump(mode="json", by_alias=True) for s in run.steps],
            "completedStepIds": run.execution_state.get("completedStepIds"),
            "executionInputs": {k: v for k, v in run.execution_state.items() if k != "planningLoop"},
        })

    @staticmethod
    def _horizon_observation_current(run, loop) -> bool:
        """Check persisted observation identity against the actual execution mapping.

        A new session must not bless a self-consistent observation fingerprint
        whose step/task mapping no longer matches the Run's trusted bindings.
        Receipt authority remains the existing Runtime observation builder.
        """
        if not PlannerActionGateway._htn_observation_current(run, loop):
            return False
        observation = loop.current.observation
        bindings = run.execution_state.get("taskBindings") or []
        if not isinstance(bindings, (list, tuple)) or any(not isinstance(b, dict) for b in bindings):
            return False
        mapping = {b.get("acgNodeId"): b.get("planNodeKey") for b in bindings}
        actual_ids = {s.step_id for s in run.steps}
        observed_ids = {s.step_id for s in observation.steps}
        return (observation.run_id == run.run_id and observation.mission_id == run.mission_id
                and len(mapping) == len(bindings) and set(mapping) == actual_ids
                and len(observed_ids) == len(observation.steps) and observed_ids == actual_ids
                and all(mapping[s.step_id] == s.task_key for s in observation.steps))

    @staticmethod
    def _horizon_review_keys(run, observation) -> tuple[str, ...]:
        requiring_review = {s.step_id for s in run.steps if s.requires_review}
        return tuple(s.task_key for s in observation.steps if s.step_id in requiring_review)

    @staticmethod
    def _horizon_control_barrier(run) -> bool:
        # Presence is a conservative hold, not an interpretation of routes,
        # control frames, parallel joins or iteration state. Runtime owns those.
        return any(n.get("nodeType") == "control" for n in (run.acg_blueprint or {}).get("nodes", []))

    @staticmethod
    def _htn_observation_current(run, loop) -> bool:
        observation = loop.current.observation
        blueprint = run.acg_blueprint or {}
        actual_status = {step.step_id: step.status.value for step in run.steps}
        return (observation.fingerprint() == loop.current.observation_id
                and blueprint.get("graphId") == observation.graph_id
                and blueprint.get("version") == observation.graph_version
                and all(actual_status.get(s.step_id) == s.status for s in observation.steps))

    def _execute_read(
        self, action_id: str, request: PlannerActionRequest, run: RuntimeRunRecord,
        loop: RuntimePlanningState, started: float,
    ) -> PlannerActionOutcome:
        target = request.query.target  # type: ignore[union-attr]
        deadline = started + self.per_action_timeout_seconds
        try:
            if target == "run_state":
                projection: Any = self._read_run_state(run, loop)
            elif target == "capability_catalog":
                projection = self._read_capability_catalog()
            elif target == "method_catalog":
                projection = self.htn_selector.query(
                    plan=TaskPlan.model_validate(run.execution_state["taskPlan"]),
                    target_key=request.query.target_key, basis=run_intent_basis(run),
                    observation=loop.current.observation)
            elif target in _HORIZON_READS:
                operation = self.horizon_selector.frontier if target == "planning_frontier" else self.horizon_selector.propose
                projection = operation(plan=TaskPlan.model_validate(run.execution_state["taskPlan"]),
                    basis=run_intent_basis(run), observation=loop.current.observation,
                    run_status=run.status.value, control_barrier=self._horizon_control_barrier(run),
                    review_keys=self._horizon_review_keys(run, loop.current.observation), deadline=deadline)
            else:
                projection = self._read_evidence(loop)
        except HorizonError as exc:
            return PlannerActionRejection(actionId=action_id, requestRef=request.request_ref,
                code="TOOL_TIMEOUT" if str(exc) == "HORIZON_DEADLINE_EXCEEDED" else "HORIZON_REJECTED",
                reason=str(exc), retryable=False)
        except HTNError as exc:
            return PlannerActionRejection(actionId=action_id, requestRef=request.request_ref,
                code="HTN_REJECTED", reason=exc.code, retryable=False)
        except Exception as exc:  # provider failure is an explicit rejection, never fake success
            if target == "method_catalog":
                return PlannerActionRejection(actionId=action_id, requestRef=request.request_ref,
                    code="HTN_REJECTED", reason="HTN_INVALID_TRUSTED_CONTEXT", retryable=False)
            return PlannerActionRejection(actionId=action_id, code="TOOL_FAILED",
                                          reason=f"read provider failed: {type(exc).__name__}: {str(exc)[:200]}",
                                          retryable=True, requestRef=request.request_ref)  # type: ignore[arg-type]
        if self.monotonic() > deadline:
            return PlannerActionRejection(actionId=action_id, code="TOOL_TIMEOUT",
                                          reason=f"read exceeded the {self.per_action_timeout_seconds}s action budget",
                                          retryable=True, requestRef=request.request_ref)  # type: ignore[arg-type]
        result = PlannerReadResult(actionId=action_id, requestRef=request.request_ref, target=target)
        if target == "run_state":
            result = result.model_copy(update={"run_state": projection})
        elif target == "capability_catalog":
            result = result.model_copy(update={"capability_catalog": projection})
        elif target == "method_catalog":
            result = result.model_copy(update={"method_catalog": projection})
        elif target in _HORIZON_READS:
            result = result.model_copy(update={"frontier" if target == "planning_frontier" else "horizon": projection})
        else:
            result = result.model_copy(update={"evidence": projection})
        return result

    def _execute_proposal(
        self, action_id: str, request: PlannerActionRequest, run: RuntimeRunRecord,
        loop: RuntimePlanningState, session: PlannerActionSession, started: float,
    ) -> PlannerActionOutcome:
        proposal = request.proposal
        assert proposal is not None
        plan = TaskPlan.model_validate(run.execution_state["taskPlan"])
        deadline = started + self.per_action_timeout_seconds
        entries: list[RegisteredProposal] = []
        expansion = None
        horizon = None
        if isinstance(proposal, PlannerCandidateTasksProposal):
            for draft in proposal.tasks:
                try:
                    self.capability_catalog.resolve(draft.capability_id)
                except KeyError:
                    return self._payload_rejection(action_id, request,
                        f"candidate capability is not in the visible catalog: {draft.capability_id}")
            assigned = tuple(f"cand:{action_id}:{index}" for index in range(len(proposal.tasks)))
            entries.append(RegisteredProposal(proposalId=_new_id("pprop"), kind="candidate_tasks",
                                              contentFingerprint=proposal_fingerprint(proposal),
                                              assignedKeys=assigned))
            record_keys = assigned
        elif isinstance(proposal, PlannerPlanRevisionProposal):
            if session.htn_used or session.horizon_used:
                return PlannerActionRejection(actionId=action_id, requestRef=request.request_ref,
                    code="PROPOSAL_ONLY", reason="HTN rounds cannot register plan revisions", retryable=False)
            patch = proposal.patch
            if patch.mission_id != session.mission_id:
                return PlannerActionRejection(actionId=action_id, code="BINDING_MISMATCH",
                    reason="revision patch belongs to a different Mission", retryable=False,
                    requestRef=request.request_ref)  # type: ignore[arg-type]
            if patch.base_plan_version != session.plan_version:
                return PlannerActionRejection(actionId=action_id, code="PLAN_VERSION_MISMATCH",
                    reason=f"revision patch bases on plan version {patch.base_plan_version}, session bound to {session.plan_version}",
                    retryable=True, requestRef=request.request_ref)  # type: ignore[arg-type]
            entries.append(RegisteredProposal(proposalId=_new_id("pprop"), kind="plan_revision",
                                              contentFingerprint=proposal_fingerprint(proposal)))
            record_keys = ()
        elif isinstance(proposal, HorizonSelection):
            try:
                horizon = self.horizon_selector.propose(plan=plan, basis=run_intent_basis(run),
                    observation=loop.current.observation, selected_keys=proposal.selected_keys,
                    input_fingerprint=proposal.input_fingerprint, run_status=run.status.value,
                    control_barrier=self._horizon_control_barrier(run),
                    review_keys=self._horizon_review_keys(run, loop.current.observation), deadline=deadline)
            except HorizonError as exc:
                return PlannerActionRejection(actionId=action_id, requestRef=request.request_ref,
                    code="TOOL_TIMEOUT" if str(exc) == "HORIZON_DEADLINE_EXCEEDED" else "HORIZON_REJECTED",
                    reason=str(exc), retryable=False)
            except (ValueError, KeyError):
                return PlannerActionRejection(actionId=action_id, requestRef=request.request_ref,
                    code="HORIZON_REJECTED", reason="HORIZON_INVALID_TRUSTED_CONTEXT", retryable=False)
            entries.append(RegisteredProposal(proposalId=_new_id("pprop"), kind="horizon",
                contentFingerprint=proposal_fingerprint(proposal), assignedKeys=horizon.candidate_keys))
        elif isinstance(proposal, PlannerMethodProposal):
            if proposal.target_key not in {node.key for node in plan.nodes}:
                return self._payload_rejection(action_id, request,
                    f"method target is not a key of the current TaskPlan: {proposal.target_key}")
            if proposal.method_id is not None:
                try:
                    expansion = self.htn_selector.expand(plan=plan, target_key=proposal.target_key,
                        basis=run_intent_basis(run), observation=loop.current.observation,
                        method_id=proposal.method_id, catalog_revision=proposal.catalog_revision,
                        preferred_method_ids=proposal.preferred_method_ids, deadline=deadline)
                except HTNError as exc:
                    return PlannerActionRejection(actionId=action_id, requestRef=request.request_ref,
                        code="HTN_CATALOG_CHANGED" if exc.code == "HTN_CATALOG_CHANGED" else "HTN_REJECTED",
                        reason=exc.code, retryable=False)
                except (ValueError, KeyError):
                    return PlannerActionRejection(actionId=action_id, requestRef=request.request_ref,
                        code="HTN_REJECTED", reason="HTN_INVALID_TRUSTED_CONTEXT", retryable=False)
            else:
                try:
                    self.capability_catalog.resolve(proposal.capability_id)
                except KeyError:
                    return self._payload_rejection(action_id, request,
                        f"method capability is not in the visible catalog: {proposal.capability_id}")
            record_keys = tuple(n.key for n in expansion.nodes if n.key != proposal.target_key) if expansion else ()
            entries.append(RegisteredProposal(proposalId=_new_id("pprop"), kind="method",
                                              contentFingerprint=proposal_fingerprint(proposal), assignedKeys=record_keys))
        else:  # pragma: no cover - closed union
            return self._payload_rejection(action_id, request, "unsupported proposal kind")
        if self.monotonic() > deadline:
            return PlannerActionRejection(actionId=action_id, code="TOOL_TIMEOUT",
                reason=f"proposal validation exceeded the {self.per_action_timeout_seconds}s action budget",
                retryable=True, requestRef=request.request_ref)  # type: ignore[arg-type]
        return PlannerProposalReceipt(actionId=action_id, requestRef=request.request_ref,
                                      proposals=tuple(entries), expansion=expansion, horizon=horizon)

    def _payload_rejection(self, action_id: str, request: PlannerActionRequest, reason: str) -> PlannerActionRejection:
        return PlannerActionRejection(actionId=action_id, code="INVALID_PAYLOAD", reason=reason[:500],
                                      retryable=True, requestRef=request.request_ref)  # type: ignore[arg-type]

    # ------------------------------------------------------------- readers

    def _read_run_state(self, run: RuntimeRunRecord, loop: RuntimePlanningState) -> RunStateProjection:
        observation = loop.current.observation
        steps = tuple(
            RunStepProjection(stepId=step.step_id, taskKey=step.task_key, status=step.status,
                              auditOutcome=step.audit_outcome, verificationReport=step.verification_report,
                              artifactCount=len(step.artifact_refs))
            for step in observation.steps[:_MAX_STEPS]
        )
        blockers = tuple(str(item)[:200] for item in observation.completion_blockers[:_MAX_BLOCKERS])
        return RunStateProjection(
            missionId=observation.mission_id, runId=observation.run_id, runStatus=run.status.value,
            graphId=observation.graph_id, graphVersion=observation.graph_version,
            planVersion=observation.plan_version, observationId=loop.current.observation_id,
            wakeReason=observation.wake_reason, steps=steps,
            remainingStepIds=tuple(observation.remaining_step_ids[:_MAX_STEPS]),
            completionBlockers=blockers, truncated=len(observation.steps) > _MAX_STEPS,
        )

    def _read_capability_catalog(self) -> CapabilityCatalogProjection:
        descriptors = self.capability_catalog.available()
        capabilities = tuple(
            CapabilityProjection(
                capabilityId=descriptor.capability_id, displayName=descriptor.display_name,
                description=str(descriptor.description)[:1000],
                planningStage=descriptor.planning_stage,
                dependsOn=tuple(descriptor.depends_on),
                optionalDependencies=tuple(descriptor.optional_dependencies),
                producesArtifact=descriptor.produces_artifact,
                requiresEvidence=descriptor.requires_evidence,
                requiresReview=descriptor.requires_review,
                riskLevelHint=str(descriptor.risk_level_hint),
                domainHints=tuple(descriptor.domain_hints),
            )
            for descriptor in descriptors[:_MAX_CAPABILITIES]
        )
        return CapabilityCatalogProjection(capabilities=capabilities, count=len(descriptors),
                                           truncated=len(descriptors) > _MAX_CAPABILITIES)

    def _read_evidence(self, loop: RuntimePlanningState) -> EvidenceProjection:
        items = []
        for step in loop.current.observation.steps[:_MAX_EVIDENCE_ITEMS]:
            checks = tuple(
                EvidenceCheckProjection(check=str(check.check), outcome=str(check.outcome))
                for evidence in step.artifact_evidence
                for check in evidence.checks[:_MAX_CHECKS]
            )
            items.append(EvidenceItemProjection(
                stepId=step.step_id, taskKey=step.task_key, commitId=step.commit_id,
                auditRef=step.audit_ref, auditOutcome=step.audit_outcome,
                artifactRefs=tuple(step.artifact_refs[:_MAX_ARTIFACT_REFS]), checks=checks,
            ))
        return EvidenceProjection(items=tuple(items),
                                  truncated=len(loop.current.observation.steps) > _MAX_EVIDENCE_ITEMS)

    # ------------------------------------------------------------- helpers

    def _load_run(self, run_id: str) -> RuntimeRunRecord:
        try:
            return self.workflow_store.get_run(run_id)
        except KeyError as exc:
            raise ValueError(f"planning action session requires an existing run: {run_id}") from exc

    @staticmethod
    def _load_loop(run: RuntimeRunRecord) -> RuntimePlanningState:
        raw = run.execution_state.get("planningLoop")
        if not isinstance(raw, dict):
            raise ValueError("run has no persisted planning loop")
        return RuntimePlanningState.model_validate(raw)

    @staticmethod
    def _request_fingerprint(request: PlannerActionRequest) -> str:
        if request.query is not None:
            return _canonical({"kind": "read", **request.query.model_dump(by_alias=True, mode="json")})
        assert request.proposal is not None
        return proposal_fingerprint(request.proposal)

    def _revoke(self, session: PlannerActionSession, reason: str) -> None:
        session.revoked = True
        session.revoke_reason = reason
        self._audit({"runtimeEvent": "planner.action.session_revoked", "sessionId": session.session_id,
                     "runId": session.run_id, "reason": reason[:200]})

    def _finish(self, action_id: str, session: PlannerActionSession | None, outcome_kind: str,
                outcome: PlannerActionOutcome, started: float) -> None:
        duration_ms = int((self.monotonic() - started) * 1000)
        event: dict[str, Any] = {
            "runtimeEvent": "planner.action",
            "protocolVersion": PLANNER_ACTION_PROTOCOL_VERSION,
            "actionId": action_id,
            "outcome": outcome_kind,
            "durationMs": duration_ms,
        }
        if session is not None:
            event.update({
                "sessionId": session.session_id,
                "actionsUsed": session.actions_used,
                "sessionRevoked": session.revoked,
            })
        if isinstance(outcome, PlannerActionRejection):
            event.update({"kind": "request", "code": outcome.code, "reason": outcome.reason[:200],
                          "requestRef": (outcome.request_ref or "")[:128] or None})
        elif isinstance(outcome, PlannerReadResult):
            event.update({"kind": "read", "target": outcome.target,
                          "requestRef": outcome.request_ref[:128], "replayed": outcome.replayed})
        else:
            event.update({"kind": "propose", "status": outcome.status,
                          "requestRef": outcome.request_ref[:128],
                          "proposalCount": len(outcome.proposals), "replayed": outcome.replayed})
        if isinstance(outcome, (PlannerReadResult, PlannerProposalReceipt)):
            horizon = outcome.horizon
            frontier = horizon.frontier if horizon is not None else (
                outcome.frontier if isinstance(outcome, PlannerReadResult) else None)
            if frontier is not None:
                event["horizonInputFingerprint"] = frontier.input_fingerprint
            if horizon is not None:
                event.update({"candidateCount": len(horizon.candidate_keys),
                    "deferredCount": len(horizon.deferred), "usedCostUnits": horizon.used_cost_units,
                    "usedRiskUnits": horizon.used_risk_units, "selectionBasis": horizon.selection_basis})
        self._audit(event)

    def _audit(self, payload: dict[str, Any]) -> None:
        if self.audit_sink is not None:
            self.audit_sink(dict(payload))


def _canonical(payload: dict) -> str:
    import hashlib
    import json

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = ["PlannerActionGateway", "PlannerActionSession", "RegisteredProposalRecord", "ALL_READ_TARGETS"]
