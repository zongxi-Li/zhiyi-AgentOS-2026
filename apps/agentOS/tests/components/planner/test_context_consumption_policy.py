from copy import deepcopy

import pytest

from components.planner.context_policy import resolve_prefetch
from components.planner.lowering_input import lowering_step_from_task, output_fields
from contracts.communication import schema_top_level_fields
from contracts.planning import PlannedTask
from support.acg.capabilities import ContextConsumptionPolicy, PlanningCapabilityDescriptor
from support.acg.native_capabilities import build_default_capability_catalog


def consumer(**policy):
    return PlanningCapabilityDescriptor(capabilityId="consumer", displayName="Consumer",
        inputContract={"type": "object", "properties": {"analysis": {}, "notes": {}}, "required": ["analysis"]},
        contextPolicy=ContextConsumptionPolicy(**policy))


def test_new_lowering_versions_execution_delivery_without_requiring_a_prefetch_policy():
    descriptor = PlanningCapabilityDescriptor(capabilityId="consumer", displayName="Consumer")
    task = PlannedTask(key="target", title="Target", objective="Read admitted context")
    step = lowering_step_from_task(task=task, descriptor=descriptor, node_id="target", dependencies=[],
        node_id_by_task={}, descriptors={}, expected_artifacts=(), router_score=1)
    assert step.input_spec["contextPolicy"] == {"executionContextVersion": 1}


@pytest.mark.parametrize("contract,fields", [
    ({"properties": {"optional": {}}}, ["optional"]),
    ({"required": ["legacy", "legacy"]}, ["legacy"]),
    ({"required": ["second", "first"], "properties": {"z": {}, "first": {}, "a": {}}},
        ["second", "first", "a", "z"]),
    ({"properties": {"object": {"properties": {"nested": {}}}}, "additionalProperties": True,
      "patternProperties": {"private.*": {}}}, ["object"]),
    ({}, []),
])
def test_output_field_authority_includes_named_optional_fields_without_opening_undeclared_fields(contract, fields):
    assert output_fields(contract) == fields
    assert schema_top_level_fields(contract) == fields


def test_contract_prefetch_keeps_constraints_and_distinct_sources():
    selected, reason = resolve_prefetch(consumer(), "producer", ["analysis", "large_unrelated", "constraints", "evidence_refs", "notes"])
    assert selected == ["analysis", "constraints", "evidence_refs", "notes"]
    assert reason == "consumer-input-contract"
    # A second producer is selected independently, including same-named fields.
    assert resolve_prefetch(consumer(), "other", ["analysis"])[0] == ["analysis"]


def test_optional_consumer_input_can_select_prefetch_without_becoming_required():
    descriptor = consumer().model_copy(update={"input_contract": {
        "type": "object", "properties": {"notes": {}}}})
    assert resolve_prefetch(descriptor, "producer", ["notes", "large_unrelated", "constraints"]) == (
        ["notes", "constraints"], "consumer-input-contract")
    assert "required" not in descriptor.input_contract


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
    descriptor = consumer(prefetchFields={"producer": ["analysis"]}, memoryTokenBudget=512,
                          supplementalReadBudget={"maxReadTokens": 2048, "pageTokens": 512, "totalTokens": 8192},
                          requestBudget={"totalTokens": 32000, "outputReserveTokens": 8000})
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
    assert initial.input_spec["contextPolicy"]["executionContextVersion"] == 1
    assert initial.input_spec["prefetch"] == {"source-id": ["analysis", "constraints"]}
    assert set(initial.input_spec["prefetch"]["source-id"]) <= set(initial.input_spec["from"]["source-id"])
    assert initial.metadata["memoryPolicy"]["tokenBudget"] == 512
    assert initial.input_spec["contextPolicy"]["supplementalReadBudget"] == {
        "version": "supplemental-read.v1", "maxReadTokens": 2048, "pageTokens": 512, "totalTokens": 8192}
    assert initial.input_spec["contextPolicy"]["requestBudget"] == {
        "version": "request-budget.v1", "totalTokens": 32000, "outputReserveTokens": 8000,
        "workingSetMode": "observe", "workingSetTargetTokens": None, "workingSetTriggerTokens": None}
    descriptor.context_policy.prefetch_fields["producer"] = ["large_unrelated"]
    assert initial.input_spec == frozen


