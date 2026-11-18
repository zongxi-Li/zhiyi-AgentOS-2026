"""Only the installed formal write-ahead adapter can prove no dispatch occurred."""
import asyncio
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from app.tools.formal_workspace import FormalWorkspaceTools
from components.executor.value_store import SQLiteExecutionValueStore
from runtime.permit_recovery import assert_native_readonly_retry_safe, assert_replay_safe_operations

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agentOS" / "tests" / "runtime"))
from test_permit_readonly_recovery import (  # noqa: E402
    _native_attempt, _replace_payload, _seed_memory_input,
)
from test_settled_session_retry_audit import _settled_shell, _register_authorization  # noqa: E402


@pytest.fixture
def session(tmp_path):
    store = SQLiteExecutionValueStore(db_path=tmp_path / "values.sqlite3")
    services, run, node, *_ = _native_attempt(store)
    run.get_step(node.step_id).capability = "verification"
    operation = node.operation_id + ":tools:0:call:1"
    key = node.operation_id + ":tools:0:model-turn"
    turn = store.get_tool_value(run_id=run.run_id, key=key)
    turn["response"]["toolCalls"].append({"id": "shell-call", "type": "function", "function": {
        "name": "shell__exec", "arguments": json.dumps({"command": "echo reviewed", "workdir": "."})}})
    _replace_payload(store, run.run_id, key, turn)
    runtime = SimpleNamespace(execution_value_store=store)
    runtime.tool_runtime = tools = FormalWorkspaceTools(runtime, SimpleNamespace(allowed_tools=()))
    services.tool_non_invocation_prover = tools.prove_not_dispatched
    try:
        yield services, run, node, operation, runtime, tools
    finally:
        store.close()


def test_formal_verification_can_retry_after_a_declared_shell_never_crossed_the_write_ahead_barrier(session):
    services, run, node, operation, _, _ = session
    before = run.model_copy(deep=True)
    receipt = services.execution_value_store.get_node_commit(run_id=run.run_id, commit_id=node.operation_id)
    proof = assert_native_readonly_retry_safe(services, run, node)
    assert proof["unconfirmedReadCount"] == 1  # It remains unknown; no receipt is synthesized.
    non_invoked = proof["nonInvocationProofs"]
    assert len(non_invoked) == 1 and non_invoked[0]["operationKey"] == operation
    assert non_invoked[0]["capabilityId"] == "shell.exec" and non_invoked[0]["dispatched"] is False
    proofs = []
    assert list(assert_replay_safe_operations(services, run, readonly_proofs=proofs)) == [receipt]
    assert proofs == [proof] and run == before
    assert services.execution_value_store.get_tool_value(run_id=run.run_id, key=operation + ":request") is None
    assert services.execution_value_store.get_node_commit(run_id=run.run_id, commit_id=node.operation_id) == receipt


@pytest.mark.parametrize("damage", ["missing_port", "replaced_adapter", "overridden_execute", "subclass",
    "replaced_ledger", "overridden_ledger", "wrong_identity", "wrong_declaration_hash"])
def test_non_invocation_requires_the_known_adapter_ledger_and_correlated_proof(session, damage):
    services, run, node, _, runtime, tools = session
    if damage == "missing_port":
        del services.tool_non_invocation_prover
    elif damage == "replaced_adapter":
        runtime.tool_runtime = SimpleNamespace(prove_not_dispatched=tools.prove_not_dispatched)
    elif damage == "overridden_execute":
        tools.execute = lambda *args, **kwargs: None
    elif damage == "subclass":
        class PluginTools(FormalWorkspaceTools):
            pass
        runtime.tool_runtime = PluginTools(runtime, SimpleNamespace(allowed_tools=()))
        services.tool_non_invocation_prover = runtime.tool_runtime.prove_not_dispatched
    elif damage == "replaced_ledger":
        runtime.execution_value_store = SimpleNamespace(db_path=services.execution_value_store.db_path)
    elif damage == "overridden_ledger":
        runtime.execution_value_store.put_tool_value = lambda **kwargs: None
    else:
        original = services.tool_non_invocation_prover
        def corrupted(**kwargs):
            proof = original(**kwargs)
            if damage == "wrong_identity":
                proof["identity"] = {**proof["identity"], "attemptId": "another-attempt"}
            else:
                proof["declarationHash"] = "0" * 64
            return proof
        services.tool_non_invocation_prover = corrupted
    with pytest.raises(ValueError):
        assert_native_readonly_retry_safe(services, run, node)


