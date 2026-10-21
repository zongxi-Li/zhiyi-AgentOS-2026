"""Initial variants for the existing Handoff/Permit authorities; no write authority."""
import sqlite3

from contracts import stable_checksum
from contracts.initial_planning import InitialPlanningSourceProvenance
from contracts.graph_handoff import GraphHandoffRecord, GraphVersionIdentityLink, StagedGraphCheckpoint
from contracts.workflow import GraphRef
from components.executor import ACGExecutionState
from runtime.initial_planning_sources import capture_initial_sources
from runtime.initial_graph_compilation import initial_recipe_fingerprint, INITIAL_MATERIALIZATION_POLICY
from runtime.planning_commit import fingerprint
from runtime.state_persistence import acg_execution_state_from_run
from support.stores.planning_commit_store import content_fingerprint


def initial_content(store, activation):
    record = store.get(activation.source_commit_id)
    mat = store.get_materialization(activation.materialization_id)
    if (activation.source_kind != "initial_plan" or record is None or record.proposal_type != "initial_plan"
            or not isinstance(record.source_provenance, InitialPlanningSourceProvenance)
            or mat is None or mat.source_kind != "initial_plan" or mat.initial_content is None
            or mat.source_commit_id != record.commit_id or mat.mission_id != record.mission_id
            or mat.source_run_id != record.source_provenance.source_run_id
            or mat.commitment_fingerprint != content_fingerprint(record)
            or mat.sources != record.sources or mat.proof_fingerprint != record.source_provenance.static_fingerprint
            or mat.initial_content.plan != record.proposal_payload):
        raise ValueError("complete accepted Initial materialization required")
    content = mat.initial_content
    if (content.blueprint.metadata.get("initialCompilationRecipe") != initial_recipe_fingerprint()
            or content.blueprint.metadata.get("initialMaterializationPolicy") != INITIAL_MATERIALIZATION_POLICY):
        raise ValueError("Initial compiler policy changed")
    return record, mat, content


def assert_initial_sources(rt, store, run, record, *, allow_candidate_identity=False, principal_fingerprint=None):
    """Revalidate static inputs without inventing a pre-activation Run snapshot.

    runtimeFingerprint remains the sealed historical value. Current execution
    is validated by Head/Permit/evidence, not compared to that initial context.
    Identity may advance only to this exact accepted plan during its own saga.
    """
    authorities = (rt.planning_commit_authority, rt.graph_activation_authority,
                   rt.graph_materialization_authority, rt.identity_lifecycle)
    if (rt.planning_commit_authority is None or rt.graph_activation_authority is None
            or rt.graph_materialization_authority is None or rt.identity_lifecycle is None
            or any(authority.store.db_path != store.db_path for authority in (
                rt.planning_commit_authority, rt.graph_activation_authority, rt.graph_materialization_authority))
            or store.latest(run.mission_id) != record or run.run_id != record.source_provenance.source_run_id
            or run.mission_id != record.mission_id or not run.execution_state.get("planningCommitRequired")):
        raise ValueError("Initial execution authorities or accepted head changed")
    principal = rt.semantic_principal_provider() if rt.semantic_principal_provider else None
    if principal_fingerprint is not None and fingerprint(principal.model_dump(mode="json") if hasattr(principal, "model_dump") else principal) != principal_fingerprint:
        raise ValueError("Initial Permit principal changed")
    provider = rt.planning_commit_authority._provider(run.run_id, record.proposal_payload, True)
    provider.store = store
    provider.initial_provenance = record.source_provenance
    if principal is None or not provider.authorize():
        raise ValueError("Initial execution authorization denied")
    with store.connection() as conn:
        revision = conn.execute("SELECT revision FROM mission_semantic_state WHERE mission_id=?", (run.mission_id,)).fetchone()
    if revision is None or revision[0] != record.source_revision:
        raise ValueError("Initial Mission revision changed")
    origin = record.source_provenance
    current = capture_initial_sources(provider, origin.runtime_fingerprint)
    excluded = {"identity_snapshot", "identity_fingerprint", "static_fingerprint"}
    if current.model_dump(exclude=excluded) != origin.model_dump(exclude=excluded):
        raise ValueError("Initial static sources changed")
    if (current.identity_snapshot != origin.identity_snapshot
            and not (allow_candidate_identity and current.identity_snapshot == record.proposal_payload)):
        raise ValueError("Initial Identity planning source changed")
    if (rt.semantic_principal_provider() != principal or not provider.authorize()
            or rt.semantic_principal_provider() != principal
            or authorities != (rt.planning_commit_authority, rt.graph_activation_authority,
                               rt.graph_materialization_authority, rt.identity_lifecycle)):
        raise ValueError("Initial execution authorization changed")
    return principal


