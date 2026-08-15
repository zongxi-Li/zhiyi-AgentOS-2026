"""管理紧凑且带版本的工作流检查点及其审计引用。"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

from contracts.workflow import Checkpoint, WorkflowRun


COMPACT_CHECKPOINT_VERSION = 2


def checkpoint_snapshot_hash(snapshot: Dict[str, Any]) -> str:
    """为检查点快照计算稳定的 SHA-256 十六进制摘要。

    输入按键排序并使用紧凑 JSON 编码，因此等价映射产生相同结果；不可 JSON
    编码的值转为字符串。函数不存储快照，时间与空间复杂度均随编码大小 O(n)。
    """

    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def checkpoint_trace_payload(checkpoint: Checkpoint) -> Dict[str, Any]:
    """把 ``checkpoint`` 投影为 Trace 事件所需的最小可审计字典。

    返回标识、版本、哈希和图元数据，不重复嵌入完整状态快照；若合同对象没有
    哈希则即时计算。该函数不修改检查点，复杂度由快照哈希计算决定，为 O(n)。
    """

    snapshot = checkpoint.state_snapshot
    return {
        "checkpointId": checkpoint.checkpoint_id,
        "stepId": checkpoint.step_id,
        "stepIds": list(checkpoint.step_ids or [checkpoint.step_id]),
        "snapshotVersion": checkpoint.snapshot_version,
        "snapshotHash": checkpoint.snapshot_hash
        or checkpoint_snapshot_hash(snapshot),
        "graphId": snapshot.get("graphId"),
        "graphVersion": snapshot.get("graphVersion"),
    }


class CheckpointStore:
    """在 ``WorkflowRun`` 内创建、查询紧凑且可恢复的检查点。

    存储直接使用运行对象的 ``checkpoints`` 列表，调用者负责同步同一运行上的
    并发写入。快照只保存运行图及必要投影，避免重复保存旧执行状态。
    """

    def create(
        self,
        run: WorkflowRun,
        step_id: str,
        *,
        step_ids: List[str] | None = None,
    ) -> Checkpoint:
        """为 ``step_id`` 及可选屏障步骤创建并追加一个检查点。

        返回新建的 ``Checkpoint``，其中步骤标识去重且确保包含 ``step_id``；
        同时把对象追加到 ``run.checkpoints``，这是唯一副作用。快照构造与图
        序列化规模为 O(n)，运行对象无 ``checkpoints`` 时会由合同错误上抛。
        """
        runtime_graph = run.runtime_graph
        graph_version = runtime_graph.graph_version if runtime_graph is not None else None
        graph_id = (
            runtime_graph.graph_id
            if runtime_graph is not None
            else (run.acg_blueprint or {}).get("graphId")
        )
        barrier_step_ids = list(dict.fromkeys(step_ids or [step_id]))
        if step_id not in barrier_step_ids:
            barrier_step_ids.insert(0, step_id)

        # RuntimeGraph owns node state, attempts, outputs, events, patches, and
        # branch decisions. Legacy WorkflowStep and run-level execution fields
        # are projections and must not be snapshotted a second time.
        state_snapshot: Dict[str, Any] = {
            "runId": run.run_id,
            "taskId": run.task_id,
            "workflowId": run.workflow_id,
            "status": run.status.value,
            "runtimeGraph": (
                runtime_graph.model_dump(by_alias=True, mode="json")
                if runtime_graph is not None
                else None
            ),
            "provenance": run.provenance,
            "executionState": dict(run.execution_state),
            "executionScope": (
                run.execution_scope.model_dump(by_alias=True, mode="json")
                if run.execution_scope is not None
                else None
            ),
            "workflowVersion": run.execution_state.get("workflowVersion"),
            "graphId": graph_id,
            "graphVersion": graph_version,
            "appliedPatchIds": (
                list(runtime_graph.applied_patch_ids) if runtime_graph is not None else []
            ),
            "conditionalDecisionCount": (
                len(runtime_graph.branch_decisions) if runtime_graph is not None else 0
            ),
        }
        checkpoint = Checkpoint(
            runId=run.run_id,
            stepId=step_id,
            stepIds=barrier_step_ids,
            snapshotVersion=COMPACT_CHECKPOINT_VERSION,
            snapshotHash=checkpoint_snapshot_hash(state_snapshot),
            stateSnapshot=state_snapshot,
            outputSnapshot={},
            canResume=True,
        )
        run.checkpoints.append(checkpoint)
        return checkpoint

    def find(self, run: WorkflowRun, checkpoint_id: str) -> Checkpoint:
        """在线性扫描 ``run.checkpoints`` 后返回指定检查点。

        找到时返回原合同对象而非副本；未找到时抛出带标识的 ``KeyError``，不
        创建占位检查点。时间复杂度 O(n)、额外空间 O(1)。
        """
        for checkpoint in run.checkpoints:
            if checkpoint.checkpoint_id == checkpoint_id:
                return checkpoint
        raise KeyError(f"checkpoint not found: {checkpoint_id}")

    def list(self, run: WorkflowRun) -> List[Checkpoint]:
        """按创建时间和检查点标识稳定返回运行的检查点列表。

        返回新列表，不改写 ``run.checkpoints`` 的原始顺序；排序复杂度为
        O(n log n)、额外空间 O(n)，并发修改由调用方同步。
        """
        return sorted(
            run.checkpoints,
            key=lambda checkpoint: (checkpoint.created_at, checkpoint.checkpoint_id),
        )


__all__ = [
    "COMPACT_CHECKPOINT_VERSION",
    "CheckpointStore",
    "checkpoint_snapshot_hash",
    "checkpoint_trace_payload",
]
