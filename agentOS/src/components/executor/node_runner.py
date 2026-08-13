"""AgentOS 单节点固定执行管线。

每个图节点必须按同一顺序运行：装配 ContextPack → 受限记忆检索 → 熵预算与输入合同
校验 → Agent/Tool Adapter 调用 → 输出合同与字段白名单校验 → 受控记忆/血缘登记 →
返回摘要和引用。图 State 只接收最后一步的引用，真实输入输出始终留在 AgentOS 服务边界。

第三方来源：LangGraph 1.2.10，commit d56666f7fbf0d380ad84cdf0cbe5aa48ab0cc086；
来源模块 ``libs/langgraph/langgraph/pregel``、``graph/state.py``。该实现改写为调用
AgentOS 通信、记忆、Adapter 与审计边界，不暴露 LangGraph 对象；完整 MIT 许可证见
``docs/THIRD_PARTY_NOTICES.md``。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from components.communicator import CommunicatorService
from components.communicator.contracts import ContextPack, estimate_tokens
from components.auditor.execution_audit import ExecutionAuditService
from components.memory import MemoryService
from adapters.agent_invocation import AgentInvocationAdapter
from contracts.communication import validate_contract_payload
from contracts.governance import AuditRequest
from contracts.memory import MemoryPolicy, MemoryType
from contracts.workflow import AgentTask, WorkflowDefinition, WorkflowRun, WorkflowStep
from service.agents.base import BaseAgent, AgentRunContext

from .graph import ACGExecutionState
from .value_store import ExecutionValueStore, InMemoryExecutionValueStore


class EntropyBudgetExceededError(ValueError):
    """跨步骤上下文的估算熵超过运行允许的预算，Adapter 尚未被调用。"""


class ACGNodeRunner:
    """执行固定节点管线，并仅返回可安全写入执行 State 的摘要和引用。"""

    def __init__(
        self,
        *,
        task: AgentTask,
        run: WorkflowRun,
        workflow: WorkflowDefinition,
        steps: Mapping[str, WorkflowStep],
        agents: Mapping[str, BaseAgent],
        communicator: CommunicatorService,
        memory: MemoryService,
        entropy_budget: int | None = None,
        value_store: ExecutionValueStore | None = None,
        communication_modes: Mapping[str, str] | None = None,
        upstream_step_ids: Mapping[str, tuple[str, ...]] | None = None,
        execution_audit: ExecutionAuditService | None = None,
        agent_invoker: AgentInvocationAdapter | None = None,
        model_runtime: object | None = None,
        capability_descriptors: Mapping[str, object] | None = None,
        tool_runtime: object | None = None,
    ) -> None:
        """注入本 run 冻结的服务、步骤和 Agent 解析结果；不创建外部连接。"""
        self.task = task
        self.run = run
        self.workflow = workflow
        self.steps = dict(steps)
        self.agents = dict(agents)
        self.communicator = communicator
        self.memory = memory
        self.entropy_budget = entropy_budget
        # 显式依赖受控仓库，而不是由运行器拼接伪引用。这样节点产物的归属、读取校验
        # 与不可变副本语义集中在唯一服务边界中，State 只会接触返回的字符串引用。
        self.value_store = value_store or InMemoryExecutionValueStore()
        self.communication_modes = dict(communication_modes or {})
        self.upstream_step_ids = {
            node_id: tuple(source_ids)
            for node_id, source_ids in (upstream_step_ids or {}).items()
        }
        self.execution_audit = execution_audit or ExecutionAuditService()
        self.agent_invoker = agent_invoker
        self.model_runtime = model_runtime
        self.capability_descriptors = dict(capability_descriptors or {})
        self.tool_runtime = tool_runtime

    @classmethod
    def minimal(cls, *, agent: BaseAgent, entropy_budget: int | None = None) -> "ACGNodeRunner":
        """构造测试用最小节点运行器，生产运行时应显式注入全部运行范围。"""
        task = AgentTask(taskId="task", title="ACG node")
        run = WorkflowRun(taskId=task.task_id, workflowId="workflow", domain="general", runtimeEngine="acg")
        workflow = WorkflowDefinition(workflowId="workflow", name="workflow", domain="general", intent="general", runtimeEngine="acg")
        step = WorkflowStep(stepId="one", name="one", agentName=agent.profile.agent_name)
        return cls(task=task, run=run, workflow=workflow, steps={"one": step}, agents={"one": agent}, communicator=CommunicatorService(run_id=run.run_id, task_id=task.task_id), memory=MemoryService(), entropy_budget=entropy_budget)

    async def __call__(self, step_id: str, state: ACGExecutionState) -> dict[str, Any]:
        """执行一个 Step，并返回 Pregel 轮次可消费的受控结果。

        ``routeValue`` 是条件控制节点在同轮读取的短生命周期值；执行图只会使用它来
        选择已声明分支，不会把它写入 ``ACGExecutionState`` 或 checkpoint。
        """
        step = self.steps[step_id]
        agent = self.agents[step_id]
        # State 只有摘要/引用。上游完整 slot 值必须由通信服务根据 outputRef 从受控
        # 仓库读取；运行器不能从摘要推断数据，也不能旁路仓库获取全量 Agent 输出。
        estimated_entropy = sum(estimate_tokens(summary) for summary in state.output_summaries.values())
        if self.entropy_budget is not None and estimated_entropy > self.entropy_budget:
            raise EntropyBudgetExceededError(
                f"step {step_id} estimated entropy {estimated_entropy} exceeds budget {self.entropy_budget}"
            )
        mode = self.communication_modes.get(step_id, "STRICT_CONTRACT")
        if mode == "EVENT":
            # EVENT 是纯通知：只把 outputRef 转为证据引用，绝不调用仓库读取其正文。
            # 上游列表由编译后的依赖图注入，避免无关步骤的事件引用被额外暴露。
            source_ids = self.upstream_step_ids.get(step_id, tuple(state.output_refs))
            pack = ContextPack(
                runId=state.run_id,
                stepId=step_id,
                objective=self.workflow.description,
                stepGoal=step.name,
                evidenceRefs=[
                    f"event:{state.output_refs[source_id]}"
                    for source_id in source_ids
                    if source_id in state.output_refs
                ],
                sourceStepIds=list(source_ids),
            )
        else:
            pack = self.communicator.assemble_execution_context(
                run_id=state.run_id,
                task_id=self.task.task_id,
                step_id=step_id,
                input_spec=step.input,
                upstream_refs=state.output_refs,
                value_store=self.value_store,
                objective=self.workflow.description,
                step_goal=step.name,
                token_budget=self.entropy_budget,
            )
        if pack.contract_status != "valid":
            raise ValueError(f"input contract is incomplete for {step_id}: {', '.join(pack.missing_fields)}")
        input_schema = step.input.get("schema", {}) if isinstance(step.input, dict) else {}
        validate_contract_payload(pack.data, input_schema, step_id=step_id, direction="input")
        memory_policy = self._memory_policy(step.input)
        memories = (
            self.memory.recall_for_step(
                run_id=state.run_id,
                step_id=step_id,
                query=step.name or step_id,
                memory_types=memory_policy["allowedTypes"] or None,
                limit=memory_policy["limit"],
                token_budget=memory_policy["tokenBudget"],
            )
            if memory_policy["read"]
            else []
        )
        memory_access = {
            "policyId": memory_policy["policyId"],
            "read": memory_policy["read"],
            "readCount": len(memories),
            "write": memory_policy["write"],
            "written": False,
            "allowedTypes": [item.value for item in memory_policy["allowedTypes"]],
            "limit": memory_policy["limit"],
            "tokenBudget": memory_policy["tokenBudget"],
            "tokensUsed": sum(estimate_tokens(record.content) for record in memories),
            "requireAudit": memory_policy["requireAudit"],
        }
        # 每个 Step 创建独立的受限工具视图，使并行节点的事件缓冲区彼此隔离；
        # 视图只能继承既有授权集合，不能在节点内扩大权限。
        step_tool_runtime = self.tool_runtime
        if self.tool_runtime is not None and hasattr(self.tool_runtime, "scoped"):
            allowed = getattr(self.tool_runtime, "allowed_tools", ())
            step_tool_runtime = self.tool_runtime.scoped(allowed)
        agent_context = AgentRunContext(
            task=self.task,
            run=self.run,
            workflow=self.workflow,
            step=step,
            memory=memories,
            contextPack=pack,
            toolRuntime=step_tool_runtime,
            modelRuntime=self.model_runtime,
            capabilityDescriptor=self.capability_descriptors.get(step.capability or ""),
        )
        output = (
            await self.agent_invoker.invoke(context=agent_context)
            if self.agent_invoker is not None
            else await agent.run(agent_context)
        )
        tool_events = list(output.tool_executions)
        runtime_events = getattr(step_tool_runtime, "events", None)
        if isinstance(runtime_events, list):
            tool_events.extend(runtime_events)
        payload = dict(output.output)
        validate_contract_payload(payload, step.output_spec, step_id=step_id, direction="output")
        allowed = set((step.output_spec.get("properties") or {}).keys()) if step.output_spec else set(payload)
        controlled = {key: value for key, value in payload.items() if key in allowed}
        risk_level = (output.risk_level or "").lower()
        severity_counts = {risk_level: 1} if risk_level else {}
        decision = self.execution_audit.assess_node(
            request=AuditRequest(
                requestId=f"audit:{state.run_id}:{step_id}",
                # 审计发生在持久化前，使用一次性待定引用，避免 deny 结果落入
                # 输出仓库或记忆仓库；allow/review 后再生成正式引用。
                subjectRef=f"pending:{state.run_id}:{step_id}",
                auditType="node_output",
                evidenceRefs=[f"trace:{step_id}"],
            ),
            severity_counts=severity_counts,
            memory_access=memory_access,
        )
        if decision.outcome == "deny":
            return {
                "outputSummary": output.summary or f"denied:{step_id}",
                "reviewRequired": False,
                "auditDecisionRef": decision.decision_id,
                "auditOutcome": decision.outcome,
                "modelInvocations": self._safe_model_invocations(output.model_invocations),
                "memoryAccess": memory_access,
            }

        self.communicator.record_production(step_id, controlled, agent_name=agent.profile.agent_name)
        write_policy = self._write_memory_policy(memory_policy)
        memory_record = (
            self.memory.remember_step_output(
                run_id=state.run_id,
                step_id=step_id,
                output=controlled,
                policy=write_policy,
            )
            if memory_policy["write"]
            else None
        )
        memory_access["written"] = memory_record is not None
        output_ref = self.value_store.put_output(
            run_id=state.run_id,
            step_id=step_id,
            payload=controlled,
        )
        return {
            "outputSummary": output.summary or f"completed:{step_id}",
            "contextRef": self.value_store.put_context_pack(
                run_id=state.run_id,
                step_id=step_id,
                payload=pack.model_dump(by_alias=True, mode="json"),
            ),
            "memoryRef": memory_record.memory_id if memory_record is not None else "memory:none",
            "traceRef": f"trace:{step_id}",
            "outputRef": output_ref,
            # 审计器只给出可重放的治理事实；Pregel 图在提交节点结果后决定是否中断，
            # 因此审计部件不会越权修改 WorkflowRun 或驱动图状态。
            "reviewRequired": decision.outcome == "review",
            "auditDecisionRef": decision.decision_id,
            "auditOutcome": decision.outcome,
            # 模型审计只保留已由 Agent 输出的调用元数据白名单，绝不回写 prompt、
            # 生成正文或供应商对象。Trace 投影层可直接消费该紧凑列表。
            "modelInvocations": self._safe_model_invocations(output.model_invocations),
            "toolCalls": self._safe_tool_calls(tool_events),
            "provenanceEvents": self.communicator.drain_provenance_events(),
            # 仅含策略、条数和预算统计；记忆正文始终留在 MemoryService/Store 中。
            "memoryAccess": memory_access,
            # 条件值只在当前 Pregel 轮次内供控制节点选择分支，绝不写入持久化 State。
            "routeValue": controlled,
        }

    @staticmethod
    def _safe_model_invocations(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """裁剪模型调用审计字段，避免 prompt、响应正文或任意扩展载荷进入 Trace。"""
        allowed = {"provider", "model", "latencyMs", "promptVersion", "usage"}
        return [
            {key: value for key, value in record.items() if key in allowed}
            for record in records
            if isinstance(record, dict)
        ]

    @staticmethod
    def _safe_tool_calls(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """裁剪工具调用审计字段，禁止参数正文进入执行事件。"""
        allowed = {"tool", "name", "status", "latencyMs", "errorCode"}
        result: list[dict[str, Any]] = []
        seen: set[tuple[tuple[str, str], ...]] = set()
        for record in records:
            if not isinstance(record, dict):
                continue
            safe = {key: value for key, value in record.items() if key in allowed}
            identity = tuple(sorted((key, repr(value)) for key, value in safe.items()))
            if identity not in seen:
                seen.add(identity)
                result.append(safe)
        return result

    @staticmethod
    def _memory_policy(step_input: object) -> dict[str, Any]:
        """解析已冻结的步骤记忆策略，并拒绝无法审计的错误声明。

        策略存放在 ``WorkflowStep.input.memoryPolicy``，因为它是 ACG Blueprint
        元数据同步到本次运行后的私有边界。缺失策略保持旧版本的“可读可写、十条”
        行为；不会因升级而改变历史蓝图的执行结果。
        """
        raw = step_input.get("memoryPolicy") if isinstance(step_input, dict) else None
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError("memoryPolicy must be an object")
        allowed_raw = raw.get("allowedTypes", [])
        if not isinstance(allowed_raw, list):
            raise ValueError("memoryPolicy.allowedTypes must be a list")
        try:
            allowed_types = [MemoryType(str(item)) for item in allowed_raw]
        except ValueError as exc:
            raise ValueError("memoryPolicy.allowedTypes contains an unsupported memory type") from exc
        read = raw.get("read", True)
        write = raw.get("write", True)
        require_audit = raw.get("requireAudit", False)
        if not all(isinstance(item, bool) for item in (read, write, require_audit)):
            raise ValueError("memoryPolicy read, write and requireAudit must be booleans")
        limit = raw.get("limit", 10)
        token_budget = raw.get("tokenBudget")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("memoryPolicy.limit must be an integer between 1 and 100")
        if token_budget is not None and (
            not isinstance(token_budget, int) or isinstance(token_budget, bool) or token_budget < 0
        ):
            raise ValueError("memoryPolicy.tokenBudget must be a non-negative integer or null")
        policy_id = raw.get("policyId", "default")
        if not isinstance(policy_id, str) or not policy_id:
            raise ValueError("memoryPolicy.policyId must be a non-empty string")
        return {
            "policyId": policy_id,
            "read": read,
            "write": write,
            "allowedTypes": allowed_types,
            "limit": limit,
            "tokenBudget": token_budget,
            "requireAudit": require_audit,
        }

    @staticmethod
    def _write_memory_policy(policy: Mapping[str, Any]) -> MemoryPolicy | None:
        """把步骤白名单收敛成 MemoryService 可执行的写入准入策略。"""
        allowed_types = list(policy["allowedTypes"])
        if not allowed_types:
            return None
        return MemoryPolicy(
            policyId=str(policy["policyId"]),
            allowedTypes=allowed_types,
            requireAudit=bool(policy["requireAudit"]),
        )


__all__ = ["ACGNodeRunner", "EntropyBudgetExceededError"]
