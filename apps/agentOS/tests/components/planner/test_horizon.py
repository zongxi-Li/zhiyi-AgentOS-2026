"""S01-04 deterministic candidates and real SQLite Runtime authority fences."""
import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from pydantic import ValidationError

from components.planner.horizon import AdaptiveHorizonSelector, HorizonError
from components.planner.react_loop import BoundedReActPlanningLoop
from components.planner.unified_actions import PlannerActionGateway
from contracts.horizon import HorizonBudget, HorizonSelection
from contracts.mission_semantic import run_intent_basis
from contracts.planner_actions import PlannerActionRequest, PlannerProposalReceipt, PlannerReadResult
from contracts.planning import PlannedTask, TaskPlan, WorksetSpec
from contracts.runtime_planning import RuntimePlanningState, StepObservation, RuntimeResourceObservation
from contracts.workflow import WorkflowStatus, StepStatus
from support.acg.native_capabilities import build_default_capability_catalog
from test_htn import context, runtime_boundary, edge, gateway_at, query_request, selector, method_request
from test_react_loop import ReActFakeLLM, runtime_at


def ready_resource(runtime, run):
    from contracts.resource import ExecutionRequirement, RuntimeProfile, Placement
    requirement = ExecutionRequirement.model_validate(next(iter(run.execution_state["bindingRequirements"].values())))
    plane = runtime.resource_plane
    placement = requirement.allowed_placements[0] if requirement.allowed_placements else Placement.DEVICE
    plane.ensure_node("node:horizon-test", placement=placement)
    plane.register_runtime(RuntimeProfile(runtimeId="runtime:horizon-test", nodeId="node:horizon-test",
        placement=placement, kind=requirement.runtime_kinds[0], capabilities=list(requirement.required_capabilities),
        trust=requirement.min_trust or "host_trusted", domains=[requirement.domain] if requirement.domain else []))
    plane.heartbeat_runtime("runtime:horizon-test")
    assert runtime.resource_binder.assess(requirement).ready


@pytest.fixture
def ready_boundary(runtime_boundary):
    runtime, store, agent, run_id, state = runtime_boundary
    run = store.get_run(run_id)
    ready_resource(runtime, run)
    observation = runtime.runtime_planning_coordinator.observe(run, state, "resume")
    current = RuntimePlanningState.model_validate(run.execution_state["planningLoop"]).current
    current = current.model_copy(update={"observation": observation, "observation_id": observation.fingerprint()})
    run.execution_state["planningLoop"] = RuntimePlanningState(current=current).model_dump(by_alias=True, mode="json")
    store.save_run(run)
    return runtime, store, agent, run_id, state


def inputs(context, keys=("A", "B", "C"), relations=(), statuses=None, risks=None, costs=None):
    statuses, risks, costs = statuses or {}, risks or {}, costs or {}
    nodes = tuple(PlannedTask(key=k, title=k, objective=k,
        capabilityRequirements=("task_understanding",), sourceRefs=("input:brief",),
        constraints=[{"constraintId": "policy", "text": "preserve privacy"}],
        acceptanceCriteria=("trace sources",), metadata={"risk": risks.get(k, "normal")},
        workset=WorksetSpec(sourceManifestRefs=("manifest:sealed",), estimatedUnitCount=costs[k]) if k in costs else None)
        for k in keys)
    steps = tuple(StepObservation(stepId=k, taskKey=k, status=statuses.get(k, "pending"),
        outputRef="output:"+k if statuses.get(k) == "completed" else None,
        commitId="commit:"+k if statuses.get(k) == "completed" else None,
        auditRef="audit:"+k if statuses.get(k) == "completed" else None,
        auditOutcome="allow" if statuses.get(k) == "completed" else None) for k in keys)
    return dict(plan=TaskPlan(missionId=context["basis"].mission_id, nodes=nodes, relations=relations),
        basis=context["basis"], observation=context["observation"].model_copy(update={
            "steps": steps, "remaining_step_ids": tuple(k for k in keys if statuses.get(k) != "completed")}))


def engine(**kw):
    return AdaptiveHorizonSelector(build_default_capability_catalog(), **kw)


