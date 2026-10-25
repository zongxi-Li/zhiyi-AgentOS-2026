"""HTTP Handoff/Permit saga and live eligibility against production authorities."""
import inspect
import sqlite3

import pytest

from app.security.internal_auth import TrustedUserContext, _trusted_user_context
from runtime.execution_permit import ExecutionPermitError
from test_agentos_c2_http import (
    PREFIX, accepted, activation_body, base, create, materialize, prepare, server,
)


def trusted_call(client, function, *args):
    """Exercise the existing Runtime path on its owning server thread."""
    async def invoke():
        token = _trusted_user_context.set(TrustedUserContext("owner", "test-owner", "user", "tenant"))
        try:
            value = function(*args)
            return await value if inspect.isawaitable(value) else value
        finally:
            _trusted_user_context.reset(token)
    return client.portal.call(invoke)


def snapshot(runtime):
    result = {}
    for path in (runtime.workflow_store.db_path, runtime.checkpoint_store.db_path,
                 runtime.execution_value_store.db_path, runtime.identity_lifecycle.repositories.storage.db_path):
        with sqlite3.connect(path) as conn:
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            result[str(path)] = {table: conn.execute('SELECT * FROM "' + table.replace('"', '""') + '" ORDER BY rowid').fetchall()
                                 for table in tables}
    return result


def paused(client, key="create"):
    created, _ = create(client, key)
    mat, _ = materialize(client, created, accepted(client, created))
    response = client.post(base(created) + "/activation", json=activation_body(mat))
    assert response.status_code == 200, response.text
    return created, mat, response.json()


def handoff_body(mat, activation):
    return {"operationId": "handoff", "activationId": activation["activationId"],
            "expectedGraphId": mat["graphId"], "expectedGraphVersion": mat["graphVersion"]}


def handoff(client, created, mat, activation):
    body = handoff_body(mat, activation)
    response = client.post(base(created) + "/handoffs", json=body)
    assert response.status_code == 200 and response.json()["status"] == "STATE_PREPARED", response.text
    return response.json(), body


def permit_body(mat, handoff):
    return {"operationId": "permit", "handoffId": handoff["handoffId"],
            "expectedGraphId": mat["graphId"], "expectedGraphVersion": mat["graphVersion"]}


def issue(client, created, mat, handoff):
    body = permit_body(mat, handoff)
    response = client.post(base(created) + "/permits", json=body)
    assert response.status_code == 200 and response.json()["status"] == "ISSUED", response.text
    return response.json(), body


def control(client, created):
    response = client.get(PREFIX + "/runs/" + created["runId"])
    assert response.status_code == 200, response.text
    return response.json()["formalControl"]


def ready_resource(runtime, run_id):
    from contracts.resource import ExecutionRequirement, RuntimeProfile, Placement
    run = runtime.workflow_store.get_run(run_id)
    requirement = ExecutionRequirement.model_validate(next(iter(run.execution_state["bindingRequirements"].values())))
    plane = runtime.resource_plane
    placement = requirement.allowed_placements[0] if requirement.allowed_placements else Placement.DEVICE
    plane.ensure_node("node:http-permit-test", placement=placement)
    plane.register_runtime(RuntimeProfile(runtimeId="runtime:http-permit-test", nodeId="node:http-permit-test",
        placement=placement, kind=requirement.runtime_kinds[0], capabilities=list(requirement.required_capabilities),
        trust=requirement.min_trust or "host_trusted", domains=[requirement.domain] if requirement.domain else []))
    plane.heartbeat_runtime("runtime:http-permit-test")
    assert runtime.resource_binder.assess(requirement).ready


