"""Check durable readiness conditions without approving reviews or executing work."""

from components.executor import ACGExecutionState
from contracts.execution import WorkflowProgressPhase
from contracts.runtime_planning import RuntimeConditionWake, RuntimePlanningState, requirement_fingerprint
from contracts.workflow import WorkflowStatus, TraceEventType, utc_now
from runtime.binding import assess_run_requirement, effective_recovery_requirement
from runtime.ports import CollaboratorAccess
from runtime.state_persistence import acg_execution_state_from_run
from runtime.workspace_review_execution import automatic_workspace_review, retire_stale_workspace_continuation
from support.stores._policy import validate_run_state


class RuntimePlanningWaitService(CollaboratorAccess):
    def __init__(self, *, collaborators, state_machine, state_persistence, validate_references, flush_identity):
        self.ports = collaborators
        self.state_machine = state_machine
        self.state_persistence = state_persistence
        self.validate_references = validate_references
        self.flush_identity = flush_identity

    @staticmethod
    def is_resource_wait(run) -> bool:
        """A plain automatic workspace wait can observe changed resource facts.

        This does not invent a model-authored waitFor or approve its next action.
        Manual questions, rejected decisions and node/control reviews keep their
        existing owners.
        """
        if not automatic_workspace_review(run):
            return False
        if (run.execution_state.get("reviewPayload") or {}).get("reasonCode") == "PLANNER_UNAVAILABLE":
            return False
        raw = run.execution_state.get("planningLoop") or {}
        current = raw.get("current") or {}
        decision = current.get("decision") or {}
        observation = current.get("observation") or {}
        return bool(not raw.get("waiting") and current.get("status") == "applied"
            and decision.get("action") == "wait" and not decision.get("waitFor")
            and not decision.get("question") and any(not fact.get("ready")
                and fact.get("stepId") in observation.get("remainingStepIds", ())
                for fact in observation.get("resourceRequirements", ())))

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
            self.release_barrier(run, state, loop, message="已收到补充要求，等待 Planner 重新决策")
            self.workflow_store.save_run(run)
            return True
        if loop.user_input_pending and run.status == WorkflowStatus.RETRYING:
            if not loop.user_inputs and (not loop.human_answers or loop.human_answers[-1].source_run_id != run.run_id):
                raise ValueError("pending user input has no owned durable answer")
            return True  # A persisted answer is redelivered through the same coordinator.
        waiting = loop.waiting
        if waiting is None:
            return self.prepare_resource_wait(run, loop, now=now)
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
        elif condition.kind == "requirement_available":
            if condition.step_id in set(state.completed_step_ids) | set(state.skipped_step_ids):
                raise ValueError("resource wait targets settled work")
            requirement = effective_recovery_requirement(run, condition.step_id)
            if requirement_fingerprint(requirement) != condition.requirement_id:
                raise ValueError("resource wait requirement changed after arming")
            if timestamp >= condition.expires_at:
                proof = {"outcome": "expired"}
            else:
                readiness = assess_run_requirement(self, run, requirement, now=timestamp)
                if not readiness.ready:
                    return False
                accepted = readiness.available_runtime_ids[:16]
                nodes = {self.resource_plane.runtime(runtime_id).node_id for runtime_id in accepted}
                proof = {"outcome": "ready",
                    "runtimeVersions": {r: readiness.runtime_versions[r] for r in accepted},
                    "nodeVersions": {n: readiness.node_versions[n] for n in sorted(nodes)},
                    "modelEndpointVersions": dict(list(readiness.model_endpoint_versions.items())[:16])}
        else:
            try:
                profile = self.resource_plane.node(condition.node_id)
                snapshot = self.resource_plane.node_snapshot(condition.node_id)
                health = self.resource_plane.node_health(condition.node_id, now=timestamp)
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
        self.release_barrier(run, state, loop, message="等待条件已满足，准备由 Planner 重新决策")
        self.trace_store.append(run, TraceEventType.RUNTIME_EVENT_CLASSIFIED,
            observation="Planner wait condition satisfied", payload={
                "runtimeEvent": "planner.runtime.woken", "observationId": waiting.observation_id,
                "conditionKind": condition.kind, **proof,
            })
        self.workflow_store.save_run(run)
        self.flush_identity(raise_on_failure=False)
        return True

    def prepare_resource_wait(self, run, loop, *, now=None) -> bool:
        if not self.is_resource_wait(run):
            return False
        if run.status == WorkflowStatus.RETRYING:
            return bool(loop.restart_pending and not run.execution_state.get("reviewPayload"))
        current = loop.current
        state = self.restore_barrier(run, current.observation_id)
        observation = current.observation
        if (observation.fingerprint() != current.observation_id
                or current.decision.observation_id != current.observation_id
                or observation.run_id != run.run_id or observation.mission_id != run.mission_id
                or observation.graph_id != state.graph_id or observation.graph_version != state.graph_version):
            raise ValueError("resource observation does not own the current planning barrier")
        settled = set(state.completed_step_ids) | set(state.skipped_step_ids)
        blocked = [fact for fact in observation.resource_requirements
            if not fact.ready and fact.step_id in observation.remaining_step_ids]
        requirements = []
        for fact in blocked:
            if fact.step_id in settled:
                raise ValueError("resource observation targets settled work")
            requirement = effective_recovery_requirement(run, fact.step_id)
            if requirement_fingerprint(requirement) != fact.requirement_id:
                raise ValueError("resource observation requirement changed after waiting")
            requirements.append((fact.step_id, requirement))
        timestamp = now if now is not None else utc_now()
        restored = [step_id for step_id, requirement in requirements
            if assess_run_requirement(self, run, requirement, now=timestamp).ready]
        if not restored:
            return False
        # The next native boundary rebuilds resource observations. Keep the
        # applied decision intact as history; readiness grants no retry/execute.
        loop = loop.model_copy(update={"restart_pending": True})
        self.release_barrier(run, state, loop, message="资源状态已恢复，准备由 Planner 重新审查")
        self.trace_store.append(run, TraceEventType.RUNTIME_EVENT_CLASSIFIED,
            observation="Blocked workspace resources are available for a fresh Planner observation",
            payload={"runtimeEvent": "planner.runtime.woken", "observationId": current.observation_id,
                "wakeSource": "resource_observation", "readyStepIds": restored})
        self.workflow_store.save_run(run)
        self.flush_identity(raise_on_failure=False)
        return True

    def release_barrier(self, run, state, loop, *, message):
        """Commit the cleared native checkpoint before exposing a durable wake.

        Checkpoint-first saves can survive a lost acknowledgement. Replay can
        adopt exactly that target body, never an unrelated checkpoint head.
        """
        original_checkpoint_id = state.checkpoint_id
        state.review_payload = None
        state.current_step_id = None
        state.checkpoint_transition_key = f"planner-wake:{original_checkpoint_id}"
        latest_id, latest = self.checkpoint_store.load_latest(run_id=run.run_id)
        proposed = state.model_dump(by_alias=True, mode="json")
        if (latest_id != original_checkpoint_id
                and dict(latest, checkpointId=None) != dict(proposed, checkpointId=None)):
            raise ValueError("planning wake found an unrelated checkpoint head")
        self.state_persistence.save_checkpoint(run, state)
        retired = retire_stale_workspace_continuation(run, value_store=self.execution_value_store,
            step_id=state.graph_id, operation_id=state.checkpoint_transition_key)
        if retired is not None:
            self.trace_store.append(run, TraceEventType.RUNTIME_EVENT_CLASSIFIED,
                observation="Superseded blocked review proposal archived at the current Planner wake",
                payload={"runtimeEvent": "planner.runtime.continuation_retired", **retired})
        run.execution_state.update(state.model_dump(by_alias=True, mode="json"))
        run.execution_state["planningLoop"] = loop.model_dump(by_alias=True, mode="json")
        run.current_step_id = None
        run.status = self.state_machine.transition(run.status, WorkflowStatus.RETRYING)
        run.lifecycle_phase = WorkflowProgressPhase.RECOVERY
        run.lifecycle_message = message
        run.runtime_revision += 1
        run.updated_at = utc_now()

    def restore_barrier(self, run, observation_id):
        """Validate a Planner barrier without approving node/control reviews."""
        validate_run_state(run)
        review = run.execution_state.get("reviewPayload") or {}
        if (review.get("subjectType") != "planner" or review.get("reasonCode") not in {"PLANNER_WAIT", "PLANNER_UNAVAILABLE"}
                or review.get("observationId") != observation_id):
            raise ValueError("automatic wake cannot approve a node or control review")
        state = acg_execution_state_from_run(run)
        raw_checkpoint = self.checkpoint_store.load(run_id=run.run_id, checkpoint_id=state.checkpoint_id)
        if raw_checkpoint is None:
            raise ValueError("planning wait checkpoint is missing")
        checkpoint = ACGExecutionState.model_validate(raw_checkpoint)
        if checkpoint != state or state.active_step_ids:
            raise ValueError("planning wait checkpoint no longer matches its barrier")
        self.validate_references(run=run, state=state)
        return state
