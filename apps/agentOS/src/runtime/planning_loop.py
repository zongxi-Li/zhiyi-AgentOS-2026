"""Observe -> Planner -> deterministic authority in the existing ACG runtime.

This service owns no graph executor, scheduler, recovery algorithm or conversation.
The current planning round is durable before the model call and before application.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from components.executor import ACGExecutionState
from contracts.planning import TaskPlan
from contracts.runtime_planning import (
    RuntimePlanningDecision, RuntimePlanningObservation, RuntimePlanningRound,
    RuntimePlanningState,
    RuntimeUserInput,
)
from contracts.workflow import RuntimeRunRecord, StepStatus, TraceEventType
from runtime.ports import CollaboratorAccess, RuntimeCollaborators
from runtime.planning_observation import RuntimePlanningObservationBuilder


class RuntimePlanningCoordinator(CollaboratorAccess):
    def __init__(
        self, *, collaborators: RuntimeCollaborators, load_goal: Callable[[str], str],
        planner_for_run: Callable, validate_references: Callable,
        apply_decision: Callable[..., Awaitable[str]], guarded_save: Callable,
    ):
        self.ports = collaborators
        self.load_goal = load_goal
        self.planner_for_run = planner_for_run
        self.validate_references = validate_references
        self.apply_decision = apply_decision
        self.guarded_save = guarded_save
        self.observation_builder = RuntimePlanningObservationBuilder(
            collaborators=collaborators, load_goal=load_goal, validate_references=validate_references,
        )

    @staticmethod
    def initialize(run: RuntimeRunRecord) -> None:
        if isinstance(run.execution_state.get("taskPlan"), dict):
            run.execution_state.setdefault("planningLoop", RuntimePlanningState().model_dump(by_alias=True, mode="json"))

    async def boundary(self, run: RuntimeRunRecord, state: ACGExecutionState, reason: str) -> str:
        """Return continue, complete or stop; invoked only with no active workers."""
        raw = run.execution_state.get("planningLoop")
        if not isinstance(raw, dict):
            return "complete" if reason == "exhausted" else "continue"
        loop = RuntimePlanningState.model_validate(raw)
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
        if reason == "progress":
            if loop.restart_pending:
                reason = "restart"
        if reason == "progress":
            settled = set(state.completed_step_ids) | set(state.skipped_step_ids)
            if all(s.step_id in settled for s in run.steps):
                return "continue"
            refs = self._verification_refs(run, state)
            if not set(refs) - set(loop.last_verification_refs):
                return "continue"
            # Bounded verification controls retain local revision authority.
            if state.control_frames:
                return "continue"
            reason = "verification"
            loop = loop.model_copy(update={"last_verification_refs": refs})
        if reason in {"resume", "restart"} and any(s.status == StepStatus.FAILED for s in run.steps):
            reason = "failure"
        replayed_observation = None
        if reason in {"resume", "restart", "failure"} and loop.current and loop.current.status in {"observed", "decided"}:
            previous = loop.current.observation
            replay = self.observe(run, state, previous.wake_reason)
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
            if loop.rounds_used >= loop.max_rounds:
                decision = RuntimePlanningDecision(observationId=observation_id, action="wait", reason="Runtime planning budget exhausted")
            else:
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
                    # Persist a safe wait, not a speculative fallback plan or raw model text.
                    decision = RuntimePlanningDecision(observationId=observation_id, action="wait", reason=f"Runtime Planner unavailable: {type(exc).__name__}")
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
            rejected = current.model_copy(update={"status": "rejected", "rejection": type(exc).__name__})
            loop = loop.model_copy(update={"current": rejected})
            self._save(run, loop, "rejected")
            safe_wait = RuntimePlanningDecision(observationId=observation_id, action="wait", reason="Deterministic authority rejected Planner decision")
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
        if decision.observation_id != observation.fingerprint():
            raise ValueError("Planner decision observation does not match the current snapshot")
        if decision.action == "complete" and (observation.remaining_step_ids or observation.completion_blockers):
            raise ValueError("Planner cannot complete unresolved work")
        if decision.action == "complete" and observation.task_acceptance is not None:
            results = {r.criterion_id: r for r in observation.task_acceptance_results}
            if any(c.criterion_id not in results or results[c.criterion_id].outcome != "passed"
                   for c in observation.task_acceptance.criteria):
                raise ValueError("Planner cannot complete unverified task acceptance requirements")
        if decision.action == "continue" and (observation.wake_reason == "failure" or not observation.remaining_step_ids or observation.completion_blockers):
            raise ValueError("Planner cannot continue an exhausted or invalid execution")
        if decision.action == "continue" and observation.failed_step_ids:
            raise ValueError("Planner must use Recovery for failed steps")
        if decision.wait_for is not None and decision.wait_for.kind == "node_available":
            if decision.wait_for.node_id not in {node_id for node_id, _ in observation.resources}:
                raise ValueError("Planner wait targets an unobserved node")
        if decision.wait_for is not None and decision.wait_for.kind == "requirement_available":
            condition = decision.wait_for
            fact = next((r for r in observation.resource_requirements if r.step_id == condition.step_id), None)
            if (condition.step_id not in observation.remaining_step_ids or fact is None
                    or fact.requirement_id != condition.requirement_id or fact.ready):
                raise ValueError("Planner wait must target a current observed blocked requirement")
        if decision.action == "recover":
            if observation.recovery_action not in {"retry", "rebind"} or len(observation.failed_step_ids) != 1:
                raise ValueError("Recovery authority has no supported retry for this failure")
            if observation.failure_source == "scheduler":
                fact = next((r for r in observation.resource_requirements
                    if r.step_id == observation.failed_step_ids[0]), None)
                if fact is None or not fact.ready:
                    raise ValueError("Scheduler recovery requires currently eligible resources")
        if decision.action == "revise":
            if observation.failure_type in {"policy", "storage"}:
                raise ValueError("Semantic revision cannot bypass integrity or policy failures")
            patch = decision.task_plan_patch
            if patch.mission_id != observation.mission_id or patch.base_plan_version != observation.plan_version:
                raise ValueError("Planner revision targets a stale or different TaskPlan")

    def _verification_refs(self, run, state) -> tuple[str, ...]:
        return tuple(sorted(state.output_refs[s.step_id] for s in run.steps
            if s.capability == "verification" and s.step_id in state.output_refs))

    def observe(self, run, state, reason) -> RuntimePlanningObservation:
        return self.observation_builder.observe(run, state, reason)
