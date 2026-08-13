"""AgentOS 融合后的 StateGraph / Pregel 执行核心。

本模块将 LangGraph 1.2.10 的 StateGraph、channel 与 Pregel 超步调度思想改写为
AgentOS 内部实现。它只负责图的编译产物执行、状态通道、并行就绪集、条件路由、
审核中断及事件流；ACG 规划、通信、记忆、Agent/Tool 适配和审计仍属于各自部件。

执行状态坚持“只存引用”：完整 slot 输入、模型输出和记忆正文不进入本状态，也不会
进入 SQLite checkpoint。条件路由所需的受控输出仅在当前 Pregel 轮次短暂使用。

第三方来源：LangGraph 1.2.10，commit d56666f7fbf0d380ad84cdf0cbe5aa48ab0cc086；
来源模块 ``graph/state.py``、``channels/base.py``、``channels/last_value.py``、
``pregel``。改写说明与完整 MIT 许可证见 ``docs/THIRD_PARTY_NOTICES.md``。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ACGExecutionState(BaseModel):
    """可检查点化的引用型执行状态。

    每个字段都是恢复执行所需的最小投影：已完成/活跃/跳过步骤、摘要以及各服务返回
    的引用。真实数据只能由 CommunicatorService、MemoryService 或输出存储按引用读取，
    以避免执行器绕过字段白名单、权限和审计边界。
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    run_id: str = Field(alias="runId")
    graph_id: str | None = Field(default=None, alias="graphId")
    current_step_id: str | None = Field(default=None, alias="currentStepId")
    completed_step_ids: list[str] = Field(default_factory=list, alias="completedStepIds")
    active_step_ids: list[str] = Field(default_factory=list, alias="activeStepIds")
    skipped_step_ids: list[str] = Field(default_factory=list, alias="skippedStepIds")
    output_summaries: dict[str, str] = Field(default_factory=dict, alias="outputSummaries")
    # 节点输出正文位于 ExecutionValueStore；State 只保存该仓库生成的 outputRef，
    # 使 checkpoint 能重启调度而不会携带 slot 数据、模型响应或其它敏感正文。
    output_refs: dict[str, str] = Field(default_factory=dict, alias="outputRefs")
    context_refs: dict[str, str] = Field(default_factory=dict, alias="contextRefs")
    memory_refs: dict[str, str] = Field(default_factory=dict, alias="memoryRefs")
    trace_refs: dict[str, str] = Field(default_factory=dict, alias="traceRefs")
    checkpoint_id: str | None = Field(default=None, alias="checkpointId")
    review_payload: dict[str, Any] | None = Field(default=None, alias="reviewPayload")


class ACGChannelError(ValueError):
    """同一 Pregel 轮次对一个单值状态通道进行了非法的并发写入。"""


class ACGSuperstepError(RuntimeError):
    """一个超步内发生节点异常后，携带失败与已取消步骤标识。"""

    def __init__(
        self,
        *,
        failed_step_ids: tuple[str, ...],
        cancelled_step_ids: tuple[str, ...],
        cause: BaseException,
    ) -> None:
        self.failed_step_ids = failed_step_ids
        self.cancelled_step_ids = cancelled_step_ids
        self.cause = cause
        super().__init__(
            "ACG superstep failed: "
            f"failed={','.join(failed_step_ids)}, cancelled={','.join(cancelled_step_ids)}"
        )


class ACGStateChannel:
    """执行状态字段通道的最小抽象。

    通道在一个 Pregel 超步结束时统一接收该轮所有任务的更新。不同通道可以定义不同
    聚合语义；当前首期使用 ``ACGLastValueChannel``，即单字段每轮只能有一个写入者。
    """

    def __init__(self, key: str) -> None:
        self.key = key

    def update(self, values: Sequence[Any]) -> bool:
        raise NotImplementedError

    def get(self) -> Any:
        raise NotImplementedError


class ACGLastValueChannel(ACGStateChannel):
    """最后值通道：一个 Pregel 轮次最多接收一次更新。

    这是 LangGraph ``LastValue`` 语义的改名实现。它将并行分支对同一状态键的竞争
    明确暴露为错误，而不是依赖不稳定的完成顺序覆盖数据。
    """

    _missing = object()

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.value: Any = self._missing

    def update(self, values: Sequence[Any]) -> bool:
        if not values:
            return False
        if len(values) != 1:
            raise ACGChannelError(f"At key '{self.key}': can receive only one value per Pregel round")
        self.value = values[0]
        return True

    def get(self) -> Any:
        if self.value is self._missing:
            raise LookupError(f"channel {self.key} is empty")
        return self.value


@dataclass(frozen=True)
class ACGNodeSpec:
    """编译后仅由执行器消费的 Step/控制节点描述。

    ACG Blueprint 仍是规划权威；本对象只是把蓝图中的通信模式、审核点和条件控制
    降为调度期可直接读取的不可变元数据，绝不泄漏到 ``contracts/``。
    """

    node_id: str
    kind: Literal["step", "control"] = "step"
    communication_mode: Literal["STRICT_CONTRACT", "EVENT"] = "STRICT_CONTRACT"
    review_required: bool = False
    condition: "ACGConditionalRoute | None" = None


