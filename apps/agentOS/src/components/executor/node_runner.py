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

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

from components.communicator import CommunicationBroker, CommunicationReader, CommunicatorService, ReliableMessage
from components.communicator.manifest import CommunicationManifest, CommunicationRule
from components.communicator.reliable import next_debate_phase
from components.communicator.contracts import ContextPack, estimate_tokens, input_revision
from components.auditor.execution_audit import ExecutionAuditService
from components.auditor.decision_store import DecisionStore, InMemoryDecisionStore
from components.memory import MemoryService, StructuredMemoryEventBuilder
from components.content import ContentManifestStore, ContentWorksetSession
from adapters.agent_invocation import AgentInvocationAdapter, AgentInvocationError
from adapters.audited_tool_runtime import AuditedToolRuntime
from adapters.resource_execution import ResourceExecutionAdapter
from contracts.communication import schema_top_level_fields, validate_contract_payload
from contracts.artifacts import canonicalize_artifact_identity, final_synthesis_output_schema
from contracts.governance import AuditRequest
from contracts.memory import MemoryPolicy, MemoryType
from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord, WorkflowDefinition, WorkflowStep
from contracts.compiled_acg import CompiledACGPackage, EvidenceManifest, MemoryManifest, SkillManifest
from contracts.execution import NodeExecutionPhase, NodeExecutionRecord
from contracts.execution_context import has_retry_evidence
from contracts.content import ContentKind
from contracts.planning import TaskImplementationBinding, TaskPlan
from service.agents.base import BaseAgent, AgentRunContext
from contracts.runtime_events import RuntimeEvent, TRANSIENT_RUNTIME_EVENT_TYPES
from runtime.live_events import runtime_event_broker

from .graph import ACGExecutionState
from .memory_input import (
    effective_memory_policy, frozen_memory_policy, memory_retrieval_identity, memory_retrieval_key,
    memory_retrieval_reference, normalize_memory_policy, validate_memory_retrieval_snapshot,
)
from .value_store import ExecutionValueStore, InMemoryExecutionValueStore


_WORKSPACE_READ_ONLY_ROLES = frozenset({"workspace_acquisition", "workspace_review", "workspace_discovery"})
_WORKSPACE_READ_ONLY_TOOLS = frozenset({"fs.read", "fs.list"})


def _workspace_read_only_step(run: RuntimeRunRecord, step: WorkflowStep) -> bool:
    """Use frozen semantic identity, never model text or generic verification."""
    if step.capability == "information_extraction" and run.execution_state.get("workspaceObservations"):
        return True
    if step.logical_role in _WORKSPACE_READ_ONLY_ROLES:
        return True
    try:
        plan = TaskPlan.model_validate(run.execution_state.get("taskPlan"))
        keys = {binding.plan_node_key for raw in run.execution_state.get("taskBindings", ())
                if (binding := TaskImplementationBinding.model_validate(raw)).acg_node_id == step.step_id}
    except (TypeError, ValueError):
        # Legacy unrelated workflows have no semantic plan/binding snapshot.
        return False
    return any(node.key in keys and (
        node.logical_role in _WORKSPACE_READ_ONLY_ROLES
        or node.metadata.get("source") in {"workspace_review", "workspace_discovery"}
        or (isinstance(node.metadata.get("taskType"), str)
            and node.metadata["taskType"] in _WORKSPACE_READ_ONLY_ROLES)
        or any(isinstance(constraint.get("workspaceReview"), dict) for constraint in node.constraints)
    ) for node in plan.nodes)


class EntropyBudgetExceededError(ValueError):
    """跨步骤上下文的估算熵超过运行允许的预算，Adapter 尚未被调用。"""


class NodeEvidenceReferenceError(ValueError):
    """An Agent result cites evidence outside its compiled evidence contract."""

    code = "OUTPUT_CONTRACT_VIOLATION"


def _safe_request_diagnostics(value: object) -> dict[str, Any]:
    """Keep bounded transport measurements, never arbitrary nested model data."""
    labels = {
        "layoutVersion": {"messages.v1", "shared-execution.v1"},
        "lengthUnit": {"characters"},
        "role": {"system", "user", "assistant", "tool", "developer", "other"},
        "segment": {"sharedPolicy", "sharedTask", "capabilityAndSchema", "nodeInput", "continuation", "message"},
        "version": {"request-budget.v1"},
        "estimator": {"json-characters-div-3.2.v1"},
        "status": {"notConfigured", "withinBudget", "exceeded"},
        "mode": {"observe", "split"},
        "workingSetMode": {"observe", "split"},
        "measurement": {"estimate"},
        "resolution": {"materialSplit", "protectedInputUnchanged"},
    }

    def select(source, fields):
        result = {}
        if not isinstance(source, dict):
            return result
        for key in fields:
            if key not in source:
                continue
            item = source[key]
            if key in labels:
                valid = isinstance(item, str) and item in labels[key]
            elif key in {"hash", "sharedPrefixHash"}:
                valid = item is None or (isinstance(item, str) and len(item) == 64
                    and all(char in "0123456789abcdef" for char in item))
            else:
                valid = item is None or (type(item) is int and item >= 0)
            if valid:
                result[key] = item
        return result

    if not isinstance(value, dict):
        return {}
    result = select(value, ("layoutVersion", "lengthUnit", "messageCount", "totalCharacters",
                            "omittedSegmentCount", "sharedPrefixHash", "sharedPrefixCharacters"))
    for name, fields in {
        "requestBudget": ("version", "estimator", "estimatedInputTokens", "status", "totalTokens",
            "outputReserveTokens", "workingSetTriggerTokens", "workingSetTargetTokens", "workingSetMode",
            "estimatedTotalTokens"),
        "workingSet": ("status", "mode", "triggerTokens", "targetTokens", "measurement", "resolution"),
    }.items():
        if isinstance(value.get(name), dict):
            result[name] = select(value[name], fields)
    if isinstance(value.get("segments"), list):
        result["segments"] = [select(item, ("index", "role", "segment", "characters", "hash"))
                              for item in value["segments"][:32] if isinstance(item, dict)]
    return result


