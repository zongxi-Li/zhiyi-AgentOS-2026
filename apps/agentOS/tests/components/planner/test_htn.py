"""Deterministic HTN contracts/algorithms, and actual SQLite Runtime tool feedback."""
import asyncio
import json
from copy import deepcopy
from dataclasses import replace

import pytest
from pydantic import ValidationError

from components.executor import ACGExecutionState
from components.mission_manager.semantic_service import MissionSemanticService
from components.planner.htn import (HTNBudget, HTNError, HTNMethodCatalog, HTNMethodSelector,
                                    build_native_htn_catalog, htn_planning_enabled)
from components.planner.react_loop import BoundedReActPlanningLoop
from components.planner.unified_actions import PlannerActionGateway
from contracts.htn import HTNCondition, HTNMethod, HTNSubtask
from contracts.mission_semantic import (MissionIntentBasis, MissionSemanticRequest, SemanticPrincipal,
                                       intent_basis_fingerprint, run_intent_basis)
from contracts.planner_actions import PlannerActionRequest, PlannerProposalReceipt
from contracts.planning import PlannedTask, TaskPlan, TaskPlanRelation
from contracts.runtime_planning import (RuntimePlanningObservation, RuntimePlanningRound,
                                        RuntimePlanningState, StepObservation)
from contracts.workflow import StepStatus, WorkflowDefinition, WorkflowStepDefinition, WorkflowStatus
from support.acg.native_capabilities import build_default_capability_catalog
from test_react_loop import ReActFakeLLM, runtime_at


@pytest.fixture
def context():
    raw = dict(missionId="mission_000000000001", sourceType="SEMANTIC", sourceRevision=1,
        commitId="sem-1", objective="Compare evidence", constraints=[
            dict(constraintId="policy", text="preserve privacy", sourceRefs=["input:brief"])],
        sourceReferences=["input:brief"], sourceStatus="UNVERIFIED",
        basisSchemaVersion=1, fingerprintVersion=1)
    basis = MissionIntentBasis(**raw, fingerprint=intent_basis_fingerprint(raw))
    plan = TaskPlan(missionId=basis.mission_id, nodes=(PlannedTask(key="task:root", title="analysis",
        objective=basis.objective, capabilityRequirements=("task_understanding",),
        metadata={"taskType": "analysis"}, sourceRefs=("input:brief",),
        constraints=[dict(type="local", value="preserve local constraint")],
        acceptanceCriteria=("source references are traceable",)),))
    observation = RuntimePlanningObservation(missionId=basis.mission_id, runId="run-test", graphId="graph-test",
        graphVersion=1, planVersion=1, wakeReason="resume", goal=basis.objective,
        missionIntentBasisRef=basis.reference(), remainingStepIds=("root",),
        steps=(StepObservation(stepId="root", taskKey="task:root", status="pending"),))
    return dict(plan=plan, target_key="task:root", basis=basis, observation=observation)


def selector(methods=None, budget=None):
    return HTNMethodSelector(catalog=HTNMethodCatalog(methods) if methods is not None else build_native_htn_catalog(),
        capability_catalog=build_default_capability_catalog(), budget=budget)


def expansion(s, context, method="analysis.evidence", **kw):
    return s.expand(**context, method_id=method, catalog_revision=s.catalog.revision, **kw)


def slot(key, capability=None, abstract=None, **kw):
    return HTNSubtask(task=PlannedTask(key=key, title=key, objective=key,
        capabilityRequirements=(capability,) if capability else (), **kw), abstractTask=abstract)


def method(method_id="custom", abstract="analysis", *, slots=None, ordering=(), conditions=()):
    return HTNMethod(methodId=method_id, abstractTask=abstract,
        subtasks=slots or (slot("understand", "task_understanding"),), ordering=ordering,
        applicability=conditions, sourceRefs=(f"htn:test:{method_id}",))


def edge(source, target):
    return TaskPlanRelation(sourceKey=source, targetKey=target, relationType="depends_on")


