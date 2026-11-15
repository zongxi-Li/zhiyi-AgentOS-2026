"""Exercise dynamic replicas through the real ACG Runtime without model/network calls.

From the repository root::

    python ops/scripts/agent_provisioning_trial.py

Two deterministic local Steps share one logical Agent. A trusted factory creates
a second instance after the Run scope is frozen. Both execute concurrently; the
replica is drained while running, cannot be reclaimed with an active lease, and
is reclaimed after completion. Reports and SQLite stores use an isolated folder.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "apps/agentOS", ROOT / "apps/agentOS/src"):
    sys.path.insert(0, str(path))


async def execute(output: Path) -> dict:
    from components.marketplace.infrastructure import InMemoryInstallationJobs
    from components.memory.store import MemoryStore
    from components.mission_manager.store import WorkflowRegistry
    from contracts.planning import PlannedTask, TaskImplementationBinding, TaskPlan
    from contracts.resource import ExecutionRequirement
    from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition
    from runtime.workflow_runtime import ExecutionRuntime
    from service.agents import AgentOutput, AgentProfile, AgentRegistry, BaseAgent
    from service.agents.provisioning import AgentProvisioner
    from support.acg.models import ACGBlueprint, StepNode
    from support.acg.planning import ACGResourcePlan, AgentBindingSpec
    from support.stores.sqlite_workflow_store import SQLiteWorkflowStore

    output.mkdir(parents=True, exist_ok=False)
    for name, filename in {
        "AGENTOS_LANGGRAPH_CHECKPOINT_DB": "checkpoints.sqlite3", "AGENTOS_EXECUTION_VALUE_DB": "values.sqlite3",
        "AGENTOS_CONTENT_MANIFEST_DB": "content.sqlite3", "AGENTOS_PROVENANCE_DB": "provenance.sqlite3",
        "AGENTOS_AUDIT_DB": "audit.sqlite3", "AGENTOS_COMMUNICATION_DB": "communication.sqlite3",
    }.items():
        os.environ[name] = str(output / filename)
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    class TrialAgent(BaseAgent):
        def __init__(self):
            super().__init__(AgentProfile(agentId="trial:worker", agentName="trial_worker", domain="general",
                capabilities=["analysis"], definitionVersion="1", executionMode="stateless", capacity=1))

        async def run(self, context):
            calls.append({"stepId": context.step.step_id, "registration":
                          context.agent_registration.model_dump(by_alias=True, mode="json")})
            if len(calls) == 2:
                started.set()
            await release.wait()
            return AgentOutput(output={"answer": f"Local execution completed: {context.step.step_id}"})

    registry = AgentRegistry()
    seed = TrialAgent()
    registry.register(seed)
    workflows = WorkflowRegistry()
    workflows.register(WorkflowDefinition(workflowId="provisioning-trial", name="Dynamic replica trial",
        domain="general", runtimeEngine="acg", steps=[WorkflowStepDefinition(
            stepId="placeholder", name="placeholder", agentName="trial_worker")]))
    runtime = ExecutionRuntime(agent_registry=registry, workflow_registry=workflows,
        workflow_store=SQLiteWorkflowStore(output / "workflow.sqlite3"), memory_store=MemoryStore())
    mission = runtime.create_mission("Execute two independent local steps", workflow_id="provisioning-trial")
    keys = ("first", "second")
    graph = ACGBlueprint(graphId="dynamic-replica", nodes=[
        StepNode(nodeId=key, capability="analysis") for key in keys
    ], edges=[], resourcePlan=ACGResourcePlan(bindings=tuple(
        AgentBindingSpec(stepId=key, plannedAgentId="trial:worker") for key in keys)))
    plan = TaskPlan(missionId=mission.mission_id, nodes=tuple(
        PlannedTask(key=f"step:{key}", title=key, objective=key) for key in keys))
    mission.input.update(acgBlueprint=graph.model_dump(by_alias=True, mode="json"),
        taskPlan=plan.model_dump(by_alias=True, mode="json"), taskBindings=[TaskImplementationBinding(
            planNodeKey=f"step:{key}", acgNodeId=key).model_dump(by_alias=True, mode="json") for key in keys])
    runtime.workflow_store.save_mission(mission)
    _, run = runtime.prepare_run(mission.mission_id)
    pool = runtime.runtime_binding_service.agent_pool
    provisioner = AgentProvisioner(pool=pool, jobs=InMemoryInstallationJobs(),
        coordinator=runtime.resource_binder.coordinator,
        refresh_runtime=runtime.runtime_binding_service.refresh_embedded_runtime)
    provisioner.register_agent_template("worker", seed=seed, factory=TrialAgent)
    job = provisioner.provision("worker", "trial-request")
    if job.status.value != "running":
        raise RuntimeError("TRIAL_PROVISIONING_FAILED")
    repeated = provisioner.provision("worker", "trial-request")
    replica = next(item for item in pool.instances() if item.ref.resource_id == job.runtime_id)
    execution = asyncio.create_task(runtime.execute_prepared_run(run.run_id))
    try:
        await asyncio.wait_for(started.wait(), timeout=15)
        held_slots = runtime.resource_binder.coordinator.active_slots(replica.ref.resource_id)
        provisioner.stop(job.job_id)
        blocked = False
        try:
            provisioner.uninstall(job.job_id)
        except ValueError:
            blocked = True
        drained = pool.describe(replica.ref)
        refused = runtime.resource_binder.bind_ready(run_id="probe", step_id="probe", attempt_id="probe",
            requirement=ExecutionRequirement(requiredCapabilities=["analysis"],
                allowedRuntimeIds=[replica.host.runtime_id]),
            agent_candidates={replica.host.runtime_id: (drained.resource,)})
    finally:
        release.set()
        await execution
    removed = provisioner.uninstall(job.job_id)
    saved = runtime.workflow_store.get_run(run.run_id)
    checks = {
        "scopeFrozenBeforeProvisioning": tuple(run.execution_scope.agent_ids) == ("trial:worker",),
        "idempotentJob": repeated.job_id == job.job_id,
        "distinctInstancesExecuted": len({item["registration"]["instanceId"] for item in calls}) == 2,
        "replicaLeaseHeld": held_slots == 1,
        "drainingRefusesNewAllocation": refused.status != "allocated" and drained.draining and not drained.resource.enabled,
        "activeLeaseBlocksRemoval": blocked,
        "reclaimedAfterCompletion": removed.status.value == "removed" and len(pool.instances()) == 1,
        "seedRetained": registry.resolve_by_id("trial:worker") is seed,
        "runCompleted": saved.status.value == "completed",
    }
    report = {"mode": "deterministic-local-acg", "networkRequests": 0, "checks": checks,
        "status": "passed" if all(checks.values()) else "failed", "runId": saved.run_id,
        "job": removed.model_dump(by_alias=True, mode="json"), "agentCalls": calls,
        "bindings": saved.execution_state.get("executionBindings"), "outputs": {
            key: runtime.execution_value_store.get_output(run_id=saved.run_id, output_ref=ref)
            for key, ref in saved.execution_state.get("outputRefs", {}).items()}}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", type=Path, help="New isolated report/store directory")
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = (args.output_dir or ROOT / "data/agent-provisioning-trials" / stamp).resolve()
    report = asyncio.run(execute(output))
    print(json.dumps({"status": report["status"], "checks": report["checks"],
                      "report": str(output / "report.json")}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
