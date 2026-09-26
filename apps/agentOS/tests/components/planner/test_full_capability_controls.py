from components.executor.compiler import ACGGraphCompiler
from components.planner.acg_lowerer import ACGLowerer
from components.planner.lowering_input import build_acg_lowering_input
from components.planner.cognitive_router import CapabilityBinding, CollaborationNetwork
from contracts.planning import PlannedTask, TaskPlan, TaskPlanRelation, VerificationLoopPolicy
from support.acg.models import ControlNode, ControlType, TaskSemanticProfile, build_default_capability_catalog


def test_lowering_freezes_reasoning_tiers_and_compiles_bounded_verification_loop() -> None:
    catalog = build_default_capability_catalog()
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
        ),
        network=network,
        task_plan=plan,
        capability_catalog=catalog,
    )
    blueprint = ACGLowerer().lower(lowering_input)

    reasoning = {step.metadata["taskPlanKey"]: step.metadata["reasoningEffort"] for step in blueprint.step_nodes()}
    assert reasoning == {"understand": "high", "refine": "max", "verify": "max"}
    loop = next(
        node for node in blueprint.nodes
        if isinstance(node, ControlNode) and node.control_type is ControlType.LOOP
    )
    assert loop.loop_spec is not None
    assert loop.loop_spec.max_iterations == 3
    assert loop.loop_spec.on_limit == "review"
    package = ACGGraphCompiler().compile_package(blueprint, run_id="run_123456789abc")
    rule = next(item for item in package.control_manifest.rules if item.loop is not None)
    assert rule.loop.max_iterations == 3