def test_stability_restart_and_input_preservation(context):
    data = inputs(context, relations=(edge("A", "C"), edge("B", "C")))
    before = deepcopy(data)
    p = engine().propose(**data)
    assert p == engine().propose(**data) and data == before
    assert p.candidate_keys == ("A", "B", "C") and p.ready_keys == ("A", "B")
    assert p.used_cost_units == 3 and p.reservation_status == "not_reserved"
    assert p.frontier.basis_fingerprint == data["basis"].fingerprint
    assert p.frontier.observation_id == data["observation"].fingerprint()
    assert p.frontier.validation_scope == "task_plan_snapshot_only"
    assert all(t.task_fingerprint for t in p.frontier.tasks)


def test_dependency_priority_is_not_fixed_prefix(context):
    s = engine(budget=HorizonBudget(costUnits=1))
    independent = s.propose(**inputs(context))
    dependency = s.propose(**inputs(context, relations=(edge("B", "C"),)))
    reordered = inputs(context, keys=("C", "A", "B"), relations=(edge("B", "C"),))
    assert independent.candidate_keys == ("A",)
    assert dependency.candidate_keys == ("B",) == s.propose(**reordered).candidate_keys
    assert len(dependency.cross_window_dependencies) == 1
    assert not dependency.cross_window_dependencies[0].prerequisite_completed


def test_risk_cost_and_budget_adapt_the_window(context):
    low = engine().propose(**inputs(context))
    expensive = engine().propose(**inputs(context, costs={"A": 20}))
    risky = engine().propose(**inputs(context, risks={k: "high" for k in ("A", "B", "C")}))
    tight = engine(budget=HorizonBudget(costUnits=2)).propose(**inputs(context))
    assert len(low.candidate_keys) == 3
    assert expensive.candidate_keys == ("B", "C")
    assert risky.candidate_keys == ("A",) and len(tight.candidate_keys) == 2
    assert len({p.frontier.input_fingerprint for p in (low, expensive, risky, tight)}) == 4


@pytest.mark.parametrize("status,classification", [
    ("running", "active"), ("retrying", "active"), ("failed", "failed"),
    ("waiting_review", "review_wait"), ("cancelled", "terminal"),
    ("skipped_by_condition", "terminal"), ("bogus", "unknown"), ("completed", "completed")])
def test_status_and_external_dependency_boundaries(context, status, classification):
    data = inputs(context, relations=(edge("A", "B"),), statuses={"A": status})
    p = engine().propose(**data)
    assert p.frontier.tasks[0].classification == classification and "A" not in p.candidate_keys
    assert ("B" in p.candidate_keys) == (status == "completed")
    assert all(r.relation.source_key == "A" for r in p.cross_window_dependencies)
    assert {r.source_key for r in p.frontier.dependencies} == {"A"}


@pytest.mark.parametrize("field,value", [("commit_id", None), ("audit_ref", None),
    ("audit_outcome", "deny"), ("verification_report", "failed")])
def test_unproven_completed_work_is_never_reexecuted(context, field, value):
    data = inputs(context, keys=("A", "B"), relations=(edge("A", "B"),), statuses={"A": "completed"})
    o = data["observation"]
    data["observation"] = o.model_copy(update={"steps": (o.steps[0].model_copy(update={field: value}), o.steps[1])})
    assert not engine().propose(**data).candidate_keys


def test_resource_readiness_has_no_reservation_authority(context):
    data = inputs(context, keys=("A",))
    o = data["observation"]
    r = RuntimeResourceObservation(stepId="A", requirementId="r"*64, ready=False,
        requiredCapabilities=("task_understanding",), runtimeKinds=("execution_backend",),
        allowedPlacements=("device",), candidateCount=0)
    data["observation"] = o.model_copy(update={"resource_requirements": (r,)})
    p = engine().propose(**data)
    assert not p.candidate_keys and p.frontier.tasks[0].classification == "resource_wait"
    data["observation"] = o.model_copy(update={"resource_requirements": (r.model_copy(update={"ready": True}),)})
    p = engine().propose(**data)
    assert p.candidate_keys == ("A",) and p.reservation_status == "not_reserved"
    assert engine().propose(**inputs(context, keys=("A",))).frontier.tasks[0].readiness == "unknown"


