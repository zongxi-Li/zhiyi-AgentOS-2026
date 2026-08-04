"""执行器 Facade：以合同与公开部件服务编排一个确定性批次。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from typing import Any, Protocol

from communicator import CommunicatorService
from contracts.resource import SchedulingDecision, SchedulingRequest
from memory import WorkingMemory

from .algorithms import select_maximum_batch
from .barrier import ResultBarrier
from .dispatcher import StepExecutionOutcome, StepExecutionPackage, dispatch
from .fault_injection import FaultInjector
from .graph import RuntimeAttempt, RuntimeGraph, RuntimeNode, RuntimeNodeStatus, ready_set


class SchedulerPort(Protocol):
    """执行器仅认识资源合同，具体 scheduler 仍可作为独立部件替换。"""
    def decide(self, request: SchedulingRequest) -> SchedulingDecision:
        """根据资源调度请求返回可审计决定；实现方不得在此接口隐藏执行图写入。"""
        ...


class ExecutorService:
    """执行图的单写服务，不导入旧运行时实现。

    上层持久化层在调用 ``commit`` 时持有运行锁；服务本身只修改提供的图副本，
    从而将并发工作与持久化事务明确分离。
    """

    def __init__(self, *, max_parallelism: int = 4, scheduler: SchedulerPort | None = None,
                 communicator: CommunicatorService | None = None, fault_injector: FaultInjector | None = None) -> None:
        self.max_parallelism = max(1, max_parallelism)
        self.scheduler = scheduler
        self.communicator = communicator or CommunicatorService()
        self.fault_injector = fault_injector or FaultInjector()

    def select_batch(self, graph: RuntimeGraph) -> list[RuntimeNode]:
        """计算就绪集并以资源槽位约束选择本轮最大稳定批次。"""
        candidates = select_maximum_batch(graph, graph.ready_set(), self.max_parallelism)
        if self.scheduler is None:
            return candidates
        admitted: list[RuntimeNode] = []
        for node in candidates:
            capability = str(node.spec.get("capability") or "generic")
            request = SchedulingRequest(requestId=f"schedule:{graph.run_id}:{node.node_id}:{graph.graph_version}",
                                        workloadId=node.node_id, requiredCapabilities=[capability],
                                        priority=max(0, int(node.spec.get("priority") or 0)))
            decision = self.scheduler.decide(request)
            if decision.decision == "allocated":
                node.current_binding = {**(node.current_binding or {}), "resourceId": decision.resource_id,
                                        "leaseId": decision.lease.lease_id if decision.lease else None}
                admitted.append(node)
        return admitted

    def package(self, *, graph: RuntimeGraph, node: RuntimeNode, task_id: str,
                run_input: dict[str, Any], run_snapshot: dict[str, Any]) -> StepExecutionPackage:
        """在状态改为 running 的同一临界区构造不可变执行包。"""
        node.status = RuntimeNodeStatus.RUNNING
        binding = dict(node.current_binding or {})
        attempt = RuntimeAttempt(attemptNumber=len(node.attempts) + 1, graphVersion=graph.graph_version,
                                 bindingId=str(binding.get("bindingId") or binding.get("resourceId") or node.node_id),
                                 agentName=str(binding.get("agentName") or node.spec.get("agentName") or ""))
        node.attempts.append(attempt)
        sources = [edge.source_id for edge in graph.effective_edges("communication") if edge.target_id == node.node_id]
        sources = sources or graph.dependency_sources(node.node_id)
        upstream = {source: dict(graph.get_node(source).output) for source in sources}
        return StepExecutionPackage(runId=graph.run_id, taskId=task_id, graphId=graph.graph_id,
                                    graphVersion=graph.graph_version, runtimeNodeId=node.node_id,
                                    attemptId=attempt.attempt_id, attemptNumber=attempt.attempt_number,
                                    binding=binding, nodeSpec=dict(node.spec), runInput=dict(run_input),
                                    upstreamOutputs=upstream, runSnapshot=dict(run_snapshot))

    def working_memory(self, package: StepExecutionPackage) -> WorkingMemory:
        """仅使用 memory 的公开 WorkingMemory 和 communicator 白名单上下文。"""
        input_spec = package.node_spec.get("inputSpec") or {}
        pack = self.communicator.assemble_context(run_id=package.run_id, step_id=package.runtime_node_id,
                                                  objective=str(package.context_metadata.get("objective") or ""),
                                                  input_spec=input_spec, upstream_outputs=package.upstream_outputs)
        memory = WorkingMemory(run_id=package.run_id, task_input=dict(package.run_input))
        for source_id, data in pack.source_data.items():
            memory.record(source_id, data)
        return memory

    async def execute(self, package: StepExecutionPackage,
                      handler: Callable[[StepExecutionPackage, WorkingMemory], Any | Awaitable[Any]]) -> StepExecutionOutcome:
        """执行私有快照；无论成功或异常均返回 detached outcome。"""
        started = datetime.now(timezone.utc)
        try:
            self.fault_injector.fire(package.runtime_node_id)
            value = handler(package, self.working_memory(package))
            if asyncio.iscoroutine(value): value = await value
            output = dict(value or {})
            return StepExecutionOutcome(runId=package.run_id, graphId=package.graph_id,
                                        scheduledGraphVersion=package.graph_version, runtimeNodeId=package.runtime_node_id,
                                        attemptId=package.attempt_id, status=RuntimeNodeStatus.COMPLETED.value,
                                        output=output, startedAt=started, endedAt=datetime.now(timezone.utc))
        except Exception as exc:
            return StepExecutionOutcome(runId=package.run_id, graphId=package.graph_id,
                                        scheduledGraphVersion=package.graph_version, runtimeNodeId=package.runtime_node_id,
                                        attemptId=package.attempt_id, status=RuntimeNodeStatus.FAILED.value,
                                        error=str(exc), errorType=type(exc).__name__, errorCode=type(exc).__name__,
                                        startedAt=started, endedAt=datetime.now(timezone.utc))

    def commit(self, graph: RuntimeGraph, outcomes: list[StepExecutionOutcome]) -> tuple[list[StepExecutionOutcome], list[StepExecutionOutcome]]:
        """用结果屏障原子合并整批结果并显式返回迟到/重复结果。"""
        barrier = ResultBarrier({outcome.attempt_id for outcome in outcomes})
        for outcome in outcomes: barrier.record(outcome)
        return barrier.merge(graph)

    def execute_ready(self, dependencies: Mapping[str, set[str]], completed: set[str], handlers: Mapping[str, Callable[[], Any]]) -> dict[str, Any]:
        """保留极简同步入口，供不需要运行图的本地调用方使用。"""
        return {node: dispatch(handlers[node], {}) for node in ready_set(dict(dependencies), completed) if node in handlers}


class ACGExecutor:
    """旧运行时的薄适配器；算法、包与屏障均由 ``ExecutorService`` 提供。"""
    def __init__(self, runtime: Any, *, max_parallelism: int = 4) -> None:
        self.runtime = runtime; self.service = ExecutorService(max_parallelism=max_parallelism)

    async def run(self, *, task: Any, run: Any, workflow: Any, blueprint: Any) -> Any:
        """驱动一次已准备 ACG 运行并返回同一应用层运行对象。"""
        # 应用层仍负责存储、trace 与 agent 调用；此适配器只保留跨部件入口。
        return await self._drive(task=task, run=run, workflow=workflow, blueprint=blueprint)

    async def resume(self, *, task: Any, run: Any, workflow: Any, blueprint: Any) -> Any:
        """在恢复后的图状态继续驱动 ACG 运行，不重建既有图。"""
        return await self._drive(task=task, run=run, workflow=workflow, blueprint=blueprint)

    async def _drive(self, *, task: Any, run: Any, workflow: Any, blueprint: Any) -> Any:
        del workflow, blueprint
        graph = getattr(run, "runtime_graph", None)
        if graph is None: return run
        # 新运行器不拥有 agent 协议；调用方可在 runtime 上提供公开 handler。
        handler = getattr(self.runtime, "execute_runtime_package", None)
        if handler is None: return run
        batches = self.service.select_batch(graph)
        packages = [self.service.package(graph=graph, node=node, task_id=str(getattr(task, "task_id", "")),
                                         run_input=dict(getattr(run, "input", {}) or {}),
                                         run_snapshot=run.model_dump(by_alias=True, mode="json")) for node in batches]
        outcomes = await asyncio.gather(*(self.service.execute(package, handler) for package in packages))
        self.service.commit(graph, list(outcomes))
        return run


class ACGWorkflowAdapter:
    """在应用层保留 ACG 启动/审核适配器，不把执行算法放回 core。"""
    def __init__(self, runtime: Any) -> None: self.runtime = runtime
    def new_executor(self) -> ACGExecutor:
        """创建绑定当前应用运行时的轻量执行适配器，不共享步骤状态。"""
        return ACGExecutor(self.runtime)

    async def start(self, *, task: Any, run: Any, workflow: Any) -> Any:
        """委托应用运行时启动 ACG；状态持久化和并发锁仍由运行时负责。"""
        return await self.runtime._start_acg(task=task, run=run, workflow=workflow, executor=self.new_executor())
    async def apply_review(self, decision: Any) -> Any:
        """委托应用运行时应用审核决定并返回更新后的运行投影。"""
        return await self.runtime._apply_acg_review(decision, executor=self.new_executor())


ExecutionAdapterFactory = Callable[..., ACGWorkflowAdapter]


def refresh_run_execution_projection(run: Any) -> None:
    """将图状态单向投影到应用层 run；函数以 duck typing 避免反向依赖模型。"""
    graph = getattr(run, "runtime_graph", None)
    if graph is None: return
    completed = [node.node_id for node in graph.nodes if node.node_type == "step" and node.status == RuntimeNodeStatus.COMPLETED]
    active = [node.node_id for node in graph.nodes if node.node_type == "step" and node.status == RuntimeNodeStatus.RUNNING]
    run.completed_step_ids = sorted(completed)
    run.active_step_ids = sorted(active)
    run.current_step_id = next((node.node_id for node in graph.nodes if node.node_type == "step" and node.status in {RuntimeNodeStatus.RUNNING, RuntimeNodeStatus.WAITING_REVIEW, RuntimeNodeStatus.RETRYING, RuntimeNodeStatus.FAILED}), None)

class Orchestrator:
    """应用层 Agent 调用适配器。

    它位于 executor 是因为唯一职责是把已规划步骤交给已选 Agent，
    不再把调度逻辑藏在已删除的旧工作流路径中。
    """

    def __init__(self, agent_registry: Any, capability_catalog: Any = None) -> None:
        self.agent_registry = agent_registry
        self.capability_catalog = capability_catalog
        self.model_runtime: Any = None

    def set_model_runtime(self, model_runtime: Any) -> None:
        """注入应用层拥有的模型运行时；仅替换引用，不启动外部连接。"""
        self.model_runtime = model_runtime

    def _capability_descriptor(self, capability: str | None) -> Any:
        if self.capability_catalog is None or not capability:
            return None
        try:
            return self.capability_catalog.get(capability)
        except KeyError:
            return None

    async def dispatch_agent(self, task: Any, run: Any, workflow: Any, step: Any,
                             memory: Any, context_pack: Any = None) -> tuple[Any, int]:
        """调度一个已绑定步骤；耗时测量 O(1)，不影响图拓扑或状态机。"""
        from time import perf_counter
        from agents.base import AgentRunContext
        from adapters.tool_adapter import configured_tool_runtime

        agent = self.agent_registry.resolve(
            domain=run.domain, agent_name=step.agent_name, capability=step.capability,
            allowed_agent_ids=(run.execution_scope.agent_ids if run.execution_scope else None),
        )
        tool_runtime = configured_tool_runtime()
        if tool_runtime is not None:
            tool_runtime = tool_runtime.scoped([
                name for name in agent.profile.allowed_tools
                if name not in {"web_search", "web_extract"}
            ])
        context = AgentRunContext(task=task, run=run, workflow=workflow, step=step,
                                  memory=memory, contextPack=context_pack,
                                  toolRuntime=tool_runtime, modelRuntime=self.model_runtime,
                                  capabilityDescriptor=self._capability_descriptor(step.capability))
        started = perf_counter()
        return await agent.run(context), int((perf_counter() - started) * 1000)

    def compose_final_output(self, run: Any) -> dict[str, Any]:
        """按步骤逆序选择最终答案，保证最后产物对调用方具有确定性。"""
        artifacts = {step.step_id: step.output for step in run.steps if step.output}
        final_answer = next((str(step.output[key]) for step in reversed(run.steps)
                             for key in ("final_answer", "draft") if step.output.get(key)), "")
        return {"artifacts": artifacts, **({"final_answer": final_answer} if final_answer else {})}


__all__ = ["ACGExecutor", "ACGWorkflowAdapter", "ExecutionAdapterFactory", "ExecutorService", "Orchestrator", "SchedulerPort", "refresh_run_execution_projection"]
