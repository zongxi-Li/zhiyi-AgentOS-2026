"""Regression tests for the public ACG model boundary."""

def test_step_node_uses_the_exported_node_type() -> None:
    from support.acg.models import NodeType, StepNode

    node = StepNode(nodeId="step-1", agentName="planner")

    assert isinstance(node.node_type, NodeType)
    assert node.node_type is NodeType.STEP


def test_acg_package_has_an_explicit_public_blueprint_export() -> None:
    from support.acg import ACGBlueprint, WknBlueprintSpec

    assert ACGBlueprint is WknBlueprintSpec
    assert WknBlueprintSpec.__name__ == "WknBlueprintSpec"
