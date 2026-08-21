"""Identity Graph 冻结的关系词表与关系矩阵。"""

from enum import Enum


class IdentityRelation(str, Enum):
    HAS_NODE = "has_node"
    REALIZED_BY = "realized_by"
    CONTAINS = "contains"
    BOUND_TO = "bound_to"
    HAS_ATTEMPT = "has_attempt"
    EXECUTES = "executes"
    PRODUCES = "produces"
    WRITES = "writes"
    DERIVED_FROM = "derived_from"


class TaskNodeBindingType(str, Enum):
    PRIMARY = "primary"
    SUPPORTING = "supporting"


class BlueprintRelationType(str, Enum):
    DEPENDENCY = "dependency"
    COMMUNICATION = "communication"
    CONTROL = "control"


RELATION_MATRIX = {
    ("UserTask", "TaskNode"): IdentityRelation.HAS_NODE,
    ("TaskNode", "ACGNode"): IdentityRelation.REALIZED_BY,
    ("AcgBlueprint", "ACGNode"): IdentityRelation.CONTAINS,
    ("ACGNode", "Resource"): IdentityRelation.BOUND_TO,
    ("WorkflowRun", "Attempt"): IdentityRelation.HAS_ATTEMPT,
    ("Attempt", "StepExecution"): IdentityRelation.EXECUTES,
    ("StepExecution", "Evidence"): IdentityRelation.PRODUCES,
    ("StepExecution", "Memory"): IdentityRelation.WRITES,
}

__all__ = [
    "BlueprintRelationType",
    "IdentityRelation",
    "RELATION_MATRIX",
    "TaskNodeBindingType",
]
