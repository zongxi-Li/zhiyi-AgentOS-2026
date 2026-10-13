"""Independent adversarial acceptance for S01-04."""
import pytest

from contracts.horizon import HorizonBudget
from contracts.planning import TaskPlan
from test_htn import context
from test_horizon import inputs, engine, edge, ready_boundary, runtime_boundary, gateway, read
from contracts.planner_actions import PlannerActionRejection, PlannerProposalReceipt
from test_horizon import choose


def test_verification_without_pass_report_does_not_satisfy_dependency(context):
    data = inputs(context, keys=("A", "V", "C"), relations=(edge("A", "V"), edge("V", "C")),
        statuses={"A": "completed", "V": "completed"})
    p = data["plan"]
    data["plan"] = p.model_copy(update={"nodes": tuple(n.model_copy(update={
        "capability_requirements": ("verification",)}) if n.key in {"V", "C"} else n for n in p.nodes)})
    result = engine().propose(**data)
    assert "C" not in result.candidate_keys
    assert next(t for t in result.frontier.tasks if t.key == "V").classification == "unknown"


def test_implicit_compilation_is_stable_under_task_permutation(context):
    data = inputs(context, keys=("A", "B", "V1", "V2"), statuses={"A": "completed", "B": "running"})
    p = data["plan"]
    nodes = tuple(n.model_copy(update={"capability_requirements": ("verification",)})
        if n.key.startswith("V") else n for n in p.nodes)
    data["plan"] = p.model_copy(update={"nodes": nodes})
    s = engine(budget=HorizonBudget(costUnits=2))
    original = s.propose(**data)
    reordered = s.propose(**{**data, "plan": data["plan"].model_copy(update={"nodes": tuple(reversed(nodes))})})
    assert original.frontier.dependencies == reordered.frontier.dependencies
    assert original.candidate_keys == reordered.candidate_keys


def test_new_session_rejects_observation_bound_to_wrong_semantic_task(ready_boundary, monkeypatch):
    _, store, _, run_id, _ = ready_boundary
    run = store.get_run(run_id)
    raw = run.execution_state["planningLoop"]["current"]["observation"]
    raw["steps"][0]["taskKey"] = "wrong-key"
    from contracts.runtime_planning import RuntimePlanningObservation
    run.execution_state["planningLoop"]["current"]["observationId"] = RuntimePlanningObservation.model_validate(raw).fingerprint()
    store.save_run(run)
    gw = gateway(store, monkeypatch)
    session = gw.open_session(run_id)
    result = gw.submit(session.session_id, read())
    assert getattr(result, "code", None) == "STALE_OBSERVATION"
    assert not session.journal


def test_completed_without_output_reference_is_unknown(context):
    data = inputs(context, keys=("A", "B"), relations=(edge("A", "B"),), statuses={"A": "completed"})
    o = data["observation"]
    data["observation"] = o.model_copy(update={"steps": (
        o.steps[0].model_copy(update={"output_ref": None}), o.steps[1])})
    assert not engine().propose(**data).candidate_keys


def test_runtime_control_condition_is_not_lost_by_task_plan_projection(ready_boundary, monkeypatch):
    from support.acg.schema import ACGBlueprint, StepNode, ControlNode, ControlType, ConditionSpec, ConditionOperator, ACGEdge, EdgeType
    from support.acg.planning import ACGResourcePlan, AgentBindingSpec
    from contracts.planning import PlannedTask, TaskImplementationBinding
    from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition, WorkflowStatus
    from contracts.runtime_planning import RuntimePlanningState, RuntimePlanningRound
    from contracts.mission_semantic import MissionSemanticRequest
    from components.executor import ACGExecutionState
    runtime, store, _, _, _ = ready_boundary
    runtime.workflow_registry.register(WorkflowDefinition(workflowId="horizon-route", name="route",
        domain="general", runtimeEngine="acg", steps=[WorkflowStepDefinition(stepId="stub", name="stub", agentName="runner")]))
    mission = runtime.create_mission("route", workflow_id="horizon-route")
    blueprint = ACGBlueprint(graphId="horizon-route", missionId=mission.mission_id, nodes=[
        StepNode(nodeId=k, capability="task_understanding") for k in ("source", "yes", "no")],
        resourcePlan=ACGResourcePlan(bindings=tuple(AgentBindingSpec(stepId=k, plannedAgentId="runner")
            for k in ("source", "yes", "no"))), edges=[
            ACGEdge(sourceId="source", targetId="if", edgeType=EdgeType.DEPENDENCY),
            ACGEdge(edgeId="yes-edge", sourceId="if", targetId="yes", edgeType=EdgeType.DEPENDENCY),
            ACGEdge(edgeId="no-edge", sourceId="if", targetId="no", edgeType=EdgeType.DEPENDENCY)])
    blueprint.nodes.append(ControlNode(nodeId="if", controlType=ControlType.IF,
        conditionSpec=ConditionSpec(sourceNodeId="source", jsonPointer="/approved", operator=ConditionOperator.BOOLEAN,
            cases={"true": "yes-edge", "false": "no-edge"}), branchEdgeIds=["yes-edge", "no-edge"]))
    plan = TaskPlan(missionId=mission.mission_id, nodes=tuple(PlannedTask(key="step:"+k, title=k, objective=k,
        capabilityRequirements=("task_understanding",)) for k in ("source", "yes", "no")),
        relations=(edge("step:source", "step:yes"), edge("step:source", "step:no")))
    mission.input.update(acgBlueprint=blueprint.model_dump(mode="json", by_alias=True),
        taskPlan=plan.model_dump(mode="json", by_alias=True), taskBindings=[TaskImplementationBinding(
            planNodeKey="step:"+k, acgNodeId=k).model_dump(mode="json", by_alias=True) for k in ("source", "yes", "no")])
    store.save_mission(mission)
    # Exercise the existing explicit legacy package path with a frozen legacy
    # basis; formal semantic creation correctly forbids arbitrary injected ACGs.
    runtime.allow_legacy_mission_intent = True
    _, run = runtime.prepare_run(mission.mission_id)
    run.status = WorkflowStatus.RUNNING
    state = ACGExecutionState(runId=run.run_id, graphId=run.acg_blueprint["graphId"], graphVersion=run.acg_blueprint["version"])
    observation = runtime.runtime_planning_coordinator.observe(run, state, "resume")
    run.execution_state["planningLoop"] = RuntimePlanningState(current=RuntimePlanningRound(
        observationId=observation.fingerprint(), observation=observation)).model_dump(mode="json", by_alias=True)
    store.save_run(run)
    assert not TaskPlan.model_validate(run.execution_state["taskPlan"]).control_policies
    gw = gateway(store, monkeypatch)
    result = gw.submit(gw.open_session(run.run_id).session_id, read())
    assert not result.horizon.candidate_keys
    assert all(t.classification == "control_wait" for t in result.horizon.frontier.tasks)


