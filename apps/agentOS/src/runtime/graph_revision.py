"""Read-only graph derivation and safe-cut checks; acceptance stays in one service."""
from contracts import stable_checksum
from types import SimpleNamespace
from contracts.graph_revision import PlanningSourceProvenance, SafeCutProof, GraphRevisionProposal
from contracts.mission_semantic import run_intent_basis
from contracts.planning import TaskPlan, TaskPlanPatch, TaskImplementationBinding
from contracts.planning_commit import PlanningCommitRequest, PlanningCommitRejection, PlanningCommitRejectionCode as Code
from contracts.recovery import SemanticPatchRequest
from components.planner.planning_commit import PlanningCommitService
from components.planner.topology import TOPOLOGY_COMPILER_VERSION
from components.executor import ACGExecutionState
from runtime.planning_commit import RuntimePlanningCommitProvider, fingerprint, with_semantic_ancestors, freeze_capability_catalog
from service.agents import AgentRegistry
from runtime.state_persistence import acg_execution_state_from_run
from runtime.semantic_patch import SemanticGraphPatchService, derive_graph_patch
from support.acg.schema import RuntimeBlueprintSpec
from support.stores.planning_commit_store import content_fingerprint


class GraphRevisionError(ValueError):
    def __init__(self, code, reason):
        self.code, self.reason = code, reason
        super().__init__(reason)


def execution_state(run):
    state = acg_execution_state_from_run(run)
    graph = run.acg_blueprint
    if state.run_id != run.run_id:
        raise GraphRevisionError(Code.INVALID_PROPOSAL, "execution evidence belongs to another Run")
    if ((state.graph_id is not None and state.graph_id != graph["graphId"])
            or (any(k in run.execution_state for k in ("graphVersion", "graph_version"))
                and state.graph_version != graph["version"])):
        raise GraphRevisionError(Code.STALE_GRAPH, "execution evidence belongs to another graph boundary")
    # Legacy TaskPlan-first Runs may omit graph identity in the state projection.
    # Fill absent identity only; never overwrite an explicitly different identity.
    return state.model_copy(update={"graph_id": graph["graphId"], "graph_version": graph["version"]})


def planning_inputs(provider, run):
    workflow = provider.runtime._workflow_for_run(run).model_copy(deep=True)
    catalog = freeze_capability_catalog(provider.runtime.capability_catalog)
    profiles = tuple(agent.profile.model_copy(deep=True) for agent in
        provider.runtime.agent_registry.scoped(run.execution_scope.agent_ids).all())
    return workflow, catalog, profiles


def source_provenance(provider, *, run=None, inputs=None):
    run = provider.run() if run is None else run
    basis = run_intent_basis(run)
    scope = run.execution_scope
    if basis is None or scope is None or not run.acg_blueprint:
        raise GraphRevisionError(Code.INVALID_PROPOSAL, "formal graph origin is unavailable")
    state = execution_state(run)
    repositories = getattr(provider.runtime.identity_lifecycle, "repositories", None)
    identity = repositories.task_plans.latest(run.mission_id) if repositories else None
    workflow, catalog, profiles = planning_inputs(provider, run) if inputs is None else inputs
    workflow_version = run.execution_state.get("workflowVersion")
    if workflow_version is not None and str(workflow_version) != str(workflow.version):
        raise GraphRevisionError(Code.STALE_STRATEGY, "workflow definition changed since Run preparation")
    static = dict(runId=run.run_id, input=run.input, basis=basis.model_dump(mode="json"),
        workflowId=run.workflow_id, workflow=workflow.model_dump(mode="json", by_alias=True),
        activeStepIds=run.active_step_ids, completedStepIds=run.completed_step_ids,
        scope=scope.model_dump(mode="json"), graph=run.acg_blueprint,
        plan=run.execution_state.get("taskPlan"), bindings=run.execution_state.get("taskBindings"),
        package=run.execution_state.get("compiledACGPackage"),
        steps=[s.model_dump(mode="json") for s in run.steps],
        state=state.model_dump(mode="json", by_alias=True, exclude={"checkpoint_id", "review_payload", "current_step_id"}),
        receipts=provider.node_commits(run), inputs=provider.runtime.workflow_store.list_planning_inputs(run.run_id),
        catalog=[d.model_dump(mode="json") for d in catalog.available()],
        agents=[profile.model_dump(mode="json") for profile in profiles],
        identity=identity.model_dump(mode="json") if identity else None,
        compiler=TOPOLOGY_COMPILER_VERSION, policy="planning-acceptance-v1", projection="runtime-static-v2")
    return PlanningSourceProvenance(version="runtime-static-v2", sourceRunId=run.run_id, graphId=run.acg_blueprint["graphId"],
        basisFingerprint=fingerprint(basis.model_dump(mode="json")), scopeFingerprint=fingerprint(scope.model_dump(mode="json")),
        staticFingerprint=fingerprint(static), compilerVersion=TOPOLOGY_COMPILER_VERSION)


