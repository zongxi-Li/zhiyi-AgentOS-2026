"""Apply strategic proposals through existing deterministic runtime authorities.

Called under the facade's short run lock. It neither invokes a model nor owns
execution, locking, graph mutation algorithms or a second lifecycle.
"""

from datetime import timedelta

from contracts.execution import WorkflowProgressPhase
from contracts.recovery import GraphPatchResult, SemanticPatchRequest
from contracts.runtime_planning import RuntimePlanningWait, requirement_fingerprint
from contracts.resource import ExecutionRequirement
from contracts.workflow import WorkflowStatus, utc_now
from runtime.ports import CollaboratorAccess


class RuntimePlanningApplication(CollaboratorAccess):
    def __init__(self, *, collaborators, state_persistence, recovery, binding,
                 semantic_revision, mission_manager, set_lifecycle, flush_identity):
        self.ports = collaborators
        self.state_persistence = state_persistence
        self.recovery = recovery
        self.binding = binding
        self.semantic_revision = semantic_revision
        self.mission_manager = mission_manager
        self.set_lifecycle = set_lifecycle
        self.flush_identity = flush_identity

    def apply(self, run, state, observation, decision, loop) -> str:
        waiting = None
        if decision.wait_for is not None:
            if decision.wait_for.kind == "node_available":
                self.resource_plane.node(decision.wait_for.node_id)
            if decision.wait_for.kind == "requirement_available":
                condition = decision.wait_for
                now = utc_now()
                if not now < condition.expires_at <= now + timedelta(hours=24):
                    raise ValueError("resource wait deadline must be within the next 24 hours")
                requirement = ExecutionRequirement.model_validate(
                    run.execution_state["bindingRequirements"][condition.step_id])
                if requirement_fingerprint(requirement) != condition.requirement_id:
                    raise ValueError("resource wait targets a changed frozen requirement")
            waiting = RuntimePlanningWait(observationId=observation.fingerprint(), condition=decision.wait_for)
        loop = loop.model_copy(update={"waiting": waiting, "user_input_pending": False})
        run.execution_state["planningLoop"] = loop.model_dump(by_alias=True, mode="json")
        if decision.action in {"continue", "complete"}:
            run.runtime_revision += 1
            run.updated_at = utc_now()
            self.workflow_store.save_run(run)
            return "complete" if decision.action == "complete" else "continue"
        if decision.action == "abort":
            self.workflow_store.save_run(run)
            failed = self.recovery.fail_run_safely(
                run.run_id, error_code="planner_aborted", error_message=decision.reason,
            )
            run.__dict__.update(failed.__dict__)
            return "stop"
        if decision.action == "recover":
            if observation.failure_source == "scheduler":
                requirement = ExecutionRequirement.model_validate(
                    run.execution_state["bindingRequirements"][observation.failed_step_ids[0]])
                fact = next(r for r in observation.resource_requirements
                    if r.step_id == observation.failed_step_ids[0])
                if (requirement_fingerprint(requirement) != fact.requirement_id
                        or not self.resource_binder.assess(requirement).ready):
                    raise ValueError("resource eligibility changed while Planner was deciding")
            # Reuse the Recovery authority's full validation before terminalizing
            # the source. A rejected proposal must leave a recoverable wait barrier.
            self.recovery.prepare_single_step_retry(
                run.run_id, observation.failed_step_ids[0], reason="runtime_planner",
                reuse_source_run=True, validate_only=True,
            )
            # Approval of a Planner barrier is not approval of failed work.
            # Clear only the already-resolved planning marker for retry validation.
            run.execution_state["reviewPayload"] = None
            self.workflow_store.save_run(run)
            self.recovery.fail_run_safely(
                run.run_id, error_code="acg_execution_failed", error_message="Planner requested deterministic recovery",
            )
            recovered = self.recovery.prepare_single_step_retry(
                run.run_id, observation.failed_step_ids[0], reason="runtime_planner",
                idempotency_key=f"planner:{observation.fingerprint()}",
                idempotency_fingerprint=observation.fingerprint(), reuse_source_run=True,
            )
            run.__dict__.update(recovered.__dict__)
            return "stop"
        # Strategic wait/revision is a durable planning barrier in the existing
        # review lifecycle. It cannot masquerade as approval of a node/control.
        state.review_payload = {
            "subjectType": "planner", "subjectId": state.graph_id,
            "observationId": observation.fingerprint(), "reason": decision.reason,
            "reasonCode": "PLANNER_REVISION" if decision.action == "revise" else "PLANNER_WAIT",
            "question": decision.question.model_dump(mode="json") if decision.question else None,
        }
        state.current_step_id = None
        state.active_step_ids = []
        checkpoint_id = self.state_persistence.save_checkpoint(run, state)
        run.execution_state.update(state.model_dump(by_alias=True, mode="json"))
        run.execution_state["checkpointId"] = checkpoint_id
        run.current_step_id = state.graph_id
        run.active_step_ids = []
        self.set_lifecycle(run, status=WorkflowStatus.WAITING_REVIEW, phase=WorkflowProgressPhase.REVIEW,
            message="Planner 已暂停任务，等待外部条件或计划修订")
        self.workflow_store.save_run(run)
        self.mission_manager.mark_waiting_review(self.mission_manager.get_mission(run.mission_id))
        if decision.action == "revise":
            request = SemanticPatchRequest(
                patchId=f"planner_{observation.fingerprint()[:24]}",
                idempotencyKey=f"planner:{observation.fingerprint()}",
                runId=run.run_id, graphId=state.graph_id, baseGraphVersion=state.graph_version,
                taskPlanPatch=decision.task_plan_patch, reason=decision.reason,
            )
            prepared = self.semantic_revision.prepare(request=request, run=run)
            if isinstance(prepared, GraphPatchResult):
                return "stop"
            self.binding.prepare(
                run=prepared.replacement_run, workflow=prepared.workflow, scope=prepared.scope,
                binding_manifest=prepared.compiled_package.binding_manifest,
            )
            self.semantic_revision.commit(prepared)
            self.flush_identity()
        return "stop"