@pytest.mark.parametrize("suffix", [":request", ":admission", ":receipt", ":result", ":unsettled"])
def test_any_existing_external_activity_prevents_non_invocation_proof(session, suffix):
    services, run, node, operation, _, tools = session
    store = services.execution_value_store
    store.put_tool_value(run_id=run.run_id, step_id=node.step_id, key=operation + suffix,
        payload={"identity": {"runId": run.run_id, "stepId": node.step_id,
            "attemptId": node.attempt_id, "commitId": node.operation_id}})
    with sqlite3.connect(store.db_path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        with pytest.raises(ValueError, match="admitted or dispatched"):
            tools.prove_not_dispatched(run=run, node=node, operation=operation, tool="shell.exec",
                raw_arguments="{}", workspace=run.input["workspaceBinding"], connection=connection,
                execution_value_store=store)
    with pytest.raises(ValueError):
        assert_native_readonly_retry_safe(services, run, node)


def test_non_invocation_cannot_be_proved_against_another_database(session, tmp_path):
    services, run, node, operation, _, tools = session
    other = SQLiteExecutionValueStore(db_path=tmp_path / "other.sqlite3")
    try:
        with sqlite3.connect(other.db_path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
            with pytest.raises(ValueError, match="different databases"):
                tools.prove_not_dispatched(run=run, node=node, operation=operation, tool="shell.exec",
                    raw_arguments="{}", workspace=run.input["workspaceBinding"], connection=connection,
                    execution_value_store=services.execution_value_store)
    finally:
        other.close()


@pytest.mark.parametrize("guarded", [False, True])
def test_native_retry_reads_real_prior_evidence_through_bound_runtime_wrappers(tmp_path, monkeypatch, guarded):
    from adapters.guarded_tool import GuardedToolRuntime
    from adapters.model.native import NativeGeneralAgent
    from adapters.model_adapter import StructuredGenerationResult
    from components.communicator.contracts import ContextPack
    from contracts.workflow import RuntimeMissionRecord, WorkflowDefinition
    from service.agents import AgentRunContext
    from support.acg.models import build_default_capability_catalog

    class Model:
        calls = []

        def is_available(self):
            return True

        async def generate_json(self, **kwargs):
            self.calls.append(kwargs)
            return StructuredGenerationResult(data={"extracted_information": {
                "facts": [], "metrics": [], "entities": [], "unknowns": []}},
                provider="fixture", model="mock", latencyMs=0)

    monkeypatch.setattr("app.tools.formal_workspace.get_chat_permission_service", lambda: object())
    store = SQLiteExecutionValueStore(db_path=tmp_path / "retry-bridge.sqlite3")
    try:
        services, run, node, operation, auth = _settled_shell(store)
        proof = _register_authorization(store, run, node, auth)
        run.execution_state["settledSessionRetryProofs"] = {node.operation_id: proof}
        new = node.model_copy(update={"operation_id": "new-active-operation", "attempt_id": "new-attempt",
            "execution_instance_id": "new-generation:run:S2:1:root"})
        store.prepare_node_commit(run_id=run.run_id, commit_id=new.operation_id)
        store.transition_node_execution(new)
        run.execution_state.update(executionGeneration="new-generation", activeStepIds=[node.step_id])
        run.get_step(node.step_id).status = "running"
        services.tool_runtime = FormalWorkspaceTools(services, SimpleNamespace(allowed_tools=()))
        root_runtime = GuardedToolRuntime(delegate=services.tool_runtime) if guarded else services.tool_runtime
        model, guards = Model(), []
        context = AgentRunContext(task=RuntimeMissionRecord(missionId=run.mission_id, title="Continue review"),
            run=run, workflow=WorkflowDefinition(workflowId="flow", name="Review", domain="general", runtimeEngine="acg"),
            step=run.get_step(node.step_id), memory=[], contextPack=ContextPack(runId=run.run_id, stepId=node.step_id),
            modelRuntime=model, capabilityDescriptor=build_default_capability_catalog().get("information_extraction"),
            commitId=new.operation_id, attemptId=new.attempt_id)
        context.tool_runtime = root_runtime.scoped({"fs.read", "shell.exec"}).bind_context(context, lambda: guards.append(True))
        before = list(store._connection.execute("SELECT reference,payload_json FROM execution_values ORDER BY reference"))
        result = asyncio.run(NativeGeneralAgent().run(context))
        assert len(model.calls) == 1 and guards == [True]
        prompt = model.calls[0]["prompt"]
        assert "fixture\\n" in prompt and "previous_attempt_tool_observation" in prompt
        assert node.attempt_id in prompt and node.operation_id in prompt and operation in prompt
        assert "not count as actions performed by this new Attempt" in model.calls[0]["system_prompt"]
        assert not result.tool_executions
        assert list(store._connection.execute("SELECT reference,payload_json FROM execution_values ORDER BY reference")) == before
        with pytest.raises(PermissionError, match="Bound NodeRunner"):
            asyncio.run(context.tool_runtime.previous_attempt_observations(context.model_copy()))
        def revoked():
            raise PermissionError("permit revoked")
        context.tool_runtime = root_runtime.scoped({"fs.read"}).bind_context(context, revoked)
        with pytest.raises(PermissionError, match="permit revoked"):
            asyncio.run(NativeGeneralAgent().run(context))
        assert len(model.calls) == 1
    finally:
        store.close()


@pytest.mark.parametrize("activity", [None, "model-turn", "request", "response", "identity", "record", "commit"])
def test_empty_native_session_proof_requires_no_admitted_model_or_tool_work(session, activity):
    services, run, old, _, _, tools = session
    store = services.execution_value_store
    node = old.model_copy(update={"operation_id": "new-empty-operation", "attempt_id": "new-empty-attempt",
        "execution_instance_id": "generation:run:S2:1:root"})
    store.prepare_node_commit(run_id=run.run_id, commit_id=node.operation_id)
    store.transition_node_execution(node)
    if activity is not None:
        key = node.operation_id + (":tools:0:model-turn" if activity == "model-turn" else ":hidden-activity")
        payload = {
            "model-turn": {"response": {}},
            "request": {"request": {"invocationId": node.operation_id + ":tools:0:call:0"}},
            "response": {"response": {"requestId": node.operation_id + ":tools:0"}},
            "identity": {"identity": {"commitId": node.operation_id}},
            "record": {"record": {"commitId": node.operation_id}},
            "commit": {"commitId": node.operation_id},
        }[activity]
        store.put_tool_value(run_id=run.run_id, step_id=node.step_id, key=key, payload=payload)
    with sqlite3.connect(store.db_path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        kwargs = dict(run=run, node=node, operation=node.operation_id, tool="native.tool-session",
            raw_arguments=None, workspace=run.input["workspaceBinding"], connection=connection, execution_value_store=store)
        if activity is not None:
            with pytest.raises(ValueError, match="admitted model or tool work"):
                tools.prove_not_dispatched(**kwargs)
        else:
            proof = tools.prove_not_dispatched(**kwargs)
            assert proof["capabilityId"] == "native.tool-session" and proof["dispatched"] is False
            assert proof["identity"]["attemptId"] == node.attempt_id and "declarationHash" not in proof


def test_formal_empty_session_with_frozen_memory_can_retry_without_replaying_work(session):
    services, run, node, _, runtime, _ = session
    store = runtime.execution_value_store
    with store._connection:
        store._connection.execute("DELETE FROM execution_values WHERE run_id=?", (run.run_id,))
    _seed_memory_input(store, run, node, with_record=True)
    before = list(store._connection.execute("SELECT * FROM execution_values ORDER BY reference"))
    proof = assert_native_readonly_retry_safe(services, run, node)
    assert proof["kind"] == "native_session_not_dispatched"
    assert proof["nonInvocationProofs"][0]["source"] == "formal-workspace-write-ahead.v1"
    assert proof["readRequestCount"] == proof["modelTurnCount"] == 0
    assert list(store._connection.execute("SELECT * FROM execution_values ORDER BY reference")) == before
    assert not run.completed_step_ids and not run.execution_state.get("outputRefs")


@pytest.mark.parametrize("cancelled", [False, True])
def test_native_retrieval_recovery_uses_the_real_adapter_write_ahead(session, monkeypatch, cancelled):
    from adapters.model.native import NativeGeneralAgent
    from app.tools.catalog import ReadOnlyToolCatalog
    from app.tools.contracts import ToolPayload
    from app.tools.runtime import AgentsToolRuntime
    from contracts.native_retrieval import retrieval_operation_key
    from contracts.workflow import RuntimeMissionRecord, WorkflowDefinition
    from service.agents import AgentRunContext

    services, run, node, _, runtime, tools = session
    store = runtime.execution_value_store
    with store._connection:
        store._connection.execute("DELETE FROM execution_values WHERE run_id=?", (run.run_id,))
    step = run.get_step(node.step_id)
    step.capability = "information_retrieval"
    catalog = ReadOnlyToolCatalog()
    tools.fallback = AgentsToolRuntime(catalog)
    tools.allowed_tools |= tools.fallback.allowed_tools
    monkeypatch.setattr("app.tools.runtime.settings.TOOL_RUNTIME_ENABLED", True)
    key = retrieval_operation_key(node.operation_id, "knowledge_search")
    calls = []

    async def scenario():
        entered = asyncio.Event()

        async def search(arguments, **_):
            calls.append(arguments)
            assert store.get_tool_value(run_id=run.run_id, key=key + ":request")["identity"]["attemptId"] == node.attempt_id
            entered.set()
            if cancelled:
                await asyncio.Future()
            return ToolPayload(summary="No indexed materials", data={"results": []})

        monkeypatch.setattr(catalog, "_knowledge_search", search)
        context = AgentRunContext(task=RuntimeMissionRecord(missionId=run.mission_id, title="Workspace review",
                input={"webSearchEnabled": False}), run=run,
            workflow=WorkflowDefinition(workflowId="flow", name="Review", domain="general", runtimeEngine="acg"),
            step=step, memory=[], attemptId=node.attempt_id, commitId=node.operation_id)
        context.tool_runtime = tools.scoped({"knowledge_search"}).bind_context(context, lambda: None)
        agent = NativeGeneralAgent()
        task = asyncio.create_task(agent.run(context))
        await asyncio.wait_for(entered.wait(), 2)
        if cancelled:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert (await task).evidence_refs
            assert (await agent.run(context)).evidence_refs

    asyncio.run(scenario())
    assert len(calls) == 1
    before = list(store._connection.execute("SELECT * FROM execution_values ORDER BY reference"))
    proof = assert_native_readonly_retry_safe(services, run, node)
    assert proof["retrievalRequestCount"] == 1
    assert proof["retrievalResultCount"] == (0 if cancelled else 1)
    assert proof["modelTurnCount"] == 0
    assert list(store._connection.execute("SELECT * FROM execution_values ORDER BY reference")) == before
    assert not run.completed_step_ids


@pytest.mark.parametrize("damage", ["owner", "policy", "fake_memory", "extra_slot", "write_request"])
def test_formal_no_dispatch_only_exempts_validated_internal_memory(session, damage):
    _, run, node, _, runtime, tools = session
    store = runtime.execution_value_store
    with store._connection:
        store._connection.execute("DELETE FROM execution_values WHERE run_id=?", (run.run_id,))
    reference, snapshot = _seed_memory_input(store, run, node, with_record=True)
    if damage == "owner":
        with store._connection:
            store._connection.execute("UPDATE execution_values SET step_id='other' WHERE reference=?", (reference,))
    elif damage in {"policy", "fake_memory"}:
        if damage == "policy": snapshot["policy"]["read"] = False
        else: snapshot["request"] = {"invocationId": node.operation_id + ":tools:0:call:0"}
        _replace_payload(store, run.run_id, node.operation_id + ":memory-retrieval", snapshot)
    else:
        key = node.operation_id + ":hidden-activity"
        payload = (snapshot if damage == "extra_slot" else
            {"request": {"invocationId": node.operation_id + ":tools:0:call:0", "capabilityId": "fs.write"}})
        store.put_tool_value(run_id=run.run_id, step_id=node.step_id, key=key, payload=payload)
    with sqlite3.connect(store.db_path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only=ON")
        with pytest.raises(ValueError):
            tools.prove_not_dispatched(run=run, node=node, operation=node.operation_id,
                tool="native.tool-session", raw_arguments=None, workspace=run.input["workspaceBinding"],
                connection=connection, execution_value_store=store)
