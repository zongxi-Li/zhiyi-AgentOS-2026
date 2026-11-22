"""Dependency revisions rebuild live context while preserving local contracts."""
import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

from components.communicator import CommunicationBroker
from components.executor.compiler import ACGGraphCompiler
from components.executor.value_store import InMemoryExecutionValueStore
from components.planner.acg_lowerer import ACGLowerer
from components.planner.semantic_patch_planning import build_semantic_patch_lowering_input
from contracts.planning import PlannedTask, TaskImplementationBinding, TaskPlan, TaskPlanRelation
from support.packs.native_capabilities import build_default_capability_catalog
from contracts.acg.planning import ACGResourcePlan, AgentBindingSpec, CommunicationSpec, EvidenceSpec, MemoryAccessSpec
from contracts.acg.schema import ACGEdge, RuntimeBlueprintSpec, StepNode


def relation(source, target):
    return TaskPlanRelation(sourceKey=source, targetKey=target, relationType="depends_on")


def source_contract(field):
    return {"type": "object", "properties": {field: {"type": "string"}, "notes": {}}}


def scenario():
    tasks = tuple(PlannedTask(key=key, title=key, objective=key,
        capabilityRequirements=("task_understanding",)) for key in "ABCD")
    plan = TaskPlan(missionId="mission_0123456789ab", nodes=tasks,
        relations=(relation("A", "B"), relation("B", "C"), relation("D", "C")))
    input_spec = {"from": {"B": ["reviewed"], "D": ["finding"]},
        "prefetch": {"B": ["reviewed"], "D": ["finding"]},
        "schema": {"type": "object", "properties": {"finding": {}}, "required": ["finding"]},
        "contextPolicy": {"version": "context-consumption.v1", "nestedReadVersion": 1,
            "selectionReasons": {"B": "registered-fields", "D": "registered-fields"},
            "requestBudget": {"totalTokens": 10000, "outputReserveTokens": 1000}},
        "customSetting": {"keep": True}}
    graph = RuntimeBlueprintSpec(graphId="graph", missionId=plan.mission_id,
        nodes=[StepNode(nodeId=key, name=key, capability="task_understanding",
            inputSpec=deepcopy(input_spec) if key == "C" else {},
            outputSpec=source_contract("reviewed" if key == "B" else "finding"),
            metadata={"taskPlanKey": key, "dependsOn": {"B": ["A"], "C": ["B", "D"]}.get(key, []),
                "memoryPolicy": {"read": True, "write": False}}) for key in "ABCD"],
        edges=[ACGEdge(sourceId=r.source_key, targetId=r.target_key, edgeType="dependency")
            for r in plan.relations],
        resourcePlan=ACGResourcePlan(bindings=tuple(AgentBindingSpec(stepId=key,
            plannedAgentId="agent:test") for key in "ABCD"), communication=(
                CommunicationSpec(producerStepId="B", consumerStepId="C", channel="B:C", allowedFields=("reviewed",)),
                CommunicationSpec(producerStepId="D", consumerStepId="C", allowedFields=("finding",),
                    channel="restricted", maxTokens=1500))))
    return plan, graph


def lower(plan, graph, next_plan):
    return ACGLowerer().lower(build_semantic_patch_lowering_input(
        blueprint=graph, current_plan=plan, next_plan=next_plan,
        base_bindings=tuple(TaskImplementationBinding(planNodeKey=key, acgNodeId=key) for key in "ABCD"),
        changed_keys=set(), capability_catalog=build_default_capability_catalog(),
        agent_registry=object(), domain="general"))