def checkpoint(provider, run):
    ref = run.execution_state.get("checkpointId")
    try:
        latest_ref, payload = provider.runtime.checkpoint_store.load_latest(run_id=run.run_id)
    except KeyError:
        if ref:
            raise GraphRevisionError(Code.CONTROL_BARRIER_BLOCKED, "checkpoint reference cannot be proved")
        return None
    if latest_ref != ref:
        raise GraphRevisionError(Code.CONTROL_BARRIER_BLOCKED, "checkpoint head is not acknowledged by the Run")
    state = ACGExecutionState.model_validate(payload)
    if (state.run_id != run.run_id or state.graph_id != run.acg_blueprint["graphId"]
            or state.graph_version != run.acg_blueprint["version"]):
        raise GraphRevisionError(Code.STALE_GRAPH, "checkpoint belongs to another graph boundary")
    current = execution_state(run)
    # A planner wait may change only orchestration markers. Every execution
    # channel must agree; unioning completed IDs alone loses other checkpoint
    # evidence after a partial persistence/recovery transition.
    excluded = {"checkpoint_id", "review_payload", "current_step_id"}
    if state.model_dump(mode="json", exclude=excluded) != current.model_dump(mode="json", exclude=excluded):
        raise GraphRevisionError(Code.CONTROL_BARRIER_BLOCKED, "checkpoint execution evidence disagrees with the Run")
    return payload


