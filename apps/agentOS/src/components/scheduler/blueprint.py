"""Blueprint projection of the shared scheduler selection rule."""
from typing import List, Set
from contracts.acg.schema import ACGBlueprint

def ready_steps(blueprint: ACGBlueprint, completed: Set[str]) -> List[str]:
    """计算就绪集：所有 DEPENDENCY 前驱都已完成、且自身未完成的 STEP 节点。

    这是执行器并行调度的核心：返回的全部 step 之间彼此无依赖，可并发执行。
    """
    from components.scheduler import select_ready_steps
    return list(select_ready_steps(
        (node.node_id for node in blueprint.nodes),
        step_ids={step.node_id for step in blueprint.step_nodes()},
        predecessors={step.node_id: set(blueprint.dependency_sources(step.node_id)) for step in blueprint.step_nodes()},
        completed=completed,
    ))