def test_retired_predecessor_is_replaced_by_saved_source_context():
    plan, graph = scenario()
    original = graph.model_dump(by_alias=True, mode="json")
    next_plan = plan.model_copy(update={"plan_version": 2,
        "nodes": tuple(task for task in plan.nodes if task.key != "B"),
        "relations": (relation("A", "C"), relation("D", "C"))})
    revised = lower(plan, graph, next_plan)
    report = revised.get_node("C")
    assert not revised.has_node("B")
    assert report.input_spec["from"] == {"D": ["finding"], "A": ["finding", "notes"]}
    assert report.input_spec["prefetch"] == report.input_spec["from"]
    assert report.input_spec["contextPolicy"]["selectionReasons"] == {
        "D": "registered-fields", "A": "dependency-output-contract"}
    for key in ("schema", "customSetting"):
        assert report.input_spec[key] == graph.get_node("C").input_spec[key]
    assert report.input_spec["contextPolicy"]["requestBudget"] == graph.get_node("C").input_spec["contextPolicy"]["requestBudget"]
    assert report.metadata["memoryPolicy"] == graph.get_node("C").metadata["memoryPolicy"]
    assert report.metadata["dependsOn"] == ["A", "D"]
    assert revised.get_node("A") == graph.get_node("A")
    assert revised.get_node("D") == graph.get_node("D")
    package = ACGGraphCompiler().compile_package(revised, run_id="run")
    manifest = ACGGraphCompiler._runtime_communication_manifest(package.communication_manifest)
    rules = {rule.producer_step_id: rule for rule in manifest.rules_for_consumer("C")}
    assert rules["D"].allowed_fields == ("finding",)
    assert rules["D"].max_tokens == 1500
    store = InMemoryExecutionValueStore()
    refs = {key: store.put_output(run_id="run", step_id=key, payload={
        "finding": key + " confirmed", "notes": key + " optional", "private": "not authorized"})
        for key in ("A", "D")}
    context = asyncio.run(CommunicationBroker(value_store=store,
        manifest=manifest).assemble_context(run_id="run", step_id="C",
            input_spec=report.input_spec, upstream_refs=refs))
    assert context.source_data == {"A": {"finding": "A confirmed", "notes": "A optional"},
                                   "D": {"finding": "D confirmed"}}
    assert graph.model_dump(by_alias=True, mode="json") == original


def test_removed_dependency_loses_access_even_when_producer_remains_in_graph():
    plan, graph = scenario()
    next_plan = plan.model_copy(update={"plan_version": 2,
        "relations": (relation("A", "B"), relation("D", "C"))})
    revised = lower(plan, graph, next_plan)
    report = revised.get_node("C")
    assert revised.has_node("B")
    assert report.input_spec["from"] == {"D": ["finding"]}
    assert report.input_spec["prefetch"] == {"D": ["finding"]}
    package = ACGGraphCompiler().compile_package(revised, run_id="run")
    assert [r.producer_step_id for r in package.communication_manifest.rules if r.consumer_step_id == "C"] == ["D"]


def test_unchanged_input_and_transitive_authorization_survive_added_direct_dependency():
    plan, graph = scenario()
    graph.get_node("C").input_spec["from"]["A"] = ["finding"]
    graph.get_node("C").input_spec["prefetch"]["A"] = ["finding"]
    original = deepcopy(graph.get_node("C").input_spec)
    next_plan = plan.model_copy(update={"plan_version": 2,
        "relations": (*plan.relations, relation("A", "C"))})
    revised = lower(plan, graph, next_plan)
    assert revised.get_node("C").input_spec == original
    assert revised.get_node("B") == graph.get_node("B")


def test_removing_last_dependency_clears_from_prefetch_and_selection_reasons():
    plan, graph = scenario()
    next_plan = plan.model_copy(update={"plan_version": 2, "relations": (relation("A", "B"),)})
    report = lower(plan, graph, next_plan).get_node("C")
    assert report.input_spec["from"] == {}
    assert report.input_spec["prefetch"] == {}
    assert report.input_spec["contextPolicy"]["selectionReasons"] == {}
    assert report.input_spec["schema"] == graph.get_node("C").input_spec["schema"]