def safe_cut(provider, source, next_plan, next_bindings, candidate, patch):
    run = provider.run()
    state = execution_state(run)
    cp = checkpoint(provider, run)
    checkpoint_state = ACGExecutionState.model_validate(cp) if cp is not None else None
    if checkpoint_state is not None and (checkpoint_state.active_step_ids or checkpoint_state.control_frames
            or checkpoint_state.loop_iterations or checkpoint_state.loop_paths or checkpoint_state.control_review_decisions
            or (checkpoint_state.review_payload is not None and checkpoint_state.review_payload.get("subjectType") != "planner")):
        raise GraphRevisionError(Code.CONTROL_BARRIER_BLOCKED, "checkpoint control/review state is not resolved")
    old = RuntimeBlueprintSpec.model_validate(run.acg_blueprint)
    if (any(n.node_type == "control" for n in (*old.nodes, *candidate.nodes)) or state.control_frames or state.loop_iterations
            or state.loop_paths or state.control_review_decisions or state.consensus_results):
        raise GraphRevisionError(Code.CONTROL_BARRIER_BLOCKED,
            "control-region proof unavailable: branch history and deterministic control-preserving lowering required")
    if (run.active_step_ids or state.active_step_ids or any(s.status.value in {"running", "retrying", "waiting_review"} for s in run.steps)
            or (state.review_payload is not None and state.review_payload.get("subjectType") != "planner")):
        raise GraphRevisionError(Code.CONTROL_BARRIER_BLOCKED, "unresolved workers or review block safe-cut")
    old_plan = TaskPlan.model_validate(run.execution_state["taskPlan"])
    bindings = {b["acgNodeId"]: b["planNodeKey"] for b in run.execution_state["taskBindings"]}
    receipts = provider.node_commits(run)
    protected_nodes = set(state.completed_step_ids) | set(state.skipped_step_ids) | set(run.completed_step_ids)
    if checkpoint_state is not None:
        protected_nodes.update((*checkpoint_state.completed_step_ids, *checkpoint_state.skipped_step_ids))
    protected_nodes.update(s.step_id for s in run.steps if s.status.value != "pending" or s.attempt or s.retry_count
        or s.output or s.resolved_input or s.started_at or s.completed_at)
    node_evidence = (state.output_refs, state.output_summaries, state.context_refs, state.memory_refs,
        state.trace_refs, state.provenance_refs, state.blackboard_snapshots, state.debate_sessions)
    protected_nodes.update(node_id for channel in node_evidence for node_id in channel)
    for b in run.execution_state["taskBindings"]:
        step_id = b["acgNodeId"]
        if (any(str(r.get("commitId", "")).startswith(f"commit:{run.run_id}:{step_id}:")
                or r.get("commitId") == f"single-step-retry:{run.run_id}:{step_id}" for r in receipts)):
            protected_nodes.add(step_id)
    if not protected_nodes <= bindings.keys():
        raise GraphRevisionError(Code.INVALID_PROPOSAL, "execution prefix has unknown node identities")
    protected_keys = with_semantic_ancestors(old_plan, {bindings[i] for i in protected_nodes})
    new_by_key = {n.key: n for n in next_plan.nodes}
    new_bindings = {b.plan_node_key: b.acg_node_id for b in next_bindings}
    for n in old_plan.nodes:
        if n.key in protected_keys and (new_by_key.get(n.key) != n or new_bindings.get(n.key) != next(
                b["acgNodeId"] for b in run.execution_state["taskBindings"] if b["planNodeKey"] == n.key)):
            raise GraphRevisionError(Code.INVALID_PROPOSAL, "semantic execution prefix changed")
    semantic_edges = lambda p: {r for r in p.relations if r.target_key in protected_keys}
    if semantic_edges(old_plan) != semantic_edges(next_plan):
        raise GraphRevisionError(Code.INVALID_PROPOSAL, "compiled predecessor obligations changed")
    old_nodes, new_nodes = {n.node_id: n for n in old.nodes}, {n.node_id: n for n in candidate.nodes}
    for node_id in protected_nodes:
        if old_nodes[node_id] != new_nodes.get(node_id):
            raise GraphRevisionError(Code.INVALID_PROPOSAL, "frozen execution node changed")
        if old.resource_plan.model_dump(mode="json") != candidate.resource_plan.model_dump(mode="json"):
            # Compare only resources addressed to this protected node, not new
            # logical decisions for pending work. No resource reservation occurs.
            def addressed(model):
                raw = model.model_dump(mode="json", by_alias=True)
                return {k: [i for i in v if isinstance(i, dict) and
                    (any(i.get(field) == node_id for field in ("stepId", "producerStepId", "consumerStepId"))
                     or any(node_id in i.get(field, ()) for field in ("stepIds", "consumerStepIds", "participantStepIds"))) ]
                    for k, v in raw.items() if isinstance(v, list)}
            if addressed(old.resource_plan) != addressed(candidate.resource_plan):
                raise GraphRevisionError(Code.INVALID_PROPOSAL, "protected logical implementation changed")
    edges = lambda graph: {(e.source_id, e.target_id, e.edge_type.value) for e in graph.edges}
    before, after = edges(old), edges(candidate)
    if {e for e in before if e[1] in protected_nodes} != {e for e in after if e[1] in protected_nodes}:
        raise GraphRevisionError(Code.INVALID_PROPOSAL, "effective graph predecessors changed")
    if patch != derive_graph_patch(old, candidate, patch_id=patch.patch_id, reason=patch.reason):
        raise GraphRevisionError(Code.INVALID_PROPOSAL, "graph diff is not derived from canonical inputs")
    touched = set(patch.removed_node_ids) | {n["nodeId"] for n in patch.added_nodes} | {n["nodeId"] for n in patch.updated_nodes}
    touched |= {e[k] for e in (*patch.added_edges, *patch.removed_edges) for k in ("sourceId", "targetId")}
    return SafeCutProof(protectedTaskKeys=tuple(sorted(protected_keys)), protectedNodeIds=tuple(sorted(protected_nodes)),
        touchedNodeIds=tuple(sorted(touched)), sourceGraphFingerprint=content_fingerprint(old),
        candidateGraphFingerprint=content_fingerprint(candidate), effectiveDependencyFingerprint=fingerprint(sorted(before)),
        executionEvidenceFingerprint=fingerprint(dict(state=state.model_dump(mode="json"), receipts=receipts,
            activeStepIds=run.active_step_ids, completedStepIds=run.completed_step_ids,
            steps=[s.model_dump(mode="json") for s in run.steps])), checkpointFingerprint=fingerprint(cp))


