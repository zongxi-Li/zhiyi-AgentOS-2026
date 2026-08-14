"""AgentOS 的 Trace 投影与导出服务。

融合执行事件的投影语义改写自 LangGraph 1.2.10，upstream commit
``d56666f7fbf0d380ad84cdf0cbe5aa48ab0cc086``，来源模块
``libs/langgraph/langgraph/pregel``。本实现只把紧凑的 AgentOS 事件字典映射为
既有 ``TraceEvent``，不会向合同层暴露 LangGraph chunk、callback 或对象；版权归
LangChain, Inc.，完整 MIT 文本见 ``docs/THIRD_PARTY_NOTICES.md``。
"""


from typing import Any, Dict, List, Optional

from contracts.workflow import AgentTask, TraceEvent, TraceEventType, WorkflowRun


class TraceStore:
    """向运行或孤立任务写入内存 Trace，并提供确定性导出。

    运行事件附着在传入 ``WorkflowRun``，任务事件保存在实例私有字典；该实现
    没有锁或持久化层，跨线程/进程写入与保留策略由调用方负责。
    """

    def __init__(self):
        self._task_events: dict[str, list[TraceEvent]] = {}

    def append(
        self,
        run: WorkflowRun,
        event_type: TraceEventType,
        observation: str = "",
        step_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        duration_ms: int = 0,
    ) -> TraceEvent:
        """创建事件并原子性语义之外地追加到 ``run.trace``。

        ``duration_ms`` 会截断为非负整数，空载荷规范化为空字典；返回追加的
        ``TraceEvent``。列表追加是唯一副作用，合同构造或并发冲突错误不被吞没。
        """
        event = self.build_event(
            run,
            event_type=event_type,
            observation=observation,
            step_id=step_id,
            agent_name=agent_name,
            payload=payload,
            duration_ms=duration_ms,
        )
        run.trace.append(event)
        return event

    def build_event(
        self,
        run: WorkflowRun,
        *,
        event_type: TraceEventType,
        observation: str = "",
        step_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        duration_ms: int = 0,
    ) -> TraceEvent:
        """构造一条尚未写入运行的 Trace 事件。

        节点完成会同时产生成功、模型、工具、记忆和血缘等审计事实。先构造全部
        合同，再由 :meth:`append_batch` 一次追加，避免其中一条构造失败时留下半批
        Trace 而被恢复逻辑误认作已经投影完成。
        """
        return TraceEvent(
            runId=run.run_id,
            stepId=step_id,
            agentName=agent_name,
            eventType=event_type,
            observation=observation,
            payload=payload or {},
            durationMs=max(0, int(duration_ms)),
        )

    def append_batch(self, run: WorkflowRun, events: List[TraceEvent]) -> List[TraceEvent]:
        """整体追加已经验证的 Trace 事件，返回独立列表。

        调用方必须先完成全部事件构造；Python 列表的单次 ``extend`` 是这里的最小
        批次边界。该方法不做去重，节点恢复的去重仍由提交标识在 Runtime 层决定。
        """
        batch = list(events)
        run.trace.extend(batch)
        return batch

    def append_execution_event(self, run: WorkflowRun, event: Dict[str, Any]) -> TraceEvent:
        """将融合执行器事件投影到既有 AgentOS Trace 词表。

        执行底座只能发送紧凑字典。本方法刻意拒绝未知事件，确保上游实现内部的
        chunk、callback 或对象不会穿透到审计合同，也避免未定义事件被静默记错。
        """
        trace = self.build_execution_event(run, event)
        run.trace.append(trace)
        return trace

    def build_execution_event(self, run: WorkflowRun, event: Dict[str, Any]) -> TraceEvent:
        """将紧凑执行事件构造成尚未追加的 Trace 合同。"""
        event_type = str(event.get("type") or "")
        projection = {
            "nodes_scheduled": TraceEventType.STEP_SCHEDULED,
            "node_started": TraceEventType.STEP_STARTED,
            "node_completed": TraceEventType.STEP_SUCCEEDED,
            "interrupted": TraceEventType.REVIEW_REQUIRED,
            "checkpoint_created": TraceEventType.CHECKPOINT_CREATED,
        }.get(event_type)
        if projection is None:
            raise ValueError(f"unsupported execution event: {event_type}")
        payload = {
            key: value
            for key, value in event.items()
            if key not in {"type", "stepId", "agentName"}
        }
        return self.build_event(
            run,
            event_type=projection,
            step_id=event.get("stepId"),
            agent_name=event.get("agentName"),
            observation=event_type.replace("_", " "),
            payload=payload,
        )

    def append_task(
        self,
        task: AgentTask,
        event_type: TraceEventType,
        observation: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> TraceEvent:
        """为尚未绑定运行的 ``task`` 记录一条内存任务事件。

        返回新事件并追加到以 task_id 分组的内部列表；该事件的 runId 固定为空。
        任务被删除后应调用清理方法，且并发访问不受本类同步保护。
        """
        event = TraceEvent(
            runId=None,
            eventType=event_type,
            observation=observation,
            payload=payload or {},
        )
        self._task_events.setdefault(task.task_id, []).append(event)
        return event

    def task_events(self, task_id: str) -> List[TraceEvent]:
        """返回 ``task_id`` 的当前事件列表副本。

        未知任务返回空列表；容器副本不会影响内部列表，但其中事件对象仍共享。
        查找和复制的时间复杂度为 O(n)，其中 n 为该任务事件数。
        """
        return list(self._task_events.get(task_id, []))

    def delete_task_events(self, task_id: str) -> None:
        """删除孤立任务的全部内存事件，释放该任务占用的引用。

        未知任务是无操作；删除后事件不可由此实例恢复。该方法不影响运行 Trace，
        并发读写同一 task_id 时的先后次序由调用方负责。
        """

        self._task_events.pop(task_id, None)

    def export_json(self, run: WorkflowRun) -> Dict[str, Any]:
        """把运行 Trace 导出为仅含 JSON 兼容值的可移植字典。

        事件经 :meth:`events` 排序后序列化，返回值可供 API、审计或报告使用；
        不修改运行对象。时间和额外空间均为 O(n)。
        """

        return {
            "runId": run.run_id,
            "taskId": run.task_id,
            "workflowId": run.workflow_id,
            "domain": run.domain,
            "status": run.status.value,
            "eventCount": len(run.trace),
            "events": [event.model_dump(by_alias=True, mode="json") for event in self.events(run)],
        }

    def export_markdown(self, run: WorkflowRun) -> str:
        """渲染按时间稳定排序的人类可读 Markdown Trace 报告。

        返回以换行结尾的字符串，包含运行元数据和每个事件的关键字段，不输出
        原始载荷以避免意外泄露。函数无副作用，时间和空间复杂度均为 O(n)。
        """

        lines: List[str] = [
            f"# Workflow Trace: {run.run_id}",
            "",
            f"- Task: {run.task_id}",
            f"- Workflow: {run.workflow_id}",
            f"- Domain: {run.domain}",
            f"- Status: {run.status.value}",
            f"- Events: {len(run.trace)}",
            "",
            "## Events",
            "",
        ]
        for index, event in enumerate(self.events(run), start=1):
            created_at = event.created_at.isoformat()
            title_parts = [f"{index}. `{event.event_type.value}`", created_at]
            if event.step_id:
                title_parts.append(f"step={event.step_id}")
            if event.agent_name:
                title_parts.append(f"agent={event.agent_name}")
            lines.append(" - ".join(title_parts))
            if event.observation:
                lines.append(f"   - {event.observation}")
            if event.duration_ms:
                lines.append(f"   - durationMs: {event.duration_ms}")
        return "\n".join(lines).rstrip() + "\n"

    def events(self, run: WorkflowRun) -> List[TraceEvent]:
        """按创建时间、事件标识返回运行事件的新列表。

        原始 ``run.trace`` 顺序不会被改写；排序复杂度 O(n log n)、额外空间
        O(n)。读取期间若被并发修改，结果遵循底层列表的可见状态。
        """
        return sorted(run.trace, key=lambda event: (event.created_at, event.event_id))
