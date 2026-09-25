"""Pure graph algorithms over ACG blueprint contracts."""

from __future__ import annotations

from typing import Any, Dict, List, Set

from .schema import ACGBlueprint, ACGValidationError, EdgeType, NodeType


class ConditionEvaluationError(ValueError):
    """A conditional branch graph is structurally invalid."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def conditional_branch_exclusive_nodes(graph: Any, control_node: Any) -> dict[str, set[str]]:
    """在线性时间 O(V+E) 内验证各条件分支在汇合点前没有共享节点。"""
    edges = {edge.edge_id: edge for edge in graph.edges}
    adjacency: dict[str, list[str]] = {}
    for edge in graph.edges:
        if edge.edge_type == EdgeType.DEPENDENCY:
            adjacency.setdefault(edge.source_id, []).append(edge.target_id)
    join_id = control_node.join_node_id
    if not join_id:
        raise ConditionEvaluationError("CONDITIONAL_JOIN_MISSING", control_node.node_id)
    branches: dict[str, set[str]] = {}
    for edge_id in control_node.branch_edge_ids:
        edge = edges.get(edge_id)
        if edge is None or edge.source_id != control_node.node_id:
            raise ConditionEvaluationError("CONDITIONAL_BRANCH_EDGE_INVALID", edge_id)
        visited: set[str] = set()
        frontier = [edge.target_id]
        while frontier:
            node_id = frontier.pop()
            if node_id == join_id or node_id in visited:
                continue
            visited.add(node_id)
            frontier.extend(adjacency.get(node_id, []))
        branches[edge_id] = visited
    branch_sets = list(branches.values())
    for index, nodes in enumerate(branch_sets):
        if any(nodes & other for other in branch_sets[index + 1:]):
            raise ConditionEvaluationError("CONDITIONAL_BRANCH_SHARED_NODE", "branches share nodes before join")
    return branches



def _dependency_adjacency(blueprint: ACGBlueprint) -> Dict[str, List[str]]:
    """构建仅含 STEP/CONTROL 节点的 DEPENDENCY 邻接表（source -> [targets]）。"""
    executable_ids = {
        n.node_id for n in blueprint.nodes
        if n.node_type in {NodeType.STEP, NodeType.CONTROL}
    }
    adjacency: Dict[str, List[str]] = {nid: [] for nid in executable_ids}
    for edge in blueprint.edges_of_type(EdgeType.DEPENDENCY):
        if edge.source_id in executable_ids and edge.target_id in executable_ids:
            adjacency[edge.source_id].append(edge.target_id)
    return adjacency


def detect_cycle(blueprint: ACGBlueprint) -> List[str]:
    """检测 DEPENDENCY 子图是否成环。返回构成环的节点 id 列表（无环则空）。"""
    adjacency = _dependency_adjacency(blueprint)
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {nid: WHITE for nid in adjacency}
    stack: List[str] = []

    def visit(node_id: str) -> List[str]:
        color[node_id] = GRAY
        stack.append(node_id)
        for nxt in adjacency.get(node_id, []):
            if color.get(nxt, WHITE) == GRAY:
                # 回边：截取从 nxt 到当前的栈片段作为环
                idx = stack.index(nxt)
                return stack[idx:] + [nxt]
            if color.get(nxt, WHITE) == WHITE:
                found = visit(nxt)
                if found:
                    return found
        color[node_id] = BLACK
        stack.pop()
        return []

    for nid in adjacency:
        if color[nid] == WHITE:
            cycle = visit(nid)
            if cycle:
                return cycle
    return []


def topological_order(blueprint: ACGBlueprint) -> List[str]:
    """Kahn 算法对 DEPENDENCY 子图做拓扑排序。成环则抛 ACGValidationError。"""
    adjacency = _dependency_adjacency(blueprint)
    indegree: Dict[str, int] = {nid: 0 for nid in adjacency}
    for targets in adjacency.values():
        for t in targets:
            indegree[t] = indegree.get(t, 0) + 1

    queue = [nid for nid, deg in indegree.items() if deg == 0]
    order: List[str] = []
    while queue:
        queue.sort()  # 稳定输出，便于测试
        node_id = queue.pop(0)
        order.append(node_id)
        for nxt in adjacency.get(node_id, []):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(order) != len(adjacency):
        raise ACGValidationError(f"ACG contains a cycle; topological sort impossible. cycle={detect_cycle(blueprint)}")
    return order


def find_dangling_dependencies(blueprint: ACGBlueprint) -> List[str]:
    """返回引用了不存在节点的 DEPENDENCY 边 id 列表。"""
    dangling: List[str] = []
    for edge in blueprint.edges_of_type(EdgeType.DEPENDENCY):
        if not blueprint.has_node(edge.source_id) or not blueprint.has_node(edge.target_id):
            dangling.append(edge.edge_id)
    return dangling


def _has_dependency_path(blueprint: ACGBlueprint, source_id: str, target_id: str) -> bool:
    adjacency = _dependency_adjacency(blueprint)
    seen: Set[str] = set()
    frontier = [source_id]
    while frontier:
        current = frontier.pop()
        if current == target_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        frontier.extend(adjacency.get(current, []))
    return False



def ready_steps(blueprint: ACGBlueprint, completed: Set[str]) -> List[str]:
    """计算就绪集：所有 DEPENDENCY 前驱都已完成、且自身未完成的 STEP 节点。

    这是执行器并行调度的核心：返回的全部 step 之间彼此无依赖，可并发执行。
    """
    ready: List[str] = []
    for step in blueprint.step_nodes():
        if step.node_id in completed:
            continue
        deps = blueprint.dependency_sources(step.node_id)
        if all(dep in completed for dep in deps):
            ready.append(step.node_id)
    return ready


__all__ = [
    "ConditionEvaluationError", "conditional_branch_exclusive_nodes", "detect_cycle",
    "find_dangling_dependencies", "ready_steps", "topological_order",
]
