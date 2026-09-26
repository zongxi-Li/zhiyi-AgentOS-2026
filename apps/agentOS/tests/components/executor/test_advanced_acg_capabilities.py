from __future__ import annotations


import asyncio

import pytest

from components.communicator import (
    BlackboardConflictError,
    CommunicationBackpressureError,
    CommunicatorService,
    DebateCoordinator,
    DebateSpec,
    ReliableMessage,
    SQLiteReliableCommunicationStore,
)
from components.executor.compiler import ACGGraphCompiler
from components.executor.graph import (
    ACGConditionalRoute,
    ACGExecutionGraph,
    ACGExecutionState,
    ACGNodeSpec,
)
from components.executor.node_runner import ACGNodeRunner
from components.executor.value_store import (
    ExecutionValueAccessError,
    InMemoryExecutionValueStore,
)
from components.memory import MemoryService
from contracts.workflow import RuntimeMissionRecord, WorkflowDefinition, RuntimeRunRecord, WorkflowStep
from service.agents.base import AgentOutput, AgentProfile, BaseAgent
from support.acg.models import ACGBlueprint, ACGEdge, EdgeType, StepNode, AgentNode


class _Agent(BaseAgent):
    def __init__(self) -> None:
        super().__init__(AgentProfile(agentName="advanced-agent", domain="general"))

    async def run(self, context):
        return AgentOutput(output={"value": True}, summary="done")


def _message(message_id: str, *, artifact_ref: str = "output:one") -> ReliableMessage:
    return ReliableMessage(
        message_id=message_id,
        run_id="run-1",
        producer_step_id="source",
        consumer_step_id="sink",
        artifact_ref=artifact_ref,
        correlation_id="run-1",
        causation_id="commit-1",
        sequence=1,
        schema_hash="a" * 64,
    )


def test_compile_package_validates_blueprint_without_run_id() -> None:
    blueprint = ACGBlueprint(
        graphId="invalid-compile",
        nodes=[StepNode(nodeId="a"), StepNode(nodeId="b")],
        edges=[ACGEdge(sourceId="a", targetId="b"),
               ACGEdge(sourceId="b", targetId="a")],
    )
    with pytest.raises(ValueError, match="cycle"):
        ACGGraphCompiler().compile_package(blueprint, run_id=None)


def test_operation_artifact_is_invisible_until_node_commit() -> None:
    store = InMemoryExecutionValueStore()
    store.prepare_node_commit(run_id="run-1", commit_id="commit-1")
    output_ref = store.put_output(
        run_id="run-1",
        step_id="source",
        payload={"secret": "staged"},
        operation_id="commit-1",
    )

    with pytest.raises(ExecutionValueAccessError, match="not committed"):
        store.get_output(run_id="run-1", output_ref=output_ref)

    store.complete_node_commit(
        run_id="run-1",
        commit_id="commit-1",
        payload={"outputRef": output_ref},
    )
    assert store.get_output(run_id="run-1", output_ref=output_ref) == {
        "secret": "staged"
    }


def test_reliable_event_is_idempotent_backpressured_and_acknowledged(tmp_path) -> None:
    store = SQLiteReliableCommunicationStore(tmp_path / "communication.sqlite3")
    first = store.publish(_message("message-1"), backlog_limit=1)
    repeated = store.publish(_message("message-1"), backlog_limit=1)

    assert repeated.payload_hash() == first.payload_hash()
    with pytest.raises(ValueError, match="payload conflict"):
        store.publish(_message("message-1", artifact_ref="output:changed"), backlog_limit=1)
    with pytest.raises(CommunicationBackpressureError):
        store.publish(_message("message-2"), backlog_limit=1)

    assert [item.message_id for item in store.pending(run_id="run-1", consumer_step_id="sink")] == ["message-1"]
    assert store.acknowledge(run_id="run-1", message_id="message-1").status == "acked"
    assert store.pending(run_id="run-1", consumer_step_id="sink") == ()


def test_blackboard_uses_snapshot_and_rejects_stale_cas(tmp_path) -> None:
    communication = SQLiteReliableCommunicationStore(tmp_path / "blackboard.sqlite3")
    version = communication.blackboard_write(
        run_id="run-1",
        partition="shared",
        key="source",
        artifact_ref="output:first",
        expected_version=0,
    )
    assert version == 1
    assert communication.blackboard_snapshot(run_id="run-1", partition="shared") == (
        1,
        {"source": "output:first"},
    )
    with pytest.raises(BlackboardConflictError, match="version conflict"):
        communication.blackboard_write(
            run_id="run-1",
            partition="shared",
            key="other",
            artifact_ref="output:other",
            expected_version=0,
        )


