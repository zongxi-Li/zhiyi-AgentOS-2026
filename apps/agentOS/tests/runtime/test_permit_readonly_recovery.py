import hashlib
import json
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

import pytest

from components.executor.value_store import SQLiteExecutionValueStore
from contracts import stable_checksum
from contracts.capability import ModelInvocationResponse
from contracts.local_runtime import LocalRuntimeExecutionRequest
from runtime.permit_recovery import (
    _readonly_session_proof, assert_native_readonly_retry_safe, assert_replay_safe_operations,
    run_step_readonly_retry_proof,
)


def _request(operation, tool, path):
    return LocalRuntimeExecutionRequest(
        protocolVersion="1", requestId=operation, invocationId=operation,
        resourceId="hands-resource", capabilityId=tool,
        authorization={"workspaceId": "workspace", "grantId": "grant"},
        input={"path": path},
        limits={"timeoutSeconds": 90, "maxStdoutBytes": 64000, "maxStderrBytes": 32000},
        idempotencyKey=operation,
    )


def _seed(store, *, tool="fs.read", missing_receipt=False, model_tool="fs__read", commit_id="commit:run:S2:1"):
    run_id, step_id, attempt_id = "run", "S2", "attempt:S2:1"
    identity = {"runId": run_id, "stepId": step_id, "attemptId": attempt_id, "commitId": commit_id}
    run = SimpleNamespace(run_id=run_id)
    node = SimpleNamespace(step_id=step_id, attempt_id=attempt_id, operation_id=commit_id)
    response = ModelInvocationResponse(
        requestId="model-turn", content={}, toolCalls=[{"id": "call", "type": "function",
            "function": {"name": model_tool, "arguments": json.dumps({"path": "note.txt"})}}],
        provider="test", model="mock",
    )
    store.put_tool_value(run_id=run_id, step_id=step_id,
        key=commit_id + ":tools:0:model-turn",
        payload={"requestHash": "a" * 64, "response": response.model_dump(by_alias=True, mode="json")})
    operation = commit_id + ":tools:0:call:0"
    request = _request(operation, tool, "note.txt")
    store.put_tool_value(run_id=run_id, step_id=step_id, key=operation + ":request",
        payload={"request": request.model_dump(by_alias=True, mode="json"), "identity": identity})
    if not missing_receipt:
        receipt = {
            "protocolVersion": "1", "requestId": str(uuid5(NAMESPACE_URL, operation)),
            "invocationId": operation, "capabilityId": tool, "grantId": "grant",
            "idempotencyKey": operation, "identity": identity, "status": "completed",
            "output": {"path": "note.txt", "text": "body"},
            "startedAt": "2026-11-16T01:00:00+00:00", "completedAt": "2026-11-16T01:00:01+00:00",
        }
        receipt["checksum"] = stable_checksum(receipt)
        receipt_ref = "tool:" + hashlib.sha256((run_id + ":" + operation + ":receipt").encode()).hexdigest()
        request_ref = "tool:" + hashlib.sha256((run_id + ":" + operation + ":request").encode()).hexdigest()
        store.put_tool_value(run_id=run_id, step_id=step_id, key=operation + ":receipt", payload=receipt)
        store.put_tool_value(run_id=run_id, step_id=step_id, key=operation + ":result",
            payload={"data": {"status": "completed"}, "record": {
                "tool": tool, "executionId": "hands-execution-1", **identity,
                "resourceId": "hands-resource", "workspaceId": "workspace", "grantId": "grant",
                "requestRef": request_ref, "receiptRef": receipt_ref,
                "receiptChecksum": receipt["checksum"],
            }})
    return run, node


@pytest.fixture
def store(tmp_path):
    value_store = SQLiteExecutionValueStore(db_path=tmp_path / "values.sqlite3")
    try:
        yield value_store
    finally:
        value_store.close()


def test_readonly_session_proof_allows_missing_read_receipt_without_settling(store):
    run, node = _seed(store, missing_receipt=True)
    proof = _readonly_session_proof(run, node,
        {"workspaceId": "workspace", "grantId": "grant"}, store._connection)
    assert proof["retrySafe"] is True
    assert proof["confirmedReadCount"] == 0 and proof["unconfirmedReadCount"] == 1


def test_readonly_session_proof_validates_authentic_receipt_and_cached_record(store):
    run, node = _seed(store)
    proof = _readonly_session_proof(run, node,
        {"workspaceId": "workspace", "grantId": "grant"}, store._connection)
    assert proof["confirmedReadCount"] == 1 and proof["unconfirmedReadCount"] == 0


