"""Legacy WorkflowDefinition to ACG compatibility adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..schema import (
    ACGBlueprint, ACGEdge, AgentNode, ComplexityLevel, EdgeType, EvidenceNode,
    MemoryNode, StepNode, _node_id,
)

if TYPE_CHECKING:
    from typing import Any as WorkflowDefinition

def _complexity_from_step_count(count: int) -> ComplexityLevel:
    if count <= 3:
        return ComplexityLevel.SIMPLE
    if count <= 7:
        return ComplexityLevel.MEDIUM
    if count <= 15:
        return ComplexityLevel.COMPLEX
    return ComplexityLevel.EXTREME


# 注入认知节点的关键词规则（覆盖中英文 capability / stepId）：
# - 产生结论性内容、值得沉淀的步骤 → 注入 Memory 节点
# - 需要外部依据支撑、可审计的步骤 → 注入 Evidence 节点
_MEMORY_KEYWORDS = ("risk", "风险", "suggest", "revision", "建议", "report", "报告", "analysis", "分析", "summary", "结论")
_EVIDENCE_KEYWORDS = ("evidence", "证据", "依据", "statute", "法条", "citation")


def _matches(text: str, keywords: tuple[str, ...]) -> bool:
    low = (text or "").lower()
    return any(k in low for k in keywords)


def promote_workflow_to_acg(
    workflow: "WorkflowDefinition",
    *,
    mission_id: str | None = None,
    enrich: bool = True,
    infer_dependencies: bool = True,
) -> ACGBlueprint:
    """把线性 WorkflowDefinition 升格为 ACGBlueprint。

    - 保留 step 顺序：用每个 step 的 stepId 作为 StepNode.node_id。
    - 依赖边：按 next_step_id 串联；若无显式 next，则按声明顺序串联。
    - reviewRequired 透传到 StepNode.review_required。
    - 每个 Step 都从 WorkflowDefinition.agent_name 降级为 AgentNode + EXECUTION 边。
    - enrich=True（默认）时继续注入可选的 Memory/Evidence 认知资源：
        * 产出结论的 Step 挂 Memory 节点 + WRITE 边
        * 需外部依据的 Step 挂 Evidence 节点 + SUPPORT 边
      这些节点与边不参与就绪集调度（执行器只看 STEP + DEPENDENCY），
      因此不改变执行行为，仅丰富拓扑的认知协作语义与可视化表达。
    """
    steps = list(workflow.steps)
    blueprint = ACGBlueprint(
        missionId=mission_id,
        objective=workflow.description or workflow.name,
        complexityLevel=_complexity_from_step_count(len(steps)),
        metadata={
            "sourceWorkflowId": workflow.workflow_id,
            "sourceWorkflowVersion": workflow.version,
            "promotedFromLinear": True,
            "enriched": enrich,
            "runtimeEngine": workflow.effective_runtime_engine,
        },
    )

    for definition in steps:
        node = StepNode(
            nodeId=definition.step_id,
            name=definition.name,
            stepType="agent",
            goal=definition.name,
            capability=definition.capability,
            inputSpec=dict(definition.input),
            outputSpec=dict(definition.output_spec),
            reviewRequired=definition.review_required,
            retryLimit=definition.max_retries,
            timeout=definition.timeout,
            priority=definition.priority,
        )
        blueprint.nodes.append(node)

    # Legacy workflow-only execution infers ordering. Canonical TaskPlan callers
    # disable this and lower only Planner-authorized semantic dependencies.
    step_ids = {definition.step_id for definition in steps}
    if infer_dependencies:
        for index, definition in enumerate(steps):
            target_id = definition.next_step_id
            if target_id in ("", "done", "completed", None):
                target_id = None
            if target_id is None and index + 1 < len(steps):
                target_id = steps[index + 1].step_id
            if target_id and target_id in step_ids:
                blueprint.edges.append(
                    ACGEdge(
                        sourceId=definition.step_id,
                        targetId=target_id,
                        edgeType=EdgeType.DEPENDENCY,
                    )
                )

    # input.from 是结构化通信契约。为每个声明的数据来源创建通信边，并补齐
    # 执行依赖，保证消费者不会在生产者完成前被调度。
    for definition in steps:
        from_map = definition.input.get("from") if isinstance(definition.input, dict) else None
        if not isinstance(from_map, dict):
            continue
        for source_id, fields in from_map.items():
            if source_id not in step_ids or source_id == definition.step_id:
                continue
            data_fields = [str(field) for field in fields] if isinstance(fields, list) else []
            blueprint.edges.append(
                ACGEdge(
                    sourceId=source_id,
                    targetId=definition.step_id,
                    edgeType=EdgeType.COMMUNICATION,
                    dataFields=data_fields,
                    metadata={"contract": "input.from"},
                )
            )
            if infer_dependencies and not any(
                edge.edge_type == EdgeType.DEPENDENCY
                and edge.source_id == source_id
                and edge.target_id == definition.step_id
                for edge in blueprint.edges
            ):
                blueprint.edges.append(
                    ACGEdge(
                        sourceId=source_id,
                        targetId=definition.step_id,
                        edgeType=EdgeType.DEPENDENCY,
                        metadata={"derivedFrom": "input.from"},
                    )
                )

    _inject_agent_bindings(blueprint, steps)
    if enrich:
        _inject_cognitive_nodes(blueprint, steps)

    blueprint.touch()
    return blueprint


def _inject_agent_bindings(blueprint: ACGBlueprint, steps) -> None:
    """Lower WorkflowDefinition assignments to canonical Agent EXECUTION edges."""
    agent_nodes: dict[str, str] = {}
    for definition in steps:
        agent_name = definition.agent_name or definition.step_id
        capability = definition.capability or ""
        if agent_name not in agent_nodes:
            agent_id = f"agent::{agent_name}"
            blueprint.nodes.append(
                AgentNode(
                    nodeId=agent_id,
                    name=agent_name,
                    role=capability or agent_name,
                    capabilityTags=[capability] if capability else [],
                )
            )
            agent_nodes[agent_name] = agent_id
        elif capability:
            agent_node = blueprint.get_node(agent_nodes[agent_name])
            if capability not in agent_node.capability_tags:
                agent_node.capability_tags.append(capability)
        blueprint.edges.append(
            ACGEdge(
                sourceId=agent_nodes[agent_name],
                targetId=definition.step_id,
                edgeType=EdgeType.EXECUTION,
            )
        )


def _inject_cognitive_nodes(blueprint: ACGBlueprint, steps) -> None:
    """Inject optional Memory and Evidence nodes for a legacy workflow."""
    memory_nodes: dict[str, str] = {}
    evidence_nodes: dict[str, str] = {}

    for definition in steps:
        step_id = definition.step_id
        cap = definition.capability or ""
        sig = f"{cap} {step_id}"

        # Evidence nodes are optional cognitive enrichment.
        output_properties = (
            definition.output_spec.get("properties", {})
            if isinstance(definition.output_spec, dict)
            else {}
        )
        declares_evidence_output = any(
            field in output_properties for field in ("evidence_refs", "evidenceRefs")
        )
        if declares_evidence_output or _matches(sig, _EVIDENCE_KEYWORDS):
            ev_id = _node_id("ev")
            blueprint.nodes.append(
                EvidenceNode(
                    nodeId=ev_id,
                    name=f"证据·{definition.name}",
                    evidenceType="retrieved",
                    producerStepId=step_id,
                )
            )
            evidence_nodes[step_id] = ev_id

        # Memory nodes are optional cognitive enrichment.
        memory_policy = (
            definition.input.get("memoryPolicy", {})
            if isinstance(definition.input, dict)
            else {}
        )
        declares_memory_write = (
            isinstance(memory_policy, dict) and memory_policy.get("write") is True
        )
        if declares_memory_write or _matches(sig, _MEMORY_KEYWORDS):
            memory_type = (
                str(memory_policy.get("writeType") or "episodic")
                if declares_memory_write
                else "episodic"
            )
            mem_id = _node_id("mem")
            blueprint.nodes.append(
                MemoryNode(nodeId=mem_id, name=f"记忆·{definition.name}", memoryType=memory_type)
            )
            blueprint.edges.append(
                ACGEdge(sourceId=step_id, targetId=mem_id, edgeType=EdgeType.WRITE)
            )
            memory_nodes[step_id] = mem_id

    # READ/SUPPORT 只连接真实声明消费该生产步骤的下游节点。
    for definition in steps:
        from_map = definition.input.get("from") if isinstance(definition.input, dict) else None
        if not isinstance(from_map, dict):
            continue
        for source_id in from_map:
            if source_id in memory_nodes:
                blueprint.edges.append(
                    ACGEdge(
                        sourceId=memory_nodes[source_id],
                        targetId=definition.step_id,
                        edgeType=EdgeType.READ,
                    )
                )
            if source_id in evidence_nodes:
                blueprint.edges.append(
                    ACGEdge(
                        sourceId=evidence_nodes[source_id],
                        targetId=definition.step_id,
                        edgeType=EdgeType.SUPPORT,
                    )
                )



__all__ = ["promote_workflow_to_acg"]