class GraphProvider(RuntimePlanningCommitProvider):
    def __init__(self, authority, run_id, payload, source, principal):
        super().__init__(authority, run_id, payload, False, principal)
        self.source = source
        self._derived_fingerprint = None

    def authorize(self, request=None):
        return self.runtime.planning_commit_authority is not None and super().authorize(request)

    def get_current_sources(self, mission_id):
        run = self.run()
        if (len(run.steps) > 256 or len((run.acg_blueprint or {}).get("edges", ())) > 1024
                or len(run.model_dump_json()) > 2_000_000
                or len(self.node_commits(run)) > 1024
                or len(self.runtime.workflow_store.list_planning_inputs(run.run_id)) > 64
                or len(self.runtime.agent_registry.all()) > 256
                or len(self.runtime.capability_catalog.available()) > 512):
            raise GraphRevisionError(Code.INVALID_PROPOSAL, "graph verification input exceeds bounded policy")
        current = super().get_current_sources(mission_id)
        return current.model_copy(update={"strategy_fingerprint": fingerprint(dict(base=current.strategy_fingerprint,
            provenance=source_provenance(self).model_dump(mode="json"), checkpoint=checkpoint(self, run),
            graphPolicy="safe-cut-dag-v1"))})

    def get_source_provenance(self, request):
        # The proposal was derived from this checked input batch; metadata must
        # not silently sample a different live batch after validation.
        return self.payload.source_provenance

    def validate_proposal(self, request):
        try:
            source = self.store.get(self.source.commit_id)
            run = self.run()
            if (source != self.source or source.proposal_type != "plan_revision"
                    or source.source_provenance is None or source.source_provenance != source_provenance(self)
                    or source.mission_id != run.mission_id or source.sources.observation_id != request.sources.observation_id
                    or source.sources.plan_version != request.sources.plan_version
                    or source.sources.graph_version != request.sources.graph_version):
                raise GraphRevisionError(Code.STALE_STRATEGY, "source commitment no longer matches trusted origin")
            existing = self.store.graph_revision_for(source.commit_id)
            if existing:
                raise GraphRevisionError(Code.DUPLICATE_CONFLICT, "source already has a graph commitment; replay its original key")
            if self.store.latest(run.mission_id).commit_id != source.commit_id:
                raise GraphRevisionError(Code.STALE_COMMITMENT, "source is no longer the Mission acceptance head")
            candidate = self.payload
            if (request.proposal_type != "graph_revision" or content_fingerprint(candidate) != request.proposal_fingerprint
                    or self._derived_fingerprint != request.proposal_fingerprint
                    or candidate.source_commit_id != source.commit_id
                    or candidate.source_proposal_fingerprint != source.proposal_fingerprint
                    or candidate.source_provenance != source.source_provenance
                    or set(request.requested_scope) != {n.key for n in candidate.next_plan.nodes}):
                raise GraphRevisionError(Code.INVALID_PROPOSAL, "graph commitment identity mismatch")
            proof = safe_cut(self, source, candidate.next_plan, candidate.next_bindings, candidate.candidate_graph, candidate.graph_patch)
            if proof != candidate.safe_cut:
                raise GraphRevisionError(Code.INVALID_PROPOSAL, "safe-cut evidence changed")
            return None
        except GraphRevisionError as exc:
            return PlanningCommitRejection(code=exc.code, reason=exc.reason)
        except (ValueError, KeyError, TypeError):
            return PlanningCommitRejection(code=Code.INVALID_PROPOSAL, reason="invalid graph commitment evidence")