def test_readonly_proof_does_not_decode_unrelated_historical_bodies(store, monkeypatch):
    run, node = _seed(store)
    marker = "unrelated-private-model-or-file-body"
    store.put_tool_value(run_id=run.run_id, step_id="other", key="another-operation:model-turn",
        payload={"requestHash": "b" * 64, "body": marker})
    loads = json.loads

    def decode_current_session(payload, *args, **kwargs):
        assert marker not in payload
        return loads(payload, *args, **kwargs)

    monkeypatch.setattr(json, "loads", decode_current_session)
    proof = _readonly_session_proof(run, node,
        {"workspaceId": "workspace", "grantId": "grant"}, store._connection)
    assert proof["confirmedReadCount"] == 1


@pytest.mark.parametrize("tool,model_tool", [("fs.write", "fs__write"), ("shell.exec", "shell__exec"),
    ("fs.read", "unknown_tool")])
def test_readonly_session_proof_rejects_non_readonly_declarations(store, tool, model_tool):
    run, node = _seed(store, tool=tool, model_tool=model_tool, missing_receipt=True)
    with pytest.raises(ValueError, match="write, shell or unknown"):
        _readonly_session_proof(run, node,
            {"workspaceId": "workspace", "grantId": "grant"}, store._connection)


@pytest.mark.parametrize("defect", ["checksum", "identity", "invocation", "request_id", "grant", "time"])
def test_existing_receipt_still_requires_authentic_correlation(store, defect):
    run, node = _seed(store)
    operation = node.operation_id + ":tools:0:call:0"
    receipt = store.get_tool_value(run_id=run.run_id, key=operation + ":receipt")
    changes = {"checksum": {"checksum": "corrupt"}, "identity": {"identity": {}},
        "invocation": {"invocationId": "other"}, "request_id": {"requestId": "other"},
        "grant": {"grantId": "other"}, "time": {"completedAt": "2026-11-15T00:00:00+00:00"}}
    receipt.update(changes[defect])
    if defect != "checksum":
        receipt["checksum"] = stable_checksum({key: value for key, value in receipt.items() if key != "checksum"})
    _replace_payload(store, run.run_id, operation + ":receipt", receipt)
    with pytest.raises(ValueError, match="Hands receipt"):
        _readonly_session_proof(run, node,
            {"workspaceId": "workspace", "grantId": "grant"}, store._connection)


def _replace_payload(store, run_id, key, payload):
    reference = "tool:" + hashlib.sha256((run_id + ":" + key).encode()).hexdigest()
    with store._connection:
        store._connection.execute("UPDATE execution_values SET payload_json=? WHERE reference=?",
                                  (json.dumps(payload), reference))


def test_readonly_proof_rejects_a_hidden_write_request_or_unknown_activity(store):
    run, node = _seed(store)
    operation = node.operation_id + ":tools:0:call:1"
    request = _request(operation, "fs.write", "note.txt")
    identity = {"runId": run.run_id, "stepId": node.step_id,
        "attemptId": node.attempt_id, "commitId": node.operation_id}
    store.put_tool_value(run_id=run.run_id, step_id=node.step_id, key=operation + ":request",
        payload={"request": request.model_dump(by_alias=True, mode="json"), "identity": identity})
    with pytest.raises(ValueError, match="undeclared request"):
        _readonly_session_proof(run, node,
            {"workspaceId": "workspace", "grantId": "grant"}, store._connection)


def _planning_snapshot(store, run, node, *, owner="__planner_context__"):
    from contracts.planning_context import planning_context_key

    operation = node.operation_id + ":tools:0:call:0"
    original = store.get_tool_value(run_id=run.run_id, key=operation + ":request")
    payload = {**original, "__planning_context__": {"version": 1, "runId": run.run_id,
        "contextKind": "tool_request", "sourceRunId": run.run_id, "stepId": node.step_id,
        "attemptId": node.attempt_id, "operationId": node.operation_id,
        "originalRef": "tool:" + hashlib.sha256((run.run_id + ":" + operation + ":request").encode()).hexdigest(),
        "status": "admitted", "trust": "host_recorded"}}
    key = planning_context_key(payload)
    reference = store.put_tool_value(run_id=run.run_id, step_id=owner, key=key, payload=payload)
    return key, reference, payload


