"""Real business input -> v2 native execution -> canonical artifact and HTTP."""
import asyncio
import hashlib
import json
import multiprocessing
import os
from pathlib import Path

import pytest

from contracts.workflow import WorkflowStatus
from examples.contract_review import CONTRACT, open_runtime, prepare_revision, result_projection


def _crash_after_B(folder, run_id):
    rt, agent = open_runtime(Path(folder))
    original = agent.run
    async def record(context):
        with (Path(folder) / "external-calls.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"step": context.step.step_id}) + "\n")
            stream.flush()
        return await original(context)
    agent.run = record
    def checkpoint_committed():
        _, payload = rt.checkpoint_store.load_latest(run_id=run_id)
        if "B" in payload["completedStepIds"]:
            os._exit(81)
    rt.acg_state_persistence.after_checkpoint_hook = checkpoint_committed
    asyncio.run(rt.execute_prepared_run(run_id))
    os._exit(89)


@pytest.mark.freeze_gate
@pytest.mark.slow_multiprocess
def test_contract_revision_restart_delivers_canonical_artifact_and_http(tmp_path, monkeypatch):
    folder = tmp_path / "contract"
    first, agent, run_id = asyncio.run(prepare_revision(folder))
    before = first.workflow_store.get_run(run_id)
    assert agent.calls == ["A"] and before.completed_step_ids == ["A"]
    assert before.execution_state["graphVersion"] == 2
    permit = first.execution_permit_authority.store.get_permit(before.execution_state["executionPermitId"])
    assert permit.status == "ISSUED" and permit.graph_version == 2
    query_before = result_projection(first, run_id)
    assert not query_before["artifacts"]
    cp_A = first.checkpoint_store.load(run_id=run_id, checkpoint_id=permit.source_checkpoint_id)
    promoted = first.checkpoint_store.load(run_id=run_id, checkpoint_id=permit.promoted_checkpoint_id)
    receipts_A = first.execution_value_store.list_node_commits(run_id=run_id)
    child = multiprocessing.get_context("spawn").Process(target=_crash_after_B, args=(str(folder), run_id))
    child.start(); child.join(35)
    if child.is_alive():
        child.terminate(); child.join(5)
        pytest.fail("native contract process failed to reach real crash cut")
    assert child.exitcode == 81
    resumed, new_agent = open_runtime(folder)
    unconfirmed = resumed.workflow_store.get_run(run_id)
    head, cp_B = resumed.checkpoint_store.load_latest(run_id=run_id)
    assert cp_B["completedStepIds"] == ["A", "B"]
    assert unconfirmed.completed_step_ids == ["A", "B"]
    assert head != unconfirmed.execution_state["checkpointId"]
    confirmed = resumed.reconcile_execution_checkpoint(run_id)
    assert confirmed.execution_state["checkpointId"] == head
    assert resumed.reconcile_execution_checkpoint(run_id) == confirmed
    with pytest.raises(ValueError):
        resumed.workflow_store.save_run(unconfirmed)
    completed = asyncio.run(resumed.execute_prepared_run(run_id))
    assert completed.status == WorkflowStatus.COMPLETED, completed.error
    assert new_agent.calls == ["C", "D"]
    assert (folder / "external-calls.jsonl").read_text(encoding="utf-8").splitlines() == ['{"step": "B"}']
    assert resumed.checkpoint_store.load(run_id=run_id, checkpoint_id=permit.source_checkpoint_id) == cp_A
    assert resumed.checkpoint_store.load(run_id=run_id, checkpoint_id=permit.promoted_checkpoint_id) == promoted
    receipts = resumed.execution_value_store.list_node_commits(run_id=run_id)
    assert len(receipts) == 4 and all(r["stage"] == "committed" for r in receipts)
    assert receipts[0] == receipts_A[0]
    for r in receipts[1:]:
        assert permit.attempt_generation in r["commitId"]
        attempt = resumed.identity_lifecycle.repositories.attempts.get(r["nodeExecution"]["attemptId"])
        assert attempt.run_id == run_id and attempt.status.value == "succeeded"
    projection = result_projection(resumed, run_id)
    assert len(projection["artifacts"]) == 1
    artifact = projection["artifacts"][0]["artifact"]
    assert artifact["artifactType"] == "run_deliverable" and artifact["artifactKey"] == "final"
    assert artifact["originRunId"] == run_id and artifact["acgNodeId"] == "D"
    assert artifact["producerAttemptId"] == next(r for r in receipts if ":D:" in r["commitId"])["nodeExecution"]["attemptId"]
    entries = projection["workspace"]["entries"]
    assert [e["artifactId"] for e in entries if e.get("kind") == "artifact" and e.get("group") == "output"] == [artifact["artifactId"]]
    # Exercise the existing production HTTP router, not a replacement API.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "agent"))
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.agentos_v2 import create_router
    from app.execution.coordinator import RunExecutionCoordinator
    from app.security.internal_auth import InternalServiceAuthMiddleware
    from examples.contract_review import OWNER
    app = FastAPI()
    token = "local-c1-integration-test-token-00000001"
    app.add_middleware(InternalServiceAuthMiddleware, token=token)
    app.include_router(create_router(resumed, RunExecutionCoordinator(resumed)))
    headers = {"x-internal-service-token": token, "x-authenticated-user-id": OWNER.actor_id,
        "x-authenticated-user-subject": "local-test", "x-authenticated-user-role": "user", "x-authenticated-tenant-id": OWNER.tenant_id}
    with TestClient(app, headers=headers) as client:
        listing = client.get(f"/agentos/v2/runs/{run_id}/artifacts")
        assert listing.status_code == 200 and listing.json()["total"] == 1
        workspace = client.get(f"/agentos/v2/missions/{completed.mission_id}/workspace", params={"runId": run_id})
        assert workspace.status_code == 200
        content = client.get(f"/agentos/v2/runs/{run_id}/artifacts/{artifact['artifactId']}/fragments")
        assert content.status_code == 200, content.text
        by_manifest = client.get(f"/agentos/v2/runs/{run_id}/artifacts/{artifact['contentRef']}/fragments")
        assert by_manifest.status_code == 200 and by_manifest.json()["items"] == content.json()["items"]
        body = "".join(item["content"] for item in content.json()["items"])
        assert "800000" in body and "240000" in body and "560000" in body
        assert "验收" in body and "知识产权" in body
        assert hashlib.sha256(body.encode()).hexdigest() == artifact["checksum"]
    replay = asyncio.run(resumed.execute_prepared_run(run_id))
    assert replay.status == WorkflowStatus.COMPLETED and new_agent.calls == ["C", "D"]
    assert result_projection(resumed, run_id)["artifacts"] == projection["artifacts"]
    evidence = Path(__file__).resolve().parents[4] / "tmp" / "c1-evidence.json"
    evidence.parent.mkdir(exist_ok=True)
    activation = resumed.execution_permit_authority.store.get_activation(permit.activation_id)
    revision = resumed.planning_commit_authority.store.get(activation.source_commit_id)
    evidence.write_text(json.dumps({"missionId": completed.mission_id, "runId": run_id,
        "graphRevisionCommitId": revision.commit_id, "sourcePlanningCommitId": revision.parent_commit_id,
        "commitmentRevision": revision.commitment_revision,
        "graphVersion": 2, "permit": permit.model_dump(mode="json", by_alias=True),
        "checkpointBeforeAck": head, "receiptIds": [r["commitId"] for r in receipts],
        "artifact": artifact, "body": body, "workspaceHttpStatus": workspace.status_code,
        "artifactHttpStatus": content.status_code}, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.freeze_gate
def test_invalid_contract_and_cancel_never_claim_final_success(tmp_path):
    rt, agent = open_runtime(tmp_path / "invalid", initialize=True)
    # Even invalid text goes through the real Agent/Runtime; no generated outputs.
    from examples.contract_review import WORKFLOW_ID, OWNER
    from contracts.mission_semantic import MissionSemanticRequest
    mission = rt.create_mission("invalid", workflow_id=WORKFLOW_ID, input={"contractText": "missing required terms", "deterministicIntent": True})
    rt.mission_semantic_service.commit(OWNER, MissionSemanticRequest(missionId=mission.mission_id,
        operationId="basis", expectedMissionRevision=0, objective="review", constraints=[], sourceRefs=["input:contractText"]))
    _, run = rt.prepare_run(mission.mission_id)
    failed = asyncio.run(rt.execute_prepared_run(run.run_id))
    assert failed.status != WorkflowStatus.COMPLETED and not result_projection(rt, run.run_id)["artifacts"]
    assert not any(r["stage"] == "committed" for r in rt.execution_value_store.list_node_commits(run_id=run.run_id))
    rt2, agent2, rid = asyncio.run(prepare_revision(tmp_path / "cancel"))
    rt2.cancel(rid)
    assert asyncio.run(rt2.execute_prepared_run(rid)).status == WorkflowStatus.CANCELLED
    assert agent2.calls == ["A"] and not result_projection(rt2, rid)["artifacts"]


@pytest.mark.freeze_gate
def test_sample_refuses_existing_or_non_sample_directories(tmp_path):
    with pytest.raises(FileExistsError):
        open_runtime(tmp_path, initialize=True)
    with pytest.raises(ValueError):
        open_runtime(tmp_path)
    assert list(tmp_path.iterdir()) == []
