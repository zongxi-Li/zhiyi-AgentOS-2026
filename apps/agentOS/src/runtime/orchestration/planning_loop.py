"""Observe -> Planner -> deterministic authority in the existing ACG runtime.

This service owns no graph executor, scheduler, recovery algorithm or conversation.
The current planning round is durable before the model call and before application.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping

from pydantic import ValidationError

from adapters.model.protocols import StructuredGenerationError
from components.executor import ACGExecutionState
from contracts.planning import TaskPlan
from contracts.runtime_planning import (
    RuntimePlanningDecision, RuntimePlanningObservation, RuntimePlanningRound,
    RuntimePlanningState, RuntimePlanningFailure,
    RuntimeUserInput,
)
from contracts.workflow import RuntimeRunRecord, StepStatus, TraceEventType
from runtime.composition.ports import CollaboratorAccess, RuntimeCollaborators
from runtime.orchestration.planning_observation import RuntimePlanningObservationBuilder


REPAIRABLE_PLANNING_REJECTIONS = frozenset({"INVALID_PROPOSAL", "DEPENDENCY_NOT_CLOSED"})


def _planning_failure_diagnostics(exc: Exception) -> tuple[RuntimePlanningFailure, dict]:
    """Preserve typed causes without publishing exception messages or model values."""
    from components.planner.task_decomposer import planning_validation_failures, safe_validation_failures

    current, seen = exc, set()
    code, retryable, structured = None, None, None
    metadata, has_validation_details = {}, False
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        cause_metadata = getattr(current, "metadata", None)
        cause_metadata = cause_metadata if isinstance(cause_metadata, Mapping) else {}
        location = safe_validation_failures([cause_metadata])[0]
        for key in ("stage", "callKey"):
            if key in cause_metadata and location.get(key) == cause_metadata[key]:
                metadata.setdefault(key, location[key])
        for key in ("attemptCount", "retryCount"):
            count = cause_metadata.get(key)
            if type(count) is int and count >= 0:
                metadata.setdefault(key, count)
        has_validation_details |= (isinstance(current, ValidationError)
            or bool(getattr(current, "validation_code", None))
            or bool(cause_metadata.get("validationFailures")))
        for attribute in ("code", "cause_code"):
            candidate = getattr(current, attribute, None)
            if isinstance(candidate, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", candidate):
                if code is None:
                    code = candidate
                elif code.startswith("PLANNER_FORMAL_") and candidate != code:
                    metadata.setdefault("causeCode", candidate)
                break
        if retryable is None and isinstance(getattr(current, "retryable", None), bool):
            retryable = current.retryable
        if structured is None and isinstance(current, StructuredGenerationError):
            structured = current
        current = current.__cause__

    stage = metadata.get("stage", "runtime_decision")
    failures = planning_validation_failures(exc, stage=stage, call_key=metadata.get("callKey", "runtime_decision"))
    if not has_validation_details and not any(item["code"] != "unclassified_validation_error" for item in failures):
        failures = []
    failure = RuntimePlanningFailure(
        errorCode=code or ("PLANNER_DECISION_INVALID" if failures else "PLANNER_UNAVAILABLE"),
        errorType=type(exc).__name__, retryable=bool(retryable), stage=stage, validationFailures=failures,
    )
    diagnostic = {"metadata": metadata} if metadata or structured is not None else {}
    if structured is not None:
        from components.planner.complexity import model_invocation_audit
        diagnostic.update(attempts=structured.attempts, modelAudit=model_invocation_audit(structured.audit))
    return failure, diagnostic


class RuntimePlanningCoordinator(CollaboratorAccess):
    def __init__(
        self, *, collaborators: RuntimeCollaborators, load_goal: Callable[[str], str],
        planner_for_run: Callable, validate_references: Callable,
        apply_decision: Callable[..., Awaitable[str]], guarded_save: Callable,
        decision_gate: Callable | None = None,
        pending_commit_wait: Callable | None = None,
    ):
        self.ports = collaborators
        self.load_goal = load_goal
        self.planner_for_run = planner_for_run
        self.validate_references = validate_references
        self.apply_decision = apply_decision
        self.guarded_save = guarded_save
        self.decision_gate = decision_gate
        self.pending_commit_wait = pending_commit_wait
        # Optional trusted host policy. It requests an observation only; all
        # persisted decisions and application authorities still apply.
        self.observe_progress: Callable[[RuntimeRunRecord, ACGExecutionState], bool] | None = None
        self.observation_builder = RuntimePlanningObservationBuilder(
            collaborators=collaborators, load_goal=load_goal, validate_references=validate_references,
        )

    @staticmethod
    def initialize(run: RuntimeRunRecord) -> None:
        if isinstance(run.execution_state.get("taskPlan"), dict):
            run.execution_state.setdefault("planningLoop", RuntimePlanningState().model_dump(by_alias=True, mode="json"))

    @staticmethod
    def prepare_rejection_feedback(run: RuntimeRunRecord, state: ACGExecutionState, *,
                                   code: str, reason: str, source_observation_id: str | None = None,
                                   proposal_ref: str | None = None) -> RuntimePlanningState:
        """Turn a formal revision denial into the next Planner round's fact.

        The caller owns the Run lock, execution fence and durable save. This
        helper only clears the stale planning/review barrier and prepares a
        fresh observation boundary; it never authorizes, retries or mutates a
        graph. A rejection is retained in the observation so the next Planner
        can repair its semantic proposal with the exact authority feedback.
        """
        loop = RuntimePlanningState.model_validate(run.execution_state.get("planningLoop") or {})
        current = loop.current
        if state.active_step_ids or run.active_step_ids or state.control_frames:
            raise ValueError("planning rejection feedback requires a quiescent planning boundary")
        if ((state.review_payload is not None and state.review_payload.get("subjectType") != "planner")
                or any(step.status in {StepStatus.RUNNING, StepStatus.RETRYING, StepStatus.WAITING_REVIEW}
                       for step in run.steps)):
            raise ValueError("planning rejection feedback cannot resolve active work or node/control review")
        observed_id = source_observation_id or (current.observation_id if current else None)
        if not observed_id:
            raise ValueError("planning rejection feedback requires an observation boundary")
        if current is not None and source_observation_id is not None and current.observation_id != source_observation_id:
            raise ValueError("planning rejection feedback targets a stale observation")
        if not isinstance(code, str) or not code.strip() or not isinstance(reason, str) or not reason.strip():
            raise ValueError("planning rejection feedback requires a code and reason")
        feedback = {"observationId": observed_id, "code": code.strip()[:128], "reason": reason.strip()[:800]}
        if proposal_ref:
            feedback["proposalRef"] = str(proposal_ref)[:256]
        run.execution_state["planningCommitRejection"] = feedback
        run.execution_state.pop("workspaceReviewContinuation", None)
        run.execution_state.pop("reviewPayload", None)
        state.review_payload = None
        state.current_step_id = None
        state.active_step_ids = []
        fresh = loop.model_copy(update={"current": None, "waiting": None,
            "restart_pending": True, "parent_observation_id": observed_id})
        run.execution_state["planningLoop"] = fresh.model_dump(by_alias=True, mode="json")
        run.execution_state.update(state.model_dump(by_alias=True, mode="json"))
        return fresh

    async def boundary(self, run: RuntimeRunRecord, state: ACGExecutionState, reason: str) -> str:
        """Return continue, complete or stop; invoked only with no active workers."""
        while True:
            outcome = await self._boundary_once(run, state, reason)
            if outcome != "replan":
                return outcome
            # A durable formal rejection is new planning evidence, not an
            # external approval requirement. Reuse the same observe/decide/apply
            # loop and let Planner select its next action from current facts.
            reason = "resume"
            await asyncio.sleep(0)

    async def _boundary_once(self, run: RuntimeRunRecord, state: ACGExecutionState, reason: str) -> str:
        raw = run.execution_state.get("planningLoop")
        if not isinstance(raw, dict):
            return "complete" if reason == "exhausted" else "continue"
        loop = RuntimePlanningState.model_validate(raw)
        if self.pending_commit_wait is not None:
            pending = await self.pending_commit_wait(run, state, loop)
            if pending is not None:
                return pending
        if not state.active_step_ids and not state.review_payload and not state.control_frames:
            known = {(item.source_run_id, item.operation_id) for item in loop.user_inputs}
            inputs = tuple(RuntimeUserInput.model_validate(item) for item in self.workflow_store.list_planning_inputs(run.run_id)
                if (item["sourceRunId"], item["operationId"]) not in known)
            if inputs:
                loop = RuntimePlanningState.model_validate(loop.model_copy(update={
                    "user_inputs": (*loop.user_inputs, *inputs), "user_input_pending": True,
                }).model_dump(by_alias=True))
                run.execution_state["planningLoop"] = loop.model_dump(by_alias=True, mode="json")
                reason = "user_input"
        if reason in {"resume", "restart"} and loop.user_input_pending:
            reason = "user_input"
        if reason in {"resume", "restart"} and loop.waiting is not None and loop.waiting.wake is not None:
            reason = "condition"
        if state.active_step_ids and reason in {"resume", "restart"}:
            # Existing node commits are replayed by the node runner with their
            # original idempotency keys, before a fresh observation is formed.
            return "continue"
        if state.active_step_ids or state.review_payload:
            raise ValueError("runtime planning requires a quiescent, resolved execution barrier")
        if reason in {"resume", "restart"}:
            from runtime.orchestration.runtime_recovery import pending_retry_dispatch
            if pending_retry_dispatch(run, state):
                # The retry authority already chose to execute this pending
                # frontier. Review its new results at the normal superstep
                # boundary, rather than asking Planner to re-decide old facts.
                return "continue"
        if reason == "progress":
            if loop.restart_pending:
                reason = "restart"
            elif self.observe_progress is not None and self.observe_progress(run, state):
                reason = "resume"
        if reason == "progress":
            settled = set(state.completed_step_ids) | set(state.skipped_step_ids)
            if all(s.step_id in settled for s in run.steps):
                return "continue"
            refs = self._verification_refs(run, state)
            verified_progress = bool(set(refs) - set(loop.last_verification_refs))
            observed_refs = {
                step.output_ref for step in loop.current.observation.steps
                if step.output_ref is not None
            } if loop.current is not None else set()
            tool_progress = bool(self._tool_output_refs(run, state) - observed_refs)
            workspace_progress = False
            if (run.execution_state.get("workspaceObservations")
                    and set(state.output_refs.values()) - observed_refs):
                from contracts.execution_evidence import workspace_observation_progress
                workspace_progress = any(item.get("complete") is not True for item in
                    workspace_observation_progress(run, self.execution_value_store))
            if not verified_progress and not tool_progress and not workspace_progress:
                return "continue"
            # Explicit verification controls retain local revision authority.
            if state.control_frames:
                return "continue"
            # A committed understanding result also establishes a new planning
            # boundary when workspace scope remains. Supplemental acquisition
            # cannot depend on a tool call that the old plan never declared.
            reason = "verification" if verified_progress else "resume"
            loop = loop.model_copy(update={"last_verification_refs": refs})
        if reason in {"resume", "restart"} and any(s.status == StepStatus.FAILED for s in run.steps):
            reason = "failure"
        replayed_observation = None
        if reason in {"resume", "restart", "failure"} and loop.current and loop.current.status in {"observed", "decided"}:
            previous = loop.current.observation
            replay = self.observe(run, state, previous.wake_reason)
            if not previous.committed_results:
                # Preserve an admitted pre-index observation's identity and
                # saved decision. A fresh boundary receives the new index.
                replay = replay.model_copy(update={"committed_results": ()})
            if not previous.context_catalog:
                replay = replay.model_copy(update={"context_catalog": ()})
            if not previous.resource_requirements and previous.failure_source is None:
                # Rounds written before resource observations retain their
                # original idempotency identity and already-persisted decision.
                replay = replay.model_copy(update={"resource_requirements": (), "resource_failovers": (),
                    "failure_reason": None, "failure_source": None, "failure_step_id": None})
            if replay.fingerprint() == loop.current.observation_id:
                reason = previous.wake_reason
                replayed_observation = previous
        observation = replayed_observation or self.observe(run, state, reason)
        observation_id = observation.fingerprint()
        current = loop.current
        if current is None or current.observation_id != observation_id:
            current = RuntimePlanningRound(observationId=observation_id, observation=observation)
            loop = loop.model_copy(update={"current": current, "restart_pending": False})
            self._save(run, loop, "observed")
        elif current.status == "applied":
            # Replay of the same persisted boundary must not call the model again.
            return "complete" if current.decision.action == "complete" else "stop" if current.decision.action in {"wait", "abort", "revise", "recover"} else "continue"

        if current.decision is None:
            loop = loop.model_copy(update={"rounds_used": loop.rounds_used + 1})
            self._save(run, loop, "requested")
            try:
                planner = self.planner_for_run(run)
                decision = await asyncio.to_thread(
                    planner.decide_runtime, observation=observation,
                    task_plan=TaskPlan.model_validate(run.execution_state["taskPlan"]),
                )
                decision = RuntimePlanningDecision.model_validate(decision)
            except Exception as exc:
                # A technical failure owns a resumable barrier. Keep its typed
                # diagnostic distinct from a model-authored external wait.
                failure, details = _planning_failure_diagnostics(exc)
                current = current.model_copy(update={"failure": failure})
                reason = f"Runtime Planner unavailable: {failure.error_type} ({failure.error_code})"
                diagnostic = {"runtimeEvent": "planner.runtime.failed", "observationId": observation_id,
                    **failure.model_dump(mode="json", by_alias=True), **details}
                self.trace_store.append(run, TraceEventType.RUNTIME_EVENT_CLASSIFIED,
                    observation="Runtime Planner decision failed", payload=diagnostic)
                decision = RuntimePlanningDecision(observationId=observation_id, action="wait", reason=reason)
            if self.decision_gate is not None:
                from runtime.orchestration.workspace_review import record_workspace_review
                record_workspace_review(run, observation, decision, loop)
                decision = await self.decision_gate(run, observation, decision)
            current = current.model_copy(update={"decision": decision, "status": "decided"})
            loop = loop.model_copy(update={"current": current})
            self._save(run, loop, "decided")
        elif self.decision_gate is not None and current.decision.action == "revise":
            decision = await self.decision_gate(run, observation, current.decision)
            if decision != current.decision:
                current = current.model_copy(update={"decision": decision, "status": "decided"})
                loop = loop.model_copy(update={"current": current})
                self._save(run, loop, "decided")
        decision = current.decision
        try:
            self.validate_decision(observation, decision)
            # Commit the applied marker with the actual authority transition. A crash
            # after this call cannot re-apply a semantic replacement or recovery.
            applied_loop = loop.model_copy(update={"current": current.model_copy(update={"status": "applied"})})
            return await self.apply_decision(run, state, observation, decision, applied_loop)
        except (ValueError, KeyError) as exc:
            rejection = f"{type(exc).__name__}: {str(exc)[:500]}"
            rejected = current.model_copy(update={"status": "rejected", "rejection": rejection})
            loop = loop.model_copy(update={"current": rejected})
            self._save(run, loop, "rejected")
            safe_wait = RuntimePlanningDecision(observationId=observation_id, action="wait", reason=f"Deterministic authority rejected Planner decision: {rejection}")
            return await self.apply_decision(run, state, observation, safe_wait, loop)

    def _save(self, run: RuntimeRunRecord, loop: RuntimePlanningState, stage: str) -> None:
        run.execution_state["planningLoop"] = loop.model_dump(by_alias=True, mode="json")
        current = loop.current
        self.trace_store.append(run, TraceEventType.RUNTIME_EVENT_CLASSIFIED,
            observation=f"Runtime planning {stage}", payload={
                "runtimeEvent": f"planner.runtime.{stage}",
                "observationId": current.observation_id if current else None,
                "wakeReason": current.observation.wake_reason if current else None,
                "action": current.decision.action if current and current.decision else None,
                "roundsUsed": loop.rounds_used,
            })
        self.guarded_save(run)

    @staticmethod
    def validate_decision(observation: RuntimePlanningObservation, decision: RuntimePlanningDecision) -> None:
        if problem := observation.decision_error(decision):
            raise ValueError(problem[1])
        if decision.action == "recover":
            from runtime.orchestration.binding import recovery_requires_resource_readiness
            if recovery_requires_resource_readiness(observation):
                fact = next((r for r in observation.resource_requirements
                    if r.step_id == observation.failed_step_ids[0]), None)
                if fact is None or not fact.ready:
                    raise ValueError("Recovery requires currently eligible execution resources")

    def _verification_refs(self, run, state) -> tuple[str, ...]:
        return tuple(sorted(state.output_refs[s.step_id] for s in run.steps
            if s.capability == "verification" and s.step_id in state.output_refs))

    def _tool_output_refs(self, run, state) -> set[str]:
        """Observe only this node frontier's immutable commits, never tool WAL."""
        output_refs = set(state.output_refs.values())
        return {
            commit["outputRef"]
            for commit in self.execution_value_store.list_node_commits(run_id=run.run_id)
            if commit.get("stage") == "committed"
            and commit.get("outputRef") in output_refs
            and commit.get("toolCalls")
        }

    def observe(self, run, state, reason) -> RuntimePlanningObservation:
        return self.observation_builder.observe(run, state, reason)