def test_reading_request_diagnostics_cannot_change_retry_safety_or_fingerprint(store):
    from runtime.planning_context_catalog import build_planning_context_catalog

    services, run, node, *_ = _native_attempt(store)
    services.workflow_store = SimpleNamespace(get_mission=lambda _: SimpleNamespace(
        title="Inspect source", domain="general", intent=None))
    before = run_step_readonly_retry_proof(services, run, node.step_id)
    entries = build_planning_context_catalog(services, run, workspace_snapshot={})
    requests = [entry for entry in entries if entry.context_kind == "tool_request"]
    assert len(requests) == 1
    assert requests[0].step_id == node.step_id
    assert requests[0].operation_id == node.operation_id
    after = run_step_readonly_retry_proof(services, run, node.step_id)
    proofs = []
    assert_replay_safe_operations(services, run, readonly_proofs=proofs)
    assert before == after == proofs[0]
    assert before["readRequestCount"] == 1 and before["unconfirmedReadCount"] == 1
    assert store.get_node_commit(run_id=run.run_id, commit_id=node.operation_id)["stage"] == "prepared"
    assert run.completed_step_ids == []


@pytest.mark.parametrize("defect", ["wrong_owner", "wrong_kind", "operation_bound", "changed_body", "wrong_run"])
def test_diagnostic_exemption_requires_the_reserved_ledger_owner_and_exact_sealed_reference(store, defect):
    run, node = _seed(store)
    key, reference, payload = _planning_snapshot(store, run, node)
    if defect in {"changed_body", "wrong_run"}:
        if defect == "changed_body":
            payload["request"]["capabilityId"] = "shell.exec"
        else:
            payload["__planning_context__"]["runId"] = "another-run"
        _replace_payload(store, run.run_id, key, payload)
    else:
        column, value = {"wrong_owner": ("step_id", node.step_id), "wrong_kind": ("kind", "context"),
            "operation_bound": ("operation_id", node.operation_id)}[defect]
        with store._connection:
            store._connection.execute(f"UPDATE execution_values SET {column}=? WHERE reference=?", (value, reference))
    with pytest.raises(ValueError, match="undeclared request|another node or kind"):
        _readonly_session_proof(run, node,
            {"workspaceId": "workspace", "grantId": "grant"}, store._connection)


def test_diagnostic_snapshot_marker_does_not_hide_a_new_undeclared_shell_request(store):
    run, node = _seed(store)
    _planning_snapshot(store, run, node)
    operation = node.operation_id + ":tools:0:call:1"
    request = _request(operation, "shell.exec", ".")
    store.put_tool_value(run_id=run.run_id, step_id=node.step_id, key=operation + ":request", payload={
        "request": request.model_dump(by_alias=True, mode="json"),
        "identity": {"runId": run.run_id, "stepId": node.step_id,
            "attemptId": node.attempt_id, "commitId": node.operation_id},
        "__planning_context__": {"version": 1, "runId": run.run_id}})
    with pytest.raises(ValueError, match="undeclared request"):
        _readonly_session_proof(run, node,
            {"workspaceId": "workspace", "grantId": "grant"}, store._connection)


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_terminal_read_receipt_without_cached_result_can_be_retry_safe(store, status):
    run, node = _seed(store)
    operation = node.operation_id + ":tools:0:call:0"
    receipt = store.get_tool_value(run_id=run.run_id, key=operation + ":receipt")
    receipt["status"] = status
    receipt["checksum"] = stable_checksum({key: value for key, value in receipt.items() if key != "checksum"})
    _replace_payload(store, run.run_id, operation + ":receipt", receipt)
    ref = "tool:" + hashlib.sha256((run.run_id + ":" + operation + ":result").encode()).hexdigest()
    with store._connection:
        store._connection.execute("DELETE FROM execution_values WHERE reference=?", (ref,))
    proof = _readonly_session_proof(run, node,
        {"workspaceId": "workspace", "grantId": "grant"}, store._connection)
    assert proof["confirmedReadCount"] == 1 and proof["unconfirmedReadCount"] == 0


