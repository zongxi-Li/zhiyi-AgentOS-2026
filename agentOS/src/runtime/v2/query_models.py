"""面向产品 API 的 AgentOS 身份查询模型。"""

from __future__ import annotations

from pydantic import Field

from contracts.execution import NodeExecutionRecord
from domain.identity_graph import ExecutionBinding, ProvenanceLink
from domain.identity_graph.contracts import ExecutionOrigin
from domain.models import AcgBlueprint, Attempt, DomainModel, StepExecution, SemanticTask, Mission, WorkflowRun


class MissionDetail(DomainModel):
    mission: Mission
    tasks: list[SemanticTask]
    blueprints: list[AcgBlueprint]
    runs: list[WorkflowRun]


class MissionRunHistory(DomainModel):
    mission_id: str = Field(alias="missionId")
    runs: list[WorkflowRun]


class AttemptDetail(DomainModel):
    attempt: Attempt
    execution_binding: ExecutionBinding | None = Field(
        default=None,
        alias="executionBinding",
    )
    executions: list[StepExecution]


class AttemptHistory(DomainModel):
    run_id: str = Field(alias="runId")
    task_id: str | None = Field(default=None, alias="taskId")
    attempts: list[AttemptDetail]


class RunExecutionNode(DomainModel):
    task: SemanticTask
    acg_node_id: str | None = Field(default=None, alias="acgNodeId")
    attempts: list[AttemptDetail]


class CompiledPackageIdentity(DomainModel):
    package_id: str = Field(alias="packageId")
    package_version: int = Field(alias="packageVersion", ge=1)
    checksum: str
    blueprint_hash: str | None = Field(default=None, alias="blueprintHash")


class RunLineage(DomainModel):
    parent_run_id: str | None = Field(default=None, alias="parentRunId")
    source_run_id: str | None = Field(default=None, alias="sourceRunId")
    rerun_reason: str | None = Field(default=None, alias="rerunReason")
    supersedes_run_id: str | None = Field(default=None, alias="supersedesRunId")
    superseded_by_run_id: str | None = Field(default=None, alias="supersededByRunId")
    source_patch_id: str | None = Field(default=None, alias="sourcePatchId")


class RunOperationalState(DomainModel):
    package: CompiledPackageIdentity | None = None
    lineage: RunLineage
    node_executions: list[NodeExecutionRecord] = Field(
        default_factory=list, alias="nodeExecutions"
    )
    control_frames: list[dict] = Field(default_factory=list, alias="controlFrames")
    communication_refs: list[str] = Field(
        default_factory=list, alias="communicationRefs"
    )
    memory_refs: list[str] = Field(default_factory=list, alias="memoryRefs")
    evidence_refs: list[str] = Field(default_factory=list, alias="evidenceRefs")
    lease_statuses: dict[str, str] = Field(default_factory=dict, alias="leaseStatuses")
    loop_iterations: dict[str, int] = Field(default_factory=dict, alias="loopIterations")
    consensus_results: dict[str, dict] = Field(
        default_factory=dict, alias="consensusResults"
    )
    debate_sessions: dict[str, dict] = Field(
        default_factory=dict, alias="debateSessions"
    )
    recovery_outcome: dict | None = Field(default=None, alias="recoveryOutcome")


class IdentityProjectionHealth(DomainModel):
    inbox_backlog: int = Field(alias="inboxBacklog", ge=0)
    inbox_failed: int = Field(alias="inboxFailed", ge=0)
    projection_backlog: int = Field(alias="projectionBacklog", ge=0)
    projection_failed: int = Field(alias="projectionFailed", ge=0)
    oldest_event_at: str | None = Field(default=None, alias="oldestEventAt")


class RunExecutionTree(DomainModel):
    run: WorkflowRun
    blueprint: AcgBlueprint
    nodes: list[RunExecutionNode]
    operational: RunOperationalState


class StepExecutionDetail(DomainModel):
    origin: ExecutionOrigin
    provenance_links: list[ProvenanceLink] = Field(alias="provenanceLinks")


class ExecutionProvenance(DomainModel):
    step_execution_id: str = Field(alias="stepExecutionId")
    outgoing: list[ProvenanceLink]
    incoming: list[ProvenanceLink]


__all__ = [
    "AttemptDetail",
    "AttemptHistory",
    "ExecutionProvenance",
    "RunExecutionNode",
    "RunExecutionTree",
    "RunLineage",
    "RunOperationalState",
    "CompiledPackageIdentity",
    "IdentityProjectionHealth",
    "StepExecutionDetail",
    "MissionDetail",
    "MissionRunHistory",
]
