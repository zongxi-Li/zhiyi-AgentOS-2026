"""Immutable package bytes survive canonical JSON persistence of blueprints."""
import json

import pytest

from components.executor.compiler import ACGGraphCompiler
from support.acg.models import ACGBlueprint, ACGEdge, StepNode
from contracts.acg.planning import ACGResourcePlan, AgentBindingSpec, CommunicationSpec


@pytest.mark.parametrize("declaration", ["inferred", "input", "resource"])
def test_compiled_package_is_identical_after_object_keys_are_sorted(declaration):
    fields = ["summary", "assumptions", "constraints"]
    source = StepNode(nodeId="source", outputSpec={
        "type": "object", "properties": {field: {"type": "string"} for field in fields},
    })
    target = StepNode(nodeId="target", inputSpec=(
        {"from": {"source": fields}} if declaration == "input" else {}
    ))
    blueprint = ACGBlueprint(graphId="persisted-graph", nodes=[source, target],
        edges=[ACGEdge(sourceId="source", targetId="target")],
        resourcePlan=ACGResourcePlan(bindings=(
            AgentBindingSpec(stepId="source", plannedAgentId="reader"),
            AgentBindingSpec(stepId="target", plannedAgentId="reviewer"),
        ), communication=(
            (CommunicationSpec(producerStepId="source", consumerStepId="target",
                channel="source:target", allowedFields=tuple(fields)),)
            if declaration == "resource" else ()
        )))
    restored = ACGBlueprint.model_validate_json(json.dumps(
        blueprint.model_dump(mode="json", by_alias=True), sort_keys=True,
    ))
    compiler = ACGGraphCompiler()

    original = compiler.compile_package(blueprint, run_id="run-persisted")
    after_restart = compiler.compile_package(restored, run_id="run-persisted")

    assert original == after_restart
    assert original.communication_manifest.rules[0].allowed_fields == tuple(
        sorted(fields) if declaration == "inferred" else fields
    )
    # Runtime projection also consumes the same frozen package after restart.
    assert compiler.compile(restored, run_id="run-persisted", package=original).compiled_package == original