def _native_attempt(store, *, missing_receipt=True, terminal_status="failed", tool="fs.read", model_tool="fs__read"):
    from adapters.model.native import NativeGeneralAgent
    from components.executor.node_runner import ACGNodeRunner
    from contracts.execution import NodeExecutionRecord
    from contracts.workflow import RuntimeRunRecord, StepStatus, WorkflowStep
    from service.agents.registry import AgentRegistry

    registry, agent = AgentRegistry(), NativeGeneralAgent()
    registry.register(agent)
    registration = registry.registration_for(agent)
    operation = ACGNodeRunner._commit_id("run", "S2", 0, execution_generation="generation")
    _seed(store, missing_receipt=missing_receipt, commit_id=operation, tool=tool, model_tool=model_tool)
    node = NodeExecutionRecord(operationId=operation,
        executionInstanceId="generation:run:S2:0:root", runId="run", stepId="S2",
        attemptId="attempt:S2:1", phase="prepared")
    store.prepare_node_commit(run_id="run", commit_id=operation)
    store.transition_node_execution(node)
    step = WorkflowStep(stepId="S2", name="reader", agentName=agent.profile.agent_name,
        capability="information_extraction", status=StepStatus.FAILED)
    run = RuntimeRunRecord(runId="run", missionId="mission", workflowId="flow", domain="general",
        runtimeEngine="acg", steps=[step],
        input={"workspaceBinding": {"workspaceId": "workspace", "grantId": "grant"}},
        executionState={"executionGeneration": "generation", "taskSettlement": {
            node.attempt_id: {"taskState": "ended", "outcome": terminal_status, "leaseState": "released"}}})
    attempt = SimpleNamespace(run_id=run.run_id, task_id="task", attempt_number=1,
        status=SimpleNamespace(value=terminal_status))
    execution = SimpleNamespace(run_id=run.run_id, task_id="task", status=SimpleNamespace(value=terminal_status))
    binding = SimpleNamespace(acg_node_id="S2", metadata={
        "agentRegistration": registration.model_dump(by_alias=True, mode="json")})
    repos = SimpleNamespace(attempts=SimpleNamespace(get=lambda _: attempt),
        step_executions=SimpleNamespace(list_for_attempt=lambda _: [execution]),
        execution_bindings=SimpleNamespace(get_for_attempt=lambda _: binding))
    services = SimpleNamespace(execution_value_store=store, agent_registry=registry,
        identity_lifecycle=SimpleNamespace(repositories=repos))
    return services, run, node, attempt, execution, binding, agent


@pytest.mark.parametrize("terminal_status", ["failed", "cancelled"])
@pytest.mark.parametrize("capability", ["information_extraction", "verification", "analysis",
    "requirement_analysis", "architecture_design", "artifact_generation", "task_understanding", "evidence_analysis"])
def test_ended_native_readonly_attempt_passes_permit_replay_safety_without_relabeling(store, terminal_status, capability):
    services, run, node, attempt, execution, _, _ = _native_attempt(store, terminal_status=terminal_status)
    run.get_step("S2").capability = capability
    before = store.get_node_commit(run_id=run.run_id, commit_id=node.operation_id)
    proof = assert_native_readonly_retry_safe(services, run, node)
    assert run_step_readonly_retry_proof(services, run, "S2") == proof
    assert proof["unconfirmedReadCount"] == 1
    proofs = []
    assert tuple(assert_replay_safe_operations(services, run, readonly_proofs=proofs)) == (before,)
    assert proofs == [proof]
    assert store.get_node_commit(run_id=run.run_id, commit_id=node.operation_id) == before
    assert before["stage"] == "prepared" and attempt.status.value == execution.status.value == terminal_status
    assert run.completed_step_ids == [] and run.execution_state.get("outputRefs", {}) == {}


@pytest.mark.parametrize("capability", ["information_retrieval", "industrial_capacity_analysis"])
def test_native_prologue_capabilities_cannot_use_session_only_recovery(store, capability):
    services, run, node, *_ = _native_attempt(store, missing_receipt=False)
    run.get_step(node.step_id).capability = capability
    with pytest.raises(ValueError, match=r"step S2: native .* execution requires its own recovery proof"):
        assert_native_readonly_retry_safe(services, run, node)


def test_material_workset_cannot_be_replayed_as_a_single_native_session(store):
    services, run, node, *_ = _native_attempt(store)
    run.get_step(node.step_id).input["workset"] = {"sourceManifestRefs": ["manifest"]}
    with pytest.raises(ValueError, match="step S2: native workset execution requires its own recovery proof"):
        assert_native_readonly_retry_safe(services, run, node)


def test_capacity_failure_can_reconcile_a_cancelled_generic_sibling_without_an_attempt_for_the_queued_node(store):
    from contracts.workflow import StepStatus, WorkflowStep

    services, run, node, *_ = _native_attempt(store, terminal_status="cancelled")
    sibling = run.get_step(node.step_id)
    sibling.capability, sibling.status = "requirement_analysis", StepStatus.CANCELLED
    run.steps.append(WorkflowStep(stepId="queued", name="queued", agentName=sibling.agent_name,
        capability="information_retrieval", status=StepStatus.FAILED))
    before = store.list_node_commits(run_id=run.run_id)
    proofs = []
    assert tuple(assert_replay_safe_operations(services, run, readonly_proofs=proofs)) == before
    assert [proof["stepId"] for proof in proofs] == [sibling.step_id]
    assert sibling.status is StepStatus.CANCELLED
    assert run.get_step("queued").status is StepStatus.FAILED
    assert store.list_node_commits(run_id=run.run_id) == before


def test_native_session_recovery_requires_a_capability_registered_by_the_bound_agent(store):
    services, run, node, *_ = _native_attempt(store)
    run.get_step(node.step_id).capability = "unregistered_capability"
    with pytest.raises(ValueError, match="step S2: capability .* is not registered"):
        assert_native_readonly_retry_safe(services, run, node)