def test_review_and_loop_control_cannot_be_bypassed(context):
    from contracts.planning import VerificationLoopPolicy
    data = inputs(context)
    o = data["observation"]
    data["observation"] = o.model_copy(update={"completion_blockers": ("review_unresolved:A",)})
    assert not engine().propose(**data).candidate_keys
    data["observation"] = o
    data["plan"] = data["plan"].model_copy(update={"control_policies": (
        VerificationLoopPolicy(bodyEntryKey="A", bodyExitKey="B", conditionSourceKey="C"),)})
    # Compiler may reject a nonsensical loop first; either rejection or a control hold is safe.
    try:
        p = engine().propose(**data)
    except (HorizonError, ValueError):
        return
    assert not p.candidate_keys and all(t.classification == "control_wait" for t in p.frontier.tasks)


def test_catalog_review_and_risk_are_not_lowered_by_task_metadata(context):
    s = engine()
    descriptor = s.capability_catalog.resolve("task_understanding")
    descriptor.risk_level_hint = "critical"
    descriptor.requires_review = True
    p = s.propose(**inputs(context))
    assert p.candidate_keys == ("A",) and p.used_risk_units == 8
    assert all(t.risk_units == 8 and t.requires_review for t in p.frontier.tasks)
    assert all(d.reason == "review_boundary" for d in p.deferred)


def test_bounded_model_subset_and_all_dependency_edges_preserved(context):
    data = inputs(context, relations=(edge("A", "B"), edge("B", "C")))
    s = engine()
    p = s.propose(**data)
    subset = s.propose(**data, selected_keys=("A", "B"), input_fingerprint=p.frontier.input_fingerprint)
    all_edges = (*subset.internal_dependencies, *(b.relation for b in subset.cross_window_dependencies))
    assert set((r.source_key, r.target_key) for r in all_edges) == {("A", "B"), ("B", "C")}
    for keys, error in [(('C',), "DEPENDENCY_GAP"), (('invented',), "OUTSIDE_CANDIDATES"),
                        (('A', 'A'), "OUTSIDE_CANDIDATES")]:
        with pytest.raises(HorizonError, match=error):
            s.propose(**data, selected_keys=keys)
    assert not s.propose(**data, selected_keys=()).candidate_keys


@pytest.mark.parametrize("mutation", ["basis", "plan", "observation", "budget", "catalog"])
def test_pure_input_binding_changes_reject_stale_selection(context, mutation):
    data, s = inputs(context), engine()
    p = s.propose(**data)
    if mutation == "basis":
        data["basis"] = None
    elif mutation == "plan":
        data["plan"] = data["plan"].model_copy(update={"metadata": {"rationale": "new"}})
    elif mutation == "observation":
        data["observation"] = data["observation"].model_copy(update={"wake_reason": "restart"})
    elif mutation == "budget":
        s.budget = HorizonBudget(costUnits=1)
    else:
        s.capability_catalog.resolve("task_understanding").risk_level_hint = "elevated"
    with pytest.raises(HorizonError, match="BINDING_MISMATCH|STALE_INPUT"):
        s.propose(**data, selected_keys=p.candidate_keys, input_fingerprint=p.frontier.input_fingerprint)


def test_input_depth_edge_count_and_deadline_bounds(context):
    s = engine(monotonic_clock=lambda: 10)
    with pytest.raises(HorizonError, match="DEADLINE"):
        s.propose(**inputs(context), deadline=9)
    with pytest.raises(HorizonError, match="INPUT_BUDGET"):
        s.propose(**inputs(context, keys=tuple(f"k:{i}" for i in range(257))))
    with pytest.raises(HorizonError, match="INPUT_BUDGET"):
        s.propose(**inputs(context, keys=tuple(f"k:{i}" for i in range(65)),
            relations=tuple(edge(f"k:{i}", f"k:{j}") for i in range(32) for j in range(32,65))))


def test_shared_compiler_is_required_and_no_invalid_topology_fallback(context):
    data = inputs(context, keys=("A", "B"))
    data["plan"] = data["plan"].model_copy(update={"relations": (edge("A", "B"), edge("B", "A"))})
    with pytest.raises(HorizonError, match="TOPOLOGY_REJECTED"):
        engine().propose(**data)


@pytest.mark.parametrize("payload", [
    {"budget": {"costUnits": 1000}}, {"completedKeys": ["A"]}, {"resourceId": "leased"},
    {"sourceExpansionRef": "old-htn"}, {"permissions": ["execute"]}, {"graphVersion": 2}])
