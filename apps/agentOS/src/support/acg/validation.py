"""Structural validation for ACG blueprints."""

from __future__ import annotations

from typing import Any, Dict

from .graph import (
    ConditionEvaluationError, _has_dependency_path,
    conditional_branch_exclusive_nodes, detect_cycle, find_dangling_dependencies,
)
from .schema import (
    ACGBlueprint, ACGValidationError, ControlNode, ControlType, EdgeType,
    NodeType, StepNode,
)

def check_contract_schema(schema: Dict[str, Any], *, label: str) -> None:
    """检查规划输出合同的最小形状，复杂 JSON Schema 交由适配器层扩展。

    这里保留图验证所需的安全下限，避免规划器重新依赖历史数据合同实现。
    """
    if not isinstance(schema, dict):
        raise ACGValidationError(f"{label} contract must be an object")


# 旧名称保留给已有 Planner、插件与持久化载荷；新边界代码使用 RuntimeBlueprintSpec。

def _validate_edge_endpoints(blueprint: ACGBlueprint) -> None:
    allowed = {
        EdgeType.DEPENDENCY: ({NodeType.STEP, NodeType.CONTROL}, {NodeType.STEP, NodeType.CONTROL}),
        EdgeType.CONTROL_FLOW: ({NodeType.CONTROL}, {NodeType.STEP, NodeType.CONTROL}),
    }
    node_types = {node.node_id: node.node_type for node in blueprint.nodes}
    for edge in blueprint.edges:
        if edge.source_id not in node_types or edge.target_id not in node_types:
            raise ACGValidationError(
                f"ACG edge {edge.edge_id} references missing endpoint: "
                f"{edge.source_id} -> {edge.target_id}"
            )
        source_types, target_types = allowed[edge.edge_type]
        if node_types[edge.source_id] not in source_types or node_types[edge.target_id] not in target_types:
            raise ACGValidationError(
                f"ACG edge {edge.edge_id} has invalid endpoint types for {edge.edge_type.value}: "
                f"{node_types[edge.source_id].value} -> {node_types[edge.target_id].value}"
            )
        if edge.edge_type == EdgeType.DEPENDENCY and edge.source_id == edge.target_id:
            raise ACGValidationError(f"ACG dependency edge {edge.edge_id} cannot target itself")


def _validate_conditional_control(blueprint: ACGBlueprint, node: ControlNode) -> None:
    if node.condition_spec is None:
        raise ACGValidationError(f"IF control {node.node_id} requires conditionSpec")
    if not 2 <= len(node.branch_edge_ids) <= 4:
        raise ACGValidationError(f"IF control {node.node_id} requires 2..4 branch edges")
    if len(set(node.branch_edge_ids)) != len(node.branch_edge_ids):
        raise ACGValidationError(f"IF control {node.node_id} has duplicate branchEdgeIds")
    if not blueprint.has_node(node.condition_spec.source_node_id):
        raise ACGValidationError(f"IF source node missing: {node.condition_spec.source_node_id}")
    if node.join_node_id and not blueprint.has_node(node.join_node_id):
        raise ACGValidationError(f"IF join node missing: {node.join_node_id}")
    source_node = blueprint.get_node(node.condition_spec.source_node_id)
    if source_node.node_type != NodeType.STEP:
        raise ACGValidationError(f"IF source must be a Step: {source_node.node_id}")
    if node.join_node_id:
        join_node = blueprint.get_node(node.join_node_id)
        if not isinstance(join_node, ControlNode) or join_node.control_type in {
            ControlType.IF,
            ControlType.LOOP,
        }:
            raise ACGValidationError(f"IF join must be an unconditional Control: {node.join_node_id}")
    incoming = blueprint.incoming(node.node_id, EdgeType.DEPENDENCY)
    if len(incoming) != 1 or incoming[0].source_id != node.condition_spec.source_node_id:
        raise ACGValidationError(f"IF control {node.node_id} requires its single declared source")
    outgoing = [
        edge
        for edge in blueprint.outgoing(node.node_id)
        if edge.edge_type in {EdgeType.DEPENDENCY, EdgeType.CONTROL_FLOW}
    ]
    if {edge.edge_id for edge in outgoing} != set(node.branch_edge_ids):
        raise ACGValidationError(f"IF control {node.node_id} has undeclared branch edges")
    declared = set(node.branch_edge_ids)
    case_edges = set(node.condition_spec.cases.values())
    if not case_edges or not case_edges.issubset(declared):
        raise ACGValidationError(f"IF control {node.node_id} has invalid condition cases")
    if node.condition_spec.default_edge_id and node.condition_spec.default_edge_id not in declared:
        raise ACGValidationError(f"IF control {node.node_id} has invalid defaultEdgeId")
    selectable = case_edges | (
        {node.condition_spec.default_edge_id} if node.condition_spec.default_edge_id else set()
    )
    if selectable != declared:
        raise ACGValidationError(f"IF control {node.node_id} has an unreachable branch")
    if node.join_node_id:
        try:
            exclusive = conditional_branch_exclusive_nodes(blueprint, node)
        except ConditionEvaluationError as exc:
            raise ACGValidationError(f"{exc.code}: {exc}") from exc
        for node_ids in exclusive.values():
            for node_id in node_ids:
                branch_node = blueprint.get_node(node_id)
                if isinstance(branch_node, ControlNode) and branch_node.control_type in {
                    ControlType.IF,
                    ControlType.LOOP,
                }:
                    raise ACGValidationError(f"nested IF/LOOP is unsupported: {branch_node.node_id}")