@pytest.mark.parametrize("capability", ["requirement_analysis", "architecture_design", "artifact_generation"])
@pytest.mark.parametrize("tool,model_tool", [("fs.write", "fs__write"), ("shell.exec", "shell__exec")])
def test_generic_native_capabilities_still_cannot_retry_dispatched_writes_or_shell(store, capability, tool, model_tool):
    services, run, node, *_ = _native_attempt(store, tool=tool, model_tool=model_tool)
    run.get_step(node.step_id).capability = capability
    with pytest.raises(ValueError, match="write, shell or unknown tool request"):
        assert_native_readonly_retry_safe(services, run, node)


@pytest.mark.parametrize("attempt_status", [None, "running", "succeeded"])
def test_native_recovery_identifies_the_step_and_actual_attempt_rejection(store, attempt_status):
    services, run, node, attempt, *_ = _native_attempt(store)
    run.get_step(node.step_id).capability = "requirement_analysis"
    if attempt_status is None:
        services.identity_lifecycle.repositories.attempts.get = lambda _: None
    else:
        attempt.status.value = attempt_status
    with pytest.raises(ValueError, match="step S2: read-only retry requires a failed or cancelled terminal Attempt"):
        assert_native_readonly_retry_safe(services, run, node)


@pytest.mark.parametrize("terminal_status", ["failed", "cancelled"])
def test_historical_readonly_attempt_survives_new_generations_without_becoming_current_retry(store, terminal_status):
    services, run, node, attempt, execution, _, _ = _native_attempt(store, terminal_status=terminal_status)
    receipt = store.get_node_commit(run_id=run.run_id, commit_id=node.operation_id)
    for generation in ("second-generation", "third-generation"):
        run.execution_state["executionGeneration"] = generation
        run.get_step("S2").attempt = run.get_step("S2").retry_count = 1
        with pytest.raises(ValueError, match="another generation"):
            assert_native_readonly_retry_safe(services, run, node)
        proofs = []
        assert tuple(assert_replay_safe_operations(services, run, readonly_proofs=proofs)) == (receipt,)
        assert proofs[0]["unconfirmedReadCount"] == 1 and proofs[0]["evidenceFingerprint"]
        assert store.get_node_commit(run_id=run.run_id, commit_id=node.operation_id) == receipt
        assert attempt.status.value == execution.status.value == terminal_status
        assert not run.completed_step_ids and not run.execution_state.get("outputRefs")


def test_cancelled_attempt_cannot_use_the_noninvoked_failure_exception(store):
    from contracts.execution import NodeExecutionPhase

    services, run, node, *_ = _native_attempt(store, terminal_status="cancelled")
    failed = node.model_copy(update={"phase": NodeExecutionPhase.FAILED, "failure_code": "AGENT_NOT_IN_SCOPE"})
    store.transition_node_execution(failed)
    with pytest.raises(ValueError, match="unsettled external operation"):
        assert_replay_safe_operations(services, run)


@pytest.mark.parametrize("defect", ["instance", "operation", "attempt_number"])
def test_historical_readonly_attempt_still_cross_checks_full_execution_identity(store, defect):
    services, run, node, attempt, *_ = _native_attempt(store)
    run.execution_state["executionGeneration"] = "next-generation"
    if defect == "instance":
        node = node.model_copy(update={"execution_instance_id": "wrong-generation:run:S2:1:root"})
    elif defect == "operation":
        node = node.model_copy(update={"operation_id": node.operation_id + ":generation:forged"})
    else:
        attempt.attempt_number = 2
    with pytest.raises(ValueError):
        assert_native_readonly_retry_safe(services, run, node, allow_historical=True)


@pytest.mark.parametrize("defect", ["running_task", "successful_attempt", "running_execution",
    "mismatched_terminal_execution", "mismatched_outcome", "missing_outcome", "unknown_outcome",
    "unknown_agent", "replaced_implementation", "wrong_generation"])