def test_model_cannot_supply_authority_or_uncommitted_htn_input(payload):
    with pytest.raises(ValidationError):
        PlannerActionRequest(requestRef="attack", proposal={"kind": "horizon",
            "inputFingerprint": "a"*64, "selectedKeys": ["A"], **payload})


def gateway(store, monkeypatch, **kw):
    monkeypatch.setenv("AGENTOS_PLANNER_ADAPTIVE_HORIZON", "1")
    catalog = build_default_capability_catalog()
    return PlannerActionGateway(workflow_store=store, capability_catalog=catalog,
        horizon_selector=AdaptiveHorizonSelector(catalog, monotonic_clock=kw.get("monotonic_clock", __import__('time').monotonic)), **kw)


def read(ref="read", target="candidate_horizon"):
    return dict(requestRef=ref, query=dict(target=target))


def choose(p, ref="select", keys=None):
    return dict(requestRef=ref, proposal=dict(kind="horizon", inputFingerprint=p.frontier.input_fingerprint,
        selectedKeys=list(p.candidate_keys if keys is None else keys)))


def test_gateway_queries_registration_concurrency_and_restart_are_read_only(ready_boundary, monkeypatch):
    _, store, _, run_id, _ = ready_boundary
    before = store.get_run(run_id).model_dump()
    def databases():
        snapshots = {}
        for path in store.db_path.parent.glob("*.sqlite3"):
            with sqlite3.connect(path) as connection:
                snapshots[path.name] = tuple(connection.iterdump())
        return snapshots
    persisted_before = databases()
    gw = gateway(store, monkeypatch)
    session = gw.open_session(run_id)
    f = gw.submit(session.session_id, read("frontier", "planning_frontier"))
    p = gw.submit(session.session_id, read()).horizon
    assert f.frontier.input_fingerprint == p.frontier.input_fingerprint and p.candidate_keys == ("step:A",)
    request = choose(p)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: gw.submit(session.session_id, request), range(4)))
    assert all(isinstance(r, PlannerProposalReceipt) for r in results)
    assert sum(r.replayed for r in results) == 3 and len(session.registered_proposals) == 1
    assert session.registered_proposals[0].horizon.candidate_keys == p.candidate_keys
    assert session.registered_proposals[0].horizon.selection_basis == "bounded_model_subset"
    assert session.registered_proposals[0].horizon.frontier == p.frontier
    assert store.get_run(run_id).model_dump() == before
    assert databases() == persisted_before  # includes audit, receipts, values, outbox and all Run records
    restored = gateway(store, monkeypatch)
    assert restored.submit(session.session_id, request).code == "UNKNOWN_SESSION"
    assert restored.submit(restored.open_session(run_id).session_id, read()).horizon == p


@pytest.mark.parametrize("mutation,code", [
    ("flag", "HORIZON_DISABLED"), ("budget", "HORIZON_POLICY_CHANGED"),
    ("catalog", "HORIZON_POLICY_CHANGED"), ("grant", "UNAUTHORIZED_TARGET"),
    ("plan_version", "PLAN_VERSION_MISMATCH"), ("plan_content", "STALE_OBSERVATION"),
    ("observation", "STALE_OBSERVATION"), ("status", "STALE_OBSERVATION"),
    ("step_output", "STALE_OBSERVATION"), ("scope", "STALE_OBSERVATION"),
    ("revoke", "SESSION_REVOKED"), ("terminal", "BINDING_MISMATCH")])
def test_cached_horizon_never_survives_world_or_authorization_change(runtime_boundary, monkeypatch, mutation, code):
    _, store, _, run_id, _ = runtime_boundary
    gw = gateway(store, monkeypatch)
    session = gw.open_session(run_id)
    request = read()
    assert isinstance(gw.submit(session.session_id, request), PlannerReadResult)
    if mutation == "flag":
        monkeypatch.setenv("AGENTOS_PLANNER_ADAPTIVE_HORIZON", "0")
    elif mutation == "budget":
        gw.horizon_selector.budget = HorizonBudget(costUnits=1)
    elif mutation == "catalog":
        gw.capability_catalog.resolve("task_understanding").risk_level_hint = "high"
    elif mutation == "grant":
        session.allowed_reads -= {"candidate_horizon"}
    elif mutation == "revoke":
        gw.revoke_session(session.session_id, "withdrawn")
    else:
        run = store.get_run(run_id)
        if mutation == "plan_version":
            run.execution_state["taskPlan"]["planVersion"] = 2
        elif mutation == "plan_content":
            run.execution_state["taskPlan"]["nodes"][0]["objective"] = "new"
        elif mutation == "observation":
            run.execution_state["planningLoop"]["current"]["observation"]["wakeReason"] = "restart"
        elif mutation == "status":
            run.steps[0].status = StepStatus.RUNNING
        elif mutation == "step_output":
            run.steps[0].output["externalEffect"] = "changed"
        elif mutation == "scope":
            run.runtime_revision += 1
        else:
            run.status = WorkflowStatus.CANCELLED
        store.save_run(run)
    assert gw.submit(session.session_id, request).code == code


