"""Independent S01-03 adversarial acceptance cases; no production stores."""
from concurrent.futures import ThreadPoolExecutor
import asyncio
import json
from threading import Barrier
from time import monotonic

import pytest

from components.planner.htn import HTNBudget, HTNError, HTNMethodCatalog
from contracts.planner_actions import PlannerProposalReceipt
from contracts.planning import PlannedTask, TaskPlan
from contracts.workflow import ReviewDecision, StepStatus, WorkflowStatus
from test_htn import (context, runtime_boundary, selector, expansion, method, slot,
                      edge, gateway_at, method_request, query_request)
from test_react_loop import ReActFakeLLM, runtime_at


@pytest.mark.parametrize("mutation,expected", [
    ("flag", "HTN_DISABLED"), ("observation", "STALE_OBSERVATION"),
    ("steps", "STALE_OBSERVATION"), ("catalog", "HTN_CATALOG_CHANGED"),
    ("ttl", "BUDGET_EXHAUSTED"),
])
def test_no_registration_after_world_changes_during_expand(runtime_boundary, monkeypatch, mutation, expected):
    _, store, _, run_id, _ = runtime_boundary
    gw = gateway_at(store)
    now = [monotonic()]
    gw.monotonic = lambda: now[0]
    session = gw.open_session(run_id, ttl_seconds=1)
    original = gw.htn_selector.expand

    def delayed(**kwargs):
        result = original(**kwargs)
        if mutation == "flag":
            monkeypatch.setenv("AGENTOS_PLANNER_HTN", "0")
        elif mutation == "catalog":
            gw.htn_selector.catalog = HTNMethodCatalog(
                [m.model_copy(update={"version": 2}) for m in gw.htn_selector.catalog.methods()])
        elif mutation == "ttl":
            now[0] += 2  # Session has expired, but the 5-second action budget has not.
        else:
            run = store.get_run(run_id)
            if mutation == "observation":
                run.execution_state["planningLoop"]["current"]["observationId"] = "new-observation"
            else:
                run.steps[0].status = StepStatus.COMPLETED
            store.save_run(run)
        return result

    monkeypatch.setattr(gw.htn_selector, "expand", delayed)
    outcome = gw.submit(session.session_id, method_request("late", session.htn_catalog_revision))
    assert outcome.code == expected
    assert not session.registered_proposals and "late" not in session.journal


def test_parent_capability_requirement_cannot_be_erased(context):
    root = context["plan"].nodes[0].model_copy(update={"capability_requirements": ("risk_analysis",)})
    plan = TaskPlan(missionId=context["plan"].mission_id, nodes=(root,))
    with pytest.raises(HTNError, match="HTN_CAPABILITY_REQUIREMENT_LOST"):
        expansion(selector(), {**context, "plan": plan}, "analysis.standard")


def test_constraint_source_cannot_invent_evidence(context):
    forged = method(slots=(slot("understand", "task_understanding", constraints=[
        dict(constraintId="new", value="additional restriction", sourceRefs=["invented:source"])]),))
    with pytest.raises(HTNError, match="HTN_UNKNOWN_SOURCE"):
        expansion(selector((forged,)), context, "custom")


def test_large_cross_group_ordering_is_bounded(context):
    root = method("root", slots=(slot("left", abstract="left"), slot("right", abstract="right")),
                  ordering=(edge("left", "right"),))
    left = method("left", "left", slots=tuple(slot(f"l{i}", "task_understanding") for i in range(16)))
    right = method("right", "right", slots=tuple(slot(f"r{i}", "task_understanding") for i in range(16)))
    with pytest.raises(HTNError, match="HTN_BUDGET_EXHAUSTED"):
        expansion(selector((root, left, right)), context, "root")
    proposal = expansion(selector((root, left, right), budget=HTNBudget(max_relations=512)), context, "root")
    assert len(proposal.atomic_keys) == 32
    assert len([e for e in proposal.relations if e.relation_type.value == "depends_on"]) == 256