def test_permit_readonly_retry_rejects_unproven_agent_or_live_task(store, defect):
    services, run, node, attempt, execution, binding, agent = _native_attempt(store)
    if defect == "running_task":
        run.execution_state["taskSettlement"][node.attempt_id]["taskState"] = "running"
    elif defect == "successful_attempt":
        attempt.status.value = "succeeded"
    elif defect == "running_execution":
        execution.status.value = "running"
    elif defect == "mismatched_terminal_execution":
        execution.status.value = "cancelled"
    elif defect == "mismatched_outcome":
        attempt.status.value = execution.status.value = "cancelled"
    elif defect == "missing_outcome":
        run.execution_state["taskSettlement"][node.attempt_id].pop("outcome")
    elif defect == "unknown_outcome":
        run.execution_state["taskSettlement"][node.attempt_id]["outcome"] = "unknown"
    elif defect == "unknown_agent":
        binding.metadata["agentRegistration"]["definitionDigest"] = "different"
    elif defect == "replaced_implementation":
        agent.run = lambda *_: None
    elif defect == "wrong_generation":
        run.execution_state["executionGeneration"] = "another"
    with pytest.raises(ValueError):
        assert_native_readonly_retry_safe(services, run, node)


def _session_non_invocation(**kwargs):
    run, node = kwargs["run"], kwargs["node"]
    assert kwargs["operation"] == node.operation_id
    assert kwargs["tool"] == "native.tool-session" and kwargs["raw_arguments"] is None
    assert kwargs["workspace"] == run.input["workspaceBinding"]
    return {"source": "formal-workspace-write-ahead.v1",
        "identity": {"runId": run.run_id, "stepId": node.step_id,
            "attemptId": node.attempt_id, "commitId": node.operation_id},
        "operationKey": node.operation_id, "capabilityId": "native.tool-session",
        "workspaceId": kwargs["workspace"]["workspaceId"], "grantId": kwargs["workspace"]["grantId"],
        "dispatched": False}


def _empty_native_attempt(store, **kwargs):
    seeded = _native_attempt(store, **kwargs)
    with store._connection:
        store._connection.execute("DELETE FROM execution_values WHERE run_id=?", (seeded[1].run_id,))
    seeded[0].tool_non_invocation_prover = _session_non_invocation
    return seeded


def _seed_memory_input(store, run, node, *, with_record=False):
    from components.executor.memory_input import frozen_memory_policy, normalize_memory_policy

    policy = normalize_memory_policy(run.get_step(node.step_id).input)
    records = ([{"memoryId": "prior-finding", "memoryType": "episodic", "scope": run.run_id,
        "content": {"finding": "previously verified dependency"}, "createdAt": "2026-11-16T00:00:00Z"}]
        if with_record else [])
    snapshot = {"schemaVersion": 1,
        "identity": {"runId": run.run_id, "stepId": node.step_id,
            "attemptId": node.attempt_id, "commitId": node.operation_id},
        "policy": frozen_memory_policy(policy), "records": records,
        "retrievalEvent": {"scope": run.run_id, "mode": "bm25", "budget": policy["tokenBudget"],
            "hitRefs": [record["memoryId"] for record in records]} if policy["read"] else None}
    reference = store.put_tool_value(run_id=run.run_id, step_id=node.step_id,
        key=node.operation_id + ":memory-retrieval", payload=snapshot)
    return reference, snapshot


@pytest.mark.parametrize("before_model", [False, True])
@pytest.mark.parametrize("read_memory", [False, True])
def test_frozen_memory_is_an_execution_input_and_does_not_block_safe_recovery(store, before_model, read_memory):
    prepare = _empty_native_attempt if before_model else _native_attempt
    services, run, node, *_ = prepare(store)
    if not read_memory:
        run.get_step(node.step_id).input = {"memoryPolicy": {"read": False, "write": False}}
    reference, snapshot = _seed_memory_input(store, run, node, with_record=read_memory)
    before = list(store._connection.execute("SELECT * FROM execution_values ORDER BY reference"))
    proof = assert_native_readonly_retry_safe(services, run, node)
    assert proof["retrySafe"] is True
    assert proof["modelTurnCount"] == (0 if before_model else 1)
    assert proof["readRequestCount"] == (0 if before_model else 1)
    assert list(store._connection.execute("SELECT * FROM execution_values ORDER BY reference")) == before
    assert store.get_output(run_id=run.run_id, output_ref=reference) == snapshot
    assert not run.completed_step_ids and not run.execution_state.get("outputRefs")


@pytest.mark.parametrize("before_model", [False, True])
@pytest.mark.parametrize("damage", ["ledger_run", "ledger_step", "ledger_kind", "ledger_operation",
    "attempt", "policy", "schema", "scope", "event", "external_fields", "untrusted_key"])
