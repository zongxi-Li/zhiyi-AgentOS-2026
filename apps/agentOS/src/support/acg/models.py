"""Compatibility facade for the historical ``support.acg.models`` API."""

from support.capabilities import CapabilityCatalog
from contracts.acg.capabilities import CapabilityPromptProfile, PlanningCapabilityDescriptor, PlanningRiskLevel, highest_planning_risk_level
from domain.acg_graph import ConditionEvaluationError, detect_cycle, find_dangling_dependencies, topological_order
from components.scheduler.blueprint import ready_steps
from support.packs.native_capabilities import (
    NATIVE_CAPABILITY_IDS, build_default_capability_catalog,
    native_capability_descriptors, register_native_capabilities,
)
from contracts.acg.planning import (
    ACGResourcePlan, AgentBindingSpec, CommunicationSpec, EvidenceSpec,
    MemoryAccessSpec, ModelRequirementSpec, SkillRequirementSpec,
)
from contracts.acg.schema import (
    ACGBlueprint, RuntimeBlueprintSpec, ACGEdge, ACGNode, ACGNodeBase,
    BlueprintStatus, ComplexityLevel, ConditionOperator, ConditionSpec,
    ConsensusSpec, ControlNode, ControlType, EdgeActivation, EdgeType,
    LoopSpec, NodeType, ParallelSpec, StepNode, parse_node,
)
from contracts.acg.semantic_profile import CapabilityCandidate, ComplexityAssessment, TaskSemanticProfile
from components.planner.acg_validation import ACGValidationError, validate_blueprint

__all__ = [
    "ACGBlueprint", "RuntimeBlueprintSpec", "ACGEdge", "ACGNode", "ACGNodeBase", "ACGValidationError",
    "ACGResourcePlan", "AgentBindingSpec", "BlueprintStatus", "CapabilityCandidate", "CapabilityCatalog",
    "CapabilityPromptProfile", "ComplexityAssessment",
    "ComplexityLevel", "CommunicationSpec", "ConditionEvaluationError", "ConditionOperator", "ConditionSpec",
    "ControlNode", "ControlType", "EdgeActivation", "EdgeType", "EvidenceSpec",
    "MemoryAccessSpec", "ModelRequirementSpec", "NATIVE_CAPABILITY_IDS", "NodeType", "PlanningCapabilityDescriptor",
    "PlanningRiskLevel", "SkillRequirementSpec", "StepNode", "TaskSemanticProfile",
    "build_default_capability_catalog", "detect_cycle", "find_dangling_dependencies",
    "highest_planning_risk_level", "native_capability_descriptors", "parse_node",
    "ready_steps", "register_native_capabilities",
    "topological_order", "validate_blueprint",
]