def test_semantically_redefined_slot_keeps_logical_key_but_not_revision(context):
    first = method(slots=(slot("understand", "task_understanding"), slot("assess", "analysis")),
                   ordering=(edge("understand", "assess"),))
    second = first.model_copy(update={"version": 2, "subtasks": (
        slot("understand", "task_understanding"), slot("assess", "risk_analysis"))})
    a, b = selector((first,)), selector((second,))
    old, new = expansion(a, context, "custom"), expansion(b, context, "custom")
    assert old.atomic_keys == new.atomic_keys  # key is not proof of unchanged content.
    assert old.nodes[-1].capability_requirements != new.nodes[-1].capability_requirements
    assert old.catalog_revision != new.catalog_revision and new.selections[0].method_version == 2
    with pytest.raises(HTNError, match="HTN_CATALOG_CHANGED"):
        b.expand(**context, method_id="custom", catalog_revision=a.catalog.revision)


def test_local_proof_does_not_prove_external_boundary_execution(context, monkeypatch):
    import components.planner.htn as htn
    root = context["plan"].nodes[0]
    external = PlannedTask(key="external", title="external", objective="existing work",
                           capabilityRequirements=("verification",))
    relation = edge(root.key, external.key)
    plan = TaskPlan(missionId=context["plan"].mission_id, nodes=(root, external), relations=(relation,))
    original = htn.validate_task_plan_for_execution
    seen = []
    def capture(**kwargs):
        seen.append(kwargs)
        return original(**kwargs)
    monkeypatch.setattr(htn, "validate_task_plan_for_execution", capture)
    proposal = expansion(selector(), {**context, "plan": plan})
    assert proposal.boundary_relations == (relation,)
    assert "external" not in {n.key for n in seen[0]["nodes"]}
    assert relation not in seen[0]["relations"] and relation not in proposal.relations


def test_concurrent_duplicate_expansion_has_one_registration(runtime_boundary):
    _, store, _, run_id, _ = runtime_boundary
    gw = gateway_at(store)
    session = gw.open_session(run_id)
    request = method_request("concurrent", session.htn_catalog_revision)
    barrier = Barrier(2)
    def submit():
        barrier.wait(timeout=5)
        return gw.submit(session.session_id, request)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit) for _ in range(2)]
        outcomes = [f.result(timeout=15) for f in futures]
    assert all(isinstance(o, PlannerProposalReceipt) for o in outcomes)
    assert sum(o.replayed for o in outcomes) == 1
    assert session.actions_used == 1 and len(session.registered_proposals) == 1
    assert outcomes[0].expansion == outcomes[1].expansion
    assert gw.revoke_session(session.session_id, "permission withdrawn")
    assert gw.submit(session.session_id, request).code == "SESSION_REVOKED"


def test_revoked_method_read_grant_cannot_use_cached_result(runtime_boundary):
    _, store, _, run_id, _ = runtime_boundary
    gw = gateway_at(store)
    session = gw.open_session(run_id)
    request = query_request()
    assert gw.submit(session.session_id, request).target == "method_catalog"
    session.allowed_reads = session.allowed_reads - {"method_catalog"}
    assert gw.submit(session.session_id, request).code == "UNAUTHORIZED_TARGET"


def test_htn_action_timeout_does_not_register_a_late_result(runtime_boundary, monkeypatch):
    _, store, _, run_id, _ = runtime_boundary
    gw = gateway_at(store)
    now = [monotonic()]
    gw.monotonic = lambda: now[0]
    session = gw.open_session(run_id)
    original = gw.htn_selector.expand
    def delayed(**kwargs):
        result = original(**kwargs)
        now[0] += 10
        return result
    monkeypatch.setattr(gw.htn_selector, "expand", delayed)
    assert gw.submit(session.session_id, method_request("late", session.htn_catalog_revision)).code == "TOOL_TIMEOUT"
    assert not session.registered_proposals


def test_result_revalidation_time_counts_toward_tool_deadline(runtime_boundary, monkeypatch):
    _, store, _, run_id, _ = runtime_boundary
    gw = gateway_at(store)
    now = [monotonic()]
    gw.monotonic = lambda: now[0]
    session = gw.open_session(run_id)
    expand = gw.htn_selector.expand
    load = store.get_run
    armed = [False]
    def arm(**kwargs):
        result = expand(**kwargs)
        armed[0] = True
        return result
    def slow_revalidation(key):
        result = load(key)
        if armed[0]:
            now[0] += 10
        return result
    monkeypatch.setattr(gw.htn_selector, "expand", arm)
    monkeypatch.setattr(store, "get_run", slow_revalidation)
    outcome = gw.submit(session.session_id, method_request("late-fence", session.htn_catalog_revision))
    assert outcome.code == "TOOL_TIMEOUT"
    assert not session.registered_proposals and "late-fence" not in session.journal


