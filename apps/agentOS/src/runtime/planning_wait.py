"""Check durable readiness conditions without approving reviews or executing work."""

from components.executor import ACGExecutionState
from contracts.execution import WorkflowProgressPhase
from contracts.runtime_planning import RuntimeConditionWake, RuntimePlanningState
from contracts.workflow import WorkflowStatus, TraceEventType, utc_now
from runtime.ports import CollaboratorAccess
from runtime.state_persistence import acg_execution_state_from_run
from support.stores._policy import validate_run_state


class RuntimePlanningWaitService(CollaboratorAccess):
    def __init__(self, *, collaborators, state_machine, validate_references, flush_identity):
        self.ports = collaborators
        self.state_machine = state_machine
        self.validate_references = validate_references
        self.flush_identity = flush_identity

    def prepare(self, run, *, now=None) -> bool:
        """Called under the existing Run lock; persist readiness before submission.

        Returning True also redelivers a wake committed before a process crash.
        Readiness is an observation for Planner, not proof work has succeeded.
        """
        if run.status not in {WorkflowStatus.WAITING_REVIEW, WorkflowStatus.RETRYING}:
            return False
        raw = run.execution_state.get("planningLoop")
        if not isinstance(raw, dict):
            return False
        loop = RuntimePlanningState.model_validate(raw)
        known = {(i.source_run_id, i.operation_id) for i in loop.user_inputs}
        pending = [i for i in self.workflow_store.list_planning_inputs(run.run_id)
                   if (i["sourceRunId"], i["operationId"]) not in known]
        if pending and run.status == WorkflowStatus.RETRYING and not run.execution_state.get("reviewPayload"):
            return True
        if pending and run.status == WorkflowStatus.WAITING_REVIEW:
            current = loop.current
            if not current or not current.decision or current.decision.question:
                return False
            state = self.restore_barrier(run, current.observation_id)
            state.review_payload = None
            state.current_step_id = None
            run.execution_state.update(state.model_dump(by_alias=True, mode="json"))
            run.status = self.state_machine.transition(run.status, WorkflowStatus.RETRYING)
            run.current_step_id = None
            run.runtime_revision += 1
            run.lifecycle_phase = WorkflowProgressPhase.RECOVERY
            run.lifecycle_message = "已收到补充要求，等待 Planner 重新决策"
            run.updated_at = utc_now()
            self.workflow_store.save_run(run)
            return True
        if loop.user_input_pending and run.status == WorkflowStatus.RETRYING:
            if not loop.user_inputs and (not loop.human_answers or loop.human_answers[-1].source_run_id != run.run_id):
                raise ValueError("pending user input has no owned durable answer")
            return True  # A persisted answer is redelivered through the same coordinator.
        waiting = loop.waiting
        if waiting is None:
            return False
        current = loop.current
        if (current is None or current.status != "applied" or current.decision is None
                or current.decision.action != "wait" or current.decision.wait_for != waiting.condition
                or current.observation_id != waiting.observation_id):
            raise ValueError("planning wait is not owned by the applied Planner decision")
        if run.status == WorkflowStatus.RETRYING:
            return waiting.wake is not None
        if waiting.wake is not None:
            raise ValueError("ready planning wait still has a review lifecycle")
        state = self.restore_barrier(run, waiting.observation_id)
        timestamp = now if now is not None else utc_now()
        condition = waiting.condition
        proof = {}
        if condition.kind == "until":
            if timestamp < condition.not_before:
                return False
        else:
            try:
                profile = self.node_service.profile(condition.node_id)
                snapshot = self.node_service.snapshot(condition.node_id)
                health = self.node_service.health(condition.node_id, now=timestamp)
            except KeyError:
                return False
            if (not profile.enabled or health.status.value != "online"
                    or health.last_heartbeat is None or health.last_heartbeat > timestamp
                    or health.consecutive_failures):
                return False
            proof = {"nodeSnapshotVersion": snapshot.version,
                "nodeObservationSequence": snapshot.snapshot.observation_sequence, "nodeHealth": "online"}
        wake = RuntimeConditionWake(observationId=waiting.observation_id, condition=condition,
            checkedAt=timestamp, **proof)
        loop = loop.model_copy(update={"waiting": waiting.model_copy(update={"wake": wake})})
        state.review_payload = None
        state.current_step_id = None
        run.execution_state.update(state.model_dump(by_alias=True, mode="json"))
        run.execution_state["planningLoop"] = loop.model_dump(by_alias=True, mode="json")
        run.current_step_id = None
        run.status = self.state_machine.transition(run.status, WorkflowStatus.RETRYING)
        run.lifecycle_phase = WorkflowProgressPhase.RECOVERY
        run.lifecycle_message = "等待条件已满足，准备由 Planner 重新决策"
        run.runtime_revision += 1
        run.updated_at = utc_now()
        self.trace_store.append(run, TraceEventType.RUNTIME_EVENT_CLASSIFIED,
            observation="Planner wait condition satisfied", payload={
                "runtimeEvent": "planner.runtime.woken", "observationId": waiting.observation_id,
                "conditionKind": condition.kind, **proof,
            })
        self.workflow_store.save_run(run)
        self.flush_identity(raise_on_failure=False)
        return True

    def restore_barrier(self, run, observation_id):
        """Validate a Planner barrier without approving node/control reviews."""
        validate_run_state(run)
        review = run.execution_state.get("reviewPayload") or {}
        if (review.get("subjectType") != "planner" or review.get("reasonCode") != "PLANNER_WAIT"
                or review.get("observationId") != observation_id):
            raise ValueError("automatic wake cannot approve a node or control review")
        state = acg_execution_state_from_run(run)
        raw_checkpoint = self.checkpoint_store.load(run_id=run.run_id, checkpoint_id=state.checkpoint_id)
        if raw_checkpoint is None:
            raise ValueError("planning wait checkpoint is missing")
        checkpoint = ACGExecutionState.model_validate(raw_checkpoint)
        if (checkpoint.run_id != run.run_id or checkpoint.graph_id != state.graph_id
                or checkpoint.graph_version != state.graph_version or checkpoint.review_payload != review
                or checkpoint.output_refs != state.output_refs
                or checkpoint.completed_step_ids != state.completed_step_ids
                or checkpoint.skipped_step_ids != state.skipped_step_ids
                or checkpoint.active_step_ids or state.active_step_ids):
            raise ValueError("planning wait checkpoint no longer matches its barrier")
        self.validate_references(run=run, state=state)
        return state
