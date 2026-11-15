"""绑定权威的契约边界：谁表达需求、谁冻结结果、线格式如何兼容。

- AgentBindingSpec / BindingRule 属于规划层（逻辑 Agent 拓扑）；
- ExecutionRequirement / ExecutionBinding 属于资源平面（Runtime 与模型端点）；
- 两层类型不得混用，持久化线格式保持 resourceId 等既有 JSON 键。
"""

from typing import get_type_hints

import pytest
from pydantic import ValidationError

from contracts.authority import LogicalAgentId, RuntimeResourceId
from contracts.compiled_acg import BindingRule
from contracts.resource import (
    ExecutionBinding,
    ExecutionRequirement,
    ModelEndpointBinding,
    Placement,
    RuntimeKind,
    TrustLevel,
)
from support.acg.planning import AgentBindingSpec


def test_planning_and_runtime_binding_identities_are_distinct_types() -> None:
    assert get_type_hints(AgentBindingSpec)["planned_agent_id"] is LogicalAgentId
    assert get_type_hints(BindingRule)["agent_node_ids"]
    assert get_type_hints(BindingRule)["allowed_resource_ids"]
    assert get_type_hints(ExecutionRequirement)["allowed_runtime_ids"]
    assert get_type_hints(ExecutionBinding)["resource_id"] is RuntimeResourceId


def test_identity_aliases_keep_existing_json_wire_shape() -> None:
    planned = AgentBindingSpec(stepId="reviewer", plannedAgentId="legal_reviewer")
    assert planned.model_dump(by_alias=True)["plannedAgentId"] == "legal_reviewer"

    requirement = ExecutionRequirement(
        requiredCapabilities=["contract_analysis"],
        allowedRuntimeIds=["runtime:edge-exec-1"],
    )
    assert requirement.model_dump(by_alias=True)["allowedRuntimeIds"] == ["runtime:edge-exec-1"]


def test_execution_requirement_defaults_to_open_thing_declaration() -> None:
    requirement = ExecutionRequirement(requiredCapabilities=["repo.read"])
    # 未声明的维度不做限制：开放式需求只锚定"要什么能力"。
    assert requirement.runtime_kinds == []
    assert requirement.allowed_placements == []
    assert requirement.min_trust is None
    assert requirement.allowed_runtime_ids == []
    assert requirement.excluded_runtime_ids == []
    assert requirement.model is None
    assert requirement.routing_hints == {}
    assert requirement.preferences == {}


def test_execution_requirement_needs_at_least_one_capability() -> None:
    with pytest.raises(ValidationError):
        ExecutionRequirement(requiredCapabilities=[])


def test_execution_binding_is_frozen_and_wire_compatible() -> None:
    binding = ExecutionBinding(
        bindingId="binding:run-1:step-2:attempt-3",
        runId="run-1",
        stepId="step-2",
        attemptId="attempt-3",
        resourceId="runtime:embedded-agents",
        runtimeKind=RuntimeKind.EXECUTION_BACKEND,
        nodeId="node:device:local",
        placement=Placement.DEVICE,
        trust=TrustLevel.HOST_TRUSTED,
        modelBinding=ModelEndpointBinding(
            endpointId="endpoint:glm-coding",
            provider="zhipu",
            model="glm-4.6",
        ),
        snapshotVersion=4,
    )
    with pytest.raises(ValidationError):
        binding.resource_id = "runtime:other"
    payload = binding.model_dump(by_alias=True, mode="json")
    # 历史运行持久化的 executionBindings 以 resourceId 键读取，必须保持不变。
    assert payload["resourceId"] == "runtime:embedded-agents"
    assert payload["runtimeKind"] == "execution_backend"
    assert payload["modelBinding"]["endpointId"] == "endpoint:glm-coding"
    assert ExecutionBinding.model_validate(payload) == binding


def test_model_binding_is_optional_for_backends_without_model_demand() -> None:
    binding = ExecutionBinding(
        bindingId="binding:run-1:step-2:attempt-3",
        runId="run-1",
        stepId="step-2",
        attemptId="attempt-3",
        resourceId="runtime:local",
        runtimeKind=RuntimeKind.EXECUTION_BACKEND,
        snapshotVersion=1,
    )
    assert binding.model_binding is None
    assert binding.node_id is None
    assert binding.placement is Placement.DEVICE