def test_compiler_freezes_debate_participants_rounds_and_quorum() -> None:
    blueprint = ACGBlueprint(
        graphId="debate",
        nodes=[
            StepNode(nodeId="left"),
            StepNode(nodeId="right"),
            StepNode(
                nodeId="judge",

                metadata={
                    "communicationMode": "DEBATE",
                    "debateParticipants": ["left", "right"],
                    "debateMaxRounds": 2,
                    "debateQuorum": 2,
                },
            ),
        AgentNode(nodeId="fixture-agent::left", name="advanced-agent"), AgentNode(nodeId="fixture-agent::right", name="advanced-agent"), AgentNode(nodeId="fixture-agent::judge", name="advanced-agent")],
        edges=[
            ACGEdge(sourceId="left", targetId="judge", edgeType=EdgeType.DEPENDENCY),
            ACGEdge(sourceId="right", targetId="judge", edgeType=EdgeType.DEPENDENCY),
            ACGEdge(sourceId="left", targetId="judge", edgeType=EdgeType.COMMUNICATION),
            ACGEdge(sourceId="right", targetId="judge", edgeType=EdgeType.COMMUNICATION),
        ACGEdge(sourceId="fixture-agent::left", targetId="left", edgeType=EdgeType.EXECUTION), ACGEdge(sourceId="fixture-agent::right", targetId="right", edgeType=EdgeType.EXECUTION), ACGEdge(sourceId="fixture-agent::judge", targetId="judge", edgeType=EdgeType.EXECUTION)],
    )

    package = ACGGraphCompiler().compile_package(blueprint, run_id="run-1")
    debate_rules = package.communication_manifest.rules

    assert len(debate_rules) == 2
    assert all(rule.participant_step_ids == ("left", "right") for rule in debate_rules)
    assert all(rule.max_rounds == 2 and rule.quorum == 2 for rule in debate_rules)


def test_debate_coordinator_is_bounded_and_requires_quorum() -> None:
    coordinator = DebateCoordinator(
        DebateSpec(participant_step_ids=("left", "right"), max_rounds=1, quorum=2)
    )
    coordinator.submit(participant_step_id="left", artifact_ref="output:left")
    with pytest.raises(RuntimeError, match="QUORUM"):
        coordinator.advance()
    coordinator.submit(participant_step_id="right", artifact_ref="output:right")
    assert coordinator.advance() == (1, "critique")


def test_blackboard_snapshot_is_frozen_before_sibling_writes(tmp_path) -> None:
    blueprint = ACGBlueprint(
        graphId="blackboard",
        nodes=[
            StepNode(nodeId="source"),
            StepNode(
                nodeId="sink",

                metadata={
                    "communicationMode": "BLACKBOARD",
                    "blackboardPartition": "shared",
                },
            ),
        AgentNode(nodeId="fixture-agent::source", name="advanced-agent"), AgentNode(nodeId="fixture-agent::sink", name="advanced-agent")],
        edges=[
            ACGEdge(sourceId="source", targetId="sink", edgeType=EdgeType.DEPENDENCY),
            ACGEdge(sourceId="source", targetId="sink", edgeType=EdgeType.COMMUNICATION),
        ACGEdge(sourceId="fixture-agent::source", targetId="source", edgeType=EdgeType.EXECUTION), ACGEdge(sourceId="fixture-agent::sink", targetId="sink", edgeType=EdgeType.EXECUTION)],
    )
    package = ACGGraphCompiler().compile_package(blueprint, run_id="run-1")
    communication = SQLiteReliableCommunicationStore(tmp_path / "snapshot.sqlite3")
    communication.blackboard_write(
        run_id="run-1", partition="shared", key="old",
        artifact_ref="output:old", expected_version=0,
    )
    agent = _Agent()
    runner = ACGNodeRunner(
        task=RuntimeMissionRecord(missionId="task-1", title="blackboard"),
        run=RuntimeRunRecord(missionId="task-1", workflowId="workflow-1", domain="general", runtimeEngine="acg"),
        workflow=WorkflowDefinition(workflowId="workflow-1", name="workflow", domain="general", intent="general", runtimeEngine="acg"),
        steps={"sink": WorkflowStep(stepId="sink", name="sink", agentName="advanced-agent")},
        agents={"sink": agent},
        communicator=CommunicatorService(run_id="run-1", mission_id="task-1"),
        memory=MemoryService(),
        communication_modes={"sink": "BLACKBOARD"},
        reliable_communication_store=communication,
        compiled_package=package,
    )
    state = ACGExecutionState(runId="run-1")

    runner.prepare_superstep(state, ("sink",))
    communication.blackboard_write(
        run_id="run-1", partition="shared", key="new",
        artifact_ref="output:new", expected_version=1,
    )

    assert state.blackboard_snapshots["sink"]["entries"] == {
        "shared:old": "output:old"
    }


def test_if_without_matching_case_or_default_fails_structurally() -> None:
    graph = ACGExecutionGraph(
        nodes=("source", "if", "target"),
        edges=(("source", "if"), ("if", "target")),
        node_specs={
            "source": ACGNodeSpec(node_id="source"),
            "if": ACGNodeSpec(
                node_id="if",
                kind="control",
                control_type="if",
                condition=ACGConditionalRoute(
                    source_step_id="source",
                    json_pointer="/choice",
                    operator="IN",
                    targets_by_case={"known": "target"},
                ),
            ),
            "target": ACGNodeSpec(node_id="target"),
        },
    )

    async def execute(step_id: str, _state: ACGExecutionState):
        return {
            "commitId": f"commit:{step_id}",
            "outputSummary": step_id,
            "routeValue": {"choice": "unknown"},
        }

    with pytest.raises(RuntimeError, match="CONTROL_NO_MATCH:if"):
        asyncio.run(graph.run(ACGExecutionState(runId="run-1"), execute))
