"""Instance facts do not introduce another execution or allocation authority."""

import ast
from pathlib import Path

from contracts.planning import PlannedTask, TaskPlan
from contracts.task import AgentInstance
from contracts.workflow import WorkflowStep
from service.agents.pool import RegisteredAgentInstance


ROOT = Path(__file__).resolve().parents[2]


def test_agent_fact_and_lifecycle_modules_do_not_depend_on_execution_or_scheduling():
    paths = [ROOT / "src/contracts/agents.py", ROOT / "service/agents/registry.py", ROOT / "service/agents/pool.py"]
    forbidden = ("runtime.workflow_runtime", "runtime.acg_execution", "components.executor", "components.resource.scheduler")
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.add(node.module or "")
                modules.update(f"{node.module}.{alias.name}" for alias in node.names)
        assert not any(module == root or module.startswith(root + ".") for root in forbidden for module in modules)


def test_existing_plan_step_and_task_statistics_are_not_repurposed_as_pool_state():
    forbidden = {"agent_registration", "agent_instance_id", "instance_id", "generation", "lease_id"}
    for contract in (TaskPlan, PlannedTask, WorkflowStep):
        assert forbidden.isdisjoint(contract.model_fields)
    assert AgentInstance is not RegisteredAgentInstance
    assert "task_id" in AgentInstance.model_fields