def test_http_full_permit_chain_gate_execution_and_restart(tmp_path):
    prepare(tmp_path)
    with server(tmp_path) as (client, runtime, agent):
        created, mat, activation = paused(client)
        h, hbody = handoff(client, created, mat, activation)
        before = snapshot(runtime)
        replay = client.post(base(created) + "/handoffs", json=hbody)
        assert replay.status_code == 200 and replay.json()["status"] == "IDEMPOTENT_REPLAY"
        assert replay.json()["handoffId"] == h["handoffId"]
        assert client.post(base(created) + "/handoffs", json={**hbody, "operationId": "competing"}).status_code == 409
        assert snapshot(runtime) == before
        status = control(client, created)
        assert status["status"] == "ACTIVATED_PAUSED"
        assert not status["permitIssued"] and not status["dispatchEligible"]
        with pytest.raises(ExecutionPermitError):
            trusted_call(client, runtime.execute_prepared_run, created["runId"])
        p, pbody = issue(client, created, mat, h)
        before = snapshot(runtime)
        replay = client.post(base(created) + "/permits", json=pbody)
        assert replay.status_code == 200 and replay.json()["permitId"] == p["permitId"]
        assert replay.json()["status"] == "IDEMPOTENT_REPLAY"
        assert client.post(base(created) + "/permits", json={**pbody, "operationId": "competing"}).status_code == 409
        replay = client.post(base(created) + "/handoffs", json=hbody)
        assert replay.status_code == 200 and replay.json()["handoffId"] == h["handoffId"]
        assert snapshot(runtime) == before
        status = control(client, created)
        assert status["permitIssued"] and status["dispatchEligible"] and status["executionAuthorized"]
        assert snapshot(runtime) == before  # eligibility is a read, never reconciliation
        assert not agent.calls and not runtime.execution_value_store.list_node_commits(run_id=created["runId"])
        trusted_call(client, runtime.execution_permit_authority.assert_dispatchable, runtime.get_status(created["runId"]))
        public = str([h, p, status])
        for sensitive in ("checkpointId", "principalFingerprint", "candidate", "packageChecksum", "sourcesFingerprint", "signature"):
            assert sensitive not in public
    with server(tmp_path) as (client, runtime, agent):
        assert control(client, created)["dispatchEligible"]
        before = snapshot(runtime)
        replay = client.post(base(created) + "/permits", json=pbody)
        assert replay.status_code == 200 and replay.json()["permitId"] == p["permitId"]
        assert client.post(base(created) + "/handoffs", json=hbody).json()["handoffId"] == h["handoffId"]
        assert snapshot(runtime) == before
        # No HTTP control silently submits a planning Run to the Coordinator.
        trusted_call(client, ready_resource, runtime, created["runId"])
        result = trusted_call(client, runtime.execute_prepared_run, created["runId"])
        assert agent.calls and agent.calls[0] == "A"
        assert len(agent.calls) == len(set(agent.calls))
        assert set(result.completed_step_ids) == set(agent.calls)
        calls = list(agent.calls)
        trusted_call(client, runtime.execute_prepared_run, created["runId"])
        assert agent.calls == calls
        # A terminal or review barrier is not another permission to dispatch.
        status = control(client, created)
        assert status["permitIssued"]
        if result.status.value in {"completed", "failed", "cancelled", "superseded"}:
            assert not status["dispatchEligible"] and not status["executionAuthorized"]


def test_http_sources_versions_ownership_and_forgery_rejected(tmp_path):
    prepare(tmp_path)
    with server(tmp_path) as (client, runtime, agent):
        created, mat, activation = paused(client)
        other, omat, oactivation = paused(client, "other")
        before = snapshot(runtime)
        hbody = handoff_body(mat, activation)
        missing = {"handoffId": "not-prepared", "operationId": "permit", "expectedGraphId": mat["graphId"], "expectedGraphVersion": 1}
        assert client.post(base(created) + "/permits", json=missing).status_code == 409
        for change in ({"expectedGraphId": "wrong"}, {"expectedGraphVersion": 99}, {"activationId": oactivation["activationId"]}):
            assert client.post(base(created) + "/handoffs", json={**hbody, **change}).status_code == 409
        for headers in ({"X-Authenticated-User-Id": "intruder"}, {"X-Authenticated-Tenant-Id": "other"}):
            assert client.post(base(created) + "/handoffs", json=hbody, headers=headers).status_code == 403
        assert snapshot(runtime) == before
        fake = runtime.get_status(created["runId"]).model_copy(deep=True)
        fake.execution_state["graphActivation"]["executionPermit"] = {"permitId": "forged"}
        with pytest.raises(ExecutionPermitError):
            trusted_call(client, runtime.execution_permit_authority.assert_dispatchable, fake)
        h, _ = handoff(client, created, mat, activation)
        oh, _ = handoff(client, other, omat, oactivation)
        pbody = permit_body(mat, h)
        issue(client, created, mat, h)
        before = snapshot(runtime)
        assert client.post(base(created) + "/handoffs", json={**hbody, "activationId": oactivation["activationId"]}).status_code == 409
        for change in ({"expectedGraphId": "wrong"}, {"expectedGraphVersion": 2}, {"handoffId": oh["handoffId"]}):
            assert client.post(base(created) + "/permits", json={**pbody, **change}).status_code == 409
        for endpoint, body in (("handoffs", hbody), ("permits", pbody)):
            for field in ("principal", "permitRecord", "executionPermit", "identity", "checkpoint", "executionReceipt", "stagedCheckpoint"):
                assert client.post(base(created) + "/" + endpoint, json={**body, field: {}}).status_code == 422
            for headers in ({"X-Authenticated-User-Id": "intruder"}, {"X-Authenticated-Tenant-Id": "other"}):
                assert client.post(base(created) + "/" + endpoint, json=body, headers=headers).status_code == 403
        assert snapshot(runtime) == before and not agent.calls


