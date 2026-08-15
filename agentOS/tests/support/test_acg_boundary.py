"""Regression tests for the public ACG model boundary."""

import importlib
from pathlib import Path

import pytest


def test_step_node_uses_the_exported_node_type() -> None:
    from support.acg.models import NodeType, StepNode

    node = StepNode(nodeId="step-1", agentName="planner")

    assert isinstance(node.node_type, NodeType)
    assert node.node_type is NodeType.STEP


def test_acg_package_has_an_explicit_public_blueprint_export() -> None:
    from support.acg import ACGBlueprint

    assert ACGBlueprint.__name__ == "ACGBlueprint"


def test_runtime_references_the_real_acg_package() -> None:
    runtime_source = Path("src/runtime/workflow_runtime.py").read_text(encoding="utf-8")

    assert "from ACG.models" not in runtime_source
    assert "from support.acg.models" in runtime_source
