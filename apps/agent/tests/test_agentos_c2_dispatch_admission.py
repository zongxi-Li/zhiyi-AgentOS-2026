"""Permanent Native-boundary regressions for Dispatch-enabled Runtime entrypoints."""
import pytest
import sqlite3

from contracts import stable_checksum

from test_agentos_c2_dispatch_http import database, permitted, endpoint, wait_run
from test_agentos_c2_http import server
from test_agentos_c2_permit_http import ready_resource, trusted_call


def test_native_execution_requires_dispatch_even_with_issued_permit(tmp_path):
    database(tmp_path)
    with server(tmp_path, dispatch=True) as (client, runtime, agent):
        created, _ = permitted(client)
        trusted_call(client, ready_resource, runtime, created["runId"])
        assert runtime.execution_dispatch_store.get(created["runId"]) is None
        rejected = False
        try:
            trusted_call(client, runtime.execute_prepared_run, created["runId"])
        except ValueError as exc:
            assert "Dispatch" in str(exc)
            rejected = True
        commits = runtime.execution_value_store.list_node_commits(run_id=created["runId"])
        assert not agent.calls and not commits, f"Permit-only bypass: calls={agent.calls}, NodeExecution commits={len(commits)}"
        assert rejected


def test_checkpoint_resume_cannot_supply_first_dispatch(tmp_path):
    database(tmp_path)
    with server(tmp_path, dispatch=True) as (client, runtime, agent):
        created, _ = permitted(client)
        run = runtime.get_status(created["runId"])
        trusted_call(client, ready_resource, runtime, run.run_id)
        async def resume():
            return await runtime.resume_from_checkpoint(run_id=run.run_id, checkpoint_id=run.execution_state["checkpointId"])
        with pytest.raises(ValueError, match="Dispatch"):
            trusted_call(client, resume)
        assert not agent.calls and not runtime.execution_value_store.list_node_commits(run_id=run.run_id)


@pytest.mark.parametrize("damage", ["checksum", "permit_id", "graph_version", "mission_id", "actor_id", "detached_store"])
def test_native_claim_rejects_corrupt_or_foreign_dispatch(tmp_path, monkeypatch, damage):
    database(tmp_path)
    with server(tmp_path, dispatch=True) as (client, runtime, agent):
        created, request = permitted(client)
        with monkeypatch.context() as patch:
            patch.setattr(runtime._test_coordinator, "_create_permitted_task", lambda c: (_ for _ in ()).throw(RuntimeError("cut")))
            assert client.post(endpoint(created), json=request).status_code == 503
        command = runtime.execution_dispatch_store.get(created["runId"])
        if damage == "detached_store":
            monkeypatch.setattr(runtime, "execution_dispatch_store", None)
        else:
            changed = command if damage == "checksum" else command.model_copy(update={damage: 99 if damage == "graph_version" else "foreign"})
            with sqlite3.connect(runtime.workflow_store.db_path) as conn:
                conn.execute("UPDATE execution_dispatch_commands SET payload=?, checksum=? WHERE run_id=?",
                    (changed.model_dump_json(), "0" * 64 if damage == "checksum" else stable_checksum(changed), command.run_id))
        trusted_call(client, ready_resource, runtime, created["runId"])
        with pytest.raises(ValueError, match="Dispatch"):
            trusted_call(client, runtime.execute_prepared_run, created["runId"])
        assert not agent.calls and not runtime._active_execution_slots
        assert not runtime.execution_value_store.list_node_commits(run_id=created["runId"])


def test_dispatch_disabled_preserves_internal_permit_execution(tmp_path):
    database(tmp_path)
    with server(tmp_path, dispatch=False) as (client, runtime, agent):
        created, _ = permitted(client)
        trusted_call(client, ready_resource, runtime, created["runId"])
        trusted_call(client, runtime.execute_prepared_run, created["runId"])
        assert agent.calls == ["A", "B", "C"]


def test_review_continuation_cannot_replace_missing_dispatch(tmp_path):
    from contracts.workflow import ReviewDecision
    from examples.contract_review import ContractReviewAgent
    class ReviewAgent(ContractReviewAgent):
        async def run(self, context):
            output = await super().run(context)
            return output.model_copy(update={"risk_level": "high"}) if context.step.step_id == "A" else output
    database(tmp_path)
    with server(tmp_path, dispatch=True, agent_factory=ReviewAgent) as (client, runtime, agent):
        created, request = permitted(client)
        trusted_call(client, ready_resource, runtime, created["runId"])
        assert client.post(endpoint(created), json=request).status_code == 202
        assert wait_run(client, created)["status"] == "waiting_review"
        with sqlite3.connect(runtime.workflow_store.db_path) as conn:
            conn.execute("DELETE FROM execution_dispatch_commands WHERE run_id=?", (created["runId"],))
        decision = ReviewDecision(runId=created["runId"], stepId="A", decision="approved", operationId="approve-no-command")
        with pytest.raises(ValueError, match="Dispatch"):
            trusted_call(client, runtime.apply_review, decision)
        assert agent.calls == ["A"]
        assert len(runtime.execution_value_store.list_node_commits(run_id=created["runId"])) == 1