def test_recovery_trusts_only_the_exact_owned_validated_memory_input(store, before_model, damage):
    prepare = _empty_native_attempt if before_model else _native_attempt
    services, run, node, *_ = prepare(store)
    reference, snapshot = _seed_memory_input(store, run, node, with_record=True)
    if damage.startswith("ledger_"):
        column, value = {"ledger_run": ("run_id", "other-run"), "ledger_step": ("step_id", "other-step"),
            "ledger_kind": ("kind", "context"), "ledger_operation": ("operation_id", node.operation_id)}[damage]
        with store._connection:
            store._connection.execute(f"UPDATE execution_values SET {column}=? WHERE reference=?", (value, reference))
    elif damage == "untrusted_key":
        with store._connection:
            store._connection.execute("DELETE FROM execution_values WHERE reference=?", (reference,))
        store.put_tool_value(run_id=run.run_id, step_id=node.step_id,
            key=node.operation_id + ":not-the-memory-input", payload=snapshot)
    else:
        if damage == "attempt": snapshot["identity"]["attemptId"] = "other-attempt"
        elif damage == "policy": snapshot["policy"]["limit"] += 1
        elif damage == "schema": snapshot["schemaVersion"] = True
        elif damage == "scope": snapshot["records"][0]["scope"] = "other-run"
        elif damage == "event": snapshot["retrievalEvent"]["hitRefs"] = []
        elif damage == "external_fields": snapshot["request"] = {"invocationId": node.operation_id + ":hidden-write"}
        _replace_payload(store, run.run_id, node.operation_id + ":memory-retrieval", snapshot)
    with pytest.raises(ValueError):
        assert_native_readonly_retry_safe(services, run, node)


@pytest.mark.parametrize("before_model", [False, True])
def test_valid_memory_input_never_hides_a_real_write_request(store, before_model):
    prepare = _empty_native_attempt if before_model else _native_attempt
    services, run, node, *_ = prepare(store)
    _seed_memory_input(store, run, node)
    operation = node.operation_id + ":tools:1:call:0"
    store.put_tool_value(run_id=run.run_id, step_id=node.step_id, key=operation + ":request",
        payload={"request": _request(operation, "fs.write", "note.txt").model_dump(by_alias=True, mode="json")})
    with pytest.raises(ValueError):
        assert_native_readonly_retry_safe(services, run, node)


def test_memory_input_alone_cannot_authorize_recovery_and_is_included_in_its_evidence_fingerprint(store):
    services, run, node, *_ = _empty_native_attempt(store)
    _, snapshot = _seed_memory_input(store, run, node)
    services.tool_non_invocation_prover = None
    with pytest.raises(ValueError, match="no-dispatch proof"):
        assert_native_readonly_retry_safe(services, run, node)
    services.tool_non_invocation_prover = _session_non_invocation
    first = assert_native_readonly_retry_safe(services, run, node)
    snapshot["retrievalEvent"]["fallbackReason"] = "SEMANTIC_MODEL_NOT_CONFIGURED"
    _replace_payload(store, run.run_id, node.operation_id + ":memory-retrieval", snapshot)
    second = assert_native_readonly_retry_safe(services, run, node)
    assert first["evidenceFingerprint"] != second["evidenceFingerprint"]


@pytest.mark.parametrize("terminal_status", ["failed", "cancelled"])
@pytest.mark.parametrize("capability", ["information_extraction", "verification", "analysis",
    "requirement_analysis", "architecture_design", "artifact_generation", "task_understanding", "evidence_analysis"])
def test_ended_native_before_first_model_turn_requires_whole_session_non_invocation(store, terminal_status, capability):
    services, run, node, attempt, execution, *_ = _empty_native_attempt(store, terminal_status=terminal_status)
    run.get_step(node.step_id).capability = capability
    before = store.list_node_commits(run_id=run.run_id)
    proof = assert_native_readonly_retry_safe(services, run, node)
    assert proof["kind"] == "native_session_not_dispatched"
    assert proof["modelTurnCount"] == proof["toolDeclarationCount"] == proof["readRequestCount"] == 0
    assert proof["nonInvocationProofs"][0]["dispatched"] is False
    assert "authorization" not in proof and "toolEvidence" not in proof
    proofs = []
    assert tuple(assert_replay_safe_operations(services, run, readonly_proofs=proofs)) == before
    assert proofs == [proof]
    assert store.list_node_commits(run_id=run.run_id) == before
    assert attempt.status.value == execution.status.value == terminal_status


@pytest.mark.parametrize("defect", ["missing", "wrong_identity", "wrong_scope", "wrong_boundary", "was_dispatched"])
def test_absent_model_turn_is_insufficient_without_matching_trusted_proof(store, defect):
    services, run, node, *_ = _empty_native_attempt(store)
    proof = _session_non_invocation(run=run, node=node, operation=node.operation_id, tool="native.tool-session",
        raw_arguments=None, workspace=run.input["workspaceBinding"])
    if defect == "missing":
        services.tool_non_invocation_prover = None
    else:
        if defect == "wrong_identity": proof["identity"]["attemptId"] = "other"
        elif defect == "wrong_scope": proof["grantId"] = "other"
        elif defect == "wrong_boundary": proof["source"] = "untrusted-adapter"
        elif defect == "was_dispatched": proof["dispatched"] = True
        services.tool_non_invocation_prover = lambda **_: proof
    with pytest.raises(ValueError, match="proof"):
        assert_native_readonly_retry_safe(services, run, node)


