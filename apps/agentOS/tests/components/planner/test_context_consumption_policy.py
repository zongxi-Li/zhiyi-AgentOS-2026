from copy import deepcopy

import pytest

from components.planner.context_policy import resolve_prefetch
from components.planner.lowering_input import lowering_step_from_task
from contracts.planning import PlannedTask
from support.acg.capabilities import ContextConsumptionPolicy, PlanningCapabilityDescriptor
from support.acg.native_capabilities import build_default_capability_catalog


def consumer(**policy):
    return PlanningCapabilityDescriptor(capabilityId="consumer", displayName="Consumer",
        inputContract={"type": "object", "properties": {"analysis": {}, "notes": {}}, "required": ["analysis"]},
        contextPolicy=ContextConsumptionPolicy(**policy))


def test_contract_prefetch_keeps_constraints_and_distinct_sources():
    selected, reason = resolve_prefetch(consumer(), "producer", ["analysis", "large_unrelated", "constraints", "evidence_refs", "notes"])
    assert selected == ["analysis", "constraints", "evidence_refs", "notes"]
    assert reason == "consumer-input-contract"
    # A second producer is selected independently, including same-named fields.
    assert resolve_prefetch(consumer(), "other", ["analysis"])[0] == ["analysis"]


def test_ambiguous_and_legacy_inputs_remain_complete():
    fields = ["artifact", "deliverable", "final_answer", "verification"]
    for capability in ("verification", "artifact_generation"):
        descriptor = build_default_capability_catalog().get(capability)
        assert resolve_prefetch(descriptor, "artifact_generation", fields) == (fields, "ambiguous-full-output")
    legacy = consumer().model_copy(update={"context_policy": None})
    assert resolve_prefetch(legacy, "producer", fields) == (fields, "legacy-full-output")


@pytest.mark.parametrize("fields", [[], ["unknown"]])
def test_registered_prefetch_rejects_empty_or_out_of_contract_fields(fields):
    with pytest.raises(ValueError):
        resolve_prefetch(consumer(prefetchFields={"producer": fields}), "producer", ["analysis"])


def test_lowering_freezes_policy_and_incremental_producer_capability():
    descriptor = consumer(prefetchFields={"producer": ["analysis"]}, memoryTokenBudget=512)
    task = PlannedTask(key="target", title="Target", objective="Analyze", capabilityRequirements=("consumer",))
    producer = PlanningCapabilityDescriptor(capabilityId="producer", displayName="Producer",
        outputContract={"required": ["analysis", "large_unrelated", "constraints"]})
    kwargs = dict(task=task, descriptor=descriptor, node_id="target-id", dependencies=["source"],
        node_id_by_task={"source": "source-id"}, descriptors={"source": producer}, expected_artifacts=(), router_score=1)
    initial = lowering_step_from_task(**kwargs)
    frozen = deepcopy(initial.input_spec)
    incremental = lowering_step_from_task(**{**kwargs, "descriptors": {}},
        dependency_output_contracts={"source": producer.output_contract}, dependency_capabilities={"source": "producer"})
    assert initial.input_spec == incremental.input_spec
    assert initial.input_spec["prefetch"] == {"source-id": ["analysis", "constraints"]}
    assert set(initial.input_spec["prefetch"]["source-id"]) <= set(initial.input_spec["from"]["source-id"])
    assert initial.metadata["memoryPolicy"]["tokenBudget"] == 512
    descriptor.context_policy.prefetch_fields["producer"] = ["large_unrelated"]
    assert initial.input_spec == frozen


def test_prefetch_is_enforced_by_context_assembly_without_losing_source_identity():
    from components.communicator.assembler import ContextAssembler
    upstream = {
        "one": {"analysis": "first", "large_unrelated": "x" * 5000, "constraints": ["keep"]},
        "two": {"analysis": "second", "large_unrelated": "y" * 5000, "constraints": ["also keep"]},
    }
    spec = {"from": {key: list(value) for key, value in upstream.items()},
            "prefetch": {key: ["analysis", "constraints"] for key in upstream}}
    pack = ContextAssembler().assemble(run_id="run", step_id="consumer", input_spec=spec, upstream_outputs=upstream)
    assert pack.source_data["one"]["analysis"] == "first"
    assert pack.source_data["two"]["analysis"] == "second"
    assert all("large_unrelated" not in fields for fields in pack.source_data.values())
    assert pack.tokens_delivered < pack.tokens_available
    spec["prefetch"]["one"] = ["not_authorized"]
    with pytest.raises(ValueError, match="subset"):
        ContextAssembler().assemble(run_id="run", step_id="consumer", input_spec=spec, upstream_outputs=upstream)


def test_initial_plan_compiles_prefetch_and_memory_budget_without_mutating_old_package():
    from components.executor.compiler import ACGGraphCompiler
    from components.planner.acg_lowerer import ACGLowerer
    from components.planner.cognitive_router import CapabilityBinding, CollaborationNetwork
    from components.planner.lowering_input import build_acg_lowering_input
    from components.planner.semantic_planner import SemanticPlanner
    from support.acg.capabilities import CapabilityCatalog
    from support.acg.semantic_profile import TaskSemanticProfile

    source = PlanningCapabilityDescriptor(capabilityId="producer", displayName="Producer",
        outputContract={"type": "object", "properties": {"analysis": {}, "large_unrelated": {}, "constraints": {}},
                        "required": ["analysis", "large_unrelated", "constraints"]})
    target = consumer().model_copy(update={"depends_on": ["producer"]})
    catalog = CapabilityCatalog([source, target])
    mission = "mission_0123456789ab"
    plan = SemanticPlanner(catalog).plan_capabilities(mission_id=mission, capabilities=["producer", "consumer"], strategy="test")
    lowering = build_acg_lowering_input(mission_id=mission, task_plan=plan, capability_catalog=catalog,
        profile=TaskSemanticProfile(primaryGoal="Analyze", requiredCapabilities=["producer", "consumer"]),
        network=CollaborationNetwork(bindings=[CapabilityBinding(capability=cap, agent_name="agent", score=1)
                                                for cap in ("producer", "consumer")]))
    blueprint = ACGLowerer().lower(lowering)
    node = next(node for node in blueprint.step_nodes() if node.capability == "consumer")
    assert list(node.input_spec["prefetch"].values()) == [["analysis", "constraints"]]
    assert node.metadata["memoryPolicy"]["tokenBudget"] == 2048
    compiler = ACGGraphCompiler()
    frozen = compiler.compile_package(blueprint, run_id="run")
    target.context_policy.memory_token_budget = 10
    assert compiler.compile_package(blueprint, run_id="run").checksum == frozen.checksum
