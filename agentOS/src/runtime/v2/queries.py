"""从 V2 Identity Graph 读取产品查询模型。"""

from __future__ import annotations

from .query_models import (
    AttemptDetail,
    AttemptHistory,
    CompiledPackageIdentity,
    ExecutionProvenance,
    IdentityProjectionHealth,
    RunExecutionNode,
    RunExecutionTree,
    RunLineage,
    RunOperationalState,
    StepExecutionDetail,
    TaskDetail,
    TaskRunHistory,
)
from domain.identity_graph import IdentityResolver
from domain.models import UserTaskStatus
from domain.repository import EntityNotFoundError, RepositorySet


class IdentityQueryService:
    """Phase 4 查询真源；只组合 Repository，不读取 WKN 运行快照。"""

    def __init__(self, repositories: RepositorySet) -> None:
        self.repositories = repositories
        self.resolver = IdentityResolver(repositories)

    def list_tasks(
        self,
        *,
        user_id: str | None = None,
        tenant_id: str | None = None,
        status: UserTaskStatus | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[TaskDetail], int]:
        tasks, total = self.repositories.user_tasks.list(
            user_id=user_id,
            tenant_id=tenant_id,
            status=status,
            offset=(max(1, page) - 1) * max(1, page_size),
            limit=page_size,
        )
        return ([self.get_task(task.task_id) for task in tasks], total)

    def get_task(self, task_id: str) -> TaskDetail:
        task = self.repositories.user_tasks.get(task_id)
        if task is None:
            raise EntityNotFoundError(f"UserTask not found: {task_id}")
        return TaskDetail(
            task=task,
            taskNodes=self.repositories.task_nodes.list_for_task(task_id),
            blueprints=self.repositories.blueprints.list_for_task(task_id),
            runs=self.repositories.runs.list_for_task(task_id),
        )

    def task_run_history(self, task_id: str) -> TaskRunHistory:
        self.get_task(task_id)
        return TaskRunHistory(
            taskId=task_id,
            runs=self.repositories.runs.list_for_task(task_id),
        )

    def get_attempt(self, attempt_id: str) -> AttemptDetail:
        attempt = self.repositories.attempts.get(attempt_id)
        if attempt is None:
            raise EntityNotFoundError(f"Attempt not found: {attempt_id}")
        return AttemptDetail(
            attempt=attempt,
            executionBinding=self.repositories.execution_bindings.get_for_attempt(
                attempt_id
            ),
            executions=self.repositories.step_executions.list_for_attempt(attempt_id),
        )

    def attempt_history(
        self,
        run_id: str,
        *,
        node_id: str | None = None,
    ) -> AttemptHistory:
        if self.repositories.runs.get(run_id) is None:
            raise EntityNotFoundError(f"WorkflowRun not found: {run_id}")
        attempts = self.repositories.attempts.list_for_run(run_id)
        if node_id is not None:
            attempts = [attempt for attempt in attempts if attempt.node_id == node_id]
        return AttemptHistory(
            runId=run_id,
            nodeId=node_id,
            attempts=[self.get_attempt(attempt.attempt_id) for attempt in attempts],
        )

    def run_execution_tree(self, run_id: str) -> RunExecutionTree:
        run = self.repositories.runs.get(run_id)
        if run is None:
            raise EntityNotFoundError(f"WorkflowRun not found: {run_id}")
        blueprint = self.repositories.blueprints.get(run.blueprint_id)
        if blueprint is None:
            raise EntityNotFoundError(f"AcgBlueprint not found: {run.blueprint_id}")
        attempts = self.repositories.attempts.list_for_run(run_id)
        attempts_by_node: dict[str, list[AttemptDetail]] = {}
        for attempt in attempts:
            attempts_by_node.setdefault(attempt.node_id, []).append(
                self.get_attempt(attempt.attempt_id)
            )
        nodes: list[RunExecutionNode] = []
        for task_node in self.repositories.task_nodes.list_for_task(run.task_id):
            bindings = self.repositories.task_node_bindings.find_for_task_node(
                task_node.node_id,
                run.blueprint_id,
            )
            nodes.append(RunExecutionNode(
                taskNode=task_node,
                acgNodeId=(bindings[0].acg_node_id if bindings else None),
                attempts=attempts_by_node.get(task_node.node_id, []),
            ))
        return RunExecutionTree(
            run=run,
            blueprint=blueprint,
            nodes=nodes,
            operational=self.run_operational_state(run_id),
        )

    def run_operational_state(self, run_id: str) -> RunOperationalState:
        run = self.repositories.runs.get(run_id)
        if run is None:
            raise EntityNotFoundError(f"WorkflowRun not found: {run_id}")
        metadata = dict(run.metadata or {})
        projection = dict(metadata.get("executionProjection") or {})
        package = None
        if all(metadata.get(key) is not None for key in (
            "compiledPackageId", "compiledPackageVersion", "compiledPackageChecksum"
        )):
            package = CompiledPackageIdentity(
                packageId=str(metadata["compiledPackageId"]),
                packageVersion=int(metadata["compiledPackageVersion"]),
                checksum=str(metadata["compiledPackageChecksum"]),
                blueprintHash=metadata.get("compiledPackageBlueprintHash"),
            )

        node_executions = []
        communication_refs: list[str] = []
        memory_refs: list[str] = []
        evidence_refs: list[str] = []
        for attempt in self.repositories.attempts.list_for_run(run_id):
            for execution in self.repositories.step_executions.list_for_attempt(
                attempt.attempt_id
            ):
                output = dict(execution.output or {})
                raw_record = output.get("nodeExecution")
                if isinstance(raw_record, dict):
                    from contracts.execution import NodeExecutionRecord

                    node_executions.append(NodeExecutionRecord.model_validate(raw_record))
                communication_refs.extend(
                    str(item) for item in output.get("communicationRefs") or []
                )
                evidence_refs.extend(
                    str(item) for item in output.get("evidenceRefs") or []
                )
                memory_ref = output.get("memoryRef")
                if isinstance(memory_ref, str) and memory_ref != "memory:none":
                    memory_refs.append(memory_ref)
        for value in (projection.get("memoryRefs") or {}).values():
            if isinstance(value, str) and value != "memory:none":
                memory_refs.append(value)

        lease_statuses: dict[str, str] = {}
        for item in projection.get("schedulingDecisions") or []:
            if not isinstance(item, dict):
                continue
            lease = item.get("lease")
            if isinstance(lease, dict) and lease.get("leaseId"):
                lease_statuses[str(lease["leaseId"])] = str(
                    lease.get("status") or "unknown"
                )
        return RunOperationalState(
            package=package,
            lineage=RunLineage(
                parentRunId=metadata.get("parentRunId"),
                supersedesRunId=metadata.get("supersedesRunId"),
                supersededByRunId=(
                    metadata.get("supersededByRunId")
                    or projection.get("supersededByRunId")
                ),
                sourcePatchId=metadata.get("sourcePatchId"),
            ),
            nodeExecutions=node_executions,
            controlFrames=list(projection.get("controlFrames") or []),
            communicationRefs=list(dict.fromkeys(communication_refs)),
            memoryRefs=list(dict.fromkeys(memory_refs)),
            evidenceRefs=list(dict.fromkeys(evidence_refs)),
            leaseStatuses=lease_statuses,
            loopIterations=dict(projection.get("loopIterations") or {}),
            consensusResults=dict(projection.get("consensusResults") or {}),
            debateSessions=dict(projection.get("debateSessions") or {}),
            recoveryOutcome=projection.get("recoveryOutcome"),
        )

    def projection_health(self) -> IdentityProjectionHealth:
        inbox = self.repositories.inbox_events.stats()
        projection = self.repositories.projection_events.stats()
        timestamps = [
            value
            for value in (inbox.get("oldestEventAt"), projection.get("oldestEventAt"))
            if value is not None
        ]
        return IdentityProjectionHealth(
            inboxBacklog=int(inbox.get("backlog") or 0),
            inboxFailed=int(inbox.get("failed") or 0),
            projectionBacklog=int(projection.get("backlog") or 0),
            projectionFailed=int(projection.get("failed") or 0),
            oldestEventAt=min(timestamps) if timestamps else None,
        )

    def step_execution_detail(self, step_execution_id: str) -> StepExecutionDetail:
        origin = self.resolver.resolve_execution_origin(step_execution_id)
        return StepExecutionDetail(
            origin=origin,
            provenanceLinks=self.repositories.provenance_links.list_from(
                step_execution_id
            ),
        )

    def execution_provenance(self, step_execution_id: str) -> ExecutionProvenance:
        if self.repositories.step_executions.get(step_execution_id) is None:
            raise EntityNotFoundError(
                f"StepExecution not found: {step_execution_id}"
            )
        return ExecutionProvenance(
            stepExecutionId=step_execution_id,
            outgoing=self.repositories.provenance_links.list_from(step_execution_id),
            incoming=self.repositories.provenance_links.list_to(step_execution_id),
        )


__all__ = ["IdentityQueryService"]