def accept_graph_revision(authority, run_id, source_commit_id, key):
    """Only this trusted adapter constructs candidates; there is no payload API."""
    try:
        runtime, store = authority.runtime, authority.store
        if not store.supports_graph_revisions:
            return PlanningCommitRejection(code=Code.STORAGE_UNAVAILABLE, reason="graph commitment index requires explicit schema preparation")
        with runtime.run_lock_manager.lock_for(run_id):
            source = store.get(source_commit_id)
            if source is None or source.proposal_type != "plan_revision" or not isinstance(source.proposal_payload, TaskPlanPatch):
                raise GraphRevisionError(Code.INVALID_PROPOSAL, "accepted semantic revision required")
            provider = GraphProvider(authority, run_id, None, source,
                runtime.semantic_principal_provider() if runtime.semantic_principal_provider else None)
            if provider.authorize() is not True or source.mission_id != provider.run().mission_id:
                raise GraphRevisionError(Code.AUTHORITY_DENIED, "source Mission authority denied")
            cached = store.get_by_idempotency_key(key)
            if cached:
                if (cached.proposal_type != "graph_revision" or cached.proposal_payload.source_commit_id != source_commit_id
                        or cached.proposal_payload.source_provenance.source_run_id != run_id):
                    raise GraphRevisionError(Code.DUPLICATE_CONFLICT, "key binds another graph commitment")
                provider.payload = cached.proposal_payload
                return PlanningCommitService(current_state_provider=provider, store=store).accept(authority.replay_request(cached, key))
            if source.source_provenance is None:
                raise GraphRevisionError(Code.INVALID_PROPOSAL, "legacy source has no versioned recoverable provenance")
            if source.sources.mission_revision != provider.get_current_sources(source.mission_id).mission_revision:
                raise GraphRevisionError(Code.STALE_MISSION, "Mission revision changed")
            if source.source_provenance != source_provenance(provider):
                raise GraphRevisionError(Code.STALE_STRATEGY, "source Run or provenance changed")
            if store.latest(source.mission_id).commit_id != source.commit_id:
                raise GraphRevisionError(Code.STALE_COMMITMENT, "source commitment is stale")
            captured = provider.get_current_sources(source.mission_id)
            run = provider.run()
            frozen_inputs = planning_inputs(provider, run)
            if source.source_provenance != source_provenance(provider, run=run, inputs=frozen_inputs):
                raise GraphRevisionError(Code.STALE_STRATEGY, "actual derivation inputs do not match accepted provenance")
            workflow, catalog, profiles = frozen_inputs
            agents = AgentRegistry()
            for profile in profiles:
                agents.register(SimpleNamespace(profile=profile))
            # Existing S02 semantic guard is computed before any graph lowering,
            # outside the ledger write transaction. No execution value is written.
            semantic = RuntimePlanningCommitProvider(authority, run_id, source.proposal_payload, False, provider.principal)
            semantic.validation_catalog = catalog
            request = authority._request(semantic, source.proposal_payload, "graph-preflight", "graph-preflight")
            problem = semantic.validate_proposal(request)
            if problem: return problem
        old = RuntimeBlueprintSpec.model_validate(run.acg_blueprint)
        if any(n.node_type == "control" for n in old.nodes):
            raise GraphRevisionError(Code.CONTROL_BARRIER_BLOCKED, "deterministic lowering cannot prove preservation of historical control regions")
        result = SemanticGraphPatchService().apply(blueprint=old,
            request=SemanticPatchRequest(patchId="graph-from:" + source.commit_id, idempotencyKey=key,
                runId=run_id, graphId=old.graph_id, baseGraphVersion=old.version,
                taskPlanPatch=source.proposal_payload, createdAt=run.created_at),
            current_plan=TaskPlan.model_validate(run.execution_state["taskPlan"]),
            base_bindings=tuple(TaskImplementationBinding.model_validate(b) for b in run.execution_state["taskBindings"]),
            agent_registry=agents, domain=workflow.domain, capability_catalog=catalog)
        # Lowerer's wall-clock timestamps are not semantic choices: normalize to
        # the frozen source timestamps for deterministic restart reconstruction.
        result.blueprint.created_at, result.blueprint.updated_at = old.created_at, old.updated_at
        old_edges = {(e.source_id, e.target_id, e.edge_type): e for e in old.edges}
        for index, edge in enumerate(result.blueprint.edges):
            identity = (edge.source_id, edge.target_id, edge.edge_type)
            previous = old_edges.get(identity)
            if previous is not None:
                result.blueprint.edges[index] = previous.model_copy(deep=True)
            else:
                edge.edge_id = "edge_" + fingerprint([source.commit_id, edge.source_id, edge.target_id, edge.edge_type.value])[:20]
        patch = derive_graph_patch(old, result.blueprint, patch_id="graph-from:" + source.commit_id)
        with runtime.run_lock_manager.lock_for(run_id):
            proof = safe_cut(provider, source, result.next_plan, result.next_bindings, result.blueprint, patch)
            candidate = GraphRevisionProposal(sourceCommitId=source.commit_id, missionId=source.mission_id,
                missionRevision=source.source_revision, sourceProposalFingerprint=source.proposal_fingerprint,
                sourceProvenance=source.source_provenance, basePlanVersion=source.sources.plan_version,
                nextPlan=result.next_plan, nextBindings=result.next_bindings, candidateGraph=result.blueprint, graphPatch=patch, safeCut=proof)
            provider.payload = candidate
            if len(candidate.model_dump_json()) > 2_000_000:
                raise GraphRevisionError(Code.INVALID_PROPOSAL, "derived graph candidate exceeds bounded policy")
            provider._derived_fingerprint = content_fingerprint(candidate)
            request = PlanningCommitRequest(proposalId="graph-revision:" + source.commit_id, proposalType="graph_revision",
                proposalFingerprint=content_fingerprint(candidate), sources=captured,
                requestedScope=tuple(n.key for n in result.next_plan.nodes), idempotencyKey=key,
                expectedCommitmentRevision=source.commitment_revision)
            return PlanningCommitService(current_state_provider=provider, store=store).accept(request)
    except GraphRevisionError as exc:
        return PlanningCommitRejection(code=exc.code, reason=exc.reason)
    except (ValueError, KeyError, TypeError):
        return PlanningCommitRejection(code=Code.INVALID_PROPOSAL, reason="graph candidate derivation failed")