def test_multiple_legal_methods_and_condition_selection(context):
    legal = method("legal", conditions=(HTNCondition(source="constraint", key="policy", equals="preserve privacy"),))
    unavailable = method("unavailable", slots=(slot("x", "nonexistent"),))
    conditional = method("on-failure", conditions=(HTNCondition(source="wake_reason", equals="failure"),))
    s = selector((method("always"), legal, conditional, unavailable))
    projection = s.query(**context)
    assert {c.method_id for c in projection.candidates if c.applicable} == {"always", "legal"}
    assert expansion(s, context, "legal").selections[0].method_id == "legal"
    changed = {**context, "observation": context["observation"].model_copy(update={"wake_reason": "failure"})}
    assert expansion(s, changed, "on-failure").selections[0].method_id == "on-failure"
    with pytest.raises(HTNError, match="HTN_METHOD_NOT_APPLICABLE"):
        expansion(s, context, "on-failure")


def test_unknown_conflicting_or_missing_conditions_reject(context):
    conditions = (HTNCondition(source="constraint", key="policy", equals="preserve privacy"),
                  HTNCondition(source="constraint", key="policy", equals="discard privacy"))
    s = selector((method(conditions=conditions), method("missing", conditions=(
        HTNCondition(source="audit_outcome", key="unknown-task", equals="allow"),))))
    assert not any(c.applicable for c in s.query(**context).candidates)
    for name, code in (("custom", "HTN_METHOD_NOT_APPLICABLE"), ("unknown", "HTN_UNKNOWN_METHOD")):
        with pytest.raises(HTNError, match=code):
            expansion(s, context, name)
    with pytest.raises(HTNError, match="HTN_UNKNOWN_METHOD"):
        expansion(s, context, "custom", preferred_method_ids=("forged",))


def test_multilevel_expansion_inherits_contracts_and_stable_keys(context):
    s = selector()
    before = deepcopy(context)
    proposal = expansion(s, context)
    assert len(proposal.selections) == 2 and len(proposal.atomic_keys) == 4
    assert len(proposal.nodes) == 6
    by_key = {n.key: n for n in proposal.nodes}
    assert all(n.parent_key in by_key for n in proposal.nodes[1:])
    assert all("input:brief" in n.source_refs for n in proposal.nodes)
    assert all(any(c.get("constraintId") == "policy" for c in n.constraints) for n in proposal.nodes)
    assert all("source references are traceable" in n.acceptance_criteria for n in proposal.nodes)
    atomic_edges = [e for e in proposal.relations if e.relation_type.value == "depends_on"]
    assert len(atomic_edges) >= 5 and all(e.source_key in proposal.atomic_keys for e in atomic_edges)
    assert proposal.basis_fingerprint == context["basis"].fingerprint
    assert context == before  # input contracts did not mutate
    modified = [m.model_copy(update={"version": m.version + 1}) for m in s.catalog.methods()]
    revised = selector(modified)
    assert revised.catalog.revision != s.catalog.revision
    assert [n.key for n in expansion(revised, context).nodes] == [n.key for n in proposal.nodes]
    assert expansion(selector(), context) == proposal  # restart rebuild is deterministic


def test_nested_ranking_only_selects_applicable_known_methods(context):
    root = method("root", slots=(slot("nested", abstract="child"),))
    s = selector((root, method("child-a", "child"), method("child-b", "child")))
    assert expansion(s, context, "root").selections[-1].method_id == "child-a"
    assert expansion(s, context, "root", preferred_method_ids=("child-b",)).selections[-1].method_id == "child-b"


@pytest.mark.parametrize("methods,code", [
    ((method(slots=(slot("again", abstract="analysis"),)),), "HTN_EXPANSION_CYCLE"),
    ((method(slots=(slot("a", "task_understanding"), slot("b", "analysis")),
             ordering=(edge("a", "b"), edge("b", "a"))),), "HTN_TOPOLOGY_INVALID"),
    ((method(slots=(slot("retrieve", "information_retrieval"),)),), "HTN_TOPOLOGY_INVALID"),
    ((method(slots=(slot("child", abstract="absent"),)),), "HTN_NO_APPLICABLE_METHOD"),
])
def test_cycle_illegal_dag_missing_producer_or_nested_method_reject(context, methods, code):
    with pytest.raises(HTNError, match=code):
        expansion(selector(methods), context, "custom")


@pytest.mark.parametrize("field", ["max_depth", "max_nodes", "max_relations", "max_candidates", "max_content_chars"])
def test_expansion_budgets_fail_closed(context, field):
    with pytest.raises(HTNError, match="HTN_BUDGET_EXHAUSTED"):
        expansion(selector(budget=replace(HTNBudget(), **{field: 1})), context)