@pytest.mark.parametrize("change,code", [("flag", "HORIZON_DISABLED"), ("grant", "UNAUTHORIZED_TARGET"),
    ("world", "STALE_OBSERVATION"), ("policy", "HORIZON_POLICY_CHANGED"), ("deadline", "TOOL_TIMEOUT"),
    ("ttl", "BUDGET_EXHAUSTED")])
def test_late_results_are_not_journaled_or_registered(runtime_boundary, monkeypatch, change, code):
    _, store, _, run_id, _ = runtime_boundary
    clock = [0.0]
    gw = gateway(store, monkeypatch, monotonic_clock=lambda: clock[0],
        per_action_timeout_seconds=20 if change == "ttl" else 5)
    session = gw.open_session(run_id, ttl_seconds=10)
    p = gw.submit(session.session_id, read()).horizon
    original = gw.horizon_selector.propose
    def late(**kw):
        result = original(**kw)
        if change == "flag":
            monkeypatch.setenv("AGENTOS_PLANNER_ADAPTIVE_HORIZON", "0")
        elif change == "grant":
            session.allowed_reads -= {"candidate_horizon"}
        elif change == "world":
            run = store.get_run(run_id)
            run.steps[0].status = StepStatus.RUNNING
            store.save_run(run)
        elif change == "policy":
            gw.horizon_selector.budget = HorizonBudget(costUnits=1)
        else:
            clock[0] = 6 if change == "deadline" else 11
        return result
    monkeypatch.setattr(gw.horizon_selector, "propose", late)
    request = choose(p)
    assert gw.submit(session.session_id, request).code == code
    assert "select" not in session.journal and not session.registered_proposals


def test_proposal_and_revision_are_mutually_exclusive(runtime_boundary, monkeypatch):
    _, store, _, run_id, _ = runtime_boundary
    gw = gateway(store, monkeypatch)
    session = gw.open_session(run_id)
    patch = dict(missionId=session.mission_id, basePlanVersion=1, planVersion=2)
    revision = dict(requestRef="rev", proposal=dict(kind="plan_revision", patch=patch))
    assert isinstance(gw.submit(session.session_id, revision), PlannerProposalReceipt)
    assert gw.submit(session.session_id, read()).code == "PROPOSAL_ONLY"
    other = gw.open_session(run_id)
    assert isinstance(gw.submit(other.session_id, read()), PlannerReadResult)
    assert gw.submit(other.session_id, revision).code == "PROPOSAL_ONLY"


def test_mixed_htn_session_catalog_fence_and_no_expansion_adoption(runtime_boundary, monkeypatch):
    from components.planner.htn import HTNMethodCatalog
    _, store, _, run_id, _ = runtime_boundary
    gw = gateway_at(store)
    monkeypatch.setenv("AGENTOS_PLANNER_ADAPTIVE_HORIZON", "1")
    gw.horizon_selector = AdaptiveHorizonSelector(gw.capability_catalog)
    session = gw.open_session(run_id)
    assert isinstance(gw.submit(session.session_id, query_request()), PlannerReadResult)
    assert isinstance(gw.submit(session.session_id, method_request("method", gw.htn_selector.catalog.revision)), PlannerProposalReceipt)
    p = gw.submit(session.session_id, read()).horizon
    assert not p.candidate_keys  # no ready resources, and HTN atoms never substituted
    assert {t.key for t in p.frontier.tasks} == {"step:A"}
    gw.htn_selector.catalog = HTNMethodCatalog([m.model_copy(update={"version": 2}) for m in gw.htn_selector.catalog.methods()])
    assert gw.submit(session.session_id, read()).code == "HTN_CATALOG_CHANGED"


