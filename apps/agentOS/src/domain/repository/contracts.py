"""Repository Protocol 使 Runtime 不依赖具体数据库。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, Sequence

from contracts.identity import (
    ArtifactId,
    AttemptId,
    BlueprintId,
    MissionId,
    RunId,
    StepExecutionId,
    TaskId,
)
from domain.models import (
    AcgBlueprint,
    Attempt,
    AttemptStatus,
    Artifact,
    RunStatus,
    StepExecution,
    StepExecutionStatus,
    SemanticTask,
    Mission,
    MissionStatus,
    WorkflowRun,
)
from domain.lifecycle_projection import LifecycleProjectionEvent
from contracts.planning import TaskPlan
if TYPE_CHECKING:
    from domain.identity_graph.bindings import (
        BlueprintNodeBinding,
        ExecutionBinding,
        ProvenanceLink,
        ResourceUsageRecord,
        RunArtifactBinding,
        TaskBinding,
    )


class MissionRepository(Protocol):
    def add(self, mission: Mission) -> None: ...
    def get(self, mission_id: MissionId) -> Mission | None: ...
    def list(
        self,
        *,
        user_id: str | None = None,
        tenant_id: str | None = None,
        status: MissionStatus | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[Mission], int]: ...
    def update_status(self, mission_id: MissionId, status: MissionStatus) -> Mission: ...


class SemanticTaskRepository(Protocol):
    def add(self, task: SemanticTask) -> None: ...
    def get(self, task_id: TaskId) -> SemanticTask | None: ...
    def list_for_mission(self, mission_id: MissionId) -> list[SemanticTask]: ...


class BlueprintRepository(Protocol):
    def add(self, blueprint: AcgBlueprint) -> None: ...
    def get(self, blueprint_id: BlueprintId) -> AcgBlueprint | None: ...
    def list_for_mission(self, mission_id: MissionId) -> list[AcgBlueprint]: ...


class RunRepository(Protocol):
    def add(self, run: WorkflowRun) -> None: ...
    def get(self, run_id: RunId) -> WorkflowRun | None: ...
    def list_for_mission(self, mission_id: MissionId) -> list[WorkflowRun]: ...
    def list_for_missions(
        self, mission_ids: Sequence[MissionId]
    ) -> dict[MissionId, list[WorkflowRun]]: ...
    def update_blueprint(
        self, run_id: RunId, blueprint_id: BlueprintId, graph_version: int
    ) -> WorkflowRun: ...
    def update_status(self, run_id: RunId, status: RunStatus) -> WorkflowRun: ...
    def merge_metadata(self, run_id: RunId, metadata: dict[str, Any]) -> WorkflowRun: ...


class AttemptRepository(Protocol):
    def add(self, attempt: Attempt) -> None: ...
    def get(self, attempt_id: AttemptId) -> Attempt | None: ...
    def list_for_run(self, run_id: RunId) -> list[Attempt]: ...
    def update_status(
        self,
        attempt_id: AttemptId,
        status: AttemptStatus,
        *,
        failure_reason: str | None = None,
    ) -> Attempt: ...


class StepExecutionRepository(Protocol):
    def add(self, execution: StepExecution) -> None: ...
    def get(self, step_execution_id: StepExecutionId) -> StepExecution | None: ...
    def list_for_attempt(self, attempt_id: AttemptId) -> list[StepExecution]: ...


class TaskBindingRepository(Protocol):
    def add(self, binding: TaskBinding) -> None: ...
    def get(self, binding_id: str) -> TaskBinding | None: ...
    def find_for_task(
        self, task_id: TaskId, blueprint_id: BlueprintId
    ) -> list[TaskBinding]: ...
    def find_for_acg_node(
        self, acg_node_id: str, blueprint_id: BlueprintId
    ) -> list[TaskBinding]: ...


class BlueprintNodeBindingRepository(Protocol):
    def add(self, binding: BlueprintNodeBinding) -> None: ...
    def list_for_blueprint(self, blueprint_id: BlueprintId) -> list[BlueprintNodeBinding]: ...


class ExecutionBindingRepository(Protocol):
    def add(self, binding: ExecutionBinding) -> None: ...
    def get_for_attempt(self, attempt_id: AttemptId) -> ExecutionBinding | None: ...
    def list_for_resource(
        self, resource_id: str, *, limit: int = 10
    ) -> list["ResourceUsageRecord"]: ...


class ArtifactRepository(Protocol):
    def add(self, artifact: Artifact) -> Artifact: ...
    def get(self, artifact_id: ArtifactId) -> Artifact | None: ...
    def list_for_mission(self, mission_id: MissionId) -> list[Artifact]: ...
    def list_for_origin_run(self, run_id: RunId) -> list[Artifact]: ...
    def list_for_attempt(self, attempt_id: AttemptId) -> list[Artifact]: ...


class RunArtifactBindingRepository(Protocol):
    def add(self, binding: RunArtifactBinding) -> RunArtifactBinding: ...
    def get(self, binding_id: str) -> RunArtifactBinding | None: ...
    def list_for_run(self, run_id: RunId) -> list[RunArtifactBinding]: ...
    def list_for_artifact(self, artifact_id: ArtifactId) -> list[RunArtifactBinding]: ...
    def find_for_slot(
        self, run_id: RunId, semantic_task_key: str, artifact_key: str
    ) -> RunArtifactBinding | None: ...


class ProvenanceLinkRepository(Protocol):
    def add(self, link: ProvenanceLink) -> None: ...
    def list_from(self, source_id: str) -> list[ProvenanceLink]: ...
    def list_to(self, target_id: str) -> list[ProvenanceLink]: ...


class LifecycleProjectionEventRepository(Protocol):
    def begin(self, event: LifecycleProjectionEvent) -> LifecycleProjectionEvent: ...
    def mark_applied(self, event_id: str) -> LifecycleProjectionEvent: ...
    def mark_failed(self, event_id: str, error: str) -> LifecycleProjectionEvent: ...
    def get(self, event_id: str) -> LifecycleProjectionEvent | None: ...
    def list_unapplied(self, *, limit: int = 200) -> list[LifecycleProjectionEvent]: ...
    def stats(self) -> dict[str, Any]: ...


class RepositorySet(Protocol):
    missions: MissionRepository
    semantic_tasks: SemanticTaskRepository
    blueprints: BlueprintRepository
    runs: RunRepository
    attempts: AttemptRepository
    step_executions: StepExecutionRepository
    task_bindings: TaskBindingRepository
    blueprint_node_bindings: BlueprintNodeBindingRepository
    execution_bindings: ExecutionBindingRepository
    artifacts: ArtifactRepository
    run_artifact_bindings: RunArtifactBindingRepository
    provenance_links: ProvenanceLinkRepository
    projection_events: LifecycleProjectionEventRepository
    inbox_events: LifecycleProjectionEventRepository
    task_plans: Any

    def persist_task_plan(self, plan: TaskPlan) -> dict[str, SemanticTask]: ...

    def ensure_attempt(
        self,
        run_id: RunId,
        node_id: TaskId,
        *,
        attempt_number: int | None = None,
        attempt_id: AttemptId | None = None,
        resource_binding: dict | None = None,
    ) -> Attempt: ...

    def ensure_step_execution(
        self,
        run_id: RunId,
        node_id: TaskId,
        attempt_id: AttemptId,
        *,
        input: dict,
        step_execution_id: StepExecutionId | None = None,
    ) -> StepExecution: ...

    def finish_execution(
        self,
        step_execution_id: StepExecutionId,
        attempt_id: AttemptId,
        *,
        step_status: StepExecutionStatus,
        attempt_status: AttemptStatus,
        output: dict,
        failure_reason: str | None = None,
    ) -> tuple[StepExecution, Attempt]: ...

    def close(self) -> None: ...


__all__ = [
    "AttemptRepository",
    "ArtifactRepository",
    "BlueprintNodeBindingRepository",
    "BlueprintRepository",
    "ExecutionBindingRepository",
    "LifecycleProjectionEventRepository",
    "ProvenanceLinkRepository",
    "RepositorySet",
    "RunRepository",
    "RunArtifactBindingRepository",
    "StepExecutionRepository",
    "SemanticTaskRepository",
    "TaskBindingRepository",
    "MissionRepository",
]
