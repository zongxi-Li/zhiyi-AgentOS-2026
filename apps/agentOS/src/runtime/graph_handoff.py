"""Prepare a versioned execution state without advancing any execution head.

Workflow owns the intent and confirmation. The checkpoint DB owns only an
immutable staged body. Retrying the original key reconciles a crash between
these stores. No normal recovery reader consumes this table.
"""
import json
import sqlite3
from pydantic import TypeAdapter
from contracts import stable_checksum
from contracts.execution import NodeExecutionRecord
from contracts.resource import ExecutionBinding as RuntimeExecutionBinding
from contracts.graph_handoff import (GraphHandoffRecord, GraphHandoffReceipt,
    GraphVersionIdentityLink, StagedGraphCheckpoint)
from contracts.graph_revision import Ref, GraphRevisionProposal
from contracts.mission_semantic import run_intent_basis
from contracts.planning import TaskPlan
from contracts.workflow import RuntimeRunRecord, GraphRef, TraceEventType
from components.executor import ACGExecutionState, ACGGraphCompiler
from components.communicator.contracts import ContextPack
from components.communicator.provenance import provenance_checksum
from domain.identity_graph.resolver import IdentityResolver
from runtime.graph_revision import GraphProvider, source_provenance, safe_cut
from runtime.planning_commit import fingerprint, fingerprint_observation
from runtime.state_persistence import acg_execution_state_from_run
from runtime.semantic_revision import SemanticRevisionService
from support.acg.schema import RuntimeBlueprintSpec
from support.run_execution_fence import acquire_run_fence, RunFenceBusy
from support.stores.graph_activation_store import validate_activation_run
from support.stores.planning_commit_store import content_fingerprint


def rejected(code, reason):
    return GraphHandoffReceipt(status="REJECTED", code=code, reason=reason)


class HandoffEvidenceError(ValueError):
    pass