def test_shared_predecessor_multilevel_closure_and_skip(context):
    data = inputs(context, keys=("P", "A", "B", "C", "D"), relations=(
        edge("P", "A"), edge("P", "B"), edge("A", "C"), edge("B", "C"), edge("C", "D")))
    s = engine()
    full = s.propose(**data)
    assert set(full.candidate_keys) == {"P", "A", "B", "C", "D"} and full.ready_keys == ("P",)
    for subset in (("A", "B", "C"), ("P", "A", "C"), ("P", "A", "B", "D")):
        with pytest.raises(ValueError, match="DEPENDENCY_GAP"):
            s.propose(**data, selected_keys=subset)
    o = data["observation"]
    data["observation"] = o.model_copy(update={"steps": tuple(
        step.model_copy(update={"status": "skipped_by_condition"}) if step.task_key == "P" else step
        for step in o.steps)})
    assert not s.propose(**data).candidate_keys


@pytest.mark.parametrize("limit,expected", [(1, ("A",)), (2, ("A", "B")), (3, ("A", "B", "C"))])
def test_exact_budget_ties_and_unaffordable_tasks(context, limit, expected):
    data = inputs(context, keys=("C", "B", "A", "Z"), costs={"Z": 100})
    result = engine(budget=HorizonBudget(costUnits=limit)).propose(**data)
    assert result.candidate_keys == expected and result.used_cost_units == limit
    assert any(d.key == "Z" and d.reason == "budget" for d in result.deferred)


def test_compiler_once_and_nonpreemptible_overrun_is_discarded(context, monkeypatch):
    import components.planner.horizon as module
    clock, calls = [0.0], []
    s = engine(monotonic_clock=lambda: clock[0])
    original = module.validate_task_plan_for_execution
    def slow_compile(**kw):
        calls.append(kw)
        result = original(**kw)
        clock[0] = 6
        return result
    monkeypatch.setattr(module, "validate_task_plan_for_execution", slow_compile)
    with pytest.raises(ValueError, match="DEADLINE"):
        s.propose(**inputs(context), deadline=5)
    assert len(calls) == 1
    too_large = inputs(context, keys=tuple(f"key:{i}" for i in range(257)))
    clock[0] = 0
    with pytest.raises(ValueError, match="INPUT_BUDGET"):
        s.propose(**too_large, deadline=5)
    assert len(calls) == 1  # admission fails before the compiler