def test_deadline_and_unknown_catalog_version_reject(context):
    s = selector()
    with pytest.raises(HTNError, match="HTN_BUDGET_EXHAUSTED"):
        expansion(s, context, deadline=0)
    with pytest.raises(HTNError, match="HTN_CATALOG_CHANGED"):
        s.expand(**context, method_id="analysis.standard", catalog_revision="f" * 64)


@pytest.mark.parametrize("status", ["completed", "running", "failed", "skipped", "waiting_review"])
def test_settled_or_active_tasks_cannot_expand(context, status):
    o = context["observation"]
    context["observation"] = o.model_copy(update={"steps": (o.steps[0].model_copy(update={"status": status}),)})
    with pytest.raises(HTNError, match="HTN_SETTLED_OR_ACTIVE_TASK"):
        expansion(selector(), context)


def test_missing_sources_and_constraint_loss_cannot_pass(context):
    with pytest.raises(ValidationError):
        HTNMethod.model_validate({**method().model_dump(by_alias=True), "sourceRefs": []})
    for sources, code in (((), "HTN_SOURCE_REQUIRED"), (("forged",), "HTN_UNKNOWN_SOURCE")):
        plan = context["plan"].model_copy(update={"nodes": (context["plan"].nodes[0].model_copy(update={"source_refs": sources}),)})
        with pytest.raises(HTNError, match=code):
            expansion(selector(), {**context, "plan": plan})
    conflict = method(slots=(slot("a", "task_understanding", constraints=[
        dict(constraintId="policy", value="discard privacy")]),))
    with pytest.raises(HTNError, match="HTN_CONSTRAINT_CONFLICT"):
        expansion(selector((conflict,)), context, "custom")
    unknown = method(slots=(slot("a", "task_understanding", sourceRefs=("fake-evidence",)),))
    with pytest.raises(HTNError, match="HTN_UNKNOWN_SOURCE"):
        expansion(selector((unknown,)), context, "custom")


def test_unknown_root_missing_basis_and_abstract_products_cannot_pass(context):
    with pytest.raises(HTNError, match="HTN_BASIS_REQUIRED"):
        expansion(selector(), {**context, "basis": None})
    with pytest.raises(HTNError, match="HTN_UNKNOWN_ABSTRACT_TASK"):
        expansion(selector(), {**context, "target_key": "unknown"})
    root = context["plan"].nodes[0].model_copy(update={"produced_artifacts": ("report",)})
    plan = TaskPlan(missionId=context["plan"].mission_id, nodes=(root,), expectedArtifacts=("report",))
    with pytest.raises(HTNError, match="HTN_TOPOLOGY_INVALID"):
        expansion(selector(), {**context, "plan": plan})


def test_catalog_is_a_deep_immutable_snapshot_and_contract_rejects_forgery():
    original = method()
    catalog = HTNMethodCatalog((original,))
    original.subtasks[0].task.constraints.append(dict(type="changed", value="untrusted"))
    assert not catalog.methods()[0].subtasks[0].task.constraints
    catalog.methods()[0].subtasks[0].task.constraints.append(dict(type="changed", value="untrusted"))
    assert not catalog.methods()[0].subtasks[0].task.constraints
    with pytest.raises(ValueError, match="unique"):
        HTNMethodCatalog((method(), method()))
    for forged in ({"definition": {}}, {"runId": "fake"}, {"capabilityId": "analysis"}):
        with pytest.raises(ValidationError):
            PlannerActionRequest.model_validate({"requestRef": "r", "proposal": {"kind": "method",
                "targetKey": "root", "methodId": "custom", "catalogRevision": catalog.revision, **forged}})


