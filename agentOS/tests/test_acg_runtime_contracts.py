"""附件一动态规划层的数据合同测试。"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from core.models import (
    ACGCheckpoint,
    ACGTask,
    AgentInstance,
    EvidenceRecord,
    MemorySnapshot,
    StepExecution,
)
from core.workflow.consensus import ConsensusEngine


def test_appendix_runtime_records_serialize_all_required_fields():
    task = ACGTask(taskName="Review", userQuery="review this contract", graphId="acg-1")
    execution = StepExecution(taskId=task.task_id, stepId="step-1")
    agent = AgentInstance(taskId=task.task_id, agentId="agent-1", modelName="model")
    evidence = EvidenceRecord(
        evidenceId="evidence-1",
        taskId=task.task_id,
        producerExecutionId=execution.step_execution_id,
        content={"claim": "supported"},
        confidence=0.9,
    )
    snapshot = MemorySnapshot(taskId=task.task_id, memoryId="memory-1", content={"context": "x"})
    checkpoint = ACGCheckpoint(taskId=task.task_id, stepExecutionId=execution.step_execution_id)

    assert task.model_dump(by_alias=True)["userQuery"] == "review this contract"
    assert execution.model_dump(by_alias=True)["stepExecutionId"] == execution.step_execution_id
    assert agent.model_dump(by_alias=True)["agentInstanceId"] == agent.agent_instance_id
    assert evidence.model_dump(by_alias=True)["confidence"] == 0.9
    assert snapshot.model_dump(by_alias=True)["version"] == 1
    assert checkpoint.model_dump(by_alias=True)["checkpointType"] == "auto"


def test_consensus_engine_is_declared_without_an_execution_implementation():
    assert hasattr(ConsensusEngine, "resolve")