class ACGNodeRunner:
    """执行固定节点管线，并仅返回可安全写入执行 State 的摘要和引用。"""

    def __init__(
        self,
        *,
        task: RuntimeMissionRecord,
        run: RuntimeRunRecord,
        workflow: WorkflowDefinition,
        steps: Mapping[str, WorkflowStep],
        agents: Mapping[str, BaseAgent],
        communicator: CommunicatorService,
        memory: MemoryService,
        entropy_budget: int | None = None,
        value_store: ExecutionValueStore | None = None,
        content_manifest_store: ContentManifestStore | None = None,
        communication_modes: Mapping[str, str] | None = None,
        upstream_step_ids: Mapping[str, tuple[str, ...]] | None = None,
        execution_audit: ExecutionAuditService | None = None,
        decision_store: DecisionStore | None = None,
        agent_invoker: AgentInvocationAdapter | None = None,
        resource_execution_adapters: Mapping[str, ResourceExecutionAdapter] | None = None,
        model_runtime: object | None = None,
        model_runtimes: Mapping[str, object] | None = None,
        capability_descriptors: Mapping[str, object] | None = None,
        tool_runtime: object | None = None,
        communication_broker: CommunicationBroker | None = None,
        skill_manifest: SkillManifest | None = None,
        memory_manifest: MemoryManifest | None = None,
        evidence_manifest: EvidenceManifest | None = None,
        reliable_communication_store: object | None = None,
        compiled_package: CompiledACGPackage | None = None,
        fault_hook: Callable[[str], None] | None = None,
        invocation_guard: Callable[[str, ACGExecutionState], None] | None = None,
        workflow_store: object | None = None,
    ) -> None:
        """注入本 run 冻结的服务、步骤和 Agent 解析结果；不创建外部连接。"""
        self.task = task
        self.run = run
        self.workflow_store = workflow_store
        from contracts.mission_semantic import run_intent_basis
        self.mission_intent_basis = run_intent_basis(run)
        if self.mission_intent_basis is not None:
            from runtime.planner_input_adapter import planner_input
            # Adapter-local compatibility projection, never saved as Mission state.
            self.task = task.model_copy(deep=True, update={
                "title": self.mission_intent_basis.objective,
                "input": planner_input(self.mission_intent_basis, task.input),
            })
        self.workflow = workflow
        self.steps = dict(steps)
        self.agents = dict(agents)
        self.communicator = communicator
        self.memory = memory
        self.entropy_budget = entropy_budget
        # 显式依赖受控仓库，而不是由运行器拼接伪引用。这样节点产物的归属、读取校验
        # 与不可变副本语义集中在唯一服务边界中，State 只会接触返回的字符串引用。
        self.value_store = value_store or InMemoryExecutionValueStore()
        self.content_manifest_store = content_manifest_store
        self.communication_modes = dict(communication_modes or {})
        self.upstream_step_ids = {
            node_id: tuple(source_ids)
            for node_id, source_ids in (upstream_step_ids or {}).items()
        }
        if upstream_step_ids is None:
            # Minimal runners declare their topology through input.from. They
            # use the same Broker as compiled runs and never scan all outputs.
            self.upstream_step_ids = {
                node_id: tuple(step.input.get("from", {}))
                for node_id, step in self.steps.items()
            }
        self.execution_audit = execution_audit or ExecutionAuditService()
        # 审计决定必须先于输出、记忆和提交记录落入独立真源。最小运行器使用内存
        # 实现；ExecutionRuntime 会注入可跨进程恢复的 SQLite 实现。
        self.decision_store = decision_store or InMemoryDecisionStore()
        self.agent_invoker = agent_invoker
        self.resource_execution_adapters = dict(resource_execution_adapters or {})
        self.model_runtime = model_runtime
        # 模型绑定在 ``prepare_run`` 时冻结为 step → provider/model，再由 Runtime
        # 组装为此映射。节点不会从可变 Agent Profile 读取模型配置，恢复时也不会
        # 因全局 Agent 注册表被修改而换用另一家模型。
        self.model_runtimes = dict(model_runtimes or {})
        # Filled by the scheduler decorator for each live step attempt. It is
        # deliberately separate from commitId, which remains an idempotency key.
        self.attempt_ids: dict[str, str] = {}
        self.agent_registrations: dict[str, object] = {}
        self.capability_descriptors = dict(capability_descriptors or {})
        self.tool_runtime = tool_runtime
        self.communication_broker = communication_broker
        self.skill_manifest = skill_manifest or SkillManifest()
        self.memory_manifest = memory_manifest or MemoryManifest()
        self.evidence_manifest = evidence_manifest or EvidenceManifest()
        self.reliable_communication_store = reliable_communication_store
        self.compiled_package = compiled_package
        # 仅由故障恢复测试在运行时对象上临时注入。生产装配不会设置该钩子，业务合同、
        # Blueprint 和持久化状态都不包含故障阶段或异常对象。
        self._fault_hook = fault_hook
        self.invocation_guard = invocation_guard

    @classmethod
    def minimal(
        cls,
        *,
        agent: BaseAgent,
        entropy_budget: int | None = None,
        resource_execution_adapters: Mapping[str, ResourceExecutionAdapter] | None = None,
    ) -> "ACGNodeRunner":
        """构造测试用最小节点运行器，生产运行时应显式注入全部运行范围。"""
        task = RuntimeMissionRecord(missionId="mission_000000000000", title="ACG node")
        run = RuntimeRunRecord(missionId=task.mission_id, workflowId="workflow", domain="general", runtimeEngine="acg")
        workflow = WorkflowDefinition(workflowId="workflow", name="workflow", domain="general", intent="general", runtimeEngine="acg")
        step = WorkflowStep(stepId="one", name="one", agentName=agent.profile.agent_name)
        return cls(
            task=task,
            run=run,
            workflow=workflow,
            steps={"one": step},
            agents={"one": agent},
            communicator=CommunicatorService(run_id=run.run_id, mission_id=task.mission_id),
            memory=MemoryService(),
            entropy_budget=entropy_budget,
            resource_execution_adapters=resource_execution_adapters,
        )

    async def __call__(self, step_id: str, state: ACGExecutionState) -> dict[str, Any]:
        """执行一个 Step，并返回 Pregel 轮次可消费的受控结果。

        ``routeValue`` 是条件控制节点在同轮读取的短生命周期值；执行图只会使用它来
        选择已声明分支，不会把它写入 ``ACGExecutionState`` 或 checkpoint。
        """
        step = self.steps[step_id]
        self._ensure_communication_broker(state)
        loop_path = tuple(state.loop_paths.get(step_id, ()))
        commit_id = self._commit_id(
            state.run_id, step_id, step.attempt, loop_path=loop_path,
            execution_generation=state.execution_generation,
        )
        committed = self.value_store.get_node_commit(run_id=state.run_id, commit_id=commit_id)
        if committed is not None and committed.get("stage") == "committed":
            # 重启恢复或投影中断后再次调度同一步骤时，提交记录是唯一真源。它只返回
            # 已保存的安全引用与元数据，不能重新调用 Agent、重复写记忆或制造新 Trace。
            replayed = dict(committed)
            self._publish_committed_memory(
                run_id=state.run_id,
                step_id=step_id,
                payload=replayed,
            )
            self._validate_committed_references(
                run_id=state.run_id,
                step_id=step_id,
                payload=replayed,
            )
            output_ref = replayed.get("outputRef")
            if isinstance(output_ref, str):
                # 条件值不允许进入提交记录或 checkpoint。需要路由时仅在本轮从已受控的
                # 输出引用短暂读取，之后仍由图层消费而不会持久化到执行状态。
                replayed["routeValue"] = self.value_store.get_output(
                    run_id=state.run_id,
                    output_ref=output_ref,
                )
                self._publish_advanced_communication(
                    state=state,
                    step_id=step_id,
                    output_ref=output_ref,
                    commit_id=commit_id,
                )
                if self.communication_modes.get(step_id) == "DEBATE":
                    self._advance_debate_session(
                        state=state,
                        step_id=step_id,
                        output_ref=output_ref,
                        commit_id=commit_id,
                    )
            return replayed
        agent = self.agents[step_id]
        # 先持久化 prepared，再进入 Agent/Tool 适配边界。若中断发生在外部调用期间，
        # 恢复会传递同一 commitId，外部实现可据此幂等重试；不会误认为已完成。
        self.value_store.prepare_node_commit(run_id=state.run_id, commit_id=commit_id)
        execution_record = NodeExecutionRecord(
            operationId=commit_id,
            executionInstanceId=(
                f"{state.execution_generation}:{state.run_id}:{step_id}:{step.attempt}:"
                f"{'.'.join(map(str, loop_path)) or 'root'}"
                if state.execution_generation else
                f"{state.run_id}:{step_id}:{step.attempt}:{'.'.join(map(str, loop_path)) or 'root'}"
            ),
            runId=state.run_id,
            stepId=step_id,
            attemptId=self.attempt_ids.get(
                step_id,
                f"{state.run_id}:{step_id}:{step.attempt}:"
                f"{'.'.join(map(str, loop_path)) or 'root'}",
            ),
            phase=NodeExecutionPhase.PREPARED,
            loopPath=loop_path,
        )
        execution_record = self.value_store.transition_node_execution(execution_record)
        # State 只有摘要/引用。上游完整 slot 值必须由 Broker 根据 outputRef 从受控
        # 仓库读取。entropyBudget 只表示 L1/L2 的规划与协作复杂度，不得在
        # L3 被重新解释为输入/输出 Token 上限或因上游摘要较多而拒绝执行。
        mode = self.communication_modes.get(step_id, "STRICT_CONTRACT")
        consumed_message_ids: list[str] = []
        if mode in {"EVENT", "DEBATE"}:
            # EVENT 是纯通知：只把 outputRef 转为证据引用，绝不调用仓库读取其正文。
            # 上游列表由编译后的依赖图注入，避免无关步骤的事件引用被额外暴露。
            source_ids = self.upstream_step_ids.get(step_id, ())
            pending_messages = (
                self.reliable_communication_store.pending(
                    run_id=state.run_id, consumer_step_id=step_id
                )
                if self.reliable_communication_store is not None
                else ()
            )
            consumed_message_ids = [message.message_id for message in pending_messages]
            debate_phase = ""
            if mode == "DEBATE" and self.compiled_package is not None:
                debate_rules = tuple(
                    rule for rule in self.compiled_package.communication_manifest.rules
                    if rule.consumer_step_id == step_id and rule.mode.value == "DEBATE"
                )
                if not debate_rules:
                    raise ValueError(f"DEBATE step {step_id} has no manifest rules")
                spec = debate_rules[0]
                producer_ids = {
                    message.producer_step_id for message in pending_messages
                    if message.producer_step_id in spec.participant_step_ids
                }
                if len(producer_ids) < int(spec.quorum or 0):
                    raise RuntimeError(f"DEBATE_QUORUM_UNREACHED:{step_id}")
                session = state.debate_sessions.setdefault(step_id, {
                    "round": 1,
                    "phase": "propose",
                    "maxRounds": spec.max_rounds,
                    "quorum": spec.quorum,
                    "participants": list(spec.participant_step_ids),
                    "appliedCommitIds": [],
                })
                debate_phase = str(session.get("phase") or "propose")
            pack = ContextPack(
                runId=state.run_id,
                stepId=step_id,
                objective=(self.mission_intent_basis.objective if self.mission_intent_basis is not None else self.workflow.description),
                stepGoal=step.goal or step.name,
                evidenceRefs=[
                    f"event:{state.output_refs[source_id]}"
                    for source_id in source_ids
                    if source_id in state.output_refs
                ] + [
                    (
                        f"debate:{debate_phase}:{message.artifact_ref}"
                        if mode == "DEBATE"
                        else f"event:{message.artifact_ref}"
                    )
                    for message in pending_messages
                ],
                sourceStepIds=list(source_ids),
            )
        elif mode == "BLACKBOARD":
            snapshot = state.blackboard_snapshots.get(step_id, {})
            entries = snapshot.get("entries") if isinstance(snapshot, dict) else {}
            refs = list(entries.values()) if isinstance(entries, dict) else []
            pack = ContextPack(
                runId=state.run_id,
                stepId=step_id,
                objective=(self.mission_intent_basis.objective if self.mission_intent_basis is not None else self.workflow.description),
                stepGoal=step.goal or step.name,
                evidenceRefs=[f"blackboard:{item}" for item in refs],
                sourceStepIds=list(self.upstream_step_ids.get(step_id, ())),
            )
        else:
            pack = await self._assemble_broker_context(
                state=state,
                step_id=step_id,
                step=step,
                commit_id=commit_id,
            )
            # Broker 是唯一正文读取入口；读取成功后才用已裁剪的 ContextPack 登记
            # 消费与交互血缘。账本仅封存摘要、字段名和引用，恢复会复用 commitId。
            self.communicator.record_context_consumption(pack, operation_id=commit_id)
        # Preserve the admitted input before any Agent/model invocation, so a
        # failed execution remains inspectable without publishing an output.
        # The reference belongs to the execution WAL, not committed graph state.
        context_ref = self.value_store.put_context_pack(
            run_id=state.run_id, step_id=step_id,
            payload=pack.model_dump(by_alias=True, mode="json"), operation_id=commit_id,
        )
        execution_record = self.value_store.transition_node_execution(execution_record.model_copy(update={
            "artifact_refs": {**execution_record.artifact_refs, "context": context_ref},
        }))
        if pack.contract_status != "valid":
            raise ValueError(f"input contract is incomplete for {step_id}: {', '.join(pack.missing_fields)}")
        input_schema = step.input.get("schema", {}) if isinstance(step.input, dict) else {}
        validate_contract_payload(pack.data, input_schema, step_id=step_id, direction="input")
        memory_policy = effective_memory_policy(step_id, step.input, self.memory_manifest)
        communication_reader = self._build_communication_reader(
            state=state,
            step_id=step_id,
            mode=mode,
        )
        workset_session = self._build_content_workset_session(
            state=state,
            step_id=step_id,
            step=step,
            commit_id=commit_id,
        )
        memories, retrieval_event = self._frozen_memory_retrieval(
            step=step, execution=execution_record, policy=memory_policy,
        )
        if self.value_store.get_tool_value(run_id=state.run_id, key=memory_retrieval_key(commit_id)) is not None:
            execution_record = self.value_store.transition_node_execution(execution_record.model_copy(update={
                "artifact_refs": {**execution_record.artifact_refs,
                    "memoryInput": memory_retrieval_reference(state.run_id, commit_id)},
            }))
        memory_access = {
            "policyId": memory_policy["policyId"],
            "read": memory_policy["read"],
            "readCount": len(memories),
            "retrievalMode": (
                retrieval_event.mode
                if memory_policy["read"] and retrieval_event is not None
                else "disabled"
            ),
            "retrievalFallbackReason": (
                retrieval_event.fallback_reason
                if memory_policy["read"] and retrieval_event is not None
                else None
            ),
            "hitRefs": [memory.memory_id for memory in memories],
            "write": memory_policy["write"],
            "written": False,
            "readTypes": [item.value for item in memory_policy["readTypes"]],
            "writeType": (
                memory_policy["writeType"].value
                if memory_policy["writeType"] is not None
                else None
            ),
            "limit": memory_policy["limit"],
            "tokenBudget": memory_policy["tokenBudget"],
            "tokensUsed": sum(estimate_tokens(record.content) for record in memories),
            "requireAudit": memory_policy["requireAudit"],
        }
        # Ordinary nodes retain the Runtime's native catalog. Acquisition and
        # repository review are read-only semantic stages: enforce that scope
        # before binding context or exposing tools to any Agent implementation.
        step_tool_runtime = self.tool_runtime
        if step_tool_runtime is not None:
            discover = getattr(step_tool_runtime, "list_tools", None)
            allowed = set(getattr(step_tool_runtime, "allowed_tools", ()))
            if callable(discover):
                allowed.update(tool.name for tool in discover())
            if not isinstance(step_tool_runtime, AuditedToolRuntime):
                step_tool_runtime = AuditedToolRuntime(delegate=step_tool_runtime, allowed_tools=allowed)
            readonly = _workspace_read_only_step(self.run, step)
            if readonly:
                allowed.intersection_update(_WORKSPACE_READ_ONLY_TOOLS)
            step_tool_runtime = step_tool_runtime.scoped(allowed, allow_unstructured_run=not readonly)
        from runtime.execution_guidance import bind_execution_guidance
        guidance, guidance_reader = bind_execution_guidance(workflow_store=self.workflow_store,
            run=self.run, step_id=step_id, commit_id=commit_id, value_store=self.value_store,
            legacy_execution=committed is not None)
        from contracts.execution_guidance import execution_guidance_reference
        execution_record = self.value_store.transition_node_execution(execution_record.model_copy(update={
            "artifact_refs": {**execution_record.artifact_refs,
                "executionGuidance": execution_guidance_reference(state.run_id, commit_id)},
        }))
        agent_context = AgentRunContext(
            task=self.task,
            run=self.run,
            workflow=self.workflow,
            step=step,
            memory=memories,
            missionIntentBasis=self.mission_intent_basis,
            contextPack=pack,
            communicationReader=communication_reader,
            contentWorksetSession=workset_session,
            toolRuntime=step_tool_runtime,
            modelRuntime=self.model_runtimes.get(step_id, self.model_runtime),
            capabilityDescriptor=self.capability_descriptors.get(step.capability or ""),
            commitId=commit_id,
            attemptId=execution_record.attempt_id,
            agentRegistration=self.agent_registrations.get(step_id),
            executionGuidance=guidance,
            executionGuidanceReader=guidance_reader,
        )
        if hasattr(step_tool_runtime, 'bind_context'):
            guard = (lambda: self.invocation_guard(step_id, state)) if self.invocation_guard else None
            step_tool_runtime = step_tool_runtime.bind_context(agent_context, guard)
            agent_context.tool_runtime = step_tool_runtime
        await runtime_event_broker.publish(
            state.run_id,
            RuntimeEvent(eventType="node.started", runId=state.run_id, nodeId=step_id,
                         attemptId=self.attempt_ids.get(step_id) or commit_id or step_id, sequence=0,
                         payload={"nodeTitle": step.name, "agentName": agent.profile.agent_name,
                                  "contextRef": context_ref,
                                  **({"memoryInputRef": execution_record.artifact_refs["memoryInput"]}
                                     if "memoryInput" in execution_record.artifact_refs else {}),
                                  **({"agentRegistration": agent_context.agent_registration.model_dump(by_alias=True, mode="json")}
                                     if agent_context.agent_registration else {})}),
        )
        resource_adapter = self.resource_execution_adapters.get(step_id)
        # Provider connection failures are transient and can happen after the
        # scheduler has already allocated the node. Retry the execution call a
        # small, bounded number of times before surfacing the node failure.
        invocation_attempt = 0
        while True:
            try:
                # Context assembly, node.started publication and retry backoff
                # may yield after Scheduler validation. Recheck immediately at
                # each Adapter invocation, including transport retries.
                if self.invocation_guard is not None:
                    self.invocation_guard(step_id, state)
                if resource_adapter is not None:
                    output = await resource_adapter.run(agent_context)
                elif self.agent_invoker is not None:
                    output = await self.agent_invoker.invoke(context=agent_context, agent=agent)
                else:
                    output = await agent.run(agent_context)
                break
            except Exception as exc:
                not_invoked = (isinstance(exc, AgentInvocationError) and exc.code == "AGENT_NOT_IN_SCOPE"
                        and resource_adapter is None and self.agent_invoker is not None
                        and self.agent_invoker.consume_not_invoked(exc, agent_context))
                permit_scope = "graphActivation" in self.run.execution_state
                retry_allowed = (bool(getattr(exc, "retryable", False))
                                 and (not permit_scope or not_invoked)
                                 and invocation_attempt < 2)
                if not_invoked and not retry_allowed:
                    # This adapter error is emitted by registry resolution
                    # before Agent.run. Keep the prepared WAL, but durably
                    # distinguish a proven non-invocation from unknown effects.
                    self.value_store.transition_node_execution(execution_record.model_copy(update={
                        "phase": NodeExecutionPhase.FAILED, "failure_code": "AGENT_NOT_IN_SCOPE",
                    }))
                # Once an Agent has been entered, a generic retryable flag
                # cannot prove that repeating its external effects is safe.
                if not retry_allowed:
                    raise
                invocation_attempt += 1
                await asyncio.sleep(min(2.0, 0.5 * (2 ** (invocation_attempt - 1))))
        final_attempt_id = getattr(agent_context.model_runtime, "last_attempt_id", None)
        if isinstance(final_attempt_id, str) and final_attempt_id:
            self.attempt_ids[step_id] = final_attempt_id
        # A completed tool action has its own receipt. Accept the candidate's
        # schema and citation identities before settling its output for audit.
        payload = dict(output.output)
        validate_contract_payload(
            payload,
            final_synthesis_output_schema(step.output_spec, step.logical_role),
            step_id=step_id,
            direction="output",
        )
        allowed = set(schema_top_level_fields(step.output_spec)) if step.output_spec else set(payload)
        controlled = {key: value for key, value in payload.items() if key in allowed}
        evidence_refs = list(output.evidence_refs)
        for key in ("evidence_refs", "evidenceRefs"):
            if isinstance(controlled.get(key), list):
                evidence_refs.extend(controlled[key])
        evidence_refs = list(dict.fromkeys(str(item) for item in evidence_refs if str(item).strip()))
        allowed_evidence_refs = set()
        if self.evidence_manifest.for_step(step_id, "produce"):
            allowed_evidence_refs.update(
                str(source["citationId"]) for source in output.sources if source.get("citationId")
            )
        if self.evidence_manifest.for_step(step_id, "consume"):
            allowed_evidence_refs.update(pack.evidence_refs)
        if set(evidence_refs) - allowed_evidence_refs:
            raise NodeEvidenceReferenceError(f"step {step_id} produced unauthorized evidence references")

        execution_record = self.value_store.transition_node_execution(
            execution_record.model_copy(update={"phase": NodeExecutionPhase.EXECUTED})
        )
        if communication_reader is not None:
            for index, dynamic_pack in enumerate(communication_reader.drain_packs()):
                # 每次补读都有独立角色键；节点重放时相同提交标识会复用血缘记录，
                # 不会把多次合法读取错误合并成同一次消费。
                self.communicator.record_context_consumption(
                    dynamic_pack,
                    operation_id=f"{commit_id}:dynamic:{index}",
                )
        if self.communication_broker is not None:
            state.communication_usage = self.communication_broker.usage_snapshot()
        tool_events = list(output.tool_executions)
        historical_tool_events = []
        if self.run.execution_state.get("retryEvidenceContextVersion") == 1 and has_retry_evidence(agent_context):
            collect_previous = getattr(step_tool_runtime, "previous_attempt_observations", None)
            if not callable(collect_previous):
                raise ValueError("retry evidence requires its bound collector before result commit")
            for item in await collect_previous(agent_context):
                record = item.get("record") or {}
                if record.get("tool") not in {"fs.read", "fs.list"} or record.get("status") != "completed":
                    continue
                if (record.get("runId") != state.run_id or record.get("stepId") != step_id
                        or record.get("commitId") == commit_id):
                    raise ValueError("historical tool evidence differs from the current node's prior Attempt")
                historical_tool_events.append(record)
        runtime_events = getattr(step_tool_runtime, "events", None)
        if isinstance(runtime_events, list):
            tool_events.extend(runtime_events)
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
        self._require_audit_decision(decision)
        self.decision_store.save(run_id=state.run_id, step_id=step_id, decision=decision)
        persisted_decision = self.decision_store.assert_decision(
            run_id=state.run_id,
            step_id=step_id,
            decision_ref=decision.decision_id,
            outcomes={decision.outcome},
        )
        execution_record = self.value_store.transition_node_execution(
            execution_record.model_copy(update={
                "phase": (
                    NodeExecutionPhase.WAITING_REVIEW
                    if persisted_decision.outcome == "review"
                    else NodeExecutionPhase.AUDITED
                ),
                "audit_ref": persisted_decision.decision_id,
            })
        )
        requires_review = step.requires_review or persisted_decision.outcome == "review"
        memory_event = StructuredMemoryEventBuilder.build(
            run_id=state.run_id,
            step_id=step_id,
            commit_id=commit_id,
            summary=output.summary,
            evidence_refs=evidence_refs,
            audit_outcome=persisted_decision.outcome,
            upstream_step_ids=self.upstream_step_ids.get(step_id, ()),
            field_count=len(controlled),
            model_invocation_count=len(output.model_invocations),
            tool_call_count=len(tool_events),
        )
        memory_event_payload = memory_event.model_dump(by_alias=True, mode="json")
        if persisted_decision.outcome == "deny":
            return {
                "outputSummary": output.summary or f"denied:{step_id}",
                "reviewRequired": False,
                "auditDecisionRef": persisted_decision.decision_id,
                "auditOutcome": persisted_decision.outcome,
                "modelInvocations": self._safe_model_invocations(output.model_invocations),
                "memoryAccess": memory_access,
                "memoryEvent": memory_event_payload,
            }

        if self.content_manifest_store is not None and step.capability == "artifact_generation":
            controlled = self._persist_artifact_manifest(
                run_id=state.run_id,
                step_id=step_id,
                logical_role=step.logical_role,
                controlled=controlled,
            )

        output_ref = self.value_store.put_output(
            run_id=state.run_id,
            step_id=step_id,
            payload=controlled,
            operation_id=commit_id,
        )
        self._inject_fault("after_values")
        self.communicator.record_production(
            step_id,
            controlled,
            agent_name=agent.profile.agent_name,
            operation_id=commit_id,
        )
        self._inject_fault("after_provenance")
        pending_memory: dict[str, Any] | None = None
        if persisted_decision.outcome == "allow" and not requires_review and memory_policy["write"]:
            pending_memory = {
                "outputRef": output_ref,
                "policyId": str(memory_policy["policyId"]),
                "writeType": memory_policy["writeType"].value,
                "auditDecisionRef": persisted_decision.decision_id,
                "memoryEvent": memory_event_payload,
            }
        elif requires_review and memory_policy["write"]:
            # 需要人工复核的内容只留下可校验输出引用和策略意图。正文仍在值仓库，
            # 批准前不进入正式 MemoryStore，也不产生可被下游读取的 memoryRef。
            pending_memory = {
                "outputRef": output_ref,
                "policyId": str(memory_policy["policyId"]),
                "writeType": memory_policy["writeType"].value,
                "auditDecisionRef": persisted_decision.decision_id,
                "memoryEvent": memory_event_payload,
            }
        self._inject_fault("after_memory")
        memory_access["written"] = False
        communication_reads = (
            self.communication_broker.drain_events(consumer_step_id=step_id)
            if self.communication_broker is not None
            else []
        )
        communication_refs = list(dict.fromkeys(
            str(item["outputRef"])
            for item in communication_reads
            if isinstance(item, dict) and item.get("outputRef")
        ))
        artifact_refs = {**execution_record.artifact_refs, "output": output_ref,
                         "context": context_ref, "trace": f"trace:{step_id}"}
        if pending_memory is not None and not requires_review:
            artifact_refs["memory"] = f"memory:{state.run_id}:{step_id}"
        committed_execution_record = execution_record.model_copy(update={
            "phase": NodeExecutionPhase.COMMITTED,
            "artifact_refs": artifact_refs,
            "commit_id": commit_id,
        })
        result = {
            "commitId": commit_id,
            "outputSummary": output.summary or f"completed:{step_id}",
            "contextRef": context_ref,
            "traceRef": f"trace:{step_id}",
            "outputRef": output_ref,
            # 审计器只给出可重放的治理事实；Pregel 图在提交节点结果后决定是否中断，
            # 因此审计部件不会越权修改 WorkflowRun 或驱动图状态。
            "reviewRequired": requires_review,
            "auditDecisionRef": persisted_decision.decision_id,
            "auditOutcome": persisted_decision.outcome,
            # 模型审计只保留已由 Agent 输出的调用元数据白名单，绝不回写 prompt、
            # 生成正文或供应商对象。Trace 投影层可直接消费该紧凑列表。
            "modelInvocations": self._safe_model_invocations(output.model_invocations),
            "toolCalls": self._safe_tool_calls(tool_events),
            **({"historicalToolEvidence": self._safe_tool_calls(historical_tool_events)}
               if historical_tool_events else {}),
            "provenanceEvents": self.communicator.drain_provenance_events(step_id=step_id),
            # Broker 的读取事件只含引用、字段名、计数和通道，Runtime 会投影为安全
            # Trace；正文仍只存在于 Value Store 与当前 Agent 调用栈。
            "communicationReads": communication_reads,
            "communicationRefs": communication_refs,
            "evidenceRefs": list(dict.fromkeys(str(item) for item in evidence_refs)),
            # Artifact bodies remain in the ContentManifest/Value Store boundary;
            # lifecycle projection receives only the sealed manifest references.
            "artifacts": self._safe_artifact_descriptors(controlled),
            "nodeExecution": committed_execution_record.model_dump(
                by_alias=True, mode="json"
            ),
            # 仅含策略、条数和预算统计；记忆正文始终留在 MemoryService/Store 中。
            "memoryAccess": memory_access,
            "memoryEvent": memory_event_payload,
            # 条件值只在当前 Pregel 轮次内供控制节点选择分支，绝不写入持久化 State。
            "routeValue": controlled,
            "runtimeEvents": [
                event for event in (getattr(output, "runtime_events", []) or [])
                if event.get("eventType") not in TRANSIENT_RUNTIME_EVENT_TYPES
            ],
        }
        if not requires_review:
            result["memoryRef"] = (
                f"memory:{state.run_id}:{step_id}"
                if pending_memory is not None
                else "memory:none"
            )
        if pending_memory is not None:
            result["pendingMemory"] = pending_memory
        # 在图状态投影之前固化不可变提交边界。若后续 Runtime 在 Trace 或 checkpoint
        # 之间中断，恢复后将复用这份记录，而不是再次执行 Agent 或重复产生副作用。
        commit_record = {
            key: value
            for key, value in result.items()
            if key != "routeValue"
        }
        self.value_store.complete_node_commit(
            run_id=state.run_id,
            commit_id=commit_id,
            payload=commit_record,
        )
        await runtime_event_broker.publish(
            state.run_id,
            RuntimeEvent(eventType="node.completed", runId=state.run_id, nodeId=step_id,
                         attemptId=self.attempt_ids.get(step_id) or commit_id or step_id, sequence=0),
        )
        self._publish_committed_memory(
            run_id=state.run_id,
            step_id=step_id,
            payload=result,
        )
        self._publish_advanced_communication(
            state=state,
            step_id=step_id,
            output_ref=output_ref,
            commit_id=commit_id,
        )
        if mode == "DEBATE":
            self._advance_debate_session(
                state=state,
                step_id=step_id,
                output_ref=output_ref,
                commit_id=commit_id,
            )
        if self.reliable_communication_store is not None:
            for message_id in consumed_message_ids:
                self.reliable_communication_store.acknowledge(
                    run_id=state.run_id, message_id=message_id
                )
        self.value_store.transition_node_execution(committed_execution_record)
        return result

    def prepare_superstep(
        self, state: ACGExecutionState, ready_step_ids: tuple[str, ...]
    ) -> None:
        """Freeze advanced communication views before any sibling starts."""
        store = self.reliable_communication_store
        package = self.compiled_package
        if store is None or package is None:
            return
        for step_id in ready_step_ids:
            if self.communication_modes.get(step_id) != "BLACKBOARD":
                continue
            rules = tuple(
                rule
                for rule in package.communication_manifest.rules
                if rule.consumer_step_id == step_id and rule.mode.value == "BLACKBOARD"
            )
            partitions = tuple(dict.fromkeys(
                str(rule.partition or rule.channel) for rule in rules
            ))
            combined: dict[str, str] = {}
            versions: dict[str, int] = {}
            for partition in partitions:
                version, entries = store.blackboard_snapshot(
                    run_id=state.run_id, partition=partition
                )
                versions[partition] = version
                for key, reference in entries.items():
                    combined[f"{partition}:{key}"] = reference
            state.blackboard_snapshots[step_id] = {
                "versions": versions,
                "entries": combined,
            }

    @staticmethod
    def _advance_debate_session(
        *, state: ACGExecutionState, step_id: str, output_ref: str, commit_id: str
    ) -> None:
        session = state.debate_sessions.get(step_id)
        if not isinstance(session, dict):
            return
        applied = session.get("appliedCommitIds", [])
        if commit_id in applied:
            return
        phase = str(session.get("phase") or "propose")
        current_round = int(session.get("round") or 1)
        next_round, next_phase = next_debate_phase(current_round, phase, session.get("maxRounds"))
        session["appliedCommitIds"] = [*applied, commit_id]
        session["round"], session["phase"] = next_round, next_phase
        if next_phase == "complete":
            session["resultArtifactRef"] = output_ref

    def _publish_committed_memory(
        self, *, run_id: str, step_id: str, payload: dict[str, Any]
    ) -> None:
        pending = payload.get("pendingMemory")
        if not isinstance(pending, dict):
            return
        if payload.get("auditOutcome") != "allow" or payload.get("reviewRequired"):
            return
        write_type = pending.get("writeType")
        memory_event = pending.get("memoryEvent")
        if not isinstance(write_type, str) or not isinstance(memory_event, dict):
            raise ValueError("committed pending memory intent is incomplete")
        memory_type = MemoryType(write_type)
        record = self.memory.remember_step_output(
            run_id=run_id,
            step_id=step_id,
            output=memory_event,
            memory_type=memory_type,
            policy=MemoryPolicy(
                policyId=str(pending.get("policyId") or "default"),
                allowedTypes=[memory_type],
            ),
        )
        expected = payload.get("memoryRef")
        if record is None or (expected is not None and record.memory_id != expected):
            raise ValueError("committed memory publication does not match memoryRef")
        memory_access = payload.get("memoryAccess")
        if isinstance(memory_access, dict):
            memory_access["written"] = True
        payload.pop("pendingMemory", None)

    def _publish_advanced_communication(self, *, state, step_id: str, output_ref: str, commit_id: str) -> None:
        store = self.reliable_communication_store
        if store is None or self.communication_broker is None:
            return
        rules = [
            rule for rule in self.communication_broker.manifest.rules
            if rule.producer_step_id == step_id
        ]
        package_rules = ()
        package = self.compiled_package
        if package is not None:
            package_rules = package.communication_manifest.rules
        for rule in rules:
            mode = self.communication_modes.get(rule.consumer_step_id, "STRICT_CONTRACT")
            if mode not in {"EVENT", "DEBATE", "BLACKBOARD"}:
                continue
            spec = next((item for item in package_rules if item.producer_step_id == step_id and item.consumer_step_id == rule.consumer_step_id), None)
            if mode in {"EVENT", "DEBATE"}:
                store.publish(
                    ReliableMessage(
                        message_id=f"message:{commit_id}:{rule.consumer_step_id}",
                        run_id=state.run_id,
                        producer_step_id=step_id,
                        consumer_step_id=rule.consumer_step_id,
                        artifact_ref=output_ref,
                        correlation_id=state.run_id,
                        causation_id=commit_id,
                        sequence=len(state.completed_step_ids),
                        schema_hash=str(getattr(spec, "schema_hash", "") or "0" * 64),
                    ),
                    backlog_limit=int(getattr(spec, "backlog_limit", 1000)),
                )
            else:
                partition = str(getattr(spec, "partition", None) or rule.channel)
                version, _ = store.blackboard_snapshot(run_id=state.run_id, partition=partition)
                store.blackboard_write(
                    run_id=state.run_id, partition=partition, key=step_id,
                    artifact_ref=output_ref, expected_version=version, append=True,
                )

    @staticmethod
    def _safe_model_invocations(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """裁剪模型调用审计字段，避免 prompt、响应正文或任意扩展载荷进入 Trace。"""
        allowed = {
            "provider", "model", "latencyMs", "promptVersion", "promptTemplateHash",
            "promptInstanceHash", "stablePrefixHash", "schemaHash", "kernelVersion",
            "preset", "presetVersion", "capabilityId", "capabilityPolicyVersion",
            "requestProtocolVersion", "outputProtocolVersion", "promptRendererVersion",
            "requestType", "providerFamily", "modelVersion", "streaming", "trustSummary",
            "usage", "finishReason", "capability", "outputPolicy",
            "requestedOutputTokens", "effectiveOutputTokens", "effectiveReason",
            "outputExhausted", "partIndex", "callChainId",
        }
        result = []
        for record in records:
            if not isinstance(record, dict):
                continue
            safe = {key: value for key, value in record.items() if key in allowed}
            if isinstance(record.get("requestDiagnostics"), dict):
                safe["requestDiagnostics"] = _safe_request_diagnostics(record["requestDiagnostics"])
            result.append(safe)
        return result

    @staticmethod
    def _safe_tool_calls(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """裁剪工具调用审计字段，禁止参数正文进入执行事件。"""
        allowed = {"tool", "name", "status", "latencyMs", "errorCode", "executionId", "receiptChecksum",
                   "runId", "stepId", "attemptId", "commitId", "resourceId", "bindingId", "receiptRef",
                   "requestRef", "workspaceId", "grantId"}
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
    def _memory_retrieval_query(step: WorkflowStep) -> str:
        """Recall for this work item, without feeding upstream bodies back in."""
        fields = (step.goal, step.name, *step.acceptance_criteria, *step.source_refs)
        parts = dict.fromkeys(value.strip() for value in fields if isinstance(value, str) and value.strip())
        return "\n".join(parts) or step.step_id

    def _frozen_memory_retrieval(self, *, step: WorkflowStep, execution: NodeExecutionRecord, policy):
        """Freeze admitted memory in the existing operation WAL before invocation.

        Later same-Run commits, expiry and retrieval improvements cannot change
        an already admitted model request. A new Attempt owns a new operation.
        Legacy WAL without this snapshot keeps its exact request-hash proof;
        do not write a replacement snapshot for an already admitted request.
        """
        key = memory_retrieval_key(execution.operation_id)
        identity = memory_retrieval_identity(execution)
        frozen_policy = frozen_memory_policy(policy)
        snapshot = self.value_store.get_tool_value(run_id=execution.run_id, key=key)
        if snapshot is not None:
            self.value_store.assert_reference(kind="output", run_id=execution.run_id,
                step_id=execution.step_id,
                reference=memory_retrieval_reference(execution.run_id, execution.operation_id))
        if snapshot is None:
            admitted = self.value_store.get_tool_value(run_id=execution.run_id,
                key=execution.operation_id + ":tools:0:model-turn") is not None
            records = (self.memory.recall_for_step(run_id=execution.run_id, step_id=execution.step_id,
                query=self._memory_retrieval_query(step), memory_types=policy["readTypes"] or None,
                limit=policy["limit"], token_budget=policy["tokenBudget"]) if policy["read"] else [])
            event = self.memory.last_retrieval_event if policy["read"] else None
            snapshot = {"schemaVersion": 1, "identity": identity, "policy": frozen_policy,
                "records": [record.model_dump(by_alias=True, mode="json") for record in records],
                "retrievalEvent": event.model_dump(by_alias=True, mode="json") if event else None}
            if not admitted:
                self.value_store.put_tool_value(run_id=execution.run_id, step_id=execution.step_id,
                                                key=key, payload=snapshot)
        return validate_memory_retrieval_snapshot(snapshot, execution=execution, policy=policy)

    _memory_policy = staticmethod(normalize_memory_policy)

    @staticmethod
    def _write_memory_policy(policy: Mapping[str, Any]) -> MemoryPolicy | None:
        """把步骤的单一写入类别收敛成 MemoryService 可执行的准入策略。"""
        write_type = policy["writeType"]
        if write_type is None:
            return None
        return MemoryPolicy(
            policyId=str(policy["policyId"]),
            allowedTypes=[write_type],
            requireAudit=bool(policy["requireAudit"]),
        )

    def _validate_committed_references(
        self,
        *,
        run_id: str,
        step_id: str,
        payload: Mapping[str, Any],
    ) -> None:
        """重放提交前重验其正文引用，防止损坏记录把其他步骤的数据带回图状态。"""
        output_ref = payload.get("outputRef")
        if isinstance(output_ref, str):
            self.value_store.assert_reference(
                kind="output", run_id=run_id, step_id=step_id, reference=output_ref
            )
        context_ref = payload.get("contextRef")
        if isinstance(context_ref, str):
            self.value_store.assert_reference(
                kind="context", run_id=run_id, step_id=step_id, reference=context_ref
            )
        decision_ref = payload.get("auditDecisionRef")
        outcome = payload.get("auditOutcome")
        if isinstance(decision_ref, str) and isinstance(outcome, str):
            self.decision_store.assert_decision(
                run_id=run_id,
                step_id=step_id,
                decision_ref=decision_ref,
                outcomes={outcome},
            )

    @staticmethod
    def _require_audit_decision(decision: object) -> None:
        """记忆策略要求审计时，只接受含稳定标识和受支持结果的审计决定。"""
        decision_id = getattr(decision, "decision_id", None)
        outcome = getattr(decision, "outcome", None)
        if not isinstance(decision_id, str) or not decision_id or outcome not in {"allow", "review", "deny"}:
            raise ValueError("audit decision is required before memory write")

    def _persist_artifact_manifest(
        self, *, run_id: str, step_id: str, controlled: dict[str, Any], logical_role: str = ""
    ) -> dict[str, Any]:
        """Seal artifact bodies and return only manifest references to projection."""
        raw = controlled.get("artifacts")
        if raw is None and isinstance(controlled.get("artifact"), dict):
            raw = [controlled["artifact"]]
        elif isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            return controlled
        normalized = dict(controlled)
        normalized_artifacts: list[dict[str, Any]] = []
        for raw_artifact in raw:
            if not isinstance(raw_artifact, dict):
                continue
            artifact = canonicalize_artifact_identity(raw_artifact, logical_role)
            artifact.setdefault("artifactKey", "primary")
            task = getattr(self, "task", None)
            task_input = getattr(task, "input", {})
            source_attachment_ids = [
                str(item) for item in (task_input.get("attachmentIds") or []) if str(item)
            ]
            if source_attachment_ids:
                artifact["metadata"] = {
                    **(artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}),
                    "sourceAttachmentIds": list(dict.fromkeys(source_attachment_ids)),
                }
            manifest_id = artifact.get("manifestId")
            checksum = artifact.get("checksum")
            content = artifact.get("content")
            if not (isinstance(manifest_id, str) and manifest_id and
                    isinstance(checksum, str) and checksum):
                if not isinstance(content, str) or not content:
                    normalized_artifacts.append(artifact)
                    continue
                manifest = self.content_manifest_store.create_manifest(
                    kind=ContentKind.ARTIFACT,
                    owner_type="run",
                    owner_id=run_id,
                    media_type=str(artifact.get("mediaType") or "text/markdown"),
                    chunking_version="markdown-sections.v1",
                )
                sections: list[str] = []
                current: list[str] = []
                for line in content.splitlines(keepends=True):
                    if line.startswith("## ") and current:
                        sections.append("".join(current))
                        current = []
                    current.append(line)
                if current or not sections:
                    sections.append("".join(current))
                for sequence, section in enumerate(sections):
                    self.content_manifest_store.append_fragment(
                        manifest_id=manifest.manifest_id,
                        sequence=sequence,
                        content=section.encode("utf-8"),
                        source_refs=(step_id,),
                    )
                sealed = self.content_manifest_store.seal_manifest(manifest.manifest_id)
                artifact["manifestId"] = sealed.manifest_id
                artifact["checksum"] = sealed.checksum
            normalized_artifacts.append(artifact)
        if normalized_artifacts:
            normalized["artifacts"] = normalized_artifacts
            # Keep the singular envelope for legacy consumers and existing tests.
            if isinstance(controlled.get("artifact"), dict):
                normalized["artifact"] = normalized_artifacts[0]
        return normalized

    @staticmethod
    def _safe_artifact_descriptors(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        raw = payload.get("artifacts")
        if raw is None and isinstance(payload.get("artifact"), dict):
            raw = [payload["artifact"]]
        elif isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            return []
        allowed = {
            "artifactKey", "semanticTaskKey", "name", "title", "artifactType",
            "type", "mediaType", "manifestId", "checksum", "metadata",
        }
        descriptors: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            descriptor = {
                key: item[key]
                for key in allowed
                if item.get(key) is not None
            }
            descriptor.setdefault("artifactKey", "primary")
            descriptors.append(descriptor)
        return descriptors

    @staticmethod
    def _commit_id(
        run_id: str, step_id: str, attempt: int, *, loop_path: tuple[int, ...] = (),
        execution_generation: str | None = None,
    ) -> str:
        """生成步骤尝试的稳定提交标识；重试次数变化才会开启新的副作用边界。"""
        suffix = f":loop:{'.'.join(map(str, loop_path))}" if loop_path else ""
        generation = f":generation:{execution_generation}" if execution_generation else ""
        return f"commit:{run_id}:{step_id}:{max(0, attempt)}{generation}{suffix}"

    def _inject_fault(self, stage: str) -> None:
        """执行测试专用中断钩子；未注入时是零行为的私有空操作。"""
        if self._fault_hook is not None:
            self._fault_hook(stage)

    def _ensure_communication_broker(self, state: ACGExecutionState) -> None:
        """Bind minimal runners to the same reference reader as compiled graphs."""
        if self.communication_broker is not None:
            return
        rules = []
        for consumer, source_ids in self.upstream_step_ids.items():
            step = self.steps[consumer]
            declared = step.input.get("from", {})
            for producer in source_ids:
                source = self.steps.get(producer)
                fields = declared.get(producer)
                if fields is None:
                    fields = sorted((source.output_spec.get("properties") or {})) if source else []
                if not isinstance(fields, list):
                    raise ValueError("input.from fields must be a list")
                rules.append(CommunicationRule(
                    producer_step_id=producer, consumer_step_id=consumer,
                    allowed_fields=tuple(fields), channel=f"{producer}:{consumer}",
                ))
        self.communication_broker = CommunicationBroker(
            manifest=CommunicationManifest(run_id=state.run_id, rules=tuple(rules)),
            value_store=self.value_store, usage=state.communication_usage,
        )
        state.communication_usage = self.communication_broker.usage_snapshot()

    async def _assemble_broker_context(
        self, *, state: ACGExecutionState, step_id: str, step: WorkflowStep, commit_id: str,
    ) -> ContextPack:
        """Delegate acquisition and assembly to the single communication core."""
        assert self.communication_broker is not None
        pack = await self.communication_broker.assemble_context(
            run_id=state.run_id, step_id=step_id, input_spec=step.input,
            upstream_refs=state.output_refs,
            objective=(self.mission_intent_basis.objective if self.mission_intent_basis is not None else self.workflow.description),
            step_goal=step.goal or step.name, operation_id=commit_id, graph_version=state.graph_version,
        )
        state.communication_usage = self.communication_broker.usage_snapshot()
        return pack

    def _build_communication_reader(
        self,
        *,
        state: ACGExecutionState,
        step_id: str,
        mode: str,
    ) -> CommunicationReader | None:
        """为严格通信节点创建仅能补读其直接上游的受控读取器。"""
        if self.communication_broker is None or mode != "STRICT_CONTRACT":
            return None
        source_ids = self.upstream_step_ids.get(step_id, tuple())
        output_refs = {
            source_id: state.output_refs[source_id]
            for source_id in source_ids
            if source_id in state.output_refs
        }
        from contracts.request_budget import SupplementalReadBudget
        step = self.steps[step_id]
        policy = (step.input.get("contextPolicy") or {}).get("supplementalReadBudget")
        def on_read(pack, operation_id):
            self.communicator.record_context_consumption(pack, operation_id=operation_id)
            state.communication_usage = self.communication_broker.usage_snapshot()
        return CommunicationReader(
            broker=self.communication_broker,
            run_id=state.run_id,
            consumer_step_id=step_id,
            output_refs=output_refs,
            max_tokens=None,
            model_budget=SupplementalReadBudget.model_validate(policy) if policy is not None else None,
            on_read=on_read,
        )
    def _build_content_workset_session(
        self, *, state: ACGExecutionState, step_id: str, step: WorkflowStep, commit_id: str
    ) -> ContentWorksetSession | None:
        if self.content_manifest_store is None or not isinstance(step.input, dict):
            return None
        raw = step.input.get("workset")
        if not isinstance(raw, dict):
            return None
        from contracts.content import WorksetSpec

        return ContentWorksetSession(
            store=self.content_manifest_store,
            spec=WorksetSpec.model_validate(raw),
            run_id=state.run_id,
            step_id=step_id,
            commit_id=commit_id,
        )


__all__ = ["ACGNodeRunner", "EntropyBudgetExceededError"]