# Actual Runtime creates the Mission/Basis/TaskPlan/ACG, and builds the observation.
# Only test harness setup writes its own temporary SQLite state.
@pytest.fixture
def runtime_boundary(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOS_PLANNER_HTN", "1")
    runtime, store, agent = runtime_at(tmp_path)
    runtime.workflow_registry.register(WorkflowDefinition(workflowId="htn", name="htn", domain="general",
        runtimeEngine="acg", planningNodes=(PlannedTask(key="step:A", title="A", objective="analyze input",
            capabilityRequirements=("task_understanding",), metadata={"taskType": "analysis"},
            sourceRefs=("input:brief",)),),
        steps=(WorkflowStepDefinition(stepId="A", name="A", agentName="runner"),)))
    owner = SemanticPrincipal(actorId="owner", tenantId="tenant")
    store._init_semantic_schema()
    store.enable_existing_mission_semantics()
    runtime.mission_semantic_service = MissionSemanticService(store=store, authorize=lambda p, m, a: p == owner)
    runtime.semantic_principal_provider = lambda: owner
    runtime.allow_legacy_mission_intent = False
    mission = runtime.create_mission("HTN", workflow_id="htn")
    runtime.mission_semantic_service.commit(owner, MissionSemanticRequest(missionId=mission.mission_id,
        operationId="first", expectedMissionRevision=0, objective="Analyze input", constraints=[],
        sourceRefs=["input:brief"]))
    _, run = runtime.prepare_run(mission.mission_id)
    # A restarted, quiescent RUNNING Run has pending nodes and no work receipts.
    # ExecutionRuntime re-enters its actual resume boundary before running an agent.
    run.status = runtime.state_machine.transition(run.status, WorkflowStatus.RUNNING)
    state = ACGExecutionState(runId=run.run_id, graphId=run.acg_blueprint["graphId"],
                              graphVersion=run.acg_blueprint["version"])
    observation = runtime.runtime_planning_coordinator.observe(run, state, "resume")
    run.execution_state["planningLoop"] = RuntimePlanningState(current=RuntimePlanningRound(
        observationId=observation.fingerprint(), observation=observation)).model_dump(by_alias=True, mode="json")
    store.save_run(run)
    return runtime, store, agent, run.run_id, state


def gateway_at(store, events=None):
    return PlannerActionGateway(workflow_store=store, capability_catalog=build_default_capability_catalog(),
        htn_selector=selector(), audit_sink=events.append if events is not None else None)


def method_request(ref, revision, method_id="analysis.evidence"):
    return dict(requestRef=ref, proposal=dict(kind="method", targetKey="step:A", methodId=method_id,
                                             catalogRevision=revision))


def query_request(ref="query"):
    return dict(requestRef=ref, query=dict(target="method_catalog", targetKey="step:A"))


def test_real_runtime_gateway_proposal_is_read_only_and_replayable(runtime_boundary):
    runtime, store, agent, run_id, _ = runtime_boundary
    events = []
    gw = gateway_at(store, events)
    session = gw.open_session(run_id)
    before = store.get_run(run_id).model_dump(mode="json")
    outbox = deepcopy(store.list_outbox())
    read = gw.submit(session.session_id, query_request())
    assert {c.method_id for c in read.method_catalog.candidates if c.applicable} == {"analysis.standard", "analysis.evidence"}
    request = method_request("select", read.method_catalog.catalog_revision)
    receipt = gw.submit(session.session_id, request)
    assert isinstance(receipt, PlannerProposalReceipt) and receipt.expansion
    assert gw.submit(session.session_id, request).expansion == receipt.expansion
    assert gw.submit(session.session_id, request).replayed
    assert session.actions_used == 2 and len(session.registered_proposals) == 1
    assert session.registered_proposals[0].expansion == receipt.expansion
    assert store.get_run(run_id).model_dump(mode="json") == before
    assert store.list_outbox() == outbox and agent.calls == []
    assert all("input:brief" not in json.dumps(e) for e in events)
    restarted = gateway_at(store)
    assert restarted.submit(session.session_id, request).code == "UNKNOWN_SESSION"
    fresh = restarted.open_session(run_id)
    assert restarted.submit(fresh.session_id, request).expansion == receipt.expansion


@pytest.mark.parametrize("change,code", [("plan", "PLAN_VERSION_MISMATCH"), ("observation", "STALE_OBSERVATION"),
                                        ("catalog", "HTN_CATALOG_CHANGED"), ("flag", "HTN_DISABLED")])
def test_htn_cached_results_never_bypass_changes(runtime_boundary, monkeypatch, change, code):
    _, store, _, run_id, _ = runtime_boundary
    gw = gateway_at(store)
    session = gw.open_session(run_id)
    request = method_request("select", gw.htn_selector.catalog.revision)
    assert isinstance(gw.submit(session.session_id, request), PlannerProposalReceipt)
    if change == "flag":
        monkeypatch.setenv("AGENTOS_PLANNER_HTN", "0")
    elif change == "catalog":
        gw.htn_selector.catalog = HTNMethodCatalog([m.model_copy(update={"version": 2}) for m in gw.htn_selector.catalog.methods()])
    else:
        run = store.get_run(run_id)
        if change == "plan":
            run.execution_state["taskPlan"]["planVersion"] = 2
        else:
            run.execution_state["planningLoop"]["current"]["observationId"] = "changed"
        store.save_run(run)
    assert gw.submit(session.session_id, request).code == code


def test_disabled_default_and_facade_assembly(runtime_boundary, monkeypatch):
    runtime, store, _, run_id, _ = runtime_boundary
    runtime.set_intent_llm(ReActFakeLLM([]))
    monkeypatch.setenv("AGENTOS_PLANNER_REACT_LOOP", "1")
    run = store.get_run(run_id)
    assert runtime._planning_engine_for_run(run).react_loop.gateway.htn_selector is not None
    monkeypatch.delenv("AGENTOS_PLANNER_HTN")
    assert not htn_planning_enabled()
    engine = runtime._planning_engine_for_run(run)
    assert engine.react_loop.gateway.htn_selector is None
    gw = gateway_at(store)
    session = gw.open_session(run_id)
    assert "method_catalog" not in session.allowed_reads
    assert gw.submit(session.session_id, method_request("off", gw.htn_selector.catalog.revision)).code == "HTN_DISABLED"
    monkeypatch.setenv("AGENTOS_PLANNER_HTN", "1")
    monkeypatch.setenv("AGENTOS_PLANNER_REACT_LOOP", "0")
    assert runtime._planning_engine_for_run(run).react_loop is None


def test_real_react_feedback_drives_method_selection_and_runtime_wait(runtime_boundary, monkeypatch, tmp_path):
    runtime, store, agent, run_id, state = runtime_boundary
    monkeypatch.setenv("AGENTOS_PLANNER_REACT_LOOP", "1")
    before = store.get_run(run_id)

    def query(payload):
        assert "htnPolicy" in payload
        return dict(turnKind="use_tool", actionRequest=query_request())

    def select_from_feedback(payload):
        catalog = payload["toolFeedback"][-1]["methodCatalog"]
        assert len([c for c in catalog["candidates"] if c["applicable"]]) == 2
        chosen = next(c["methodId"] for c in catalog["candidates"] if c["applicable"])
        return dict(turnKind="use_tool", actionRequest=method_request("select", catalog["catalogRevision"], chosen))

    def finish(payload):
        proposal = payload["toolFeedback"][-1]["expansion"]
        assert proposal["selections"][0]["methodId"] == "analysis.evidence"
        assert len(proposal["atomicKeys"]) == 4
        return dict(turnKind="decide", finalDecision=dict(observationId=payload["observationId"],
            action="wait", reason="HTN hierarchy awaits independent review"))

    llm = ReActFakeLLM([query, select_from_feedback, finish])
    recovered, recovered_store, recovered_agent = runtime_at(tmp_path)
    recovered.workflow_registry.register(runtime.workflow_registry.get("htn"))
    recovered.set_intent_llm(llm)
    after = asyncio.run(recovered.execute_prepared_run(run_id))
    assert after.status == WorkflowStatus.WAITING_REVIEW and agent.calls == []
    for field in ("taskPlan", "taskBindings", "missionIntentBasis"):
        assert before.execution_state[field] == after.execution_state[field]
    assert after.acg_blueprint == before.acg_blueprint and after.run_id == before.run_id
    assert after.execution_state["planningLoop"]["current"]["decision"]["action"] == "wait"
    assert len(llm.prompts) == 3
    assert asyncio.run(recovered.execute_prepared_run(run_id)).status == WorkflowStatus.WAITING_REVIEW
    assert len(llm.prompts) == 3  # persisted applied observation prevents duplicate calls
    assert recovered_agent.calls == [] and run_intent_basis(recovered_store.get_run(run_id)) == run_intent_basis(before)


@pytest.mark.parametrize("final_action", ["continue", "complete", "recover", "revise"])
def test_htn_cannot_turn_proposal_into_execution_or_revision(runtime_boundary, final_action):
    _, store, _, run_id, _ = runtime_boundary
    run = store.get_run(run_id)
    gw = gateway_at(store)
    observation = RuntimePlanningState.model_validate(run.execution_state["planningLoop"]).current.observation
    plan = TaskPlan.model_validate(run.execution_state["taskPlan"])
    patch = dict(missionId=run.mission_id, basePlanVersion=1, planVersion=2, addNodes=[])

    def final(payload):
        decision = dict(observationId=payload["observationId"], action=final_action, reason="attempt apply")
        if final_action == "revise":
            decision["taskPlanPatch"] = patch
        return dict(turnKind="decide", finalDecision=decision)

    llm = ReActFakeLLM([lambda p: dict(turnKind="use_tool", actionRequest=query_request()), final])
    loop = BoundedReActPlanningLoop(llm=llm, gateway=gw)
    assert loop.decide(observation=observation, task_plan=plan).action == "wait"
    session = next(iter(gw._sessions.values()))
    denied = gw.submit(session.session_id, dict(requestRef="revision", proposal=dict(kind="plan_revision", patch=patch)))
    assert denied.code == "PROPOSAL_ONLY"
    assert store.get_run(run_id).model_dump() == run.model_dump()


def test_revision_session_cannot_then_use_htn(runtime_boundary):
    _, store, _, run_id, _ = runtime_boundary
    gw = gateway_at(store)
    session = gw.open_session(run_id)
    run = store.get_run(run_id)
    patch = dict(missionId=run.mission_id, basePlanVersion=1, planVersion=2)
    assert isinstance(gw.submit(session.session_id, dict(requestRef="revision", proposal=dict(kind="plan_revision", patch=patch))), PlannerProposalReceipt)
    assert gw.submit(session.session_id, query_request()).code == "PROPOSAL_ONLY"


def test_rejected_tool_feedback_changes_the_next_method_choice(runtime_boundary):
    _, store, _, run_id, _ = runtime_boundary
    gw = gateway_at(store)
    run = store.get_run(run_id)
    observation = RuntimePlanningState.model_validate(run.execution_state["planningLoop"]).current.observation
    plan = TaskPlan.model_validate(run.execution_state["taskPlan"])

    def retry_with_query(payload):
        rejection = payload["toolFeedback"][-1]
        assert rejection["rejectionCode"] == "HTN_REJECTED" and rejection["rejectionReason"] == "HTN_UNKNOWN_METHOD"
        return dict(turnKind="use_tool", actionRequest=query_request())

    def choose_legal(payload):
        catalog = payload["toolFeedback"][-1]["methodCatalog"]
        chosen = next(c["methodId"] for c in catalog["candidates"] if c["applicable"])
        return dict(turnKind="use_tool", actionRequest=method_request("corrected", catalog["catalogRevision"], chosen))

    def finish(payload):
        assert payload["toolFeedback"][-1]["expansion"]["selections"][0]["methodId"] == "analysis.evidence"
        return dict(turnKind="decide", finalDecision=dict(observationId=payload["observationId"], action="wait", reason="review"))

    llm = ReActFakeLLM([lambda p: dict(turnKind="use_tool",
        actionRequest=method_request("wrong", gw.htn_selector.catalog.revision, "forged")), retry_with_query, choose_legal, finish])
    decision = BoundedReActPlanningLoop(llm=llm, gateway=gw).decide(observation=observation, task_plan=plan)
    assert decision.reason == "review" and len(llm.prompts) == 4
    assert store.get_run(run_id).model_dump() == run.model_dump()


@pytest.mark.parametrize("mutation", ["steps", "graph", "observation_content"])
def test_current_persisted_facts_are_checked_before_htn_replay(runtime_boundary, mutation):
    _, store, _, run_id, _ = runtime_boundary
    gw = gateway_at(store)
    session = gw.open_session(run_id)
    request = method_request("select", gw.htn_selector.catalog.revision)
    assert isinstance(gw.submit(session.session_id, request), PlannerProposalReceipt)
    run = store.get_run(run_id)
    if mutation == "steps":
        run.steps[0].status = StepStatus.COMPLETED
    elif mutation == "graph":
        run.acg_blueprint["version"] = 2
    else:
        run.execution_state["planningLoop"]["current"]["observation"]["wakeReason"] = "failure"
    store.save_run(run)
    assert gw.submit(session.session_id, request).code == "STALE_OBSERVATION"


def test_empty_method_registry_does_not_fake_a_valid_plan(context):
    with pytest.raises(HTNError, match="HTN_NO_METHOD"):
        selector(()).query(**context)


def test_external_dependencies_are_retained_and_key_collisions_reject(context):
    old_plan = context["plan"]
    external = PlannedTask(key="external", title="external", objective="existing work")
    relation = edge("external", "task:root")
    plan = TaskPlan(missionId=old_plan.mission_id, nodes=(*old_plan.nodes, external), relations=(relation,))
    proposal = expansion(selector(), {**context, "plan": plan})
    assert proposal.boundary_relations == (relation,)
    collision = PlannedTask(key=proposal.atomic_keys[0], title="existing", objective="existing")
    collided_plan = TaskPlan(missionId=old_plan.mission_id, nodes=(*old_plan.nodes, collision))
    with pytest.raises(HTNError, match="HTN_KEY_COLLISION"):
        expansion(selector(), {**context, "plan": collided_plan})


def test_receipts_worksets_and_existing_hierarchy_cannot_be_dropped(context):
    from contracts.planning import WorksetSpec
    root = context["plan"].nodes[0]
    workset_root = root.model_copy(update={"workset": WorksetSpec(sourceManifestRefs=("manifest:sealed",))})
    with pytest.raises(HTNError, match="HTN_WORKSET_UNSUPPORTED"):
        expansion(selector(), {**context, "plan": context["plan"].model_copy(update={"nodes": (workset_root,)})})
    child = PlannedTask(key="existing-child", title="child", objective="child", parentKey=root.key)
    plan = TaskPlan(missionId=context["plan"].mission_id, nodes=(root, child))
    with pytest.raises(HTNError, match="HTN_EXISTING_HIERARCHY"):
        expansion(selector(), {**context, "plan": plan})
    o = context["observation"]
    committed = o.model_copy(update={"steps": (o.steps[0].model_copy(update={"commit_id": "external-effect-receipt"}),)})
    with pytest.raises(HTNError, match="HTN_SETTLED_OR_ACTIVE_TASK"):
        expansion(selector(), {**context, "observation": committed})


def test_directory_change_during_expansion_is_rejected(context, monkeypatch):
    s = selector()
    original = s._candidates
    def replace_directory(*args, **kwargs):
        result = original(*args, **kwargs)
        s.catalog = HTNMethodCatalog([m.model_copy(update={"version": 2}) for m in s.catalog.methods()])
        return result
    monkeypatch.setattr(s, "_candidates", replace_directory)
    with pytest.raises(HTNError, match="HTN_CATALOG_CHANGED"):
        expansion(s, context)


def test_invalid_local_dependencies_and_predicates_are_rejected():
    with pytest.raises(ValidationError, match="local dependency"):
        method(ordering=(edge("understand", "unknown"),))
    with pytest.raises(ValidationError):
        HTNCondition(source="execute_arbitrary_code", equals="true")
    with pytest.raises(ValidationError):
        HTNCondition(source="constraint", equals="true")


def test_later_mission_revision_cannot_change_frozen_run_selection(runtime_boundary):
    runtime, store, _, run_id, _ = runtime_boundary
    run = store.get_run(run_id)
    owner = runtime.semantic_principal_provider()
    runtime.mission_semantic_service.commit(owner, MissionSemanticRequest(missionId=run.mission_id,
        operationId="second", expectedMissionRevision=1, objective="Different current Mission",
        constraints=[dict(constraintId="later", text="a new constraint", sourceRefs=[])], sourceRefs=[]))
    gw = gateway_at(store)
    session = gw.open_session(run_id)
    receipt = gw.submit(session.session_id, method_request("select", gw.htn_selector.catalog.revision))
    assert isinstance(receipt, PlannerProposalReceipt)
    assert receipt.expansion.basis_fingerprint == run_intent_basis(run).fingerprint
    assert all(not any(c.get("constraintId") == "later" for c in n.constraints) for n in receipt.expansion.nodes)
    assert run_intent_basis(store.get_run(run_id)).source_revision == 1
