"""Graph version reads follow confirmed Run lineage and retain reference-only evidence."""

from copy import deepcopy
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.agentos_v2 import create_router
from app.execution.coordinator import RunExecutionCoordinator
from app.security.internal_auth import TrustedUserContext, _trusted_user_context
from contracts import stable_checksum
from contracts.graph_activation import GraphActivationRecord
from contracts.graph_handoff import GraphHandoffRecord, GraphVersionIdentityLink, StagedGraphCheckpoint
from contracts.recovery import GraphPatch
from contracts.workflow import GraphRef
from domain.models import AcgBlueprint
from contracts.acg.schema import RuntimeBlueprintSpec
from support.stores.graph_activation_store import SQLiteGraphActivationStore
from support.stores.graph_handoff_store import SQLiteGraphHandoffStore
from support.stores.graph_materialization_store import SQLiteGraphMaterializationStore
from support.stores.planning_commit_store import SQLitePlanningCommitStore, content_fingerprint
from apps.agent.tests.test_agentos_v2_api import _runtime


@pytest.fixture
def history(tmp_path):
    runtime = _runtime(tmp_path, with_identity=True)
    mission = runtime.create_mission("graph history", workflow_id="api-workflow")
    _, run = runtime.prepare_run(mission.mission_id)
    repositories = runtime.identity_lifecycle.repositories
    identity = repositories.runs.get(run.run_id)
    first = repositories.blueprints.get(identity.blueprint_id)
    ledger_path = tmp_path / "graph-ledger.sqlite3"
    SQLitePlanningCommitStore.upgrade_schema(ledger_path)
    SQLiteGraphMaterializationStore.upgrade_schema(ledger_path)
    SQLiteGraphActivationStore.upgrade_schema(ledger_path)
    SQLiteGraphHandoffStore.upgrade_schema(ledger_path)
    ledger = SQLiteGraphHandoffStore(ledger_path)
    runtime.graph_handoff_authority = SimpleNamespace(store=ledger)
    runtime.graph_activation_authority = SimpleNamespace(store=ledger)
    commits = {}
    runtime.planning_commit_authority = SimpleNamespace(get_commit=commits.get)

    def append(version, *, projected=True, status="STATE_PREPARED", activation_status="ACTIVATED_PAUSED", handoff=True):
        old = repositories.blueprints.get(repositories.runs.get(run.run_id).blueprint_id)
        graph = deepcopy(run.acg_blueprint)
        graph["version"] = version
        graph["nodes"].append({"nodeId": f"extra-{version}", "nodeType": "step", "name": f"Extra {version}", "capability": "analysis"})
        blueprint = AcgBlueprint(missionId=run.mission_id, version=version + 10,
            graphId=graph["graphId"], graph=graph, metadata={"plannerPlanVersion": version})
        if projected:
            repositories.blueprints.add(blueprint)
            repositories.runs.update_blueprint(run.run_id, blueprint.blueprint_id, blueprint.version)
        candidate = StagedGraphCheckpoint(checkpointId=f"staged:{version}", handoffId=f"handoff:{version}",
            runId=run.run_id, activationId=f"activation:{version}", graphVersion=version,
            packageChecksum="a" * 64, state={"runId": run.run_id, "graphId": graph["graphId"],
                "graphVersion": version, "checkpointId": f"staged:{version}", "activeStepIds": [],
                "reviewPayload": None, "currentStepId": None, "completedStepIds": ["report"],
                "skippedStepIds": [], "outputRefs": {"report": "output:retained"},
                "privateBody": "DO-NOT-EXPOSE-HISTORICAL-BODY"})
        handoff_record = GraphHandoffRecord(handoffId=f"handoff:{version}", idempotencyKey=f"handoff-key:{version}",
            runId=run.run_id, activationId=f"activation:{version}", graphVersion=version,
            sourceCheckpointId=f"source:{version}", sourceCheckpointVersion=1,
            sourceCheckpointFingerprint="b" * 64, prefixFingerprint="c" * 64, sourcesFingerprint="d" * 64,
            identityLink=GraphVersionIdentityLink(runId=run.run_id, sourceBlueprintId=old.blueprint_id,
                sourceGraph=GraphRef(graphId=graph["graphId"], version=str(version - 1)),
                candidateGraph=GraphRef(graphId=graph["graphId"], version=str(version)),
                sourceIdentityFingerprint="e" * 64, candidatePackageChecksum="a" * 64,
                prefixAttemptIds=("attempt:retained",)), candidate=candidate,
            candidateFingerprint=stable_checksum(candidate), status=status)
        activation = GraphActivationRecord(activationId=f"activation:{version}", idempotencyKey=f"activation-key:{version}",
            materializationId=f"materialization:{version}", sourceCommitId=f"commit:{version}",
            missionId=run.mission_id, runId=run.run_id, graphId=graph["graphId"],
            sourceGraphVersion=version - 1, candidateGraphVersion=version,
            packageChecksum="a" * 64, commitmentFingerprint="f" * 64, proofFingerprint="0" * 64,
            status=activation_status)
        with ledger._transaction():
            ledger._append_activation(activation)
            if handoff:
                ledger._append_handoff(handoff_record)
        patch = GraphPatch(patchId=f"patch:{version}", graphId=graph["graphId"],
            baseGraphVersion=version - 1, graphVersion=version, addedNodes=({"nodeId": f"extra-{version}"},),
            reason=f"Read the next evidence page {version}")
        commits[f"commit:{version}"] = SimpleNamespace(status="ACCEPTED", mission_id=run.mission_id,
            proposal_type="graph_revision", proposal_payload=SimpleNamespace(mission_id=run.mission_id,
                graph_patch=patch, candidate_graph=RuntimeBlueprintSpec.model_validate(graph),
                source_provenance=SimpleNamespace(source_run_id=run.run_id, graph_id=graph["graphId"]),
                safe_cut=SimpleNamespace(source_graph_fingerprint=content_fingerprint(RuntimeBlueprintSpec.model_validate(old.graph)),
                    candidate_graph_fingerprint=content_fingerprint(RuntimeBlueprintSpec.model_validate(graph)))))
        run.acg_blueprint = graph
        run.execution_state.update(graphId=graph["graphId"], graphVersion=version, taskPlanVersion=version)
        runtime.workflow_store.save_run(run)
        return blueprint, handoff_record

    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))
    return SimpleNamespace(runtime=runtime, run=run, repositories=repositories, first=first,
        append=append, ledger=ledger, commits=commits, client=TestClient(app))


