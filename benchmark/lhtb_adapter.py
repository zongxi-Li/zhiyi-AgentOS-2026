"""Phase-1 adapter: one official LHTB task through the AgentOS Runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from time import monotonic
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (
    _REPO_ROOT / "apps" / "agentOS",
    _REPO_ROOT / "apps" / "agentOS" / "src",
    _REPO_ROOT / "apps" / "agent",
):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from adapters.model.long_running_terminal import LongRunningTerminalAgent
from benchmark.lhtb_environment import DockerTaskEnvironment, LHTBTaskSpec
from components.recovery.terminal_action_store import TerminalActionStore
from contracts.planning import PlannedTask, TaskImplementationBinding, TaskPlan
from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition
from runtime import ExecutionRuntime
from support.acg.models import (
    ACGEdge,
    AgentNode,
    EdgeType,
    PlanningCapabilityDescriptor,
    RuntimeBlueprintSpec,
    StepNode,
)


WORKFLOW_ID = "lhtb-terminal-v1"
CAPABILITY_ID = "lhtb_terminal_execution"
AGENT_NAME = "lhtb_long_running_terminal_agent"
STEP_ID = "execute_lhtb_migration"


@dataclass(frozen=True)
class LHTBBenchmarkResult:
    benchmark: str
    task_id: str
    run_id: str
    completed: bool
    verified: bool
    reward: float
    passed_gates: int
    total_gates: int
    e2e_ms: int
    agent_turns: int
    model_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    terminal_commands: int
    failed_commands: int
    timeout_commands: int
    unknown_commands: int
    task_count: int
    acg_nodes: int
    acg_edges: int
    checkpoint_count: int
    resume_count: int
    peak_context_estimate: int
    truncated_observation_count: int
    communication_available: int
    communication_delivered: int
    communication_reduction: int
    provenance_valid: bool
    verifier_details: dict[str, Any]
    workspace_export: str


def _capability_descriptor() -> PlanningCapabilityDescriptor:
    return PlanningCapabilityDescriptor(
        capabilityId=CAPABILITY_ID,
        displayName="Isolated terminal execution",
        description="Execute bounded shell commands in the task workspace and inspect their results.",
        planningStage="execution",
        promptProfile={
            "profileId": "lhtb-terminal-v1",
            "purpose": "Perform multi-step work through an isolated terminal workspace.",
            "requiredTools": ["terminal"],
            "executionPrinciples": [
                "Inspect before mutation.",
                "Use command observations to choose the next action.",
                "Never assume a command succeeded without checking its result.",
            ],
        },
        inputContract={"type": "object"},
        outputContract={"type": "object"},
        producesArtifact=True,
        requiresReview=False,
        riskLevelHint="elevated",
        parallelizable=False,
        domainHints=["software-engineering"],
        source="native",
    )


def _workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        workflowId=WORKFLOW_ID,
        name="LHTB terminal execution",
        domain="software-engineering",
        intent="lhtb_terminal",
        version="1.0.0",
        description="Phase-1 benchmark-scoped long-running terminal workflow.",
        runtimeEngine="acg",
        implementationId=WORKFLOW_ID,
        requiredCapabilities=[CAPABILITY_ID],
        tags=["benchmark", "lhtb"],
        steps=[
            WorkflowStepDefinition(
                stepId=STEP_ID,
                name="Execute migration in the task workspace",
                agentName=AGENT_NAME,
                capability=CAPABILITY_ID,
                goal="Complete the supplied LHTB instruction through iterative terminal actions.",
                logicalRole="task",
                maxRetries=0,
                timeout=0,
            )
        ],
    )


def _plan_and_blueprint(mission_id: str, instruction: str) -> tuple[TaskPlan, RuntimeBlueprintSpec, list[dict[str, str]]]:
    plan = TaskPlan(
        missionId=mission_id,
        nodes=(
            PlannedTask(
                key=STEP_ID,
                title="Execute the long-running terminal migration",
                objective="Use the isolated task environment to complete the supplied migration instruction.",
                capabilityRequirements=(CAPABILITY_ID,),
                acceptanceCriteria=("The official LHTB verifier evaluates the resulting workspace.",),
                logicalRole="task",
                producedArtifacts=(),
            ),
        ),
    )
    blueprint = RuntimeBlueprintSpec(
        graphId=f"acg:{mission_id}:lhtb",
        missionId=mission_id,
        objective=instruction[:500],
        nodes=[
            StepNode(
                nodeId=STEP_ID,
                name="Execute the long-running terminal migration",
                agentName=AGENT_NAME,
                capability=CAPABILITY_ID,
                logicalRole="task",
                goal="Complete the supplied task instruction in the persistent container workspace.",
                timeout=0,
                retryLimit=0,
            ),
            AgentNode(
                nodeId=f"agent::{AGENT_NAME}",
                name=AGENT_NAME,
                role="long-running terminal agent",
                capabilityTags=[CAPABILITY_ID],
            ),
        ],
        edges=[
            ACGEdge(
                sourceId=f"agent::{AGENT_NAME}",
                targetId=STEP_ID,
                edgeType=EdgeType.EXECUTION,
            )
        ],
        metadata={"communicationBudget": 0, "benchmarkScoped": True},
    )
    blueprint.touch()
    bindings = [TaskImplementationBinding(planNodeKey=STEP_ID, acgNodeId=STEP_ID).model_dump(by_alias=True)]
    return plan, blueprint, bindings


def _runtime_environment(work_dir: Path) -> dict[str, str]:
    values = dict(os.environ)
    values["ENVIRONMENT"] = "development"
    values["AGENTOS_COORDINATION_REDIS_URL"] = ""
    values["AGENTOS_WORKFLOW_DB_PATH"] = str(work_dir / "workflow.sqlite3")
    for name in (
        "AGENTOS_LANGGRAPH_CHECKPOINT_DB",
        "AGENTOS_EXECUTION_VALUE_DB",
        "AGENTOS_CONTENT_MANIFEST_DB",
        "AGENTOS_EXECUTION_MEMORY_DB",
        "AGENTOS_PROVENANCE_DB",
        "AGENTOS_AUDIT_DB",
        "AGENTOS_RESOURCE_DB",
        "AGENTOS_RESOURCE_HEALTH_DB",
        "AGENTOS_EVOLUTION_DB",
    ):
        values[name] = str(work_dir / f"{name.lower()}.sqlite3")
    return values


async def run_one_task(
    *,
    lhtb_root: str | Path,
    output_dir: str | Path | None = None,
    max_turns: int = 256,
) -> LHTBBenchmarkResult:
    spec = LHTBTaskSpec.load(lhtb_root)
    output_path = Path(output_dir).resolve() if output_dir else Path(tempfile.mkdtemp(prefix="agentos-lhtb-result-"))
    output_path.mkdir(parents=True, exist_ok=True)
    runtime_work = output_path / "agentos-runtime"
    runtime_work.mkdir(parents=True, exist_ok=True)
    environment = DockerTaskEnvironment(spec)
    ledger = TerminalActionStore(runtime_work / "terminal_actions.sqlite3")
    runtime: ExecutionRuntime | None = None
    setup = None
    started = monotonic()
    try:
        environment.start()
        from adapters.terminal_runtime import FileTerminalOutputStore, HarborTerminalRuntime
        from app.execution.coordinator import RunExecutionCoordinator
        from app.execution.wiring import build_default_runtime, build_model_setup

        terminal = HarborTerminalRuntime(
            environment=environment,
            workspace_root="/app",
            ledger=ledger,
            output_store=FileTerminalOutputStore(output_path / "terminal-output"),
        )
        runtime = build_default_runtime(
            environment=_runtime_environment(runtime_work),
            terminal_runtime=terminal,
            terminal_action_store=ledger,
            scheduler_lease_ttl_seconds=spec.agent_timeout_sec + 300.0,
            enable_terminal_agent=True,
        )
        runtime.capability_catalog.register(_capability_descriptor())
        runtime.agent_registry.register(LongRunningTerminalAgent())
        runtime.workflow_registry.register(_workflow())
        setup = build_model_setup(runtime, environment=_runtime_environment(runtime_work))
        await setup.start()
        if not isinstance(runtime.default_model_binding, dict):
            raise RuntimeError("no configured AgentOS model binding is available for LHTB")

        input_payload = {
            "userIntent": spec.instruction,
            "lhtbInstruction": spec.instruction,
            "lhtb": {
                "task_id": spec.task_id,
                "workspace": "/app",
                "max_turns": max_turns,
                "agent_timeout_sec": spec.agent_timeout_sec,
                "model_call_timeout_sec": min(120.0, spec.agent_timeout_sec),
                "terminal_command_timeout_sec": 120.0,
                "verifier_timeout_sec": spec.verifier_timeout_sec,
            },
        }
        mission = runtime.create_mission(
            title=spec.task_id,
            domain="software-engineering",
            intent="lhtb_terminal",
            input=input_payload,
            workflow_id=WORKFLOW_ID,
        )
        plan, blueprint, bindings = _plan_and_blueprint(mission.mission_id, spec.instruction)
        mission.input.update(
            {
                "taskPlan": plan.model_dump(by_alias=True, mode="json"),
                "acgBlueprint": blueprint.model_dump(by_alias=True, mode="json"),
                "taskBindings": bindings,
            }
        )
        runtime.workflow_store.save_mission(mission)
        _, run = runtime.prepare_run(mission.mission_id, workflow_id=WORKFLOW_ID)
        runtime.terminal_run_deadlines[run.run_id] = monotonic() + spec.agent_timeout_sec
        coordinator = RunExecutionCoordinator(runtime)
        if not await coordinator.submit(run.run_id):
            raise RuntimeError(f"AgentOS coordinator rejected run {run.run_id}")
        while coordinator.is_active(run.run_id):
            await asyncio.sleep(0.5)
        final_run = runtime.workflow_store.get_run(run.run_id)
        workspace_export = environment.export_workspace(output_path / "workspace")
        verifier = environment.run_official_verifier(workspace_export)
        output = final_run.output if isinstance(final_run.output, dict) else {}
        result = LHTBBenchmarkResult(
            benchmark="lhtb",
            task_id=spec.task_id,
            run_id=run.run_id,
            completed=final_run.status.value == "completed",
            verified=verifier.verified,
            reward=verifier.reward,
            passed_gates=verifier.passed_gates,
            total_gates=verifier.total_gates,
            e2e_ms=round((monotonic() - started) * 1000),
            agent_turns=int(output.get("agentTurns", 0) or 0),
            model_calls=int(output.get("modelCalls", 0) or 0),
            input_tokens=int(output.get("inputTokens", 0) or 0),
            output_tokens=int(output.get("outputTokens", 0) or 0),
            total_tokens=int(output.get("totalTokens", 0) or 0),
            terminal_commands=int(output.get("terminalCommands", 0) or 0),
            failed_commands=int(output.get("failedCommands", 0) or 0),
            timeout_commands=int(output.get("timeoutCommands", 0) or 0),
            unknown_commands=int(output.get("unknownCommands", 0) or 0),
            task_count=1,
            acg_nodes=len(blueprint.nodes),
            acg_edges=len(blueprint.edges),
            checkpoint_count=len(final_run.checkpoints),
            resume_count=0,
            peak_context_estimate=int(output.get("peakContextEstimate", 0) or 0),
            truncated_observation_count=int(output.get("truncatedObservationCount", 0) or 0),
            communication_available=0,
            communication_delivered=0,
            communication_reduction=0,
            provenance_valid=bool(final_run.provenance),
            verifier_details=verifier.details,
            workspace_export=str(workspace_export),
        )
        (output_path / "benchmark_result.json").write_text(
            json.dumps(asdict(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return result
    finally:
        if setup is not None:
            await setup.close()
        if runtime is not None:
            from app.execution.wiring import close_runtime
            close_runtime(runtime)
        ledger.close()
        environment.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run exactly one LHTB phase-1 task through AgentOS")
    parser.add_argument("--lhtb-root", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument("--max-turns", type=int, default=256)
    args = parser.parse_args()
    result = asyncio.run(
        run_one_task(
            lhtb_root=args.lhtb_root,
            output_dir=args.output_dir,
            max_turns=args.max_turns,
        )
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