def test_prefetch_is_enforced_by_context_assembly_without_losing_source_identity():
    import asyncio
    from components.communicator import CommunicationBroker, CommunicationManifest, CommunicationRule
    from components.executor.value_store import InMemoryExecutionValueStore
    upstream = {
        "one": {"analysis": "first", "large_unrelated": "x" * 5000, "constraints": ["keep"]},
        "two": {"analysis": "second", "large_unrelated": "y" * 5000, "constraints": ["also keep"]},
    }
    spec = {"from": {key: list(value) for key, value in upstream.items()},
            "prefetch": {key: ["analysis", "constraints"] for key in upstream}}
    store = InMemoryExecutionValueStore()
    refs = {source: store.put_output(run_id="run", step_id=source, payload=output)
            for source, output in upstream.items()}
    broker = CommunicationBroker(value_store=store, manifest=CommunicationManifest(run_id="run", rules=tuple(
        CommunicationRule(producer_step_id=source, consumer_step_id="consumer",
                          allowed_fields=tuple(output), channel=f"{source}:consumer")
        for source, output in upstream.items())))
    pack = asyncio.run(broker.assemble_context(run_id="run", step_id="consumer", input_spec=spec, upstream_refs=refs))
    assert pack.source_data["one"]["analysis"] == "first"
    assert pack.source_data["two"]["analysis"] == "second"
    assert all("large_unrelated" not in fields for fields in pack.source_data.values())
    assert pack.tokens_delivered < pack.tokens_available
    spec["prefetch"]["one"] = ["not_authorized"]
    with pytest.raises(ValueError, match="subset"):
        asyncio.run(broker.assemble_context(run_id="run", step_id="consumer", input_spec=spec, upstream_refs=refs))


@pytest.mark.parametrize("producer_id,consumer_id,optional_field,value", [
    ("task_understanding", "information_extraction", "success_criteria", ["Preserve every finding"]),
    ("information_retrieval", "evidence_analysis", "sources", [{"citationId": "source:1"}]),
    ("information_retrieval", "evidence_analysis", "retrieval_mode", "workspace"),
])
def test_declared_optional_output_remains_available_for_authorized_supplemental_reads(
    producer_id, consumer_id, optional_field, value,
):
    import asyncio
    from components.communicator import CommunicationBroker, CommunicationManifest, CommunicationRule
    from components.communicator.reader import CommunicationReader
    from components.executor.value_store import InMemoryExecutionValueStore

    catalog = build_default_capability_catalog()
    producer, target = catalog.get(producer_id), catalog.get(consumer_id)
    task = PlannedTask(key="target", title="Target", objective="Use prior evidence",
        capabilityRequirements=(consumer_id,))
    step = lowering_step_from_task(task=task, descriptor=target, node_id="target-id", dependencies=["source"],
        node_id_by_task={"source": "source-id"}, descriptors={"source": producer},
        expected_artifacts=(), router_score=1)
    allowed = step.input_spec["from"]["source-id"]
    assert optional_field in allowed and optional_field not in producer.output_contract["required"]
    store = InMemoryExecutionValueStore()
    reference = store.put_output(run_id="run", step_id="source-id",
        payload={optional_field: value, "undeclared_private": "do not expose"})
    broker = CommunicationBroker(value_store=store, manifest=CommunicationManifest(run_id="run", rules=(
        CommunicationRule(producer_step_id="source-id", consumer_step_id="target-id",
            allowed_fields=tuple(allowed), channel="source:target"),)))
    reader = CommunicationReader(broker=broker, run_id="run", consumer_step_id="target-id",
        output_refs={"source-id": reference}, max_tokens=None)
    pack = asyncio.run(reader.read("source-id", [optional_field]))
    assert pack.source_data == {"source-id": {optional_field: value}}
    if optional_field == "retrieval_mode":
        assert optional_field not in step.input_spec["prefetch"]["source-id"]
    with pytest.raises(PermissionError, match="not permitted"):
        asyncio.run(reader.read("source-id", ["undeclared_private"]))


def test_declared_optional_fields_do_not_expand_an_explicitly_restricted_channel():
    import asyncio
    from components.communicator import CommunicationBroker, CommunicationManifest, CommunicationRule
    from components.executor.value_store import InMemoryExecutionValueStore

    store = InMemoryExecutionValueStore()
    reference = store.put_output(run_id="run", step_id="source",
        payload={"analysis": "allowed", "sources": ["restricted"]})
    broker = CommunicationBroker(value_store=store, manifest=CommunicationManifest(run_id="run", rules=(
        CommunicationRule(producer_step_id="source", consumer_step_id="target",
            allowed_fields=("analysis",), channel="frozen-restricted"),)))
    with pytest.raises(PermissionError, match="not permitted"):
        asyncio.run(broker.read_reference(run_id="run", consumer_step_id="target", output_ref=reference,
            requested_fields=["sources"], max_tokens=None, reason="declared but not authorized"))


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
                        "required": ["analysis"]})
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
    rule = next(rule for rule in frozen.communication_manifest.rules if rule.consumer_step_id == node.node_id)
    assert rule.allowed_fields == ("analysis", "constraints", "large_unrelated")
    target.context_policy.memory_token_budget = 10
    assert compiler.compile_package(blueprint, run_id="run").checksum == frozen.checksum