@pytest.mark.parametrize("action", ["continue", "recover", "complete", "revise"])
def test_react_horizon_round_cannot_commit_or_execute(runtime_boundary, monkeypatch, action):
    _, store, _, run_id, _ = runtime_boundary
    gw = gateway(store, monkeypatch)
    run = store.get_run(run_id)
    o = RuntimePlanningState.model_validate(run.execution_state["planningLoop"]).current.observation
    plan = TaskPlan.model_validate(run.execution_state["taskPlan"])
    def finish(payload):
        d = dict(observationId=payload["observationId"], action=action, reason="attempt execution")
        if action == "revise":
            d["taskPlanPatch"] = dict(missionId=run.mission_id, basePlanVersion=1, planVersion=2)
        return dict(turnKind="decide", finalDecision=d)
    llm = ReActFakeLLM([lambda p: dict(turnKind="use_tool", actionRequest=read()), finish])
    result = BoundedReActPlanningLoop(llm=llm, gateway=gw).decide(observation=o, task_plan=plan)
    assert result.action == "wait" and "Horizon selection is proposal-only" in result.reason
    assert store.get_run(run_id).model_dump() == run.model_dump()


def test_real_runtime_feedback_wait_and_restart_without_proposal(ready_boundary, monkeypatch, tmp_path):
    runtime, store, _, run_id, _ = ready_boundary
    monkeypatch.setenv("AGENTOS_PLANNER_REACT_LOOP", "1")
    monkeypatch.setenv("AGENTOS_PLANNER_ADAPTIVE_HORIZON", "1")
    monkeypatch.setenv("AGENTOS_PLANNER_HTN", "0")
    before = store.get_run(run_id)
    def select_feedback(payload):
        p = payload["toolFeedback"][-1]["horizon"]
        assert p["candidateKeys"] == ["step:A"] and p["reservationStatus"] == "not_reserved"
        return dict(turnKind="use_tool", actionRequest=dict(requestRef="select", proposal=dict(
            kind="horizon", inputFingerprint=p["frontier"]["inputFingerprint"], selectedKeys=p["candidateKeys"])))
    def finish(payload):
        assert payload["toolFeedback"][-1]["outcome"] == "registered"
        return dict(turnKind="decide", finalDecision=dict(observationId=payload["observationId"], action="wait", reason="review Horizon"))
    llm = ReActFakeLLM([lambda p: dict(turnKind="use_tool", actionRequest=read()), select_feedback, finish])
    restored, restored_store, agent = runtime_at(tmp_path)
    restored.workflow_registry.register(runtime.workflow_registry.get("htn"))
    ready_resource(restored, before)
    restored.set_intent_llm(llm)
    after = asyncio.run(restored.execute_prepared_run(run_id))
    assert after.status == WorkflowStatus.WAITING_REVIEW and not agent.calls
    assert after.execution_state["planningLoop"]["current"]["decision"]["reason"] == "review Horizon"
    assert len(llm.prompts) == 3
    for key in ("taskPlan", "taskBindings", "missionIntentBasis"):
        assert before.execution_state.get(key) == after.execution_state.get(key)
    assert before.execution_state.get("completedStepIds", []) == after.execution_state["completedStepIds"]
    assert after.acg_blueprint == before.acg_blueprint
    restarted, _, restarted_agent = runtime_at(tmp_path)
    restarted.workflow_registry.register(runtime.workflow_registry.get("htn"))
    assert asyncio.run(restarted.execute_prepared_run(run_id)).status == WorkflowStatus.WAITING_REVIEW
    assert not restarted_agent.calls  # persisted wait does not require an in-memory proposal


