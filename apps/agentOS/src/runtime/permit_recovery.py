"""Evidence-only reconciliation of an acknowledged Permit execution prefix.

No execution, receipt synthesis, checkpoint rollback or GraphVersion mutation.
Only a finished plain-DAG superstep already projected into Workflow may be
acknowledged. Other crash cuts remain explicit recovery barriers.
"""
import sqlite3

from components.executor import ACGExecutionState
from components.executor.node_runner import ACGNodeRunner
from components.communicator.contracts import ContextPack
from components.communicator.provenance import provenance_checksum
from contracts.execution import NodeExecutionRecord
from contracts.workflow import WorkflowStatus, TraceEventType, utc_now
from contracts import stable_checksum
from domain.identity_graph.resolver import IdentityResolver
from runtime.state_persistence import acg_execution_state_from_run
from support.run_execution_fence import acquire_run_fence
from support.stores.planning_commit_store import content_fingerprint
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore
from support.acg.schema import RuntimeBlueprintSpec


def assert_settled_operations(services, run):
    """Prepared WAL is not a failure receipt; only proven non-invocation settles it."""
    receipts = services.execution_value_store.list_node_commits(run_id=run.run_id)
    with sqlite3.connect(services.execution_value_store.db_path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        operations = {row[0] for row in conn.execute("SELECT operation_id FROM acg_node_executions WHERE run_id=?", (run.run_id,))}
        if operations != {item["commitId"] for item in receipts}:
            raise ValueError("unexplained execution operations block Permit recovery")
        for receipt in receipts:
            row = conn.execute("SELECT payload_json FROM acg_node_executions WHERE run_id=? AND operation_id=?",
                               (run.run_id, receipt["commitId"])).fetchone()
            node = NodeExecutionRecord.model_validate_json(row[0]) if row else None
            if receipt.get("stage") == "committed":
                if (node is None or node.phase.value != "committed"
                        or node.model_dump(mode="json", by_alias=True) != receipt.get("nodeExecution")
                        or node.operation_id != receipt["commitId"] or node.commit_id != receipt["commitId"]
                        or node.run_id != run.run_id or node.step_id not in run.completed_step_ids):
                    raise ValueError("committed operation lacks confirmed Workflow completion or execution evidence")
                # A v1 prefix is already frozen by the promoted checkpoint.
                # All subsequent completions must belong to this generation.
                authority = services.execution_permit_authority
                record = authority.store.get_permit(run.execution_state["executionPermitId"])
                initial = services.checkpoint_store.load(run_id=run.run_id, checkpoint_id=record.promoted_checkpoint_id)
                if node.step_id not in initial["completedStepIds"]:
                    attempt_number = run.get_step(node.step_id).attempt
                    generation = run.execution_state["executionGeneration"]
                    if (node.operation_id != ACGNodeRunner._commit_id(run.run_id, node.step_id, attempt_number,
                                                                   execution_generation=generation)
                            or node.execution_instance_id != f"{generation}:{run.run_id}:{node.step_id}:{attempt_number}:root"):
                        raise ValueError("committed operation belongs to another generation or Attempt")
                continue
            attempt = services.identity_lifecycle.repositories.attempts.get(node.attempt_id) if node else None
            if (node is None or node.phase.value != "failed" or node.failure_code != "AGENT_NOT_IN_SCOPE"
                    or node.run_id != run.run_id or node.operation_id != receipt["commitId"]
                    or not node.execution_instance_id.startswith(str(run.execution_state.get("executionGeneration")) + ":")
                    or attempt is None or attempt.run_id != run.run_id or attempt.status.value != "failed"):
                raise ValueError("unsettled external operation requires explicit side-effect reconciliation")
    return receipts


def _evidence(authority, run, candidate, record):
    rt = authority.runtime
    initial = rt.checkpoint_store.load(run_id=run.run_id, checkpoint_id=record.promoted_checkpoint_id)
    handoff = authority.store.get_handoff(record.handoff_id)
    if initial != authority._promoted_checkpoint_payload(record, handoff):
        raise ValueError("Permit recovery initial checkpoint is corrupt")
    state = ACGExecutionState.model_validate(candidate)
    projected = acg_execution_state_from_run(run)
    if (state.active_step_ids or state.skipped_step_ids or state.review_payload
            or state.control_frames or state.loop_paths or state.loop_iterations
            or state.blackboard_snapshots or state.debate_sessions
            or state.control_review_decisions or state.consensus_results):
        raise ValueError("Permit reconciliation supports only a settled plain DAG superstep")
    # The new checkpoint must be exactly the already-persisted projection,
    # apart from the superstep's settled active list and its new checkpoint ID.
    expected = projected.model_copy(deep=True)
    if not set(expected.active_step_ids) <= set(state.completed_step_ids):
        raise ValueError("Permit recovery contains an unfinished active operation")
    expected.active_step_ids = []
    expected.checkpoint_id = state.checkpoint_id
    if expected != state or set(run.completed_step_ids) != set(state.completed_step_ids):
        raise ValueError("Checkpoint differs from the confirmed Workflow execution projection")
    package = run.execution_state["compiledACGPackage"]
    from contracts.compiled_acg import load_compiled_acg_package
    compiled = load_compiled_acg_package(package)
    if any(n.node_type.value != "step" for n in RuntimeBlueprintSpec.model_validate(run.acg_blueprint).nodes):
        raise ValueError("control graph recovery is unsupported")
    complete = set(state.completed_step_ids)
    if any(edge.target_id in complete and edge.source_id not in complete for edge in compiled.edges):
        raise ValueError("recovered execution prefix is not dependency closed")
    for field in ("outputRefs", "contextRefs", "memoryRefs", "traceRefs", "outputSummaries", "provenanceRefs"):
        if any(candidate[field].get(key) != value for key, value in initial[field].items()):
            raise ValueError("Permit recovery changed the promoted execution prefix")
    if not set(initial["completedStepIds"]) <= complete:
        raise ValueError("Permit recovery lost the promoted completed prefix")
    ledger = rt.provenance_store.load_ledger(run_id=run.run_id, mission_id=run.mission_id)
    rt.acg_execution_service.validate_state_references(run=run, state=state, ledger=ledger)
    receipts = assert_settled_operations(rt, run)
    if any(item.get("stage") == "committed" and (item.get("nodeExecution") or {}).get("stepId") not in complete for item in receipts):
        raise ValueError("unprojected committed work requires separate evidence reconciliation")
    repos = rt.identity_lifecycle.repositories
    identity = repos.runs.get(run.run_id)
    with sqlite3.connect(rt.execution_value_store.db_path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        for key in complete - set(initial["completedStepIds"]):
            step = run.get_step(key)
            commit_id = ACGNodeRunner._commit_id(run.run_id, key, step.attempt,
                                               execution_generation=record.attempt_generation)
            receipt = next((item for item in receipts if item.get("commitId") == commit_id), None)
            if receipt is None or receipt.get("reviewRequired") or receipt.get("auditOutcome") != "allow":
                raise ValueError("missing committed, unreviewed execution receipt")
            node = NodeExecutionRecord.model_validate(receipt.get("nodeExecution"))
            row = conn.execute("SELECT payload_json FROM acg_node_executions WHERE run_id=? AND operation_id=?",
                               (run.run_id, commit_id)).fetchone()
            if (row is None or NodeExecutionRecord.model_validate_json(row[0]) != node
                    or node.phase.value != "committed" or node.commit_id != commit_id
                    or node.run_id != run.run_id or node.step_id != key
                    or node.audit_ref != receipt.get("auditDecisionRef")
                    or node.artifact_refs.get("output") != receipt.get("outputRef")
                    or node.artifact_refs.get("context") != receipt.get("contextRef")
                    or node.execution_instance_id != f"{record.attempt_generation}:{run.run_id}:{key}:{step.attempt}:root"):
                raise ValueError("receipt and durable NodeExecutionRecord disagree")
            attempt = repos.attempts.get(node.attempt_id)
            task = IdentityResolver(repos).resolve_semantic_task(blueprint_id=identity.blueprint_id, acg_node_id=key)
            executions = repos.step_executions.list_for_attempt(node.attempt_id)
            binding = repos.execution_bindings.get_for_attempt(node.attempt_id)
            selected = run.execution_state.get("executionBindings", {}).get(key, {})
            if (attempt is None or attempt.run_id != run.run_id or attempt.task_id != task.task_id
                    or attempt.status.value != "succeeded" or len(executions) != 1
                    or executions[0].status.value != "succeeded" or executions[0].run_id != run.run_id
                    or executions[0].task_id != task.task_id or executions[0].output.get("nodeExecution") != receipt["nodeExecution"]
                    or binding is None or binding.resource_id != selected.get("resourceId")
                    or binding.acg_node_id != key or binding.attempt_id != node.attempt_id
                    or selected.get("attemptId") != node.attempt_id
                    or selected.get("runId") != run.run_id or selected.get("stepId") != key):
                raise ValueError("Identity success or Scheduler resource identity is not settled")
            for channel, field in ((state.output_refs, "outputRef"), (state.context_refs, "contextRef"),
                                   (state.memory_refs, "memoryRef"), (state.trace_refs, "traceRef"),
                                   (state.output_summaries, "outputSummary")):
                if channel.get(key) != receipt.get(field):
                    raise ValueError("checkpoint execution references differ from the committed receipt")
            rt.decision_store.assert_decision(run_id=run.run_id, step_id=key,
                                             decision_ref=receipt["auditDecisionRef"], outcomes={"allow"})
            output = rt.execution_value_store.get_output(run_id=run.run_id, output_ref=receipt["outputRef"])
            pack = ContextPack.model_validate(rt.execution_value_store.get_context_pack(
                run_id=run.run_id, context_ref=receipt["contextRef"]))
            if (pack.run_id != run.run_id or pack.step_id != key or pack.contract_status != "valid"
                    or not any(event.operation_id == commit_id and event.producer_step_id == key
                               and event.checksum == provenance_checksum(output) for event in ledger.productions)
                    or not any(event.operation_id == commit_id + ":consume" and event.consumer_step_id == key
                               and event.checksum == provenance_checksum(pack.data) for event in ledger.consumptions)):
                raise ValueError("execution values differ from sealed Provenance")
            if not any(event.event_type == TraceEventType.STEP_SUCCEEDED and event.step_id == key
                       and event.payload.get("commitId") == commit_id for event in run.trace):
                raise ValueError("Workflow success Trace is missing")
    return state, stable_checksum(receipts)


def reconcile_checkpoint(authority, run_id):
    rt = authority.runtime
    with rt.run_lock_manager.lock_for(run_id), acquire_run_fence(authority.store.db_path, run_id):
        run = authority._workflow_run(run_id)
        projection = run.execution_state.get("graphActivation", {}).get("executionPermit") or {}
        record = authority.store.get_permit(projection.get("permitId"))
        if record is None or record.status != "ISSUED":
            raise ValueError("an issued Permit is required for checkpoint reconciliation")
        authority._assert_dispatch_authority(record, check_checkpoint=False)
        head, payload = rt.checkpoint_store.load_latest(run_id=run_id)
        if head == run.execution_state.get("checkpointId"):
            authority.assert_dispatchable(run)
            # Even without a new checkpoint, unknown prepared work must never
            # silently become an automatic retry after process death.
            assert_settled_operations(rt, run)
            return run
        version = rt.checkpoint_store.version(run_id=run_id, checkpoint_id=head)
        if run.status not in {WorkflowStatus.RUNNING, WorkflowStatus.RETRYING}:
            raise ValueError("review or terminal Run cannot automatically acknowledge a checkpoint")
        state, _ = _evidence(authority, run, payload, record)
        candidate = run.model_copy(deep=True)
        candidate.execution_state.update(state.model_dump(by_alias=True, mode="json"))
        candidate.active_step_ids = []
        candidate.runtime_revision += 1
        candidate.updated_at = utc_now()
        # Use the same current-head validation as dispatch on the proposed Run,
        # without persisting or relaxing that public safety gate.
        authority._assert_recovery_head(record, authority.store.get_handoff(record.handoff_id), candidate)
        with authority.store._transaction():
            if content_fingerprint(authority._workflow_run(run_id)) != content_fingerprint(run):
                raise ValueError("Run changed during Permit checkpoint reconciliation")
            authority._assert_dispatch_authority(record, check_checkpoint=False)
            _evidence(authority, run, payload, record)
            if (rt.checkpoint_store.load_latest(run_id=run_id) != (head, payload)
                    or rt.checkpoint_store.latest_version(run_id=run_id) != version):
                raise ValueError("Checkpoint head changed during reconciliation")
            if not SQLiteWorkflowStore._upsert_run(authority.store._local.connection, candidate):
                raise ValueError("Run rejected checkpoint acknowledgement")
        return candidate