class GraphHandoffAuthority:
    def __init__(self, runtime, store, staged_store):
        if (runtime.graph_activation_authority is None
                or store.db_path != runtime.graph_activation_authority.store.db_path
                or store.db_path != runtime.workflow_store.db_path.resolve()
                or staged_store.db_path != runtime.checkpoint_store.db_path.resolve()
                or staged_store.db_path == store.db_path):
            raise HandoffEvidenceError("handoff requires the authoritative Workflow and separate checkpoint stores")
        self.runtime, self.store, self.staged_store = runtime, store, staged_store

    def _validated_candidate(self, activation_id, key):
        rt, store = self.runtime, self.store
        authorities = (rt.graph_activation_authority, rt.planning_commit_authority, rt.identity_lifecycle)
        if (rt.graph_handoff_authority is not self or rt.graph_activation_authority is None
                or rt.planning_commit_authority is None
                or rt.planning_commit_authority.store.db_path != store.db_path
                or rt.graph_activation_authority.store.db_path != store.db_path
                or rt.workflow_store.db_path.resolve() != store.db_path
                or self.staged_store.db_path != rt.checkpoint_store.db_path.resolve()):
            raise HandoffEvidenceError("handoff authority unavailable")
        activation = store.get_activation(activation_id)
        if activation is None or activation.status != "ACTIVATED_PAUSED":
            raise HandoffEvidenceError("paused activation required")
        with store.connection() as conn:
            row = conn.execute("SELECT payload FROM runs WHERE run_id=?", (activation.run_id,)).fetchone()
            run = RuntimeRunRecord.model_validate_json(row[0]) if row else None
            if run is None or validate_activation_run(conn, run) is None:
                raise HandoffEvidenceError("complete formal Head required")
            revision = conn.execute("SELECT revision FROM mission_semantic_state WHERE mission_id=?", (run.mission_id,)).fetchone()
        if run.execution_state.get("checkpointId") is not None:
            raise HandoffEvidenceError("paused Run must not have a v2 recovery head")
        if len(run.steps) > 256 or len(run.model_dump_json()) > 2_000_000:
            raise HandoffEvidenceError("handoff source exceeds bounded graph policy")
        with rt._execution_slot_guard:
            if run.run_id in rt._active_execution_slots:
                raise HandoffEvidenceError("live execution occupies handoff")
        mat = store.get_materialization(activation.materialization_id)
        graph = store.get(activation.source_commit_id)
        if activation.source_kind == "initial_plan":
            from runtime.initial_execution import build_initial_handoff
            return build_initial_handoff(self, activation, run, key)
        if graph is None or not isinstance(graph.proposal_payload, GraphRevisionProposal):
            raise HandoffEvidenceError("accepted graph revision required")
        proposal = graph.proposal_payload
        source = store.get(proposal.source_commit_id)
        if (source is None or source.proposal_type != "plan_revision" or graph.parent_commit_id != source.commit_id
                or graph.commitment_revision != source.commitment_revision + 1 or store.latest(run.mission_id) != graph
                or not (graph.mission_id == source.mission_id == run.mission_id)
                or graph.source_revision != source.source_revision or proposal.mission_revision != graph.source_revision
                or graph.source_provenance != source.source_provenance
                or proposal.source_provenance != source.source_provenance
                or proposal.source_proposal_fingerprint != source.proposal_fingerprint
                or content_fingerprint(proposal) != graph.proposal_fingerprint
                or mat.commitment_fingerprint != content_fingerprint(graph)
                or mat.proof_fingerprint != content_fingerprint(proposal.safe_cut) or mat.sources != graph.sources
                or mat.sources.plan_version != source.sources.plan_version
                or mat.sources.graph_version != source.sources.graph_version
                or mat.sources.observation_id != source.sources.observation_id
                or mat.sources.observation_fingerprint != source.sources.observation_fingerprint
                or mat.sources.mission_revision != source.sources.mission_revision
                or revision is None or revision[0] != graph.source_revision):
            raise HandoffEvidenceError("acceptance chain or current Mission revision changed")
        ancestor, seen = source, set()
        while ancestor.parent_commit_id is not None:
            if ancestor.commit_id in seen or len(seen) >= 256:
                raise HandoffEvidenceError("invalid acceptance ancestry")
            seen.add(ancestor.commit_id)
            parent = store.get(ancestor.parent_commit_id)
            if parent is None or parent.mission_id != run.mission_id or parent.commitment_revision + 1 != ancestor.commitment_revision:
                raise HandoffEvidenceError("missing acceptance ancestor")
            ancestor = parent
        if ancestor.commitment_revision != 1:
            raise HandoffEvidenceError("invalid acceptance root")
        if (run.execution_state.get("taskPlan") != proposal.next_plan.model_dump(mode="json", by_alias=True)
                or run.execution_state.get("taskBindings") != [b.model_dump(mode="json", by_alias=True) for b in proposal.next_bindings]
                or run.acg_blueprint != proposal.candidate_graph.model_dump(mode="json", by_alias=True)
                or ACGGraphCompiler().compile_package(proposal.candidate_graph, run_id=run.run_id) != mat.package):
            raise HandoffEvidenceError("candidate semantics or current compiler changed")
        SemanticRevisionService._validate_bindings(proposal.next_plan, proposal.candidate_graph, proposal.next_bindings)
        principal = rt.semantic_principal_provider() if rt.semantic_principal_provider else None
        provider = GraphProvider(rt.planning_commit_authority, run.run_id, proposal, source, principal)
        provider.store = store
        if not provider.authorize():
            raise HandoffEvidenceError("handoff authorization denied")
        repos = rt.identity_lifecycle.repositories
        identity = repos.runs.get(run.run_id)
        mission_identity = repos.missions.get(run.mission_id)
        if identity is None or identity.mission_id != run.mission_id or identity.graph_version != activation.source_graph_version:
            raise HandoffEvidenceError("existing source Identity required")
        if mission_identity is None or mission_identity.mission_id != run.mission_id:
            raise HandoffEvidenceError("source Mission Identity missing")
        identity_graph = repos.blueprints.get(identity.blueprint_id)
        original_plan = repos.task_plans.latest(run.mission_id)
        if identity_graph is None or original_plan is None:
            raise HandoffEvidenceError("source Identity graph and plan required")
        old = RuntimeBlueprintSpec.model_validate(identity_graph.graph)
        original_plan = TaskPlan.model_validate(original_plan.model_dump(mode="json", by_alias=True))
        if (identity_graph.blueprint_id != identity.blueprint_id or identity_graph.mission_id != run.mission_id
                or identity_graph.graph_id != old.graph_id or identity_graph.version != old.version
                or old.graph_id != activation.graph_id or old.version != activation.source_graph_version
                or original_plan.plan_version != source.sources.plan_version):
            raise HandoffEvidenceError("source Identity version mismatch")
        old_package = ACGGraphCompiler().compile_package(old, run_id=run.run_id)
        if any(identity.metadata.get(k) != v for k, v in {
                "workflowId": run.workflow_id, "runtimeGraphId": old.graph_id,
                "taskPlanVersion": original_plan.plan_version}.items()):
            raise HandoffEvidenceError("source Identity planning reference mismatch")
        if any(identity.metadata.get(k) != v for k,v in {
            "compiledPackageId": old_package.package_id, "compiledPackageChecksum": old_package.checksum,
            "compiledPackageVersion": old_package.package_version, "compiledPackageBlueprintHash": old_package.blueprint_hash}.items()):
            raise HandoffEvidenceError("source Identity immutable package mismatch")
        cp_id = run.execution_state["graphActivation"]["supersededCheckpointId"]
        latest_id, cp = rt.checkpoint_store.load_latest(run_id=run.run_id)
        if not cp_id or latest_id != cp_id:
            raise HandoffEvidenceError("source checkpoint head mismatch")
        cp_version = rt.checkpoint_store.version(run_id=run.run_id, checkpoint_id=cp_id)
        if rt.checkpoint_store.latest_version(run_id=run.run_id) != cp_version:
            raise HandoffEvidenceError("source checkpoint version mismatch")
        cp_state = ACGExecutionState.model_validate(cp)
        if (cp_state.run_id != run.run_id or cp_state.graph_id != old.graph_id
                or cp_state.graph_version != old.version or cp_state.checkpoint_id != cp_id):
            raise HandoffEvidenceError("source checkpoint identity mismatch")
        state = acg_execution_state_from_run(run)
        if state.review_payload is not None and state.review_payload.get("subjectType") != "planner":
            raise HandoffEvidenceError("unresolved review blocks handoff")
        excluded = {"graph_version", "checkpoint_id", "review_payload", "current_step_id"}
        if state.model_dump(exclude=excluded) != cp_state.model_dump(exclude=excluded):
            raise HandoffEvidenceError("checkpoint execution channels disagree")
        if (state.active_step_ids or state.skipped_step_ids or state.control_frames or state.loop_iterations
                or state.loop_paths or state.control_review_decisions or state.consensus_results
                or state.blackboard_snapshots or state.debate_sessions
                or any(n.node_type == "control" for n in (*old.nodes, *proposal.candidate_graph.nodes))):
            raise HandoffEvidenceError("only a settled no-control completed prefix is supported")
        if set(state.completed_step_ids) != set(run.completed_step_ids) or len(set(state.completed_step_ids)) != len(state.completed_step_ids):
            raise HandoffEvidenceError("completed prefix projection mismatch")
        # Reconstruct only a historical validation view; never persist or execute it.
        # The accepted static fingerprint proves every reconstructed byte. Changes
        # to pending source semantics that cannot be recovered fail closed.
        source_run = run.model_copy(deep=True)
        source_run.acg_blueprint = old.model_dump(mode="json", by_alias=True)
        source_run.steps = [s for s in source_run.steps if s.step_id in {n.node_id for n in old.step_nodes()}]
        source_run.execution_state.update(cp_state.model_dump(mode="json", by_alias=True))
        source_run.execution_state.update(taskPlan=original_plan.model_dump(mode="json", by_alias=True),
            taskPlanVersion=original_plan.plan_version, compiledACGPackage=old_package.model_dump(mode="json", by_alias=True),
            taskBindings=[b.model_dump(mode="json", by_alias=True) for b in proposal.next_bindings if b.acg_node_id in {s.step_id for s in source_run.steps}])
        source_nodes = {n.key: n for n in original_plan.nodes}
        source_bindings = {b["planNodeKey"]: b["acgNodeId"] for b in source_run.execution_state["taskBindings"]}
        with repos.storage.read() as conn:
            rows = [dict(row) for row in conn.execute("""SELECT semantic_key,task_id,payload_json FROM task_plan_nodes
                WHERE mission_id=? AND plan_version=? ORDER BY semantic_key""", (run.mission_id, original_plan.plan_version))]
        if set(source_bindings) != set(source_nodes) or {row["semantic_key"] for row in rows} != set(source_nodes):
            raise HandoffEvidenceError("source Identity plan mapping is incomplete")
        source_identity_nodes = []
        for row in rows:
            node_key = row["semantic_key"]
            bound = repos.task_bindings.find_for_acg_node(source_bindings[node_key], identity.blueprint_id)
            semantic = IdentityResolver(repos).resolve_semantic_task(blueprint_id=identity.blueprint_id,
                acg_node_id=source_bindings[node_key])
            if (len(bound) != 1 or bound[0].binding_type.value != "primary"
                    or bound[0].task_id != row["task_id"] or semantic.task_id != row["task_id"]
                    or semantic.mission_id != run.mission_id or semantic.semantic_task_key != node_key
                    or json.loads(row["payload_json"]) != source_nodes[node_key].model_dump(mode="json", by_alias=True)):
                raise HandoffEvidenceError("source Identity semantic snapshot mapping mismatch")
            source_identity_nodes.append(dict(snapshot=source_nodes[node_key].model_dump(mode="json", by_alias=True),
                semantic=semantic.model_dump(mode="json"), binding=bound[0].model_dump(mode="json")))
        provider.run = lambda: source_run
        current = (source_run.execution_state.get("planningLoop") or {}).get("current") or {}
        if (current.get("observationId") != source.sources.observation_id
                or fingerprint_observation(current, source_run) != source.sources.observation_fingerprint):
            raise HandoffEvidenceError("historical source Observation mismatch")
        if source_provenance(provider) != proposal.source_provenance:
            raise HandoffEvidenceError("current origin differs from accepted frozen provenance")
        if safe_cut(provider, source, proposal.next_plan, proposal.next_bindings, proposal.candidate_graph, proposal.graph_patch) != proposal.safe_cut:
            raise HandoffEvidenceError("current source safe-cut differs")
        # Potentially blocking identity/permission hooks precede the last source
        # and evidence reads. No callback may introduce new authoritative values
        # after those reads and before the Workflow confirmation.
        if (rt.semantic_principal_provider() != principal or not provider.authorize()
                or source_provenance(provider) != proposal.source_provenance):
            raise HandoffEvidenceError("authorization or origin changed during validation")
        # Read-only reference validation, not NodeRunner replay (which publishes memory).
        ledger = rt.provenance_store.load_ledger(run_id=run.run_id, mission_id=run.mission_id)
        rt.acg_execution_service.validate_state_references(run=run, state=state, ledger=ledger)
        completed = set(state.completed_step_ids)
        for step_id in completed:
            successes = [event for event in run.trace if event.event_type == TraceEventType.STEP_SUCCEEDED
                         and event.step_id == step_id]
            if not successes or any(event.run_id != run.run_id for event in successes):
                raise HandoffEvidenceError("completed Trace belongs to another Run")
        if any(set(channel) != completed for channel in (state.output_summaries, state.output_refs,
                state.context_refs, state.memory_refs, state.trace_refs, state.provenance_refs)):
            raise HandoffEvidenceError("execution channels must describe exactly the verified completed prefix")
        if any(e.target_id in completed and e.source_id not in completed for e in mat.package.edges):
            raise HandoffEvidenceError("completed prefix is not dependency closed")
        receipts = provider.node_commits(run)
        expected_receipts = {f"commit:{run.run_id}:{s.step_id}:{s.attempt}" for s in run.steps if s.step_id in completed}
        if {r.get("commitId") for r in receipts} != expected_receipts or any(r.get("stage") != "committed" for r in receipts):
            raise HandoffEvidenceError("unsettled or unexplained receipts")
        attempts, evidence = [], []
        # The independent node-execution table and Identity Attempt must agree
        # with the immutable receipt; never manufacture an execution fact.
        with sqlite3.connect(rt.execution_value_store.db_path.resolve().as_uri() + "?mode=ro", uri=True) as values:
            operations = values.execute("SELECT operation_id FROM acg_node_executions WHERE run_id=?", (run.run_id,)).fetchall()
            if {r[0] for r in operations} != expected_receipts:
                raise HandoffEvidenceError("unexplained execution operation")
            for step in run.steps:
                if step.step_id not in completed:
                    if (step.status.value != "pending" or step.attempt or step.retry_count or step.output
                            or step.resolved_input or step.started_at or step.completed_at):
                        raise HandoffEvidenceError("unfinished node is not pristine pending")
                    continue
                if step.status.value != "completed":
                    raise HandoffEvidenceError("completed node status mismatch")
                r = next(r for r in receipts if r["commitId"] == f"commit:{run.run_id}:{step.step_id}:{step.attempt}")
                node = NodeExecutionRecord.model_validate(r["nodeExecution"])
                row = values.execute("SELECT run_id,payload_json,phase FROM acg_node_executions WHERE operation_id=?", (r["commitId"],)).fetchone()
                commit_row = values.execute("SELECT stage FROM acg_node_commits WHERE commit_id=? AND run_id=?", (r["commitId"],run.run_id)).fetchone()
                if (row is None or row[0] != run.run_id or row[2] != "committed" or node != NodeExecutionRecord.model_validate_json(row[1])
                        or commit_row is None or commit_row[0] != "committed" or node.phase.value != "committed"
                        or node.run_id != run.run_id or node.step_id != step.step_id or node.operation_id != r["commitId"]
                        or node.commit_id != r["commitId"] or node.loop_path or r.get("reviewRequired") or r.get("auditOutcome") != "allow"
                        or node.audit_ref != r.get("auditDecisionRef")
                        or node.execution_instance_id != f"{run.run_id}:{step.step_id}:{step.attempt}:root"
                        or node.artifact_refs.get("output") != r.get("outputRef")
                        or node.artifact_refs.get("context") != r.get("contextRef")):
                    raise HandoffEvidenceError("receipt and execution identity mismatch")
                attempt = repos.attempts.get(node.attempt_id)
                executions = repos.step_executions.list_for_attempt(node.attempt_id) if attempt else ()
                bindings = repos.task_bindings.find_for_acg_node(acg_node_id=step.step_id, blueprint_id=identity.blueprint_id)
                if (attempt is None or attempt.run_id != run.run_id or attempt.status.value != "succeeded"
                        or attempt.attempt_number != max(step.attempt, step.retry_count) + 1
                        or not any(b.task_id == attempt.task_id for b in bindings)
                        or not any(e.run_id == run.run_id and e.task_id == attempt.task_id and e.status.value == "succeeded" for e in executions)):
                    raise HandoffEvidenceError("source Attempt identity not confirmed")
                if state.output_summaries.get(step.step_id) != r.get("outputSummary"):
                    raise HandoffEvidenceError("receipt output summary mismatch")
                matching_executions = [e for e in executions if e.output.get("nodeExecution") == r["nodeExecution"]
                           and e.output.get("outputRef") == r.get("outputRef")
                           and e.output.get("contextRef") == r.get("contextRef")]
                if len(executions) != 1 or len(matching_executions) != 1:
                    raise HandoffEvidenceError("Identity execution output differs from receipt")
                origin = IdentityResolver(repos).resolve_execution_origin(matching_executions[0].step_execution_id)
                plan_key = next(b["planNodeKey"] for b in source_run.execution_state["taskBindings"]
                                if b["acgNodeId"] == step.step_id)
                runtime_binding = RuntimeExecutionBinding.model_validate(
                    (run.execution_state.get("executionBindings") or {}).get(step.step_id))
                scheduled = [item for item in run.execution_state.get("schedulingDecisions", ())
                             if item.get("attemptId") == attempt.attempt_id]
                expected_identity_metadata = {
                    "runtimeBindingId": runtime_binding.binding_id,
                    "runtimeKind": runtime_binding.runtime_kind.value,
                    "snapshotVersion": runtime_binding.snapshot_version,
                    **runtime_binding.metadata,
                }
                # For legacy embedded agents the lifecycle event records the
                # selected resource as the Identity agent id when the profile
                # has no explicit agent_id. The Run projection separately
                # records the stable registry id (usually the profile name).
                # Accept either documented representation, but no unrelated id.
                identity_agent_ids = {
                    str((run.execution_state.get("logicalAgents") or {}).get(step.step_id) or ""),
                    str(runtime_binding.resource_id),
                }
                if (origin.mission != mission_identity or origin.run != identity or origin.blueprint != identity_graph
                        or origin.semantic_task.mission_id != run.mission_id
                        or origin.semantic_task.task_id != attempt.task_id or origin.semantic_task.semantic_task_key != plan_key
                        or origin.attempt != attempt or origin.step_execution != matching_executions[0]
                        or origin.task_binding.blueprint_id != identity.blueprint_id
                        or origin.task_binding.acg_node_id != step.step_id
                        or origin.task_binding.task_id != attempt.task_id
                        or origin.execution_binding.attempt_id != attempt.attempt_id
                        or origin.execution_binding.acg_node_id != step.step_id
                        or runtime_binding.run_id != run.run_id or runtime_binding.step_id != step.step_id
                        or runtime_binding.attempt_id != attempt.attempt_id
                        or (run.execution_state.get("resourceBindings") or {}).get(step.step_id) != runtime_binding.resource_id
                        or len(scheduled) != 1 or scheduled[0].get("stepId") != step.step_id
                        or RuntimeExecutionBinding.model_validate(scheduled[0].get("binding")) != runtime_binding
                        or origin.execution_binding.resource_id != runtime_binding.resource_id
                        or str(origin.execution_binding.agent_id) not in identity_agent_ids
                        or origin.execution_binding.metadata != expected_identity_metadata):
                    raise HandoffEvidenceError("Identity origin ownership or version mismatch")
                for channel, field in ((state.output_refs,"outputRef"), (state.context_refs,"contextRef"),
                                       (state.memory_refs,"memoryRef"), (state.trace_refs,"traceRef")):
                    if channel.get(step.step_id) != r.get(field):
                        raise HandoffEvidenceError("receipt references disagree with prefix")
                rt.decision_store.assert_decision(run_id=run.run_id, step_id=step.step_id,
                    decision_ref=r["auditDecisionRef"], outcomes={"allow"})
                output = rt.execution_value_store.get_output(run_id=run.run_id, output_ref=r["outputRef"])
                context = rt.execution_value_store.get_context_pack(run_id=run.run_id, context_ref=r["contextRef"])
                pack = ContextPack.model_validate(context)
                if (pack.run_id != run.run_id or pack.step_id != step.step_id or pack.contract_status != "valid"
                        or not any(e.operation_id == r["commitId"] and e.producer_step_id == step.step_id
                                   and e.checksum == provenance_checksum(output) for e in ledger.productions)
                        or not any(e.operation_id == r["commitId"] + ":consume" and e.consumer_step_id == step.step_id
                                   and e.checksum == provenance_checksum(pack.data) for e in ledger.consumptions)):
                    raise HandoffEvidenceError("output or context content differs from sealed provenance")
                memory_ref = r.get("memoryRef")
                memory = rt.memory_store.get(memory_ref) if memory_ref and memory_ref != "memory:none" else None
                pending = r.get("pendingMemory")
                if memory_ref != "memory:none" and (memory is None or not isinstance(pending, dict)
                        or memory.content != pending.get("memoryEvent") or memory.memory_type.value != pending.get("writeType")):
                    raise HandoffEvidenceError("memory differs from committed intent")
                evidence.append(dict(receipt=r, execution=node.model_dump(mode="json"), output=fingerprint(output),
                    context=fingerprint(context), attempt=attempt.model_dump(mode="json"),
                    memory=memory.model_dump(mode="json") if memory else None,
                    origin=origin.model_dump(mode="json"),
                    executions=[e.model_dump(mode="json") for e in executions]))
                attempts.append(node.attempt_id)
        # Check semantic ancestry/effective dependencies via the existing SafeCut
        # and compiler above, not a second DAG compiler.
        basis = run_intent_basis(run)
        if basis is None or basis.source_revision != revision[0]:
            raise HandoffEvidenceError("frozen Basis mismatch")
        if {a.attempt_id for a in repos.attempts.list_for_run(run.run_id)} != set(attempts):
            raise HandoffEvidenceError("unexplained pending or historical attempt requires separate recovery")
        if set(run.execution_state.get("attemptIds", {}).values()) != set(attempts):
            raise HandoffEvidenceError("cached Attempt identities differ from confirmed prefix")
        # Source callbacks may have changed the Workflow projection while the
        # initial verification was outside a write transaction. Never publish
        # the cached Run after such a callback.
        with store.connection() as conn:
            row = conn.execute("SELECT payload FROM runs WHERE run_id=?", (run.run_id,)).fetchone()
            if row is None or RuntimeRunRecord.model_validate_json(row[0]) != run:
                raise HandoffEvidenceError("Run changed during source verification")
        identity_link = GraphVersionIdentityLink(runId=run.run_id, sourceBlueprintId=identity.blueprint_id,
            sourceGraph=GraphRef(graphId=old.graph_id, version=str(old.version), checksum=old_package.checksum),
            candidateGraph=GraphRef(graphId=activation.graph_id, version=str(activation.candidate_graph_version), checksum=mat.package_checksum),
            sourceIdentityFingerprint=fingerprint(dict(run=identity.model_dump(mode="json"),
                blueprint=identity_graph.model_dump(mode="json"), mission=mission_identity.model_dump(mode="json"),
                sourceNodes=source_identity_nodes)),
            candidatePackageChecksum=mat.package_checksum, prefixAttemptIds=tuple(sorted(attempts)))
        prefix_hash = fingerprint(dict(state=cp, checkpointVersion=cp_version, evidence=evidence))
        sources_hash = fingerprint(dict(run=run.model_dump(mode="json"), graph=content_fingerprint(graph),
            identity=identity_link.model_dump(mode="json"), origin=proposal.source_provenance.model_dump(mode="json"), principal=principal.model_dump(mode="json")))
        handoff_id = "gho_" + stable_checksum(dict(activation=activation_id, prefix=prefix_hash, sources=sources_hash))[:40]
        candidate_state = state.model_copy(deep=True, update={"checkpoint_id": None, "review_payload": None, "current_step_id": None})
        candidate_id = "stagedckpt_" + stable_checksum(dict(handoff=handoff_id, state=candidate_state.model_dump(mode="json")))[:40]
        candidate_state.checkpoint_id = candidate_id
        candidate = StagedGraphCheckpoint(checkpointId=candidate_id, handoffId=handoff_id,
            runId=run.run_id, activationId=activation_id, graphVersion=activation.candidate_graph_version,
            packageChecksum=mat.package_checksum, state=candidate_state.model_dump(mode="json", by_alias=True))
        if (rt.graph_handoff_authority is not self or rt._run_cancellation_requested(run.run_id)
                or authorities != (rt.graph_activation_authority, rt.planning_commit_authority, rt.identity_lifecycle)):
            raise HandoffEvidenceError("authorization changed during handoff validation")
        return GraphHandoffRecord(handoffId=handoff_id, idempotencyKey=key, runId=run.run_id,
            activationId=activation_id, graphVersion=activation.candidate_graph_version,
            sourceCheckpointId=cp_id, sourceCheckpointVersion=cp_version,
            sourceCheckpointFingerprint=fingerprint(cp), prefixFingerprint=prefix_hash,
            sourcesFingerprint=sources_hash, identityLink=identity_link, candidate=candidate,
            candidateFingerprint=stable_checksum(candidate), status="STAGING")

    def prepare(self, activation_id, *, idempotency_key):
        try:
            activation_id = TypeAdapter(Ref).validate_python(activation_id)
            key = TypeAdapter(Ref).validate_python(idempotency_key)
            activation = self.store.get_activation(activation_id)
            if activation is None:
                return rejected("INVALID_PROPOSAL", "activation unavailable")
            with self.runtime.run_lock_manager.lock_for(activation.run_id), acquire_run_fence(self.store.db_path, activation.run_id):
                candidate = self._validated_candidate(activation_id, key)
                with self.store._transaction():
                    if self._validated_candidate(activation_id, key) != candidate:
                        raise HandoffEvidenceError("handoff sources changed before intent")
                    old = self.store.handoff_by_key(key)
                    other = self.store.handoff_for(activation_id)
                    if old is not None:
                        if old.model_copy(update={"status": "STAGING"}) != candidate:
                            return rejected("DUPLICATE_CONFLICT", "key binds another handoff")
                    elif other is not None:
                        return rejected("DUPLICATE_CONFLICT", "activation has a handoff; reconcile original key")
                    else:
                        self.store._append_handoff(candidate)
                # External write never holds the Workflow write lock. Failure or
                # process death leaves a durable intent and an optional orphaned
                # staged body; neither can be used by normal recovery.
                if old and old.status == "STATE_PREPARED":
                    if self.staged_store.get(candidate.candidate.checkpoint_id) != candidate.candidate:
                        raise HandoffEvidenceError("confirmed staged checkpoint missing or corrupt")
                else:
                    self.staged_store.stage(candidate.candidate)
                with self.store._transaction():
                    if self.staged_store.get(candidate.candidate.checkpoint_id) != candidate.candidate:
                        raise HandoffEvidenceError("staged checkpoint missing or corrupt")
                    if self._validated_candidate(activation_id, key) != candidate:
                        raise HandoffEvidenceError("handoff sources changed before confirmation")
                    current = self.store.handoff_by_key(key)
                    if current == candidate:
                        self.store._confirm_handoff(candidate)
                    elif current != candidate.model_copy(update={"status": "STATE_PREPARED"}):
                        raise HandoffEvidenceError("handoff intent changed")
                return GraphHandoffReceipt(status="IDEMPOTENT_REPLAY" if old and old.status == "STATE_PREPARED" else "STATE_PREPARED",
                    handoffId=candidate.handoff_id)
        except RunFenceBusy:
            return rejected("CONTROL_BARRIER_BLOCKED", "execution or handoff occupies the Run")
        except HandoffEvidenceError as exc:
            return rejected("INVALID_PROPOSAL", str(exc))
        except (ValueError, LookupError, TypeError, AttributeError):
            return rejected("INVALID_PROPOSAL", "invalid, stale or incomplete handoff evidence")
        except (sqlite3.Error, RuntimeError):
            return rejected("STORAGE_UNAVAILABLE", "handoff storage unavailable; reconcile original key")