def validate_blueprint(blueprint: ACGBlueprint) -> None:
    """规划器交付前的图级验证。非法则抛 ACGValidationError。"""
    step_nodes = blueprint.step_nodes()
    if not step_nodes:
        raise ACGValidationError("ACG must contain at least one Step node")

    node_ids = [node.node_id for node in blueprint.nodes]
    duplicate_nodes = sorted({node_id for node_id in node_ids if node_ids.count(node_id) > 1})
    if duplicate_nodes:
        raise ACGValidationError(f"ACG has duplicate node ids: {duplicate_nodes}")
    edge_ids = [edge.edge_id for edge in blueprint.edges]
    duplicate_edges = sorted({edge_id for edge_id in edge_ids if edge_ids.count(edge_id) > 1})
    if duplicate_edges:
        raise ACGValidationError(f"ACG has duplicate edge ids: {duplicate_edges}")

    _validate_edge_endpoints(blueprint)
    cycle = detect_cycle(blueprint)
    if cycle:
        raise ACGValidationError(f"ACG contains a cycle: {' -> '.join(cycle)}")

    step_ids = {node.node_id for node in blueprint.step_nodes()}
    bindings_by_step: dict[str, list] = {}
    for binding in blueprint.resource_plan.bindings:
        if binding.step_id not in step_ids:
            raise ACGValidationError(
                f"Agent binding references missing Step: {binding.step_id}"
            )
        bindings_by_step.setdefault(binding.step_id, []).append(binding)
    if any(len(bindings) != 1 for bindings in bindings_by_step.values()):
        raise ACGValidationError("Each Step requires exactly one AgentBindingSpec")
    if any(step_id not in bindings_by_step for step_id in step_ids):
        raise ACGValidationError("Each Step requires exactly one AgentBindingSpec")
    for node in blueprint.nodes:
        if isinstance(node, ControlNode) and node.control_type == ControlType.LOOP:
            if node.loop_spec is None:
                raise ACGValidationError(f"LOOP control {node.node_id} requires loopSpec")
            for ref in (node.loop_spec.body_entry_id, node.loop_spec.body_exit_id):
                if not blueprint.has_node(ref):
                    raise ACGValidationError(f"LOOP control {node.node_id} references missing node: {ref}")
        if isinstance(node, ControlNode) and node.control_type == ControlType.PARALLEL:
            if node.parallel_spec is not None:
                refs = [*node.parallel_spec.branch_entry_ids, node.parallel_spec.join_node_id]
                if len(set(node.parallel_spec.branch_entry_ids)) != len(node.parallel_spec.branch_entry_ids):
                    raise ACGValidationError(f"PARALLEL control {node.node_id} has duplicate branches")
                if any(not blueprint.has_node(ref) for ref in refs):
                    raise ACGValidationError(f"PARALLEL control {node.node_id} references missing nodes")
        if isinstance(node, ControlNode) and node.control_type == ControlType.CONSENSUS:
            if node.consensus_spec is not None:
                if node.consensus_spec.quorum > len(node.consensus_spec.participant_step_ids):
                    raise ACGValidationError(f"CONSENSUS control {node.node_id} quorum exceeds participants")
                if any(not blueprint.has_node(ref) for ref in node.consensus_spec.participant_step_ids):
                    raise ACGValidationError(f"CONSENSUS control {node.node_id} references missing participants")
        if isinstance(node, ControlNode) and node.control_type == ControlType.IF:
            _validate_conditional_control(blueprint, node)
        if not isinstance(node, StepNode):
            continue
        try:
            check_contract_schema(node.output_spec, label=f"{node.node_id}.outputSpec")
        except ValueError as exc:
            raise ACGValidationError(str(exc)) from exc
        input_schema = node.input_spec.get("schema") if isinstance(node.input_spec, dict) else None
        if isinstance(input_schema, dict):
            try:
                check_contract_schema(input_schema, label=f"{node.node_id}.inputSpec.schema")
            except ValueError as exc:
                raise ACGValidationError(str(exc)) from exc
        from_map = node.input_spec.get("from") if isinstance(node.input_spec, dict) else None
        if isinstance(from_map, dict):
            for source_id in from_map:
                source = str(source_id)
                if not blueprint.has_node(source):
                    raise ACGValidationError(f"Step {node.node_id} input.from references missing Step {source}")
                source_node = blueprint.get_node(source)
                if source_node.node_type != NodeType.STEP:
                    raise ACGValidationError(f"Step {node.node_id} input.from source is not a Step: {source}")
                if not _has_dependency_path(blueprint, source, node.node_id):
                    raise ACGValidationError(
                        f"Step {node.node_id} consumes {source} without an execution dependency path"
                    )

    for spec in blueprint.resource_plan.memory:
        if spec.step_id not in step_ids:
            raise ACGValidationError(f"Memory access references missing Step: {spec.step_id}")
    for spec in blueprint.resource_plan.skills:
        if spec.step_id not in step_ids:
            raise ACGValidationError(f"Skill requirement references missing Step: {spec.step_id}")
    for spec in blueprint.resource_plan.evidence:
        if spec.producer_step_id and spec.producer_step_id not in step_ids:
            raise ACGValidationError(
                f"Evidence spec {spec.evidence_id} references missing producer Step: "
                f"{spec.producer_step_id}"
            )
        if any(consumer not in step_ids for consumer in spec.consumer_step_ids):
            raise ACGValidationError(
                f"Evidence spec {spec.evidence_id} references missing consumer Step"
            )
    for spec in blueprint.resource_plan.communication:
        if spec.producer_step_id not in step_ids or spec.consumer_step_id not in step_ids:
            raise ACGValidationError(
                f"Communication spec references missing Step: "
                f"{spec.producer_step_id} -> {spec.consumer_step_id}"
            )
        if spec.producer_step_id == spec.consumer_step_id:
            raise ACGValidationError("Communication spec cannot target its producer Step")
        if not _has_dependency_path(
            blueprint, spec.producer_step_id, spec.consumer_step_id
        ):
            raise ACGValidationError(
                f"Communication spec has no execution dependency path: "
                f"{spec.producer_step_id} -> {spec.consumer_step_id}"
            )




__all__ = ["ACGValidationError", "check_contract_schema", "validate_blueprint"]