@pytest.mark.parametrize("react,htn,horizon", [(0,0,0),(0,1,1),(1,0,0),(1,1,0),(1,0,1),(1,1,1)])
def test_feature_flag_assembly_is_independent(runtime_boundary, monkeypatch, react, htn, horizon):
    runtime, store, _, run_id, _ = runtime_boundary
    runtime.set_intent_llm(ReActFakeLLM([]))
    monkeypatch.setenv("AGENTOS_PLANNER_REACT_LOOP", str(react))
    monkeypatch.setenv("AGENTOS_PLANNER_HTN", str(htn))
    monkeypatch.setenv("AGENTOS_PLANNER_ADAPTIVE_HORIZON", str(horizon))
    e = runtime._planning_engine_for_run(store.get_run(run_id))
    if not react:
        assert e.react_loop is None
        return
    gw = e.react_loop.gateway
    session = gw.open_session(run_id)
    assert (gw.htn_selector is not None) == bool(htn)
    assert (gw.horizon_selector is not None) == bool(horizon)
    assert ("candidate_horizon" in session.allowed_reads) == bool(horizon)
    assert ("method_catalog" in session.allowed_reads) == bool(htn)


def test_run_review_barrier_overrides_pending_and_ready(context):
    data = inputs(context)
    s = engine()
    p = s.propose(**data, run_status="waiting_review")
    assert not p.candidate_keys and all(t.classification == "review_wait" for t in p.frontier.tasks)
    assert p.frontier.input_fingerprint != s.propose(**data).frontier.input_fingerprint


def test_review_after_restart_loses_proposal_and_executes_only_original_plan(ready_boundary, monkeypatch, tmp_path):
    import json
    from contracts.workflow import ReviewDecision
    runtime, store, agent, run_id, _ = ready_boundary
    monkeypatch.setenv("AGENTOS_PLANNER_REACT_LOOP", "1")
    monkeypatch.setenv("AGENTOS_PLANNER_ADAPTIVE_HORIZON", "1")
    before = store.get_run(run_id)
    def choose_feedback(p):
        h = p["toolFeedback"][-1]["horizon"]
        return dict(turnKind="use_tool", actionRequest=dict(requestRef="selection", proposal=dict(
            kind="horizon", inputFingerprint=h["frontier"]["inputFingerprint"], selectedKeys=h["candidateKeys"])))
    runtime.set_intent_llm(ReActFakeLLM([lambda p: dict(turnKind="use_tool", actionRequest=read()),
        choose_feedback, lambda p: dict(turnKind="decide", finalDecision=dict(
            observationId=p["observationId"], action="wait", reason="review Horizon"))]))
    paused = asyncio.run(runtime.execute_prepared_run(run_id))
    assert paused.status == WorkflowStatus.WAITING_REVIEW and not agent.calls
    restarted, reopened, resumed_agent = runtime_at(tmp_path)
    restarted.workflow_registry.register(runtime.workflow_registry.get("htn"))
    class ResumeModel:
        calls = 0
        def generate_json(self, prompt, schema, **kwargs):
            self.calls += 1
            p = json.loads(prompt)
            assert p["toolFeedback"] == []
            return dict(turnKind="decide", finalDecision=dict(observationId=p["observationId"],
                action="continue" if p["observation"]["remainingStepIds"] else "complete", reason="original plan"))
    model = ResumeModel()
    restarted.set_intent_llm(model)
    assert not restarted._planning_engine_for_run(reopened.get_run(run_id)).react_loop.gateway._sessions
    gw = restarted._planning_engine_for_run(reopened.get_run(run_id)).react_loop.gateway
    session = gw.open_session(run_id)
    blocked = gw.submit(session.session_id, read()).horizon
    assert not blocked.candidate_keys and blocked.frontier.run_status == "waiting_review"
    result = asyncio.run(restarted.apply_review(ReviewDecision(runId=run_id,
        stepId=paused.current_step_id, decision="approved", operationId="horizon-review-after-loss")))
    assert result.status == WorkflowStatus.COMPLETED and result.run_id == run_id
    assert result.acg_blueprint == before.acg_blueprint
    assert result.execution_state["taskPlan"] == before.execution_state["taskPlan"]
    assert resumed_agent.calls == ["A"] and model.calls == 2


def test_changed_request_ref_and_revoked_selection_grant(ready_boundary, monkeypatch):
    _, store, _, run_id, _ = ready_boundary
    gw = gateway(store, monkeypatch)
    session = gw.open_session(run_id)
    p = gw.submit(session.session_id, read()).horizon
    assert isinstance(gw.submit(session.session_id, choose(p)), PlannerProposalReceipt)
    assert gw.submit(session.session_id, choose(p, keys=())).code == "DUPLICATE_ACTION"
    session.allowed_reads -= {"candidate_horizon"}
    assert gw.submit(session.session_id, choose(p)).code == "UNAUTHORIZED_TARGET"
    assert gw.verify_binding(session).code == "UNAUTHORIZED_TARGET"