def add_transitive_context(graph):
    report = graph.get_node("C")
    report.input_spec["from"]["A"] = ["finding", "notes"]
    report.input_spec["prefetch"]["A"] = ["finding"]
    report.input_spec["contextPolicy"]["selectionReasons"]["A"] = "registered-fields"
    graph.resource_plan.communication += (CommunicationSpec(producerStepId="A", consumerStepId="C",
        channel="transitive", allowedFields=("finding", "notes")),)
    graph.resource_plan.memory = (MemoryAccessSpec(stepId="A", memoryId="memo", access="write"),
        MemoryAccessSpec(stepId="C", memoryId="memo", access="read"))
    graph.resource_plan.evidence = (EvidenceSpec(evidenceId="fact", producerStepId="A",
        consumerStepIds=("C",), source="workflow"),)


def test_indirect_path_removal_prunes_input_communication_memory_and_evidence_together():
    plan, graph = scenario()
    add_transitive_context(graph)
    original_source = graph.get_node("A").model_copy(deep=True)
    # C still directly depends on B and D; only B's upstream path changes.
    next_plan = plan.model_copy(update={"plan_version": 2,
        "relations": (relation("B", "C"), relation("D", "C"))})
    revised = lower(plan, graph, next_plan)
    report = revised.get_node("C")
    assert "A" not in report.input_spec["from"]
    assert "A" not in report.input_spec["prefetch"]
    assert "A" not in report.input_spec["contextPolicy"]["selectionReasons"]
    assert revised.get_node("A") == original_source
    assert revised.resource_plan.memory == (graph.resource_plan.memory[0],)
    assert revised.resource_plan.evidence[0].consumer_step_ids == ()
    assert all(spec.producer_step_id != "A" for spec in revised.resource_plan.communication)
    package = ACGGraphCompiler().compile_package(revised, run_id="run")
    assert all(rule.producer_step_id != "A" for rule in package.communication_manifest.rules)


def test_replaced_transitive_source_rebuilds_context_and_communication_contract(monkeypatch):
    from components.planner.cognitive_router import CognitiveRouter
    from support.capabilities import CapabilityCatalog, PlanningCapabilityDescriptor

    plan, graph = scenario()
    add_transitive_context(graph)
    new_contract = source_contract("finding")
    new_contract["properties"].pop("notes")
    new_contract["properties"]["updated_notes"] = {}
    catalog = CapabilityCatalog([PlanningCapabilityDescriptor(capabilityId="task_understanding",
        displayName="Task", outputContract=new_contract)])
    monkeypatch.setattr(CognitiveRouter, "candidates_for", lambda *args, **kwargs: [
        SimpleNamespace(logical_agent_id="agent:test", score=1, ephemeral=False)])
    next_plan = plan.model_copy(update={"plan_version": 2, "nodes": tuple(
        task.model_copy(update={"objective": "Replace producer"}) if task.key == "A" else task
        for task in plan.nodes)})
    revised = ACGLowerer().lower(build_semantic_patch_lowering_input(
        blueprint=graph, current_plan=plan, next_plan=next_plan,
        base_bindings=tuple(TaskImplementationBinding(planNodeKey=key, acgNodeId=key) for key in "ABCD"),
        changed_keys={"A"}, capability_catalog=catalog, agent_registry=object(), domain="general"))
    report = revised.get_node("C")
    assert report.input_spec["from"]["A"] == ["finding", "updated_notes"]
    assert report.input_spec["prefetch"]["A"] == ["finding", "updated_notes"]
    package = ACGGraphCompiler().compile_package(revised, run_id="run")
    rule = next(rule for rule in package.communication_manifest.rules
        if rule.producer_step_id == "A" and rule.consumer_step_id == "C")
    assert rule.allowed_fields == ("finding", "updated_notes")


def test_rebinding_is_identical_after_canonical_json_restart_roundtrip():
    plan, graph = scenario()
    add_transitive_context(graph)
    next_plan = plan.model_copy(update={"plan_version": 2,
        "nodes": tuple(task for task in plan.nodes if task.key != "B"),
        "relations": (relation("A", "C"), relation("D", "C"))})
    restarted = RuntimeBlueprintSpec.model_validate_json(json.dumps(
        graph.model_dump(by_alias=True, mode="json"), sort_keys=True))
    first, second = lower(plan, graph, next_plan), lower(plan, restarted, next_plan)
    assert first.resource_plan == second.resource_plan
    assert first.nodes == second.nodes