@pytest.mark.parametrize("field", ["taskPlan", "acgBlueprint", "taskBindings", "runtimeRevision"])
def test_same_version_context_mutation_cannot_replay_old_proposal(runtime_boundary, field):
    _, store, _, run_id, _ = runtime_boundary
    gw = gateway_at(store)
    session = gw.open_session(run_id)
    request = method_request("cached", session.htn_catalog_revision)
    assert isinstance(gw.submit(session.session_id, request), PlannerProposalReceipt)
    run = store.get_run(run_id)
    if field == "taskPlan":
        run.execution_state[field]["nodes"][0]["constraints"].append(dict(type="local", value="new restriction"))
    elif field == "acgBlueprint":
        run.acg_blueprint.setdefault("metadata", {})["auditMutation"] = "changed"
    elif field == "taskBindings":
        run.execution_state[field][0]["planNodeKey"] = "changed-key"
    else:
        run.runtime_revision += 1
    store.save_run(run)
    assert gw.submit(session.session_id, request).code == "STALE_OBSERVATION"


@pytest.mark.parametrize("react,htn", [(False, False), (False, True), (True, False)])
def test_disabled_flags_use_original_decision_chain(runtime_boundary, monkeypatch, react, htn):
    runtime, store, _, run_id, _ = runtime_boundary
    monkeypatch.setenv("AGENTOS_PLANNER_REACT_LOOP", "1" if react else "0")
    monkeypatch.setenv("AGENTOS_PLANNER_HTN", "1" if htn else "0")
    class Model:
        calls = 0
        def generate_json(self, prompt, schema, **kwargs):
            self.calls += 1
            payload = json.loads(prompt)
            assert "htnPolicy" not in payload
            result = dict(observationId=payload["observationId"], action="wait", reason="legacy wait")
            return dict(turnKind="decide", finalDecision=result) if react else result
    model = Model()
    runtime.set_intent_llm(model)
    result = asyncio.run(runtime.execute_prepared_run(run_id))
    assert result.status == WorkflowStatus.WAITING_REVIEW and model.calls == 1
    assert result.execution_state["planningLoop"]["current"]["decision"]["reason"] == "legacy wait"


def test_review_after_restart_does_not_need_or_apply_lost_proposal(runtime_boundary, monkeypatch, tmp_path):
    runtime, store, agent, run_id, _ = runtime_boundary
    monkeypatch.setenv("AGENTOS_PLANNER_REACT_LOOP", "1")
    before = store.get_run(run_id)
    def query(payload):
        return dict(turnKind="use_tool", actionRequest=query_request())
    def select(payload):
        revision = payload["toolFeedback"][-1]["methodCatalog"]["catalogRevision"]
        return dict(turnKind="use_tool", actionRequest=method_request("select", revision))
    def wait(payload):
        assert payload["toolFeedback"][-1]["expansion"]
        return dict(turnKind="decide", finalDecision=dict(observationId=payload["observationId"], action="wait", reason="review proposal"))
    runtime.set_intent_llm(ReActFakeLLM([query, select, wait]))
    paused = asyncio.run(runtime.execute_prepared_run(run_id))
    assert paused.status == WorkflowStatus.WAITING_REVIEW and agent.calls == []
    restarted, reopened, resumed_agent = runtime_at(tmp_path)
    restarted.workflow_registry.register(runtime.workflow_registry.get("htn"))
    class ResumeModel:
        calls = 0
        def generate_json(self, prompt, schema, **kwargs):
            self.calls += 1
            p = json.loads(prompt)
            assert p["toolFeedback"] == []
            return dict(turnKind="decide", finalDecision=dict(observationId=p["observationId"],
                action="continue" if p["observation"]["remainingStepIds"] else "complete", reason="original plan only"))
    model = ResumeModel()
    restarted.set_intent_llm(model)
    assert not restarted._planning_engine_for_run(reopened.get_run(run_id)).react_loop.gateway._sessions
    result = asyncio.run(restarted.apply_review(ReviewDecision(runId=run_id,
        stepId=paused.current_step_id, decision="approved", operationId="review-after-proposal-loss")))
    assert result.status == WorkflowStatus.COMPLETED
    assert result.run_id == run_id and result.acg_blueprint == before.acg_blueprint
    assert result.execution_state["taskPlan"] == before.execution_state["taskPlan"]
    assert resumed_agent.calls == ["A"] and model.calls == 2
