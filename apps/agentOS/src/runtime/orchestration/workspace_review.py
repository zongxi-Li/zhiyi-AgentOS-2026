"""Continue an authorized review through the existing formal graph authorities.

There is no executor or retry loop here. The native Runtime owns execution;
the existing commitment, activation, handoff and Permit journals own recovery.
"""
from __future__ import annotations

import sqlite3
import logging
from time import monotonic

from contracts import stable_checksum
from contracts.execution import WorkflowProgressPhase
from contracts.planning import TaskPlanPatch
from contracts.workflow import WorkflowStatus, utc_now
from support.run_execution_fence import acquire_run_fence, RunFenceBusy
from support.stores.execution_dispatch_store import DispatchCommand


_TERMINAL_STATUSES = {WorkflowStatus.COMPLETED, WorkflowStatus.FAILED,
                      WorkflowStatus.CANCELLED, WorkflowStatus.SUPERSEDED}


class _TransitionRejected(ValueError):
    def __init__(self, receipt):
        raw_code = getattr(receipt, "code", "AUTHORITY_UNAVAILABLE")
        self.code = getattr(raw_code, "value", raw_code)
        self.retryable = getattr(receipt, "retryable", False)
        self.authority_reason = str(getattr(receipt, "reason", None) or "authority unavailable")[:500]
        super().__init__(f"Workspace review graph transition rejected: {self.code}: "
            f"{self.authority_reason}")


def automatic_workspace_review(run) -> bool:
    binding = run.input.get("workspaceBinding") or {}
    return bool(run.review_mode == "auto" and binding.get("workspaceId") and binding.get("grantId")
                and not binding.get("revoked") and run.execution_state.get("workspaceObservations"))


def queue_workspace_revision(run, observation, decision) -> None:
    """Keep only the semantic proposal; accepted facts stay in their journals."""
    run.execution_state["workspaceReviewContinuation"] = {
        "observationId": observation.fingerprint(), "sourceGraphVersion": observation.graph_version,
        "patch": decision.task_plan_patch.model_dump(mode="json", by_alias=True),
    }


def record_workspace_review(run, observation, decision, loop) -> None:
    if not observation.workspace_observations:
        return
    previous = run.execution_state.get("workspaceReview") or {}
    gaps = {"missingReadCount": 0, "missingListingCount": 0, "unsupportedEntryCount": 0,
            "missingReads": [], "missingListings": [], "unsupportedEntries": []}
    for item in observation.workspace_observations:
        for key in ("missingReadCount", "missingListingCount", "unsupportedEntryCount"):
            gaps[key] += item.get(key, 0)
        for key in ("missingReads", "missingListings", "unsupportedEntries"):
            gaps[key] = sorted(set((*gaps[key], *item.get(key, ()))))
    rounds = list(previous.get("rounds") or ())
    observation_ref = observation.fingerprint()
    if not any(item.get("observationRef") == observation_ref for item in rounds):
        rounds.append({"round": loop.rounds_used, "graphVersion": observation.graph_version,
            "action": decision.action, "reason": decision.reason,
            "stepIds": [step.step_id for step in observation.steps if step.status == "completed"],
            "addedStepIds": [], "observationRef": observation_ref,
            "traceRefs": []})
    status = ("completed" if decision.action == "complete" else
              "blocked" if decision.action in {"wait", "abort"} and not run.execution_state.get("workspaceReviewContinuation") else
              "reviewing" if decision.action == "revise" or run.execution_state.get("workspaceReviewContinuation") else "reading")
    run.execution_state["workspaceReview"] = {"schemaVersion": 1, "round": loop.rounds_used,
        "graphVersion": observation.graph_version, "status": status, "gaps": gaps, "rounds": rounds}


