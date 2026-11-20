"""Safe-cut preserves historical publication and input obligations."""
from types import SimpleNamespace

import pytest

from contracts.planning import PlannedTask, TaskImplementationBinding, TaskPlan
from contracts.workflow import RuntimeRunRecord, StepStatus, WorkflowStep
from runtime.orchestration.graph_revision import GraphRevisionError, safe_cut
from components.planner.semantic_patch import derive_graph_patch
from contracts.acg.planning import ACGResourcePlan, CommunicationSpec, EvidenceSpec
from contracts.acg.schema import ACGEdge, RuntimeBlueprintSpec, StepNode


class EmptyCheckpointStore:
    def load_latest(self, *, run_id):
        raise KeyError(run_id)


def boundary(*, channels=(), evidence=(), completed=("A",)):
    old = RuntimeBlueprintSpec(graphId="graph", missionId="mission_0123456789ab", nodes=[
        StepNode(nodeId=key, name=key, capability="task_understanding") for key in ("A", "B")],
        edges=[ACGEdge(edgeId="ab", sourceId="A", targetId="B", edgeType="dependency")],
        resourcePlan=ACGResourcePlan(communication=channels, evidence=evidence))
    plan = TaskPlan(missionId="mission_0123456789ab", nodes=tuple(
        PlannedTask(key=key, title=key, objective=key) for key in ("A", "B")))
    bindings = tuple(TaskImplementationBinding(planNodeKey=key, acgNodeId=key) for key in ("A", "B"))
    run = RuntimeRunRecord(runId="run", missionId="mission_0123456789ab", workflowId="test", domain="test",
        runtimeEngine="acg", acgBlueprint=old.model_dump(by_alias=True, mode="json"),
        completedStepIds=list(completed), steps=[WorkflowStep(stepId=key, name=key, agentName="test",
            status=StepStatus.COMPLETED if key in completed else StepStatus.PENDING) for key in ("A", "B")],
        executionState={"taskPlan": plan.model_dump(by_alias=True, mode="json"),
            "taskBindings": [item.model_dump(by_alias=True, mode="json") for item in bindings]})
    provider = SimpleNamespace(run=lambda: run, node_commits=lambda run: [],
        runtime=SimpleNamespace(checkpoint_store=EmptyCheckpointStore()))
    return provider, old, plan, bindings


def channel(producer="A", consumer="B", **kwargs):
    return CommunicationSpec(producerStepId=producer, consumerStepId=consumer,
        channel=f"{producer}:{consumer}", **kwargs)


def check(provider, old, plan, bindings, candidate):
    candidate.version = old.version + 1
    patch = derive_graph_patch(old, candidate, patch_id="test")
    return safe_cut(provider, None, plan, bindings, candidate, patch)


def test_new_strict_consumer_can_pull_immutable_result_without_changing_producer():
    provider, old, plan, bindings = boundary()
    candidate = old.model_copy(deep=True)
    candidate.resource_plan.communication = (channel(),)
    assert check(provider, old, plan, bindings, candidate).protected_node_ids == ("A",)


@pytest.mark.parametrize("mode", ["EVENT", "BLACKBOARD", "DEBATE"])
def test_completed_producer_cannot_acquire_new_advanced_publication(mode):
    provider, old, plan, bindings = boundary()
    candidate = old.model_copy(deep=True)
    candidate.resource_plan.communication = (channel(mode=mode),)
    with pytest.raises(GraphRevisionError, match="protected logical implementation"):
        check(provider, old, plan, bindings, candidate)


@pytest.mark.parametrize("mode", ["EVENT", "BLACKBOARD", "DEBATE"])
def test_implicit_edge_cannot_change_pending_reader_to_historical_publication(mode):
    provider, old, plan, bindings = boundary()
    candidate = old.model_copy(deep=True)
    candidate.nodes[1].metadata["communicationMode"] = mode
    with pytest.raises(GraphRevisionError, match="historical publication obligations"):
        check(provider, old, plan, bindings, candidate)


@pytest.mark.parametrize("field,value", [("allowed_fields", ("new_field",)), ("channel", "changed"), ("mode", "EVENT")])
@pytest.mark.parametrize("completed", [("A",), ("A", "B")])
def test_existing_channel_remains_frozen_for_completed_producer_or_consumer(field, value, completed):
    provider, old, plan, bindings = boundary(channels=(channel(),), completed=completed)
    candidate = old.model_copy(deep=True)
    candidate.resource_plan.communication = (channel().model_copy(update={field: value}),)
    with pytest.raises(GraphRevisionError, match="protected logical implementation"):
        check(provider, old, plan, bindings, candidate)


@pytest.mark.parametrize("field,value", [("source", "changed"), ("schema_", {"type": "integer"})])
def test_completed_producer_evidence_contract_cannot_change(field, value):
    evidence = EvidenceSpec(evidenceId="fact", producerStepId="A", source="frozen", consumerStepIds=("B",))
    provider, old, plan, bindings = boundary(evidence=(evidence,))
    candidate = old.model_copy(deep=True)
    candidate.resource_plan.evidence = (evidence.model_copy(update={field: value}),)
    with pytest.raises(GraphRevisionError, match="protected logical implementation"):
        check(provider, old, plan, bindings, candidate)


def test_completed_participant_cannot_acquire_new_conversation_obligation():
    provider, old, plan, bindings = boundary()
    candidate = old.model_copy(deep=True)
    candidate.resource_plan.communication = (channel(participantStepIds=("A",)),)
    with pytest.raises(GraphRevisionError, match="protected logical implementation"):
        check(provider, old, plan, bindings, candidate)