def test_version_chain_uses_runtime_versions_and_only_handoff_inherited_evidence(history):
    second, _ = history.append(2)
    third, _ = history.append(3)
    before = history.runtime.workflow_store.get_run(history.run.run_id).model_dump(mode="json")

    response = history.client.get(f"/agentos/v2/runs/{history.run.run_id}/graph/versions")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["currentGraphVersion"] == 3 and body["currentBlueprintId"] == third.blueprint_id
    assert [item["graphVersion"] for item in body["items"]] == [1, 2, 3]
    assert [item["blueprintId"] for item in body["items"]] == [history.first.blueprint_id, second.blueprint_id, third.blueprint_id]
    assert [item["current"] for item in body["items"]] == [False, False, True]
    assert body["items"][1]["predecessorBlueprintId"] == history.first.blueprint_id
    assert body["items"][2]["patch"]["addedNodeIds"] == ["extra-3"]
    assert body["items"][2]["reason"] == "Read the next evidence page 3"
    assert body["items"][1]["inherited"] == {"completedStepIds": ["report"], "skippedStepIds": [],
        "attemptIds": ["attempt:retained"], "outputRefs": {"report": "output:retained"}}
    assert body["items"][0]["inherited"]["completedStepIds"] == []
    assert "DO-NOT-EXPOSE" not in response.text and '"nodes"' not in response.text
    assert history.runtime.workflow_store.get_run(history.run.run_id).model_dump(mode="json") == before
    current = history.client.get(f"/agentos/v2/runs/{history.run.run_id}/graph")
    assert current.status_code == 200 and current.json()["graphVersion"] == 3


def test_historical_snapshot_has_no_current_runtime_status_or_resource_overlay(history):
    history.append(2)
    history.run.completed_step_ids = ["extra-2"]
    history.run.execution_state["resourceBindings"] = {"extra-2": "live-resource"}
    history.runtime.workflow_store.save_run(history.run)

    response = history.client.get(f"/agentos/v2/runs/{history.run.run_id}/graph",
        params={"blueprintId": history.first.blueprint_id})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["historical"] and body["graphVersion"] == 1
    assert "extra-2" not in {node["nodeId"] for node in body["nodes"]}
    assert not {"completedStepIds", "activeStepIds", "resourceBindings", "stepStates", "workspaceReview"} & body.keys()


def test_snapshot_cannot_select_an_unrelated_mission_branch(history):
    history.append(2)
    sibling = AcgBlueprint(missionId=history.run.mission_id, graphId=history.run.acg_blueprint["graphId"],
        version=99, graph={**history.run.acg_blueprint, "version": 8})
    history.repositories.blueprints.add(sibling)

    response = history.client.get(f"/agentos/v2/runs/{history.run.run_id}/graph",
        params={"blueprintId": sibling.blueprint_id})

    assert response.status_code == 404