@pytest.mark.parametrize("cut", ["stage_ack", "confirmation", "checkpoint_ack", "identity_ack", "issue_transaction"])
def test_http_saga_real_store_failure_and_restart_convergence(tmp_path, monkeypatch, cut):
    prepare(tmp_path)
    with server(tmp_path) as (client, runtime, agent):
        created, mat, activation = paused(client)
        hbody = handoff_body(mat, activation)
        with monkeypatch.context() as patch:
            if cut in {"stage_ack", "confirmation"}:
                target = runtime.graph_handoff_authority.staged_store if cut == "stage_ack" else runtime.graph_handoff_authority.store
                method = "stage" if cut == "stage_ack" else "_confirm_handoff"
                original = getattr(target, method)
                def fail(*args, **kwargs):
                    original(*args, **kwargs)
                    raise sqlite3.OperationalError("real write occurred; private ACK lost")
                patch.setattr(target, method, fail)
                response = client.post(base(created) + "/handoffs", json=hbody)
            else:
                h, _ = handoff(client, created, mat, activation)
                pbody = permit_body(mat, h)
                if cut == "issue_transaction":
                    with sqlite3.connect(runtime.workflow_store.db_path) as conn:
                        conn.execute("CREATE TRIGGER http_deny_issue BEFORE UPDATE ON graph_execution_permits WHEN NEW.status='ISSUED' BEGIN SELECT RAISE(ABORT,'issue fault'); END")
                else:
                    target = runtime.checkpoint_store if cut == "checkpoint_ack" else runtime.identity_lifecycle
                    method = "save_promoted" if cut == "checkpoint_ack" else "on_run_prepared"
                    original = getattr(target, method)
                    def fail(*args, **kwargs):
                        original(*args, **kwargs)
                        raise sqlite3.OperationalError("external transaction committed; private ACK lost")
                    patch.setattr(target, method, fail)
                response = client.post(base(created) + "/permits", json=pbody)
        assert response.status_code == 503, response.text
        assert "private" not in response.text
        status = control(client, created)
        assert not status["permitIssued"] and not status["dispatchEligible"] and not status["executionAuthorized"]
        with pytest.raises(ExecutionPermitError):
            trusted_call(client, runtime.execute_prepared_run, created["runId"])
        assert not agent.calls
        if cut == "issue_transaction":
            with sqlite3.connect(runtime.workflow_store.db_path) as conn:
                conn.execute("DROP TRIGGER http_deny_issue")
    with server(tmp_path) as (client, runtime, agent):
        if cut in {"stage_ack", "confirmation"}:
            response = client.post(base(created) + "/handoffs", json=hbody)
            assert response.status_code == 200 and response.json()["status"] == "STATE_PREPARED", response.text
            pbody = permit_body(mat, response.json())
        response = client.post(base(created) + "/permits", json=pbody)
        assert response.status_code == 200 and response.json()["status"] == "ISSUED", response.text
        before = snapshot(runtime)
        replay = client.post(base(created) + "/permits", json=pbody)
        assert replay.json()["permitId"] == response.json()["permitId"]
        assert snapshot(runtime) == before
        assert control(client, created)["dispatchEligible"] and not agent.calls


@pytest.mark.parametrize("change", ["cancel", "terminal", "mission", "permission", "checkpoint", "source", "identity", "authority"])
def test_http_historical_issuance_is_not_current_dispatch_authority(tmp_path, monkeypatch, change):
    prepare(tmp_path)
    with server(tmp_path) as (client, runtime, agent):
        created, mat, activation = paused(client)
        h, _ = handoff(client, created, mat, activation)
        _, pbody = issue(client, created, mat, h)
        assert control(client, created)["dispatchEligible"]
        if change == "cancel":
            response = client.post(PREFIX + "/runs/" + created["runId"] + "/cancel")
            assert response.status_code == 200, response.text
        elif change == "terminal":
            async def terminalize():
                await runtime.fail_run_safely(created["runId"], error_code="test_terminal", error_message="test terminal boundary")
            trusted_call(client, terminalize)
        elif change == "mission":
            response = client.post(f'{PREFIX}/missions/{created["missionId"]}/semantics', json={
                "operationId": "changed", "expectedMissionRevision": 1, "objective": "Changed objective",
                "constraints": [], "sourceRefs": [],
            })
            assert response.status_code == 200
        elif change == "permission":
            authorizer = runtime.mission_semantic_service.authorize
            monkeypatch.setattr(runtime.mission_semantic_service, "authorize", lambda principal, mission, action:
                                action == "read" and authorizer(principal, mission, action))
        elif change == "checkpoint":
            def drift():
                runtime.checkpoint_store.save(run_id=created["runId"], checkpoint_id="unacknowledged", state={"forged": True})
            trusted_call(client, drift)
        elif change == "source":
            runtime.workflow_registry.register(runtime.workflow_registry.get(created["workflowId"]).model_copy(update={"name": "changed-source"}))
        elif change == "identity":
            # Actual Identity database mutation, not a mocked authority decision.
            with runtime.identity_lifecycle.repositories.storage.transaction() as conn:
                conn.execute("DELETE FROM task_plan_nodes WHERE mission_id=?", (created["missionId"],))
        else:
            monkeypatch.setattr(runtime, "execution_permit_authority", None)
        before = snapshot(runtime)
        status = control(client, created)
        assert status["permitIssued"] is True
        assert status["dispatchEligible"] is False and status["executionAuthorized"] is False
        assert snapshot(runtime) == before
        response = client.post(base(created) + "/permits", json=pbody)
        assert response.status_code in {403, 409, 503}, response.text
        assert snapshot(runtime) == before and not agent.calls
