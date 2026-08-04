"""记忆部件的共享数据合同与运行期工作记忆。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from contracts.memory import MemoryPolicy, MemoryQuery, MemoryRecord, MemoryType, MemoryWriteBatch


def _read(source: object, name: str, default: Any = None) -> Any:
    """同时接收合同对象与字典，避免工作记忆反向依赖运行时实现。"""
    if isinstance(source, Mapping):
        return source.get(name, source.get(name[:1].lower() + name[1:], default))
    return getattr(source, name, default)


@dataclass
class WorkingMemory:
    """一次运行内对 Agent 可见的最小工作上下文。

    此对象只保存任务输入和已经获准投递的步骤观察；持久化、召回和图状态
    仍分别属于 memory、retrieval 与 executor 部件，避免把旧工作流对象带回。
    """

    run_id: str
    task_input: dict[str, Any] = field(default_factory=dict)
    observations: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_run(cls, run: object) -> "WorkingMemory":
        """从运行快照提取已完成观察，不要求特定的旧 core 模型。"""
        raw_steps = _read(run, "steps", []) or _read(run, "nodes", []) or []
        observations: dict[str, dict[str, Any]] = {}
        for step in raw_steps:
            status = str(_read(step, "status", "")).lower()
            output = _read(step, "output", {}) or {}
            step_id = _read(step, "step_id", None) or _read(step, "stepId", None) or _read(step, "node_id", None)
            if step_id and isinstance(output, Mapping) and status in {"completed", "waiting_review", "waiting review"}:
                observations[str(step_id)] = dict(output)
        return cls(
            run_id=str(_read(run, "run_id", None) or _read(run, "runId", "")),
            task_input=dict(_read(run, "input", {}) or _read(run, "task_input", {}) or {}),
            observations=observations,
        )

    def record(self, step_id: str, output: Mapping[str, Any]) -> None:
        """写入一个步骤的输出副本，调用方后续改动不会污染历史观察。"""
        self.observations[str(step_id)] = dict(output)

    @classmethod
    def from_context_pack(cls, run: object, pack: object) -> "WorkingMemory":
        """仅采纳通信器已白名单过滤后的 source_data，禁止旁路读取上游全量输出。"""
        source_data = _read(pack, "source_data", None) or _read(pack, "sourceData", {}) or {}
        observations = {
            str(source_id): dict(data)
            for source_id, data in source_data.items()
            if isinstance(data, Mapping)
        }
        return cls(
            run_id=str(_read(run, "run_id", None) or _read(run, "runId", _read(pack, "run_id", ""))),
            task_input=dict(_read(run, "input", {}) or _read(run, "task_input", {}) or {}),
            observations=observations,
        )


__all__ = ["MemoryPolicy", "MemoryQuery", "MemoryRecord", "MemoryType", "MemoryWriteBatch", "WorkingMemory"]
