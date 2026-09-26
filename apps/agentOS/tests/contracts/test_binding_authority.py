from typing import get_type_hints

from contracts.authority import LogicalAgentId, RuntimeResourceId
from contracts.compiled_acg import BindingRule
from contracts.resource import BindingRequirement, ExecutionBinding
from support.acg.planning import AgentBindingSpec


def test_planning_and_runtime_binding_identities_are_distinct_types() -> None:
    assert get_type_hints(AgentBindingSpec)["planned_agent_id"] is LogicalAgentId
    assert get_type_hints(BindingRule)["agent_node_ids"]
    assert get_type_hints(BindingRule)["allowed_resource_ids"]
    assert get_type_hints(BindingRequirement)["allowed_resource_ids"]
    assert get_type_hints(ExecutionBinding)["resource_id"] is RuntimeResourceId


def test_identity_aliases_keep_existing_json_wire_shape() -> None:
    planned = AgentBindingSpec(stepId="reviewer", plannedAgentId="legal_reviewer")
    assert planned.model_dump(by_alias=True)["plannedAgentId"] == "legal_reviewer"

    requirement = BindingRequirement(
        requiredCapabilities=["contract_analysis"],
        allowedResourceIds=["worker-1"],
    )
    assert requirement.model_dump(by_alias=True)["allowedResourceIds"] == ["worker-1"]