def assert_initial_unexecuted(rt, run):
    if (run.active_step_ids or run.completed_step_ids
            or any(s.status.value != "pending" or s.attempt or s.retry_count or s.output or s.resolved_input
                   or s.started_at or s.completed_at for s in run.steps)
            or rt.execution_value_store.list_node_commits(run_id=run.run_id)
            or rt.identity_lifecycle.repositories.attempts.list_for_run(run.run_id)):
        raise ValueError("Initial execution already has work or unresolved side effects")
    with sqlite3.connect(rt.execution_value_store.db_path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        if conn.execute("SELECT 1 FROM acg_node_executions WHERE run_id=? LIMIT 1", (run.run_id,)).fetchone():
            raise ValueError("Initial execution has historical operations")


def build_initial_handoff(authority, activation, run, key):
    rt, store = authority.runtime, authority.store
    record, mat, content = initial_content(store, activation)
    principal = assert_initial_sources(rt, store, run, record)
    if (run.acg_blueprint != content.blueprint.model_dump(mode="json", by_alias=True)
            or run.execution_state.get("taskPlan") != content.plan.model_dump(mode="json", by_alias=True)
            or run.execution_state.get("taskBindings") != [b.model_dump(mode="json", by_alias=True) for b in content.bindings]
            or run.execution_state.get("graphActivation", {}).get("executionPermit") is not None
            or run.active_step_ids or run.completed_step_ids
            or any(s.status.value != "pending" or s.attempt or s.retry_count or s.output or s.resolved_input
                   or s.started_at or s.completed_at for s in run.steps)):
        raise ValueError("Initial Run is not the pristine accepted graph")
    assert_initial_unexecuted(rt, run)
    state = ACGExecutionState(runId=run.run_id, graphId=mat.graph_id, graphVersion=1)
    if acg_execution_state_from_run(run) != state or rt.checkpoint_store.latest_version(run_id=run.run_id) != 0:
        raise ValueError("Initial execution has an unexplained recovery state")
    repos = rt.identity_lifecycle.repositories
    mission = repos.missions.get(run.mission_id)
    if mission is None or repos.runs.get(run.run_id) is not None or repos.attempts.list_for_run(run.run_id):
        raise ValueError("Initial Identity source is not an unexecuted Mission")
    source_fp = fingerprint(dict(mission=mission.model_dump(mode="json"), run=None,
        plan=record.source_provenance.identity_snapshot.model_dump(mode="json", by_alias=True)
             if record.source_provenance.identity_snapshot else None))
    link = GraphVersionIdentityLink(sourceKind="initial_plan", runId=run.run_id,
        sourceBlueprintId=None, sourceGraph=None,
        candidateGraph=GraphRef(graphId=mat.graph_id, version="1", checksum=mat.package_checksum),
        sourceIdentityFingerprint=source_fp, candidatePackageChecksum=mat.package_checksum, prefixAttemptIds=())
    prefix_fp = fingerprint(state.model_dump(mode="json", by_alias=True))
    sources_fp = fingerprint(dict(run=run.model_dump(mode="json"), commit=content_fingerprint(record),
        identity=link.model_dump(mode="json"), principal=principal.model_dump(mode="json")))
    handoff_id = "gho_" + stable_checksum(dict(activation=activation.activation_id, prefix=prefix_fp, sources=sources_fp))[:40]
    cp_id = "stagedckpt_" + stable_checksum(dict(handoff=handoff_id, state=state.model_dump(mode="json")))[:40]
    state.checkpoint_id = cp_id
    candidate = StagedGraphCheckpoint(sourceKind="initial_plan", checkpointId=cp_id, handoffId=handoff_id,
        runId=run.run_id, activationId=activation.activation_id, graphVersion=1,
        packageChecksum=mat.package_checksum, state=state.model_dump(mode="json", by_alias=True))
    # Re-read after external source hooks; never confirm a cached Run/authority.
    with store.connection() as conn:
        row = conn.execute("SELECT payload FROM runs WHERE run_id=?", (run.run_id,)).fetchone()
    from contracts.workflow import RuntimeRunRecord
    if (row is None or RuntimeRunRecord.model_validate_json(row[0]) != run
            or rt.graph_handoff_authority is not authority or rt._run_cancellation_requested(run.run_id)):
        raise ValueError("Initial handoff changed during validation")
    if assert_initial_sources(rt, store, run, record) != principal:
        raise ValueError("Initial handoff principal changed")
    return GraphHandoffRecord(sourceKind="initial_plan", handoffId=handoff_id, idempotencyKey=key,
        runId=run.run_id, activationId=activation.activation_id, graphVersion=1,
        sourceCheckpointId=None, sourceCheckpointVersion=None, sourceCheckpointFingerprint=None,
        prefixFingerprint=prefix_fp, sourcesFingerprint=sources_fp, identityLink=link, candidate=candidate,
        candidateFingerprint=stable_checksum(candidate), status="STAGING")
