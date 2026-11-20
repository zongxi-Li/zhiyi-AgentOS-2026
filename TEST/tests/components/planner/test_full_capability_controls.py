from components.executor.compiler import ACGGraphCompiler
from components.planner.acg_lowerer import ACGLowerer
from components.planner.lowering_input import build_acg_lowering_input
from components.planner.cognitive_router import CapabilityBinding, CollaborationNetwork
from contracts.planning import PlannedTask, TaskPlan, TaskPlanRelation, VerificationLoopPolicy
from contracts.acg.schema import ControlNode, ControlType
from contracts.acg.semantic_profile import TaskSemanticProfile
from support.packs.native_capabilities import build_default_capability_catalog


def test_lowering_freezes_reasoning_tiers_and_compiles_acceptance_driven_verification_loop() -> None:
    from contracts.resource import ModelDemand
    from support.capabilities import CapabilityCatalog

    catalog = build_default_capability_catalog()
    demand = ModelDemand(requiredFeatures=["streaming"], minContextTokens=8192)
    catalog = CapabilityCatalog(descriptor.model_copy(update={"model_demand": demand})
        if descriptor.capability_id == "solution_design" else descriptor for descriptor in catalog.available())
    tasks = (
        PlannedTask(
            key="understand", title="Understand", objective="Resolve the mission contract",
            capabilityRequirements=("task_understanding",), acceptanceCriteria=("contract ready",),
        ),
        PlannedTask(
            key="refine", title="Refine", objective="Refine the complete solution",
            capabilityRequirements=("solution_design",), acceptanceCriteria=("solution ready",),
            logicalRole="decision",
        ),
        PlannedTask(
            key="verify", title="Verify", objective="Verify every acceptance criterion",
            capabilityRequirements=("verification",), acceptanceCriteria=("status emitted",),
            logicalRole="verification",
        ),
    )
    plan = TaskPlan(
        missionId="mission_123456789abc",
        nodes=tasks,
        relations=(
            TaskPlanRelation(sourceKey="understand", targetKey="refine", relationType="depends_on"),
            TaskPlanRelation(sourceKey="refine", targetKey="verify", relationType="depends_on"),
        ),
        controlPolicies=(VerificationLoopPolicy(
            bodyEntryKey="refine", bodyExitKey="verify", conditionSourceKey="verify",
            statusPointer="/verification/status", repeatValues=("partial", "failed"),
            maxRevisions=2, onExhausted="human_review",
        ),),
    )
    capabilities = [item.capability_requirements[0] for item in tasks]
    network = CollaborationNetwork(
        bindings=[CapabilityBinding(capability=item, agent_name="native_general_agent", score=4.0) for item in capabilities],
        entropy_budget=1024,
    )
    lowering_input = build_acg_lowering_input(
        mission_id=plan.mission_id,
        profile=TaskSemanticProfile(
            primaryGoal="Design and verify", requiredCapabilities=capabilities,
            estimatedComplexity="complex", entropyBudget=1024,
            evidenceScope="task_input_only", webExtraction="snippets",
        ),
        network=network,
        task_plan=plan,
        capability_catalog=catalog,
    )
    blueprint = ACGLowerer().lower(lowering_input)
    restored = type(blueprint).model_validate_json(blueprint.model_dump_json(by_alias=True))
    assert restored.metadata["evidenceScope"] == "task_input_only"
    assert restored.metadata["webExtraction"] == "snippets"

    reasoning = {step.metadata["taskPlanKey"]: step.metadata["reasoningEffort"] for step in blueprint.step_nodes()}
    assert reasoning == {"understand": "high", "refine": "max", "verify": "max"}
    loop = next(
        node for node in blueprint.nodes
        if isinstance(node, ControlNode) and node.control_type is ControlType.LOOP
    )
    assert loop.loop_spec is not None
    assert loop.loop_spec.max_iterations is None
    assert loop.loop_spec.on_limit == "review"
    package = ACGGraphCompiler().compile_package(blueprint, run_id="run_123456789abc")
    demanded_step = next(step.node_id for step in blueprint.step_nodes() if step.capability == "solution_design")
    assert package.binding_manifest.for_step(demanded_step).model_demand == demand
    assert restored.resource_plan.models == blueprint.resource_plan.models
    rule = next(item for item in package.control_manifest.rules if item.loop is not None)
    assert rule.loop.max_iterations is None


def loop_graph():
    from types import SimpleNamespace
    from components.executor.graph import ACGExecutionGraph, ACGExecutionState
    from contracts.compiled_acg import ControlManifest, ControlRule, ConditionalControlSpec, LoopControlSpec

    manifest = ControlManifest(entryNodeIds=("read",), exitNodeIds=("done",),
        rules=(ControlRule(controlId="review-loop", controlType="loop", loop=LoopControlSpec(
        bodyEntryId="read", bodyExitId="verify", maxIterations=1,
        condition=ConditionalControlSpec(sourceStepId="verify", jsonPointer="/status", operator="IN",
            targetsByCase={"partial": "read", "passed": "done"}))),))
    graph = ACGExecutionGraph(nodes=("read", "verify", "done"), edges=(("read", "verify"), ("verify", "done")),
        compiled_package=SimpleNamespace(control_manifest=manifest))
    return graph, ACGExecutionState(runId="run-loops")


def test_legacy_iteration_count_cannot_stop_real_progress_and_acceptance_exits():
    graph, state = loop_graph()
    for index in range(40):
        state.completed_step_ids = ["read", "verify"]
        graph._advance_loop_frames(state, {"read": {"observedPath": f"part-{index}.py"},
                                          "verify": {"status": "partial", "remaining": 40 - index}})
        assert state.review_payload is None
    assert state.loop_iterations["review-loop"] == 40
    state.completed_step_ids = ["read", "verify"]
    graph._advance_loop_frames(state, {"verify": {"status": "passed"}})
    assert state.control_frames == [] and state.review_payload is None


def test_unchanged_loop_evidence_waits_for_new_input_without_accepting_failed_review():
    import json

    graph, state = loop_graph()
    values = {"read": {"text": "PRIVATE SOURCE"}, "verify": {"status": "partial"}}
    for _ in range(2):
        state.completed_step_ids = ["read", "verify"]
        graph._advance_loop_frames(state, values)
    assert state.review_payload["reasonCode"] == "LOOP_NO_PROGRESS"
    assert "PRIVATE SOURCE" not in json.dumps(state.model_dump())