def test_cancel_during_compute_leaves_no_success_registration(ready_boundary, monkeypatch):
    from contracts.workflow import WorkflowStatus
    _, store, _, run_id, _ = ready_boundary
    gw = gateway(store, monkeypatch)
    session = gw.open_session(run_id)
    p = gw.submit(session.session_id, read()).horizon
    original = gw.horizon_selector.propose
    def cancel(**kw):
        result = original(**kw)
        run = store.get_run(run_id)
        run.status = WorkflowStatus.CANCELLED
        store.save_run(run)
        return result
    monkeypatch.setattr(gw.horizon_selector, "propose", cancel)
    outcome = gw.submit(session.session_id, choose(p))
    assert isinstance(outcome, PlannerActionRejection) and outcome.code == "BINDING_MISMATCH"
    assert "select" not in session.journal and not session.registered_proposals


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "run", "malformed_binding"])
def test_reopened_session_rejects_incomplete_or_wrong_run_observation(ready_boundary, monkeypatch, mutation):
    from contracts.runtime_planning import RuntimePlanningObservation
    _, store, _, run_id, _ = ready_boundary
    run = store.get_run(run_id)
    raw = run.execution_state["planningLoop"]["current"]["observation"]
    if mutation == "missing":
        raw["steps"] = []
    elif mutation == "duplicate":
        raw["steps"].append(dict(raw["steps"][0]))
    elif mutation == "run":
        raw["runId"] = "another-run"
    else:
        run.execution_state["taskBindings"] = [None]
    run.execution_state["planningLoop"]["current"]["observationId"] = RuntimePlanningObservation.model_validate(raw).fingerprint()
    store.save_run(run)
    gw = gateway(store, monkeypatch)
    session = gw.open_session(run_id)
    outcome = gw.submit(session.session_id, read())
    assert isinstance(outcome, PlannerActionRejection) and outcome.code == "STALE_OBSERVATION"
    assert not session.journal and not session.registered_proposals


def test_contract_legal_but_unsupported_risk_is_explicitly_rejected(context):
    from components.planner.horizon import HorizonError
    data = inputs(context, keys=("A",))
    p = data["plan"]
    node = p.nodes[0].model_copy(update={"metadata": {"risk": {"level": "high"}}})
    data["plan"] = TaskPlan(missionId=p.mission_id, nodes=(node,))
    with pytest.raises(HorizonError, match="UNKNOWN_RISK"):
        engine().propose(**data)


def test_runtime_review_requirement_is_preserved_without_catalog_review_flag(ready_boundary, monkeypatch):
    _, store, _, run_id, _ = ready_boundary
    run = store.get_run(run_id)
    run.steps[0].requires_review = True
    store.save_run(run)
    gw = gateway(store, monkeypatch)
    assert not gw.capability_catalog.resolve("task_understanding").requires_review
    result = gw.submit(gw.open_session(run_id).session_id, read())
    assert result.horizon.frontier.tasks[0].requires_review


def test_runtime_review_keys_stop_future_work_and_cannot_be_model_supplied(context):
    from contracts.planner_actions import PlannerActionRequest
    data = inputs(context, keys=("A", "B"), relations=(edge("A", "B"),))
    result = engine().propose(**data, review_keys=("A",))
    assert result.candidate_keys == ("A",) and result.deferred[0].reason == "review_boundary"
    with pytest.raises(ValueError):
        PlannerActionRequest(requestRef="attack", proposal=dict(kind="horizon",
            inputFingerprint=result.frontier.input_fingerprint, selectedKeys=["A"], reviewKeys=[]))


def test_runtime_cancellation_signal_before_terminal_save_blocks_publication(ready_boundary, monkeypatch):
    from test_react_loop import ReActFakeLLM
    runtime, store, _, run_id, _ = ready_boundary
    monkeypatch.setenv("AGENTOS_PLANNER_REACT_LOOP", "1")
    monkeypatch.setenv("AGENTOS_PLANNER_ADAPTIVE_HORIZON", "1")
    runtime.set_intent_llm(ReActFakeLLM([]))
    gw = runtime._planning_engine_for_run(store.get_run(run_id)).react_loop.gateway
    session = gw.open_session(run_id)
    p = gw.submit(session.session_id, read()).horizon
    original = gw.horizon_selector.propose
    def signal(**kw):
        result = original(**kw)
        runtime._signal_run_cancellation(run_id)
        return result
    monkeypatch.setattr(gw.horizon_selector, "propose", signal)
    outcome = gw.submit(session.session_id, choose(p))
    assert isinstance(outcome, PlannerActionRejection) and outcome.code == "BINDING_MISMATCH"
    assert not session.registered_proposals and "select" not in session.journal


def test_cancellation_during_final_policy_read_is_rechecked(ready_boundary, monkeypatch):
    from test_react_loop import ReActFakeLLM
    runtime, store, _, run_id, _ = ready_boundary
    monkeypatch.setenv("AGENTOS_PLANNER_REACT_LOOP", "1")
    monkeypatch.setenv("AGENTOS_PLANNER_ADAPTIVE_HORIZON", "1")
    runtime.set_intent_llm(ReActFakeLLM([]))
    gw = runtime._planning_engine_for_run(store.get_run(run_id)).react_loop.gateway
    session = gw.open_session(run_id)
    p = gw.submit(session.session_id, read()).horizon
    phase, calls = [False], [0]
    propose = gw.horizon_selector.propose
    def produced(**kw):
        result = propose(**kw)
        phase[0] = True
        return result
    available = gw.capability_catalog.available
    def final_policy_read():
        if phase[0]:
            calls[0] += 1
            if calls[0] == 2:
                runtime._signal_run_cancellation(run_id)
        return available()
    monkeypatch.setattr(gw.horizon_selector, "propose", produced)
    monkeypatch.setattr(gw.capability_catalog, "available", final_policy_read)
    result = gw.submit(session.session_id, choose(p))
    assert isinstance(result, PlannerActionRejection) and result.code == "BINDING_MISMATCH"
    assert not session.registered_proposals and "select" not in session.journal