@dataclass(frozen=True)
class ACGConditionalRoute:
    """从 ACG ``IF`` 控制节点编译出的受限条件路由。

    ``json_pointer`` 只读取本轮节点的受控输出；不执行任意 Python 表达式。结果仅为
    一个已声明的目标节点，未被选择的兄弟分支会在状态中标记为跳过。
    """

    source_step_id: str
    json_pointer: str
    operator: str
    targets_by_case: dict[str, str]
    default_target: str | None = None

    def select(self, source_value: dict[str, Any]) -> str | None:
        """按受限操作符求值并返回一个目标节点；无匹配时使用默认目标。"""
        value: Any = source_value
        for segment in (item for item in self.json_pointer.split("/") if item):
            if not isinstance(value, dict) or segment not in value:
                value = None
                break
            value = value[segment]
        if self.operator == "BOOLEAN":
            key = "true" if bool(value) else "false"
        elif self.operator == "EXISTS":
            key = "true" if value is not None else "false"
        elif self.operator == "IN":
            key = str(value)
        else:
            key = str(value)
        return self.targets_by_case.get(key, self.default_target)


NodeRunner = Callable[[str, ACGExecutionState], Awaitable[dict[str, Any]]]


class ACGExecutionGraph:
    """编译完成的 AgentOS 执行图，采用 Pregel 的“轮次屏障”调度。

    一个超步中所有 ready Step 并发运行；只有全体结果返回后，才统一提交摘要/引用并
    计算下一批 ready 节点。这个屏障保证并行分支不因完成时序不同而改变依赖可见性。
    控制节点没有 Agent 调用：它们在超步间推进，用于条件分支、并行汇合和起止屏障。
    """

    def __init__(
        self,
        *,
        nodes: tuple[str, ...],
        edges: tuple[tuple[str, str], ...] = (),
        node_specs: dict[str, ACGNodeSpec] | None = None,
    ) -> None:
        self.nodes = tuple(dict.fromkeys(nodes))
        self.edges = tuple(edges)
        self.node_specs = node_specs or {node_id: ACGNodeSpec(node_id=node_id) for node_id in self.nodes}
        known = set(self.nodes)
        if set(self.node_specs) != known or any(source not in known or target not in known for source, target in self.edges):
            raise ValueError("graph nodes and edges must be declared consistently")
        self._validate_acyclic()

    def ready_steps(self, state: ACGExecutionState) -> tuple[str, ...]:
        """返回当前超步可并发执行的 Step，排除控制节点和未选择的分支。"""
        completed = set(state.completed_step_ids)
        inactive = set(state.active_step_ids) | set(state.skipped_step_ids)
        ready: list[str] = []
        for node_id in self.nodes:
            spec = self.node_specs[node_id]
            if node_id in completed or node_id in inactive or spec.kind != "step":
                continue
            predecessors = {source for source, target in self.edges if target == node_id}
            if predecessors <= completed:
                ready.append(node_id)
        return tuple(ready)

    def select_routes(self, control_id: str, source_value: dict[str, Any]) -> tuple[str, ...]:
        """供调试和编译测试读取某个条件控制节点的目标分支。"""
        route = self.node_specs[control_id].condition
        if route is None:
            return ()
        target = route.select(source_value)
        return (target,) if target else ()

    def _advance_controls(
        self,
        state: ACGExecutionState,
        route_values: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """推进满足前驱条件的控制节点，并根据路由结果标记跳过分支。"""
        completed = set(state.completed_step_ids)
        skipped = set(state.skipped_step_ids)
        changed = True
        while changed:
            changed = False
            for control_id, spec in self.node_specs.items():
                if spec.kind != "control" or control_id in completed:
                    continue
                predecessors = {source for source, target in self.edges if target == control_id}
                effective_predecessors = predecessors - skipped
                if not effective_predecessors <= completed:
                    continue
                if spec.condition is not None:
                    value = (route_values or {}).get(spec.condition.source_step_id, {})
                    target = spec.condition.select(value)
                    if target is not None:
                        branch_targets = {target_id for source, target_id in self.edges if source == control_id}
                        skipped.update(branch_targets - {target})
                state.completed_step_ids.append(control_id)
                completed.add(control_id)
                changed = True
        state.skipped_step_ids = [node_id for node_id in self.nodes if node_id in skipped]

    async def run(self, state: ACGExecutionState, execute: NodeRunner) -> ACGExecutionState:
        """执行至完成或审核中断；调用方应持久化每个流事件对应的状态。"""
        async for _ in self.astream(state, execute):
            pass
        return state

    async def resume(self, state: ACGExecutionState, command: Any, execute: NodeRunner) -> ACGExecutionState:
        """消费同 runId 的审核恢复命令，并从已持久化的状态继续而不重跑审核步骤。"""
        command_run_id = getattr(command, "run_id", None)
        if command_run_id != state.run_id:
            raise ValueError("resume command runId does not match execution state")
        if state.review_payload is None:
            raise ValueError("execution state is not waiting for review")
        state.review_payload = None
        return await self.run(state, execute)

    async def astream_after_resume(self, state: ACGExecutionState, command: Any, execute: NodeRunner):
        """消费恢复命令后继续产生事件流，避免 Runtime 需要绕过图的审核语义。"""
        command_run_id = getattr(command, "run_id", None)
        if command_run_id != state.run_id:
            raise ValueError("resume command runId does not match execution state")
        if state.review_payload is None:
            raise ValueError("execution state is not waiting for review")
        state.review_payload = None
        async for event in self.astream(state, execute):
            yield event

    async def astream(self, state: ACGExecutionState, execute: NodeRunner):
        """产生 AgentOS 事件字典，供 runtime/auditor 投影为既有 TraceEvent。"""
        route_values: dict[str, dict[str, Any]] = {}
        self._advance_controls(state, route_values)
        while len(set(state.completed_step_ids) | set(state.skipped_step_ids)) < len(self.nodes):
            ready = self.ready_steps(state)
            if not ready:
                raise RuntimeError("execution graph has no schedulable step nodes")
            yield {"type": "nodes_scheduled", "stepIds": list(ready)}
            state.active_step_ids = list(ready)
            state.current_step_id = ready[0] if len(ready) == 1 else None
            tasks = {
                step_id: asyncio.create_task(execute(step_id, state), name=f"acg:{state.run_id}:{step_id}")
                for step_id in ready
            }
            done, pending = await asyncio.wait(tasks.values(), return_when=asyncio.FIRST_EXCEPTION)
            failures = [
                step_id
                for step_id, task in tasks.items()
                if task.done() and not task.cancelled() and task.exception() is not None
            ]
            if failures:
                # 整个超步是原子提交边界：即使某个兄弟任务恰好先返回，它的结果也
                # 不能被提交。因此除失败节点外的所有兄弟均投影为 cancelled，未完成
                # 的任务再实际发送取消信号，避免调度时序影响最终状态。
                cancelled = [step_id for step_id in ready if step_id not in failures]
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                state.active_step_ids = []
                cause = tasks[failures[0]].exception()
                assert cause is not None
                yield {
                    "type": "superstep_failed",
                    "failedStepIds": failures,
                    "cancelledStepIds": cancelled,
                }
                raise ACGSuperstepError(
                    failed_step_ids=tuple(failures),
                    cancelled_step_ids=tuple(cancelled),
                    cause=cause,
                ) from cause
            results = [tasks[step_id].result() for step_id in ready]
            for step_id, result in zip(ready, results):
                # 严重风险由审计器给出 deny。此时节点结果不能进入 State，也不能产生
                # outputRef、memoryRef 或下游调度条件；Runtime 会将该异常收敛为失败。
                if result.get("auditOutcome") == "deny":
                    raise RuntimeError(
                        f"execution denied at {step_id}: {result.get('auditDecisionRef') or 'policy decision'}"
                    )
                if isinstance(result.get("routeValue"), dict):
                    route_values[step_id] = dict(result["routeValue"])
                if result.get("outputSummary") is not None:
                    state.output_summaries[step_id] = str(result["outputSummary"])
                if result.get("outputRef") is not None:
                    state.output_refs[step_id] = str(result["outputRef"])
                for key, destination in (("contextRef", state.context_refs), ("memoryRef", state.memory_refs), ("traceRef", state.trace_refs)):
                    if result.get(key) is not None:
                        destination[step_id] = str(result[key])
                state.completed_step_ids.append(step_id)
                yield {
                    "type": "node_completed",
                    "stepId": step_id,
                    "outputSummary": state.output_summaries.get(step_id, ""),
                    "modelInvocations": list(result.get("modelInvocations") or []),
                    "toolCalls": list(result.get("toolCalls") or []),
                }
                if self.node_specs[step_id].review_required or result.get("reviewRequired"):
                    review_payload = {
                        "stepId": step_id,
                        "traceRef": state.trace_refs.get(step_id),
                    }
                    if result.get("auditDecisionRef") is not None:
                        review_payload["auditDecisionRef"] = str(result["auditDecisionRef"])
                    state.review_payload = review_payload
                    from components.recovery.checkpoint import ExecutionInterrupt

                    raise ExecutionInterrupt("execution requires review", state.review_payload)
            state.active_step_ids = []
            self._advance_controls(state, route_values)
            yield {
                "type": "superstep_completed",
                "stepIds": list(ready),
            }
        state.current_step_id = None

    def _validate_acyclic(self) -> None:
        """在图构造时拒绝依赖环，避免运行期出现没有 ready 节点的死锁。"""
        remaining = set(self.nodes)
        predecessors = {node: {source for source, target in self.edges if target == node} for node in self.nodes}
        while remaining:
            roots = {node for node in remaining if not (predecessors[node] & remaining)}
            if not roots:
                raise ValueError("execution graph contains a cycle")
            remaining -= roots


__all__ = ["ACGChannelError", "ACGConditionalRoute", "ACGExecutionGraph", "ACGExecutionState", "ACGLastValueChannel", "ACGNodeSpec", "ACGStateChannel", "ACGSuperstepError"]
