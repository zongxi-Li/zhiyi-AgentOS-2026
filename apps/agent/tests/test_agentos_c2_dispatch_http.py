"""Explicit durable Dispatch through the real Coordinator and Native Scheduler."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from contracts.workflow import WorkflowStatus
from examples.contract_review import ContractReviewAgent
from support.stores.execution_dispatch_store import SQLiteExecutionDispatchStore
from test_agentos_c2_http import PREFIX, base, prepare, server
from test_agentos_c2_permit_http import paused, handoff, issue, ready_resource, trusted_call, snapshot


def database(folder):
    prepare(folder)
    SQLiteExecutionDispatchStore.upgrade_schema(folder / "workflow.sqlite")


def permitted(client):
    created, mat, activation = paused(client)
    h, _ = handoff(client, created, mat, activation)
    p, _ = issue(client, created, mat, h)
    run = client.get(PREFIX + "/runs/" + created["runId"]).json()
    request = {"operationId": "dispatch", "expectedPermitId": p["permitId"],
               "expectedGraphId": mat["graphId"], "expectedGraphVersion": mat["graphVersion"],
               "expectedRuntimeRevision": run["runtimeRevision"]}
    return created, request


def endpoint(created):
    return base(created).removesuffix("/graph") + "/execution/dispatches"


def wait_run(client, created):
    for _ in range(400):
        response = client.get(PREFIX + "/runs/" + created["runId"])
        assert response.status_code == 200, response.text
        run = response.json()
        if run["status"] in {"completed", "failed", "waiting_review", "cancelled"}:
            return run
        time.sleep(.025)
    pytest.fail("Dispatch did not reach a lifecycle boundary")


def delivery_setup(runtime, coordinator):
    from examples.contract_review import WORKFLOW_ID
    from support.acg.native_capabilities import build_default_capability_catalog
    definition = runtime.workflow_registry.get(WORKFLOW_ID)
    output = build_default_capability_catalog().get("artifact_generation").output_contract
    runtime.workflow_registry.register(definition.model_copy(update={
        "planning_nodes": tuple(n.model_copy(update={"capability_requirements": ("artifact_generation",)})
                                if n.key == "step:C" else n for n in definition.planning_nodes),
        "steps": tuple(s.model_copy(update={"capability": "artifact_generation", "output_spec": output})
                       if s.step_id == "C" else s for s in definition.steps),
    }))


def test_http_dispatch_executes_once_with_checkpoint_audit_and_artifact(tmp_path):
    database(tmp_path)
    with server(tmp_path, dispatch=True, setup=delivery_setup) as (client, runtime, agent):
        created, request = permitted(client)
        assert not agent.calls
        trusted_call(client, ready_resource, runtime, created["runId"])
        response = client.post(endpoint(created), json=request)
        assert response.status_code == 202, response.text
        dispatch_id = response.json()["dispatchId"]
        final = wait_run(client, created)
        assert final["status"] == "completed", final
        assert agent.calls == ["A", "B", "C"]
        run = runtime.get_status(created["runId"])
        assert run.completed_step_ids == ["A", "B", "C"]
        commits = runtime.execution_value_store.list_node_commits(run_id=run.run_id)
        assert len(commits) == 3 and all(r["stage"] == "committed" for r in commits)
        for receipt in commits:
            trusted_call(client, lambda: runtime.decision_store.assert_decision(
                run_id=run.run_id, step_id=receipt["nodeExecution"]["stepId"],
                decision_ref=receipt["auditDecisionRef"], outcomes={"allow"}))
        checkpoint = trusted_call(client, lambda: runtime.checkpoint_store.load_latest(run_id=run.run_id))
        assert checkpoint[1]["executionPermitId"] == request["expectedPermitId"]
        assert set(checkpoint[1]["completedStepIds"]) == {"A", "B", "C"}
        artifacts = client.get(PREFIX + "/runs/" + run.run_id + "/artifacts")
        assert artifacts.status_code == 200 and artifacts.json()["total"] > 0, artifacts.text
        before = snapshot(runtime)
        replay = client.post(endpoint(created), json=request)
        assert replay.status_code == 202 and replay.json()["dispatchId"] == dispatch_id
        assert replay.json()["status"] == "IDEMPOTENT_REPLAY"
        assert snapshot(runtime) == before and agent.calls == ["A", "B", "C"]
        assert client.post(endpoint(created), json={**request, "operationId": "other"}).status_code == 409
    with server(tmp_path, dispatch=True, setup=delivery_setup) as (client, runtime, agent):
        assert wait_run(client, created)["status"] == "completed"
        assert client.post(endpoint(created), json=request).json()["dispatchId"] == dispatch_id
        assert not agent.calls and not runtime._active_execution_slots
        assert not runtime._test_coordinator.is_active(created["runId"])


def test_dispatch_schema_is_explicit_and_missing_marker_fails_closed(tmp_path):
    prepare(tmp_path)
    with pytest.raises((RuntimeError, sqlite3.Error)):
        with server(tmp_path, dispatch=True):
            pytest.fail("unupgraded Dispatch schema accepted")
    with server(tmp_path) as (client, runtime, agent):
        created, request = permitted(client)
        assert client.post(endpoint(created), json=request).status_code == 409
        assert not agent.calls
    SQLiteExecutionDispatchStore.upgrade_schema(tmp_path / "workflow.sqlite")
    with server(tmp_path, dispatch=True) as (client, runtime, agent):
        assert not agent.calls
        assert runtime.execution_dispatch_store.commands() == []


def test_dispatch_denies_forgery_stale_versions_and_untrusted_subjects(tmp_path):
    database(tmp_path)
    with server(tmp_path, dispatch=True) as (client, runtime, agent):
        created, request = permitted(client)
        for changed in ({"expectedPermitId": "forged"}, {"expectedGraphId": "forged"},
                        {"expectedGraphVersion": 2}, {"expectedRuntimeRevision": 999}):
            assert client.post(endpoint(created), json={**request, **changed}).status_code == 409
        for field in ("principal", "executionPermit", "checkpoint", "executionState"):
            assert client.post(endpoint(created), json={**request, field: {}}).status_code == 422
        for headers in ({"X-Authenticated-User-Id": "intruder"}, {"X-Authenticated-Tenant-Id": "other"}):
            assert client.post(endpoint(created), json=request, headers=headers).status_code == 403
        source, mat, activation = paused(client, "without-permit")
        assert client.post(endpoint(source), json=request).status_code == 409
        # A no-Permit Run and all rejection paths leave the journal empty.
        assert runtime.execution_dispatch_store.commands() == [] and not agent.calls
        after = snapshot(runtime)
        assert client.post(endpoint(created).replace(created["missionId"], source["missionId"]), json=request).status_code == 409
        assert snapshot(runtime) == after


def test_two_dispatch_keys_have_one_durable_owner(tmp_path):
    database(tmp_path)
    with server(tmp_path, dispatch=True) as (client, runtime, agent):
        created, request = permitted(client)
        trusted_call(client, ready_resource, runtime, created["runId"])
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda key: client.post(endpoint(created), json={**request, "operationId": key}), ("one", "two")))
        assert sorted(r.status_code for r in responses) == [202, 409]
        assert len(runtime.execution_dispatch_store.commands()) == 1
        assert wait_run(client, created)["status"] == "completed"
        assert agent.calls == ["A", "B", "C"]


@pytest.mark.parametrize("cut", ["before_task", "after_task"])
def test_dispatch_ack_loss_recovers_same_command(tmp_path, monkeypatch, cut):
    database(tmp_path)
    with server(tmp_path, dispatch=True) as (client, runtime, agent):
        created, request = permitted(client)
        trusted_call(client, ready_resource, runtime, created["runId"])
        coordinator = runtime._test_coordinator
        original = coordinator._create_permitted_task
        with monkeypatch.context() as patch:
            def fail(command):
                if cut == "after_task":
                    original(command)
                raise RuntimeError("private Dispatch ACK lost")
            patch.setattr(coordinator, "_create_permitted_task", fail)
            response = client.post(endpoint(created), json=request)
        assert response.status_code == 503 and "private" not in response.text
        command = runtime.execution_dispatch_store.get(created["runId"])
        assert command is not None
        replay = client.post(endpoint(created), json=request)
        assert replay.status_code == 202 and replay.json()["dispatchId"] == command.dispatch_id
        assert wait_run(client, created)["status"] == "completed"
        assert agent.calls == ["A", "B", "C"]


@pytest.mark.parametrize("change", ["cancel", "mission", "permission"])
def test_dispatch_drift_is_rejected_without_admission(tmp_path, monkeypatch, change):
    database(tmp_path)
    with server(tmp_path, dispatch=True) as (client, runtime, agent):
        created, request = permitted(client)
        if change == "cancel":
            assert client.post(PREFIX + "/runs/" + created["runId"] + "/cancel").status_code == 200
        elif change == "mission":
            assert client.post(f'{PREFIX}/missions/{created["missionId"]}/semantics', json={
                "operationId": "change", "expectedMissionRevision": 1, "objective": "Changed objective",
                "constraints": [], "sourceRefs": [],
            }).status_code == 200
        else:
            original = runtime.mission_semantic_service.authorize
            monkeypatch.setattr(runtime.mission_semantic_service, "authorize", lambda p, m, a: a == "read" and original(p, m, a))
        response = client.post(endpoint(created), json=request)
        assert response.status_code in {403, 409}, response.text
        assert runtime.execution_dispatch_store.commands() == [] and not agent.calls


def test_permit_without_dispatch_never_executes_after_restart(tmp_path):
    database(tmp_path)
    with server(tmp_path, dispatch=True) as (client, runtime, agent):
        created, request = permitted(client)
        assert not agent.calls
    with server(tmp_path, dispatch=True) as (client, runtime, agent):
        time.sleep(.1)
        assert not agent.calls and runtime.execution_dispatch_store.commands() == []
        assert runtime.get_status(created["runId"]).execution_state["executionPermitId"] == request["expectedPermitId"]


def test_accepted_command_unknown_side_effect_blocks_recovery(tmp_path, monkeypatch):
    database(tmp_path)
    with server(tmp_path, dispatch=True) as (client, runtime, agent):
        created, request = permitted(client)
        with monkeypatch.context() as patch:
            patch.setattr(runtime._test_coordinator, "_create_permitted_task", lambda command: (_ for _ in ()).throw(RuntimeError("cut")))
            assert client.post(endpoint(created), json=request).status_code == 503
        with sqlite3.connect(runtime.execution_value_store.db_path) as conn:
            conn.execute("INSERT INTO acg_node_executions(operation_id, run_id, payload_json, phase) VALUES(?,?,?,?)",
                         ("unknown-external-effect", created["runId"], "{}", "started"))
    with server(tmp_path, dispatch=True) as (client, runtime, agent):
        run = runtime.get_status(created["runId"])
        assert run.status == WorkflowStatus.FAILED and run.error["code"] == "dispatch_recovery_blocked"
        assert not agent.calls
        assert client.post(endpoint(created), json=request).status_code == 202
        assert not agent.calls


@pytest.mark.parametrize("mode,exit_code", [("admission", 73), ("effect", 74), ("checkpoint", 75)])
def test_real_process_death_dispatch_recovery(tmp_path, mode, exit_code):
    folder = tmp_path / "process"
    folder.mkdir()
    child = r'''
import json, os, sys
from pathlib import Path
from test_agentos_c2_dispatch_http import database, permitted, endpoint
from test_agentos_c2_http import server
from test_agentos_c2_permit_http import trusted_call, ready_resource
from examples.contract_review import ContractReviewAgent
folder, mode = Path(sys.argv[1]), sys.argv[2]
database(folder)
class Agent(ContractReviewAgent):
    async def run(self, context):
        with (folder / "effects.txt").open("a", encoding="utf-8") as stream:
            stream.write(context.step.step_id + "\n")
        if mode == "effect":
            os._exit(74)
        return await super().run(context)
def setup(rt, coordinator):
    if mode == "admission":
        coordinator._create_permitted_task = lambda command: os._exit(73)
    if mode == "checkpoint":
        original = rt.checkpoint_store.save
        def save(**kwargs):
            result = original(**kwargs)
            state = kwargs["state"]
            run = rt.workflow_store.get_run(kwargs["run_id"])
            if state.get("completedStepIds") == ["A"] and run.completed_step_ids == ["A"]:
                os._exit(75)
            return result
        rt.checkpoint_store.save = save
with server(folder, dispatch=True, setup=setup, agent_factory=Agent) as (client, runtime, agent):
    created, request = permitted(client)
    (folder / "request.json").write_text(json.dumps([created, request]), encoding="utf-8")
    trusted_call(client, ready_resource, runtime, created["runId"])
    response = client.post(endpoint(created), json=request)
    for _ in range(400):
        import time
        time.sleep(.025)
raise RuntimeError("requested crash cut not reached")
'''
    root = Path(__file__).resolve().parents[3]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(str(root / p) for p in ("apps/agent", "apps/agentOS", "apps/agentOS/src", "apps/agent/tests"))
    env["AGENT_CHROMA_PATH"] = str(folder / "chroma")
    result = subprocess.run([sys.executable, "-c", child, str(folder), mode], env=env, cwd=root,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    assert result.returncode == exit_code, result.stdout[-2500:] + result.stderr[-2500:]
    created, request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
    def setup(rt, coordinator):
        ready_resource(rt, created["runId"])
    with server(folder, dispatch=True, setup=setup) as (client, runtime, agent):
        final = wait_run(client, created)
        if mode == "effect":
            assert final["status"] == "failed" and not agent.calls
            assert runtime.get_status(created["runId"]).error["code"] == "dispatch_recovery_blocked"
        else:
            assert final["status"] == "completed", final
            assert agent.calls == (["A", "B", "C"] if mode == "admission" else ["B", "C"])
        assert client.post(endpoint(created), json=request).status_code == 202
        assert len(runtime.execution_dispatch_store.commands()) == 1
    assert not runtime._active_execution_slots
    assert not runtime._test_coordinator._tasks
    assert runtime._test_coordinator._wake_task.done()
    if mode != "admission":
        assert (folder / "effects.txt").read_text(encoding="utf-8").splitlines() == ["A"]


def test_cancel_after_native_slot_claim_does_not_invoke_agent(tmp_path, monkeypatch):
    database(tmp_path)
    with server(tmp_path, dispatch=True) as (client, runtime, agent):
        created, request = permitted(client)
        trusted_call(client, ready_resource, runtime, created["runId"])
        original = runtime._claim_acg_execution
        def claim(run):
            original(run)
            runtime.cancel(run.run_id)
        monkeypatch.setattr(runtime, "_claim_acg_execution", claim)
        assert client.post(endpoint(created), json=request).status_code == 202
        assert wait_run(client, created)["status"] == "cancelled"
        assert client.post(endpoint(created), json=request).status_code == 202
        assert not agent.calls
    assert not runtime._active_execution_slots and not runtime._test_coordinator._tasks


def test_review_pause_cannot_be_reactivated_by_dispatch_replay(tmp_path):
    database(tmp_path)
    class ReviewAgent(ContractReviewAgent):
        async def run(self, context):
            output = await super().run(context)
            return output.model_copy(update={"risk_level": "high"}) if context.step.step_id == "A" else output
    with server(tmp_path, dispatch=True, agent_factory=ReviewAgent) as (client, runtime, agent):
        created, request = permitted(client)
        trusted_call(client, ready_resource, runtime, created["runId"])
        assert client.post(endpoint(created), json=request).status_code == 202
        assert wait_run(client, created)["status"] == "waiting_review"
        assert not client.get(PREFIX + "/runs/" + created["runId"]).json()["formalControl"]["dispatchEligible"]
        before = snapshot(runtime)
        assert client.post(endpoint(created), json=request).status_code == 202
        assert agent.calls == ["A"] and snapshot(runtime) == before
        run = runtime.get_status(created["runId"])
        review = run.execution_state["reviewPayload"]
        response = client.post(PREFIX + "/runs/" + run.run_id + "/reviews", json={
            "operationId": "approve", "stepId": review.get("subjectId") or run.current_step_id,
            "decision": "approved", "expectedRunUpdatedAt": run.updated_at.isoformat(),
        })
        assert response.status_code == 200, response.text
        assert wait_run(client, created)["status"] == "completed"
        assert agent.calls == ["A", "B", "C"]


def test_cancel_races_dispatch_without_reactivating_run(tmp_path):
    database(tmp_path)
    class SlowAgent(ContractReviewAgent):
        async def run(self, context):
            await asyncio.sleep(.1)
            return await super().run(context)
    with server(tmp_path, dispatch=True, agent_factory=SlowAgent) as (client, runtime, agent):
        created, request = permitted(client)
        trusted_call(client, ready_resource, runtime, created["runId"])
        with ThreadPoolExecutor(max_workers=2) as pool:
            dispatch = pool.submit(client.post, endpoint(created), json=request)
            cancel = pool.submit(client.post, PREFIX + "/runs/" + created["runId"] + "/cancel")
            response, cancelled = dispatch.result(), cancel.result()
        assert response.status_code in {202, 409} and cancelled.status_code == 200
        assert wait_run(client, created)["status"] == "cancelled"
        calls = list(agent.calls)
        replay = client.post(endpoint(created), json=request)
        assert replay.status_code == (202 if runtime.execution_dispatch_store.get(created["runId"]) else 409)
        assert agent.calls == calls and "B" not in agent.calls
    assert not runtime._active_execution_slots and not runtime._test_coordinator._tasks


def test_shutdown_leaves_no_tasks_and_uncertain_invocation_is_blocked(tmp_path):
    database(tmp_path)
    class BlockingAgent(ContractReviewAgent):
        def __init__(self):
            super().__init__()
            self.entered = threading.Event()
        async def run(self, context):
            self.calls.append(context.step.step_id)
            self.entered.set()
            await asyncio.Event().wait()
    with server(tmp_path, dispatch=True, agent_factory=BlockingAgent) as (client, runtime, agent):
        created, request = permitted(client)
        trusted_call(client, ready_resource, runtime, created["runId"])
        assert client.post(endpoint(created), json=request).status_code == 202
        assert agent.entered.wait(5)
    assert not runtime._active_execution_slots and not runtime._test_coordinator._tasks
    assert runtime._test_coordinator._wake_task.done()
    with server(tmp_path, dispatch=True) as (client, reopened, agent):
        run = reopened.get_status(created["runId"])
        assert run.status == WorkflowStatus.FAILED and run.error["code"] == "dispatch_recovery_blocked"
        assert not agent.calls


def test_provider_failure_dispatch_replay_does_not_retry_node(tmp_path):
    database(tmp_path)
    class FailedProvider(ContractReviewAgent):
        async def run(self, context):
            self.calls.append(context.step.step_id)
            raise RuntimeError("provider connection failed after possible invocation")
    with server(tmp_path, dispatch=True, agent_factory=FailedProvider) as (client, runtime, agent):
        created, request = permitted(client)
        trusted_call(client, ready_resource, runtime, created["runId"])
        assert client.post(endpoint(created), json=request).status_code == 202
        assert wait_run(client, created)["status"] == "failed"
        assert client.post(endpoint(created), json=request).status_code == 202
        assert agent.calls == ["A"]
    with server(tmp_path, dispatch=True) as (client, runtime, agent):
        assert client.post(endpoint(created), json=request).status_code == 202
        assert not agent.calls


def test_mission_drift_at_durable_acceptance_boundary_is_revalidated(tmp_path, monkeypatch):
    from contracts.mission_semantic import MissionSemanticRequest
    database(tmp_path)
    with server(tmp_path, dispatch=True) as (client, runtime, agent):
        created, request = permitted(client)
        original = runtime.execution_dispatch_store.accept
        def drift(command, validate):
            runtime.mission_semantic_service.commit(runtime.semantic_principal_provider(), MissionSemanticRequest(
                missionId=created["missionId"], operationId="boundary-change", expectedMissionRevision=1,
                objective="Changed at submission", constraints=[], sourceRefs=[]))
            return original(command, validate)
        monkeypatch.setattr(runtime.execution_dispatch_store, "accept", drift)
        assert client.post(endpoint(created), json=request).status_code == 409
        assert runtime.execution_dispatch_store.commands() == [] and not agent.calls


def test_unknown_schema_or_corrupt_command_blocks_reconstruction(tmp_path, monkeypatch):
    database(tmp_path)
    with server(tmp_path, dispatch=True) as (client, runtime, agent):
        created, request = permitted(client)
        with monkeypatch.context() as patch:
            patch.setattr(runtime._test_coordinator, "_create_permitted_task", lambda c: (_ for _ in ()).throw(RuntimeError("cut")))
            assert client.post(endpoint(created), json=request).status_code == 503
    path = tmp_path / "workflow.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE execution_dispatch_schema SET version=2")
    with pytest.raises(RuntimeError, match="version 1"):
        with server(tmp_path, dispatch=True):
            pytest.fail("unsupported schema accepted")
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE execution_dispatch_schema SET version=1")
        conn.execute("UPDATE execution_dispatch_commands SET checksum=?", ("0" * 64,))
    with pytest.raises(ValueError, match="integrity failure"):
        with server(tmp_path, dispatch=True):
            pytest.fail("corrupt command accepted")