class WorkspaceReviewContinuation:
    def __init__(self, runtime):
        self.runtime = runtime
        # Transport/storage backoff is process-local; mutating an accepted
        # source Run between authority stages would invalidate its provenance.
        self._deferred: dict[str, tuple[float, float]] = {}
        self._blocked: dict[str, str] = {}

    def _defer_storage(self, run_id):
        delay = min(60.0, self._deferred.get(run_id, (0.0, 0.5))[1] * 2)
        self._deferred[run_id] = (monotonic() + delay, delay)

    def _publish_status(self, run_id, status, code=None, *, diagnostics=None):
        """The public display is independent of immutable authority snapshots."""
        from contracts.runtime_events import RuntimeEvent
        from runtime.events.live_events import runtime_event_broker
        try:
            runtime_event_broker.bind_run(run_id, self.runtime.workflow_store)
            payload = {"stage": "workspace_review", "status": status}
            if code is not None:
                payload["errorCode"] = code
            if diagnostics is not None:
                payload.update(diagnostics)
            event = "retry" if status == "retrying" else status
            runtime_event_broker.publish_from_thread(run_id, RuntimeEvent(eventType="workspace.review." + event,
                runId=run_id, sequence=0, payload=payload))
        except Exception:
            logging.getLogger(__name__).warning("workspace_review_display_unavailable", extra={"runId": run_id, "errorCode": code})

    def _boundary_fingerprint(self, run):
        return stable_checksum({"run": run.model_dump(mode="json"),
            "inputs": self.runtime.workflow_store.list_planning_inputs(run.run_id)})

    @staticmethod
    def _confirmed(receipt):
        if receipt is None or receipt.status == "REJECTED":
            raise _TransitionRejected(receipt)
        return receipt

    @staticmethod
    def _rejection_code(pending):
        code = pending.get("errorCode")
        if code:
            return code
        # Runs queued by older versions recorded only this host exception's
        # canonical diagnostic. Read that legacy fact without reinterpreting
        # arbitrary model prose as an authority receipt.
        if pending.get("errorType") == "_TransitionRejected":
            prefix = "Workspace review graph transition rejected: "
            reason = pending.get("reason", "")
            if isinstance(reason, str) and reason.startswith(prefix):
                return reason[len(prefix):].split(":", 1)[0]
        return None

    def can_replan(self, run):
        """A proposal denial is feedback, rather than an operator approval."""
        from runtime.orchestration.planning_loop import REPAIRABLE_PLANNING_REJECTIONS
        pending = run.execution_state.get("workspaceReviewContinuation")
        activation = run.execution_state.get("graphActivation") or {}
        observation = ((run.execution_state.get("planningLoop") or {}).get("current") or {}).get("observationId")
        review = run.execution_state.get("reviewPayload") or {}
        return bool(automatic_workspace_review(run) and isinstance(pending, dict)
            and pending.get("blocked") and pending.get("errorType") == "_TransitionRejected"
            and self._rejection_code(pending) in REPAIRABLE_PLANNING_REJECTIONS
            and observation and observation == pending.get("observationId") == review.get("observationId")
            and review.get("subjectType") == "planner" and review.get("subjectId") == run.execution_state.get("graphId")
            and pending.get("sourceGraphVersion") == run.execution_state.get("graphVersion")
            and not (activation and activation.get("executionPermit") is None)
            and run.status == WorkflowStatus.WAITING_REVIEW)

    def _prepare_replan(self, run, pending, *, code, reason):
        """Return the same Run to its existing Planner, without executing work."""
        from components.executor import ACGExecutionState
        from runtime.orchestration.state_persistence import acg_execution_state_from_run
        rt = self.runtime
        with rt.run_lock_manager.lock_for(run.run_id), acquire_run_fence(rt.workflow_store.db_path, run.run_id):
            current = rt.workflow_store.get_run(run.run_id)
            if (current.execution_state.get("workspaceReviewContinuation") != pending
                    or not automatic_workspace_review(current)
                    or current.status != WorkflowStatus.WAITING_REVIEW
                    or rt._run_cancellation_requested(run.run_id)):
                return None
            activation = current.execution_state.get("graphActivation") or {}
            if activation and activation.get("executionPermit") is None:
                return None
            principal = rt.semantic_principal_provider() if rt.semantic_principal_provider else None
            rt.mission_semantic_service.require_write_access(principal, current.mission_id)
            if current.execution_state.get("executionPermitId"):
                # The existing Dispatch admission will require the same proof
                # before resuming. Check it here so an unreconciled write is
                # explained at this barrier, rather than falsely advertised as
                # an executable retry. Unacknowledged pure reads remain safe.
                from runtime.orchestration.permit_recovery import assert_replay_safe_operations
                assert_replay_safe_operations(rt, current)
            expected = current.model_copy(deep=True)
            state = acg_execution_state_from_run(current)
            review = state.review_payload or {}
            if (review.get("subjectType") != "planner"
                    or review.get("subjectId") != state.graph_id
                    or review.get("observationId") != pending.get("observationId")
                    or pending.get("sourceGraphVersion") != state.graph_version):
                raise ValueError("planning rejection feedback does not own the current review barrier")
            original_checkpoint = rt.checkpoint_store.load(run_id=current.run_id, checkpoint_id=state.checkpoint_id)
            if original_checkpoint is None or ACGExecutionState.model_validate(original_checkpoint) != state:
                raise ValueError("planning rejection feedback differs from its native checkpoint")
            rt._validate_acg_state_references(run=current, state=state)
            rt.prepare_planning_commit_rejection_feedback(current, state, code=code, reason=reason,
                source_observation_id=pending["observationId"], proposal_ref=stable_checksum(pending["patch"]))
            state.checkpoint_transition_key = f"planner-rejection:{expected.execution_state['checkpointId']}"
            # Persist the cleared strategic barrier in the native checkpoint:
            # Permit resume loads that body, not merely the Run projection.
            # A crash after checkpoint save is replayable only if the new head
            # is precisely this same feedback state. Never acknowledge other
            # unfinished work or roll a checkpoint back.
            latest_id, latest = rt.checkpoint_store.load_latest(run_id=current.run_id)
            proposed = state.model_dump(by_alias=True, mode="json")
            if latest_id != expected.execution_state.get("checkpointId"):
                if dict(latest, checkpointId=None) != dict(proposed, checkpointId=None):
                    raise ValueError("planning rejection feedback found an unrelated checkpoint head")
            checkpoint_id = rt.acg_state_persistence.save_checkpoint(current, state)
            current.execution_state.update(state.model_dump(by_alias=True, mode="json"))
            current.execution_state["checkpointId"] = checkpoint_id
            current.status = rt.state_machine.transition(current.status, WorkflowStatus.RETRYING)
            current.current_step_id = None
            current.runtime_revision += 1
            current.lifecycle_phase = WorkflowProgressPhase.RECOVERY
            current.lifecycle_message = "正在根据审查反馈自动修正计划"
            review = current.execution_state.get("workspaceReview")
            if isinstance(review, dict):
                review["status"] = "reviewing"
            current.updated_at = utc_now()
            rt.workflow_store.save_run(current, expected_snapshot=expected)
        self._publish_status(run.run_id, "retrying", code)
        return current

    def resume(self, run):
        """Run once at a settled boundary; journal replay resumes interrupted stages."""
        pending = run.execution_state.get("workspaceReviewContinuation")
        if (not automatic_workspace_review(run) or not isinstance(pending, dict)
                or run.status in _TERMINAL_STATUSES):
            return None
        if pending.get("blocked") and not self.can_replan(run):
            return None
        # A queued proposal is not a settled execution boundary. In particular,
        # restart may observe the decided round before its checkpoint was saved.
        if run.status != WorkflowStatus.WAITING_REVIEW and not (
                run.execution_state.get("graphVersion", 0) > pending.get("sourceGraphVersion", 0)):
            return None
        rt = self.runtime
        if monotonic() < self._deferred.get(run.run_id, (0.0, 0.0))[0]:
            return None
        blocked = self._blocked.get(run.run_id)
        if blocked is not None and blocked == self._boundary_fingerprint(run):
            return None
        if any(getattr(rt, name, None) is None for name in (
                "planning_commit_authority", "graph_materialization_authority", "graph_activation_authority",
                "graph_handoff_authority", "execution_permit_authority")):
            return None
        try:
            if pending.get("blocked"):
                return self._prepare_replan(run, pending, code=self._rejection_code(pending), reason=pending["reason"])
            result = self._advance(run, pending)
            if result is not None:
                self._deferred.pop(run.run_id, None)
                self._blocked.pop(run.run_id, None)
                self._publish_status(run.run_id, "resumed")
            return result
        except (sqlite3.Error, RunFenceBusy) as exc:
            # Journals may have committed before a lost acknowledgement. Leave
            # their frozen source Run intact and replay on the next state wake.
            self._defer_storage(run.run_id)
            self._publish_status(run.run_id, "retrying", "CONTROL_BARRIER_BLOCKED" if isinstance(exc, RunFenceBusy)
                else "STORAGE_UNAVAILABLE")
            return None
        except (ValueError, KeyError, PermissionError) as exc:
            if isinstance(exc, _TransitionRejected) and (exc.code == "STORAGE_UNAVAILABLE" or exc.retryable):
                self._defer_storage(run.run_id)
                self._publish_status(run.run_id, "retrying", exc.code)
                return None
            if isinstance(exc, _TransitionRejected):
                from runtime.orchestration.planning_loop import REPAIRABLE_PLANNING_REJECTIONS
                if exc.code in REPAIRABLE_PLANNING_REJECTIONS:
                    try:
                        prepared = self._prepare_replan(run, pending, code=exc.code, reason=str(exc))
                        if prepared is not None:
                            return prepared
                    except (sqlite3.Error, RunFenceBusy):
                        self._defer_storage(run.run_id)
                        self._publish_status(run.run_id, "retrying", "CONTROL_BARRIER_BLOCKED")
                        return None
                    except (ValueError, KeyError, PermissionError) as feedback_error:
                        # Feedback must not resolve another review or conceal
                        # an unrelated checkpoint. Preserve the formal denial
                        # below when a new observation cannot safely be formed.
                        logging.getLogger(__name__).warning("workspace_review_feedback_unavailable",
                            extra={"runId": run.run_id, "errorCode": exc.code})
                        exc = feedback_error
            # Preserve every confirmed journal stage. A denied operation never
            # turns into authorization, a receipt or an optimistic next graph.
            diagnostics = None
            try:
                with rt.run_lock_manager.lock_for(run.run_id), acquire_run_fence(rt.workflow_store.db_path, run.run_id):
                    current = rt.workflow_store.get_run(run.run_id)
                    if (current.execution_state.get("workspaceReviewContinuation") != pending
                            or current.status in _TERMINAL_STATUSES):
                        return None
                    expected = current.model_copy(deep=True)
                    # A paused activation is immutable until Permit. Journals
                    # remain its durable explanation and recovery point.
                    projection = current.execution_state.get("graphActivation") or {}
                    if projection and projection.get("executionPermit") is None:
                        self._blocked[run.run_id] = self._boundary_fingerprint(current)
                        diagnostics = {"activationId": projection.get("activationId"),
                            "observationId": pending.get("observationId"),
                            "graphVersion": current.execution_state.get("graphVersion"),
                            "errorType": type(exc).__name__}
                        if isinstance(exc, _TransitionRejected):
                            diagnostics["authorityReason"] = exc.authority_reason
                        logging.getLogger(__name__).warning(
                            "workspace_review_graph_transition_rejected run_id=%s activation_id=%s code=%s reason=%s",
                            run.run_id, projection.get("activationId"), getattr(exc, "code", type(exc).__name__),
                            exc.authority_reason if isinstance(exc, _TransitionRejected) else type(exc).__name__)
                    else:
                        review = dict(current.execution_state.get("workspaceReview") or {})
                        review.update(status="blocked", graphVersion=current.execution_state.get("graphVersion", 1))
                        current.execution_state["workspaceReview"] = review
                        # Keep a machine-readable authority code alongside the
                        # bounded human diagnostic.  The projection layer uses
                        # this to distinguish an immutable graph rejection from
                        # a transport/storage retry; it must never infer that
                        # every WAITING_REVIEW state needs operator approval.
                        current.execution_state["workspaceReviewContinuation"] = {
                            **pending,
                            "blocked": True,
                            "errorType": type(exc).__name__,
                            "errorCode": getattr(exc, "code", None) or type(exc).__name__,
                            "reason": str(exc)[:500],
                        }
                        current.updated_at = utc_now()
                        rt.workflow_store.save_run(current, expected_snapshot=expected)
                if diagnostics is None:
                    self._publish_status(run.run_id, "blocked", getattr(exc, "code", type(exc).__name__))
                else:
                    self._publish_status(run.run_id, "blocked", getattr(exc, "code", type(exc).__name__), diagnostics=diagnostics)
            except (sqlite3.Error, RunFenceBusy):
                self._defer_storage(run.run_id)
                self._publish_status(run.run_id, "retrying", "CONTROL_BARRIER_BLOCKED")
            return None

    def _advance(self, run, pending):
        rt = self.runtime
        principal = rt.semantic_principal_provider() if rt.semantic_principal_provider else None
        rt.mission_semantic_service.require_write_access(principal, run.mission_id)
        if rt._run_cancellation_requested(run.run_id):
            return None
        key = f"workspace-review:{run.run_id}:{pending['observationId']}"
        patch = TaskPlanPatch.model_validate(pending["patch"])
        ledger = rt.planning_commit_authority.store
        source = ledger.get_by_idempotency_key(key + ":semantic")
        if source is None:
            with rt.run_lock_manager.lock_for(run.run_id):
                current = rt.workflow_store.get_run(run.run_id)
                if current.execution_state.get("graphVersion") != pending["sourceGraphVersion"]:
                    raise ValueError("Workspace review proposal targets a stale graph")
                receipt = self._confirmed(rt.planning_commit_authority.accept_patch_locked(
                    run.run_id, patch, proposal_id=key, idempotency_key=key + ":semantic"))
                source = ledger.get(receipt.commit_id)
        if (source is None or source.proposal_type != "plan_revision" or source.mission_id != run.mission_id
                or source.proposal_payload != patch or source.sources.graph_version != pending["sourceGraphVersion"]):
            raise ValueError("Workspace review semantic lineage differs from the queued proposal")
        graph = ledger.get_by_idempotency_key(key + ":graph")
        if graph is None:
            receipt = self._confirmed(rt.accept_graph_revision(run.run_id, source.commit_id, idempotency_key=key + ":graph"))
            graph = ledger.get(receipt.commit_id)
        if (graph is None or graph.proposal_type != "graph_revision"
                or graph.proposal_payload.source_commit_id != source.commit_id):
            raise ValueError("Workspace review graph lineage is inconsistent")
        materializations = rt.graph_materialization_authority.store
        materialization = materializations.materialization_for(graph.commit_id)
        if materialization is None:
            receipt = self._confirmed(rt.materialize_graph_revision(graph.commit_id, idempotency_key=key + ":materialize"))
            materialization = materializations.get_materialization(receipt.materialization_id)
        activations = rt.graph_activation_authority.store
        activation = activations.activation_for(materialization.materialization_id)
        if activation is None or activation.status != "ACTIVATED_PAUSED":
            self._confirmed(rt.prepare_graph_activation(materialization.materialization_id, idempotency_key=key + ":activate"))
            receipt = self._confirmed(rt.commit_graph_activation(materialization.materialization_id, idempotency_key=key + ":activate"))
            activation = activations.get_activation(receipt.activation_id)
        handoffs = rt.graph_handoff_authority.store
        handoff = handoffs.handoff_for(activation.activation_id)
        if handoff is None or handoff.status != "STATE_PREPARED":
            receipt = self._confirmed(rt.prepare_graph_handoff(activation.activation_id, idempotency_key=key + ":handoff"))
            handoff = handoffs.get_handoff(receipt.handoff_id)
        permit = self._confirmed(rt.issue_execution_permit(handoff.handoff_id, idempotency_key=key + ":permit"))
        dispatch = getattr(rt, "execution_dispatch_store", None)
        with rt.run_lock_manager.lock_for(run.run_id), acquire_run_fence(rt.workflow_store.db_path, run.run_id):
            current = rt.workflow_store.get_run(run.run_id)
            if (current.status in _TERMINAL_STATUSES
                    or current.execution_state.get("workspaceReviewContinuation") != pending):
                return None
            if (current.execution_state.get("graphVersion") != graph.proposal_payload.candidate_graph.version
                    or current.execution_state.get("executionPermitId") != permit.permit_id):
                raise ValueError("Workspace review finalization targets another graph or Permit")
            rt.execution_permit_authority.assert_dispatchable(current)
            if getattr(rt, "execution_dispatch_enabled", False):
                if dispatch is None:
                    raise ValueError("Workspace review Dispatch authority is unavailable")
                parent = dispatch.get(run.run_id)
                command = DispatchCommand(dispatch_id="dispatch_" + stable_checksum(key)[:40], operation_key=key + ":dispatch",
                    request_fingerprint=stable_checksum({"observation": pending["observationId"], "permit": permit.permit_id}),
                    mission_id=current.mission_id, run_id=current.run_id, permit_id=permit.permit_id,
                    graph_id=current.execution_state["graphId"], graph_version=current.execution_state["graphVersion"],
                    runtime_revision=current.runtime_revision, actor_id=principal.actor_id, tenant_id=principal.tenant_id)
                if parent is not None and parent.graph_version == command.graph_version:
                    # The admission already exists after a lost ACK. Its exact
                    # revision is historical authority, not the mutable Run's.
                    if any(getattr(parent, field) != getattr(command, field) for field in (
                            "operation_key", "request_fingerprint", "mission_id", "permit_id", "graph_id", "actor_id", "tenant_id")):
                        raise ValueError("Workspace review Dispatch replay differs from accepted authority")
                    command = parent
                dispatch.accept_continuation(command, parent, rt.execution_permit_authority.assert_dispatchable)
            expected = current.model_copy(deep=True)
            current.execution_state.pop("workspaceReviewContinuation", None)
            review = current.execution_state.get("workspaceReview")
            if isinstance(review, dict):
                review.update(graphVersion=current.execution_state["graphVersion"], status="reading")
                for round_ in review.get("rounds") or ():
                    if round_.get("observationRef") == pending["observationId"]:
                        round_.update(patchRef=graph.commit_id, graphVersion=current.execution_state["graphVersion"],
                            addedStepIds=[node["nodeId"] for node in graph.proposal_payload.graph_patch.added_nodes])
            current.updated_at = utc_now()
            rt.workflow_store.save_run(current, expected_snapshot=expected)
        return current