@pytest.mark.parametrize("marker", ["request", "identity", "record", "commit", "model_turn", "misaddressed_model_turn"])
def test_empty_session_proof_closes_all_existing_external_or_frozen_activity(store, marker):
    services, run, node, *_ = _empty_native_attempt(store)
    payloads = {
        "request": {"request": {"invocationId": node.operation_id + ":tools:3:call:0"}},
        "identity": {"identity": {"commitId": node.operation_id}},
        "record": {"record": {"commitId": node.operation_id}},
        "commit": {"commitId": node.operation_id},
        "model_turn": {"requestHash": "a" * 64, "response": {"requestId": node.operation_id + ":tools:3"}},
        "misaddressed_model_turn": {"requestHash": "a" * 64, "response": {"requestId": "another:tools:3"}},
    }
    key = node.operation_id + (":tools:3:model-turn" if "model_turn" in marker else ":tools:3:call:0:" + marker)
    store.put_tool_value(run_id=run.run_id, step_id=node.step_id, key=key, payload=payloads[marker])
    services.tool_non_invocation_prover = lambda **_: pytest.fail("activity must block empty-session admission")
    with pytest.raises(ValueError):
        assert_native_readonly_retry_safe(services, run, node)


@pytest.mark.parametrize("defect", ["live", "wrong_generation", "wrong_agent", "wrong_capability"])
def test_empty_session_still_requires_ended_native_identity_and_supported_capability(store, defect):
    services, run, node, attempt, _, binding, _ = _empty_native_attempt(store)
    if defect == "live": attempt.status.value = "running"
    elif defect == "wrong_generation": run.execution_state["executionGeneration"] = "other"
    elif defect == "wrong_agent": binding.metadata["agentRegistration"]["definitionDigest"] = "other"
    elif defect == "wrong_capability": run.get_step(node.step_id).capability = "information_retrieval"
    with pytest.raises(ValueError):
        assert_native_readonly_retry_safe(services, run, node)


def test_second_retry_keeps_previous_settled_authorization_and_observations_when_current_attempt_did_no_work(store):
    from components.executor.node_runner import ACGNodeRunner
    from runtime.permit_recovery import settled_retry_observations
    from test_settled_session_retry_audit import _register_authorization, _settled_shell

    services, run, old, operation, auth = _settled_shell(store)
    registered = _register_authorization(store, run, old, auth)
    run.execution_state["settledSessionRetryProofs"] = {old.operation_id: registered}
    old_attempt = services.identity_lifecycle.repositories.attempts.get(old.attempt_id)
    new = old.model_copy(update={"operation_id": ACGNodeRunner._commit_id(run.run_id, old.step_id, 1,
        execution_generation="generation"), "attempt_id": "attempt:S2:2",
        "execution_instance_id": "generation:run:S2:1:root"})
    store.prepare_node_commit(run_id=run.run_id, commit_id=new.operation_id)
    store.transition_node_execution(new)
    new_attempt = SimpleNamespace(run_id=run.run_id, task_id=old_attempt.task_id, attempt_number=2,
        status=SimpleNamespace(value="failed"))
    services.identity_lifecycle.repositories.attempts.get = lambda key: old_attempt if key == old.attempt_id else new_attempt
    services.tool_non_invocation_prover = _session_non_invocation
    run.get_step(old.step_id).attempt = 1
    run.execution_state["taskSettlement"][new.attempt_id] = {"taskState": "ended", "outcome": "failed"}
    before = settled_retry_observations(services, run, old.step_id)
    later_auth = {**auth, "operationId": "second-explicit-recovery", "requestFingerprint": "second-request", "policyRevision": 2}
    readonly, settled = [], []
    receipts = assert_replay_safe_operations(services, run, readonly_proofs=readonly,
        operator_recovery=later_auth, settled_proofs=settled)
    assert len(receipts) == 2
    assert len(readonly) == len(settled) == 1
    assert readonly[0]["operationId"] == new.operation_id
    assert readonly[0]["kind"] == "native_session_not_dispatched"
    assert settled[0] == registered
    assert settled[0]["authorization"] == auth
    assert settled[0]["authorization"]["policyRevision"] == 1
    assert settled_retry_observations(services, run, old.step_id) == before
    assert before[0]["record"]["attemptId"] == old.attempt_id
    assert before[0]["operationKey"] == operation