def test_unactivated_or_staging_candidate_does_not_become_a_historical_version(history):
    history.append(2)
    active_graph = deepcopy(history.run.acg_blueprint)
    history.append(3, projected=False, status="STAGING", activation_status="ACTIVATION_PREPARED")
    history.run.acg_blueprint = active_graph
    history.run.execution_state.update(graphVersion=2, taskPlanVersion=2)
    history.runtime.workflow_store.save_run(history.run)

    response = history.client.get(f"/agentos/v2/runs/{history.run.run_id}/graph/versions")

    assert response.status_code == 200, response.text
    assert [item["graphVersion"] for item in response.json()["items"]] == [1, 2]
    assert response.json()["proposals"] == []


def test_paused_activation_does_not_invent_an_identity_snapshot_or_creation_time(history):
    history.append(2, projected=False)

    response = history.client.get(f"/agentos/v2/runs/{history.run.run_id}/graph/versions")
    graph = history.client.get(f"/agentos/v2/runs/{history.run.run_id}/graph")

    assert response.status_code == graph.status_code == 200
    current = response.json()["items"][-1]
    assert current["graphVersion"] == graph.json()["graphVersion"] == 2
    assert current["current"] and current["status"] == "active"
    assert current["blueprintId"] is current["createdAt"] is None
    assert graph.json()["blueprintId"] is None


def test_activation_before_handoff_retains_its_proven_source_graph(history):
    history.append(2, projected=False, handoff=False)

    response = history.client.get(f"/agentos/v2/runs/{history.run.run_id}/graph/versions")
    previous = history.client.get(f"/agentos/v2/runs/{history.run.run_id}/graph",
        params={"blueprintId": history.first.blueprint_id})

    assert response.status_code == previous.status_code == 200
    assert [item["graphVersion"] for item in response.json()["items"]] == [1, 2]
    current = response.json()["items"][-1]
    assert current["predecessorBlueprintId"] == history.first.blueprint_id
    assert current["activationId"] == "activation:2" and current["handoffId"] is None
    assert current["reason"] == "Read the next evidence page 2"
    assert current["inherited"] == {"completedStepIds": [], "skippedStepIds": [], "attemptIds": [], "outputRefs": {}}
    assert previous.json()["historical"] and previous.json()["graphVersion"] == 1


@pytest.mark.parametrize("invalid_proof", ["source_graph_fingerprint", "source_run_id", "status"])
def test_activation_source_requires_exact_graph_and_accepted_run_proof(history, invalid_proof):
    history.append(2, projected=False, handoff=False)
    commit = history.commits["commit:2"]
    if invalid_proof == "source_graph_fingerprint":
        commit.proposal_payload.safe_cut.source_graph_fingerprint = "0" * 64
    elif invalid_proof == "source_run_id":
        commit.proposal_payload.source_provenance.source_run_id = "another-run"
    else:
        commit.status = "REJECTED"

    response = history.client.get(f"/agentos/v2/runs/{history.run.run_id}/graph/versions")
    previous = history.client.get(f"/agentos/v2/runs/{history.run.run_id}/graph",
        params={"blueprintId": history.first.blueprint_id})

    assert response.status_code == 200
    assert [item["graphVersion"] for item in response.json()["items"]] == [2]
    assert response.json()["items"][0]["predecessorBlueprintId"] is None
    assert previous.status_code == 404


@pytest.mark.parametrize("suffix", ["/graph/versions", "/graph?blueprintId=nonexistent"])
def test_graph_history_keeps_run_owner_authorization(history, suffix):
    actor = TrustedUserContext(user_id="other", subject="other", role="operator", tenant_id="other-tenant")
    token = _trusted_user_context.set(actor)
    try:
        response = history.client.get(f"/agentos/v2/runs/{history.run.run_id}{suffix}")
    finally:
        _trusted_user_context.reset(token)
    assert response.status_code == 404


def test_corrupt_handoff_is_not_presented_as_verified_graph_history(history):
    history.append(2)
    with history.ledger.connection() as conn, conn:
        conn.execute("UPDATE graph_handoffs SET checksum=?", ("0" * 64,))

    response = history.client.get(f"/agentos/v2/runs/{history.run.run_id}/graph/versions")

    assert response.status_code == 409


def test_current_graph_without_identity_can_be_browsed_without_claiming_history(tmp_path):
    runtime = _runtime(tmp_path, with_identity=True)
    mission = runtime.create_mission("legacy graph", workflow_id="api-workflow")
    _, run = runtime.prepare_run(mission.mission_id)
    runtime.identity_lifecycle = None
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))
    response = TestClient(app).get(f"/agentos/v2/runs/{run.run_id}/graph/versions")
    assert response.status_code == 200
    assert response.json()["currentBlueprintId"] is None
    assert [item["graphVersion"] for item in response.json()["items"]] == [1]
    assert response.json()["proposals"] == []