def test_verification_time_is_included_in_full_tool_deadline(ready_boundary, monkeypatch):
    _, store, _, run_id, _ = ready_boundary
    clock = [0.0]
    gw = gateway(store, monkeypatch, monotonic_clock=lambda: clock[0])
    session = gw.open_session(run_id)
    original = gw.horizon_selector.propose
    def slow_provider(**kw):
        p = original(**kw)
        clock[0] += 3
        return p
    monkeypatch.setattr(gw.horizon_selector, "propose", slow_provider)
    verify = gw._check_binding
    def slow_revalidation(*args):
        result = verify(*args)
        if clock[0] >= 3:
            clock[0] += 3
        return result
    monkeypatch.setattr(gw, "_check_binding", slow_revalidation)
    assert gw.submit(session.session_id, read()).code == "TOOL_TIMEOUT"
    assert not session.journal


def test_frozen_basis_is_used_after_current_mission_revision(ready_boundary, monkeypatch):
    from contracts.mission_semantic import MissionSemanticRequest
    runtime, store, _, run_id, _ = ready_boundary
    gw = gateway(store, monkeypatch)
    session = gw.open_session(run_id)
    p = gw.submit(session.session_id, read()).horizon
    run = store.get_run(run_id)
    runtime.mission_semantic_service.commit(runtime.semantic_principal_provider(),
        MissionSemanticRequest(missionId=run.mission_id, operationId="later", expectedMissionRevision=1,
            objective="different current objective", constraints=[], sourceRefs=["input:later"]))
    assert gw.submit(session.session_id, read()).horizon == p
    assert p.frontier.basis_fingerprint == run_intent_basis(run).fingerprint


@pytest.mark.parametrize("mutation", ["boundary", "completed", "budget", "ready", "partition"])
def test_horizon_contract_rejects_unproved_boundary_and_execution_claims(context, mutation):
    from contracts.horizon import HorizonProposal
    data = inputs(context, relations=(edge("A", "B"),))
    p = engine(budget=HorizonBudget(costUnits=1)).propose(**data)
    raw = p.model_dump(by_alias=True, mode="json")
    if mutation == "boundary":
        raw["crossWindowDependencies"] = []
    elif mutation == "completed":
        raw["crossWindowDependencies"][0]["prerequisiteCompleted"] = True
    elif mutation == "budget":
        raw["usedCostUnits"] = 0
    elif mutation == "ready":
        raw["readyKeys"] = []
    else:
        raw["deferred"] = []
    with pytest.raises(ValidationError):
        HorizonProposal.model_validate(raw)


def test_absent_step_and_missing_remaining_membership_do_not_fabricate_pending_work(context):
    data = inputs(context)
    o = data["observation"]
    data["observation"] = o.model_copy(update={"steps": (o.steps[0],), "remaining_step_ids": ()})
    p = engine().propose(**data)
    assert not p.candidate_keys and all(t.classification == "unknown" for t in p.frontier.tasks)


def test_compiler_inferred_dependencies_are_preserved(context):
    data = inputs(context, keys=("A", "B"))
    p = data["plan"]
    nodes = (p.nodes[0], p.nodes[1].model_copy(update={"capability_requirements": ("verification",)}))
    data["plan"] = p.model_copy(update={"nodes": nodes})
    result = engine().propose(**data)
    assert ("A", "B") in {(r.source_key, r.target_key) for r in result.frontier.dependencies}
    assert result.ready_keys == ("A",)


def test_completed_review_uses_trusted_observer_review_resolution(context):
    data = inputs(context, keys=("A", "B"), relations=(edge("A", "B"),), statuses={"A": "completed"})
    o = data["observation"]
    data["observation"] = o.model_copy(update={"steps": (
        o.steps[0].model_copy(update={"audit_outcome": "review"}), o.steps[1]),
        "completion_blockers": ("review_unresolved:A",)})
    assert not engine().propose(**data).candidate_keys
    data["observation"] = data["observation"].model_copy(update={"completion_blockers": ()})
    p = engine().propose(**data)
    assert p.candidate_keys == ("B",) and p.cross_window_dependencies[0].prerequisite_completed
    assert "A" not in p.candidate_keys
