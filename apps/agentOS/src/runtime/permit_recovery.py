"""Evidence-only reconciliation of an acknowledged Permit execution prefix.

No execution, receipt synthesis, checkpoint rollback or GraphVersion mutation.
Only a finished plain-DAG superstep already projected into Workflow may be
acknowledged. Other crash cuts remain explicit recovery barriers.
"""
from datetime import datetime
import hashlib
import json
import sqlite3
from uuid import NAMESPACE_URL, uuid5

from components.executor import ACGExecutionState
from components.executor.node_runner import ACGNodeRunner
from components.communicator.contracts import ContextPack
from components.communicator.provenance import provenance_checksum
from contracts.execution import NodeExecutionRecord
from contracts.agents import AgentRegistrationRef
from contracts.capability import ModelInvocationResponse
from contracts.local_runtime import LocalRuntimeExecutionRequest
from contracts.execution_evidence import workspace_relative_path
from contracts.resource import ExecutionBinding
from contracts.workflow import WorkflowStatus, TraceEventType, utc_now
from contracts import stable_checksum
from domain.identity_graph.resolver import IdentityResolver
from runtime.state_persistence import acg_execution_state_from_run
from support.run_execution_fence import acquire_run_fence
from support.stores.planning_commit_store import content_fingerprint
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore
from support.acg.schema import RuntimeBlueprintSpec


_UNSUCCESSFUL_ATTEMPT_STATES = frozenset({"failed", "cancelled"})


def operator_recovery_authorization(services, run, step_id, operation_id, fingerprint):
    """Freeze trusted operator intent; ordinary dispatch never calls this path."""
    from contracts.task_operator_policy import task_approval_scope_matches

    policy = services.workflow_store.get_task_operator_policy(run.mission_id)
    binding = dict(run.input.get("workspaceBinding") or {})
    profile = getattr(getattr(services, "local_runtime_resource", None), "profile", None)
    if not binding.get("resourceId"):
        binding["resourceId"] = getattr(profile, "runtime_id", None)
    if (policy.permission != "task_collaboration" or policy.approval_mode != "full"
            or not task_approval_scope_matches(policy, binding) or not binding.get("resourceId")):
        return None
    authority = getattr(services, "workspace_authority", None)
    authorization = (authority.resolve(run) if authority else
                     getattr(services, "local_runtime_authorization", None))
    if (authorization is None or authorization.workspace_id != binding.get("workspaceId")
            or authorization.grant_id != binding.get("grantId")):
        raise ValueError("settled-session recovery requires current workspace authority")
    provider = getattr(services, "semantic_principal_provider", None)
    actor = provider() if callable(provider) else None
    if actor is None or not getattr(actor, "actor_id", None) or not operation_id or not fingerprint:
        raise ValueError("settled-session recovery requires an explicit trusted operator identity")
    return {"intent": "recover", "operationId": operation_id, "requestFingerprint": fingerprint,
        "missionId": run.mission_id, "runId": run.run_id, "stepId": step_id,
        "policyRevision": policy.policy_revision,
        "actor": {"userId": actor.actor_id, "tenantId": actor.tenant_id},
        "workspaceScope": {key: binding[key] for key in ("workspaceId", "grantId", "resourceId")},
        "mayRepeatSettledActions": True}


def is_failed_planner_recovery(run):
    """A failed node behind an idle Planner barrier is an explicit retry target."""
    review = run.execution_state.get("reviewPayload") or {}
    loop = run.execution_state.get("planningLoop") or {}
    current = loop.get("current") or {}
    decision = current.get("decision") or {}
    return (run.status == WorkflowStatus.WAITING_REVIEW and review.get("subjectType") == "planner"
        and not run.active_step_ids and not run.execution_state.get("activeStepIds")
        and not decision.get("question")
        and len([step for step in run.steps if step.status.value == "failed"]) == 1)


def _tool_reference(run_id, key):
    return "tool:" + hashlib.sha256((run_id + ":" + key).encode()).hexdigest()


def assert_native_readonly_retry_safe(services, run, node, *, connection=None, allow_historical=False):
    """Prove an ended native acquisition can start a new Attempt safely.

    Read/list requests may have lost their acknowledgement: repeating them has
    no workspace write effect. This proof neither settles those requests nor
    promotes their output into committed evidence. Other native tools and
    arbitrary Agent implementations remain outside this recovery path.
    """
    try:
        return _assert_native_readonly_retry_safe(services, run, node,
            connection=connection, allow_historical=allow_historical)
    except (AttributeError, KeyError, TypeError) as exc:
        raise ValueError("read-only retry evidence is incomplete or malformed") from exc


def run_step_readonly_retry_proof(services, run, step_id):
    """Read the current failed operation and prove it safe without mutating it."""
    step = run.get_step(step_id)
    if step.status.value != "failed":
        raise ValueError("read-only retry proof requires the current failed step")
    if getattr(services.execution_value_store, "db_path", None) is None:
        raise ValueError("read-only retry proof requires a durable execution ledger")
    operation = ACGNodeRunner._commit_id(run.run_id, step_id, step.attempt,
        execution_generation=run.execution_state.get("executionGeneration"))
    with sqlite3.connect(services.execution_value_store.db_path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        row = conn.execute("SELECT payload_json FROM acg_node_executions WHERE run_id=? AND operation_id=?",
                           (run.run_id, operation)).fetchone()
        if row is None:
            raise ValueError("read-only retry lacks the current failed execution record")
        node = NodeExecutionRecord.model_validate_json(row[0])
        return assert_native_readonly_retry_safe(services, run, node, connection=conn)


def _unsuccessful_operation_generation(run, node, attempt, *, allow_historical):
    """Cross-check immutable Attempt numbering and both execution identifiers.

    A retained unsuccessful operation may predate the current graph. Its generation
    comes from the complete execution-instance suffix, never a loose prefix or
    the current projection. Direct retries still require the current generation.
    """
    if (node.run_id != run.run_id or node.loop_path or attempt is None
            or attempt.run_id != run.run_id or attempt.status.value not in _UNSUCCESSFUL_ATTEMPT_STATES):
        raise ValueError("retry operation lacks its unsuccessful terminal Attempt identity")
    counter = attempt.attempt_number - 1
    suffix = f"{run.run_id}:{node.step_id}:{counter}:root"
    instance = node.execution_instance_id
    generation = None
    if instance != suffix:
        if not instance.endswith(":" + suffix):
            raise ValueError("retry execution instance belongs to another Attempt")
        generation = instance[:-len(suffix) - 1]
        if not generation:
            raise ValueError("retry execution generation is empty")
    if (counter < 0 or node.operation_id != ACGNodeRunner._commit_id(
            run.run_id, node.step_id, counter, execution_generation=generation)
            or not allow_historical and generation != run.execution_state.get("executionGeneration")):
        raise ValueError("read-only retry operation belongs to another generation or Attempt")
    return generation


def _assert_native_readonly_retry_safe(services, run, node, *, connection=None, allow_historical=False,
                                      settled_authorization=None):
    from adapters.model.native import NativeGeneralAgent

    repos = services.identity_lifecycle.repositories
    attempt = repos.attempts.get(node.attempt_id)
    step = run.get_step(node.step_id)
    if (node.phase.value != "prepared" or node.run_id != run.run_id or node.loop_path
            or attempt is None or attempt.run_id != run.run_id
            or attempt.status.value not in _UNSUCCESSFUL_ATTEMPT_STATES
            # These native branches have no external tool prologue outside the
            # frozen AgentToolSession. Retrieval/calculator branches do.
            or step.capability not in {"information_extraction", "verification"}):
        raise ValueError("read-only retry requires an unsuccessful terminal native tool-session Attempt")
    _unsuccessful_operation_generation(run, node, attempt, allow_historical=allow_historical)
    executions = repos.step_executions.list_for_attempt(node.attempt_id)
    if (len(executions) != 1 or executions[0].status.value != attempt.status.value
            or executions[0].run_id != run.run_id or executions[0].task_id != attempt.task_id):
        raise ValueError("read-only retry requires the matching terminal StepExecution")
    settlement = run.execution_state.get("taskSettlement", {}).get(node.attempt_id) or {}
    # Shutdown cancels the local Attempt before restart recovery marks its
    # Run/step failed. Preserve that history and prove the same terminal outcome;
    # this proof grants no authority to resume a cancelled or still-active Run.
    if (settlement.get("taskState") != "ended"
            or settlement.get("outcome") != attempt.status.value):
        raise ValueError("read-only retry requires the previous local task to have exited with the same outcome")
    binding = repos.execution_bindings.get_for_attempt(node.attempt_id)
    if binding is None or binding.acg_node_id != node.step_id:
        raise ValueError("read-only retry lacks the previous Agent binding")
    registration = AgentRegistrationRef.model_validate(binding.metadata.get("agentRegistration"))
    native = [item for item in services.agent_registry.registrations()
              if (item.definition.agent_id == registration.agent_id
                  and item.definition.digest == registration.definition_digest
                  and item.definition.source == "native"
                  and item.definition.agent_name == step.agent_name
                  and type(item.implementation) is NativeGeneralAgent
                  and "run" not in vars(item.implementation))]
    if not native:
        raise ValueError("read-only retry requires the known native Agent implementation")
    workspace = run.input.get("workspaceBinding") or {}
    if not workspace.get("workspaceId") or not workspace.get("grantId"):
        raise ValueError("read-only retry requires its frozen workspace binding")
    prover = getattr(services, "tool_non_invocation_prover", None)
    if connection is None:
        with sqlite3.connect(services.execution_value_store.db_path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
            return _native_session_proof(run, node, workspace, conn,
                non_invocation_prover=prover, execution_value_store=services.execution_value_store,
                settled_authorization=settled_authorization)
    return _native_session_proof(run, node, workspace, connection,
        non_invocation_prover=prover, execution_value_store=services.execution_value_store,
        settled_authorization=settled_authorization)


def _readonly_session_proof(run, node, workspace, conn, *, non_invocation_prover=None, execution_value_store=None):
    return _native_session_proof(run, node, workspace, conn,
        non_invocation_prover=non_invocation_prover, execution_value_store=execution_value_store)


def _native_session_proof(run, node, workspace, conn, *, non_invocation_prover=None,
                          execution_value_store=None, settled_authorization=None):
    settled = settled_authorization is not None
    frozen_workspace = workspace
    identity = {"runId": run.run_id, "stepId": node.step_id,
                "attemptId": node.attempt_id, "commitId": node.operation_id}
    if settled:
        scope = settled_authorization.get("workspaceScope") or {}
        if (settled_authorization.get("intent") != "recover"
                or settled_authorization.get("mayRepeatSettledActions") is not True
                or settled_authorization.get("missionId") != run.mission_id
                or settled_authorization.get("runId") != run.run_id
                or settled_authorization.get("stepId") != node.step_id
                or not settled_authorization.get("operationId")
                or not settled_authorization.get("requestFingerprint")
                or not (settled_authorization.get("actor") or {}).get("userId")
                or type(settled_authorization.get("policyRevision")) is not int
                or any(scope.get(key) != workspace.get(key) for key in ("workspaceId", "grantId"))
                or not scope.get("resourceId")
                or workspace.get("resourceId") not in {None, scope["resourceId"]}):
            raise ValueError("settled-session recovery lacks its exact operator authorization")
        workspace = {**workspace, "resourceId": scope["resourceId"]}
    # Tool keys are hashed, so use their primary-key lookups rather than
    # decoding every historical model turn and file body in this Run for each
    # failed Attempt. Only ownership references need the Run-wide closure scan.
    values = {}

    def value(key):
        reference = _tool_reference(run.run_id, key)
        if reference not in values:
            row = conn.execute("SELECT payload_json,step_id,kind FROM execution_values WHERE run_id=? AND reference=?",
                               (run.run_id, reference)).fetchone()
            if row and settled and (row[1] != node.step_id or row[2] != "output"):
                raise ValueError("settled-session tool evidence belongs to another node or kind")
            payload = json.loads(row[0]) if row else None
            if payload is not None and not isinstance(payload, dict):
                raise ValueError("read-only retry has malformed tool activity")
            values[reference] = payload
        return values[reference]

    prefix = node.operation_id + ":"
    if settled or value(f"{node.operation_id}:tools:0:model-turn") is None:
        # Hashed references cannot be decoded. Cross-check each native turn's
        # own addressing, so a hidden/gapped turn cannot evade closure by
        # replacing the response requestId with another operation's identity.
        turn_rows = conn.execute("SELECT reference,payload_json FROM execution_values WHERE run_id=? AND step_id=? "
            "AND reference LIKE 'tool:%' AND json_type(payload_json,'$.requestHash') IS NOT NULL",
            (run.run_id, node.step_id)).fetchall()
        for reference, payload_json in turn_rows:
            payload = json.loads(payload_json)
            turn_id = (payload.get("response") or {}).get("requestId")
            if not isinstance(turn_id, str) or reference != _tool_reference(run.run_id, turn_id + ":model-turn"):
                raise ValueError("native retry has a hidden or misaddressed frozen model turn")
    activity = conn.execute(
        "SELECT reference,json_extract(payload_json, '$.request.invocationId') "
        "FROM execution_values WHERE run_id=? AND reference LIKE 'tool:%' AND ("
        "substr(json_extract(payload_json, '$.request.invocationId'),1,?)=? "
        "OR json_extract(payload_json, '$.identity.commitId')=? "
        "OR json_extract(payload_json, '$.record.commitId')=? "
        "OR json_extract(payload_json, '$.commitId')=? "
        "OR substr(json_extract(payload_json, '$.response.requestId'),1,?)=?)",
        (run.run_id, len(prefix), prefix, node.operation_id, node.operation_id, node.operation_id, len(prefix), prefix),
    ).fetchall()

    declared, expected_refs, turns = {}, set(), 0
    while (turn := value(f"{node.operation_id}:tools:{turns}:model-turn")) is not None:
        key = f"{node.operation_id}:tools:{turns}"
        expected_refs.add(_tool_reference(run.run_id, key + ":model-turn"))
        response = ModelInvocationResponse.model_validate(turn["response"])
        if not isinstance(turn.get("requestHash"), str) or len(turn["requestHash"]) != 64:
            raise ValueError("read-only retry has an invalid frozen model turn")
        if settled and (response.request_id != key or any(c not in "0123456789abcdef" for c in turn["requestHash"])):
            raise ValueError("settled-session model turn has a different invocation identity")
        for index, call in enumerate(response.tool_calls):
            function = call.get("function") or {}
            name = {"fs__read": "fs.read", "fs__list": "fs.list", "fs__write": "fs.write",
                    "fs__patch": "fs.patch", "shell__exec": "shell.exec",
                    "context__list_sources": "context.list_sources", "context__read": "context.read",
                    "context__read_page": "context.read_page"}.get(function.get("name"))
            if name is None:
                raise ValueError("read-only retry contains a write, shell or unknown tool declaration")
            declared[f"{key}:call:{index}"] = (name, function.get("arguments"))
        turns += 1
    non_invocations = []
    if not turns:
        # A native Agent can fail while preparing historical evidence, before
        # its first model response. Only the installed write-ahead adapter can
        # prove that this ended Attempt never admitted an external operation.
        # A failed error code or an absent model-turn alone proves nothing.
        if activity or not callable(non_invocation_prover):
            raise ValueError("native retry lacks a frozen session or a trusted no-dispatch proof")
        proof = non_invocation_prover(run=run, node=node, operation=node.operation_id,
            tool="native.tool-session", raw_arguments=None, workspace=frozen_workspace,
            connection=conn, execution_value_store=execution_value_store)
        expected = {"source": "formal-workspace-write-ahead.v1", "identity": identity,
            "operationKey": node.operation_id, "capabilityId": "native.tool-session",
            "workspaceId": workspace["workspaceId"], "grantId": workspace["grantId"],
            "dispatched": False}
        if proof != expected:
            raise ValueError("native no-dispatch proof does not match its ended session identity")
        non_invocations.append(proof)
    for ref, invocation in activity:
        if isinstance(invocation, str) and invocation.startswith(node.operation_id + ":"):
            if invocation not in declared or ref != _tool_reference(run.run_id, invocation + ":request"):
                raise ValueError("read-only retry contains an undeclared request")
    requests, confirmed, unconfirmed, effects = 0, 0, 0, 0
    tool_evidence = []
    for operation, (tool, raw_arguments) in declared.items():
        for suffix in (":request", ":receipt", ":result", ":admission", ":unsettled"):
            expected_refs.add(_tool_reference(run.run_id, operation + suffix))
        request_wal = value(operation + ":request")
        receipt = value(operation + ":receipt")
        cached = value(operation + ":result")
        admission = value(operation + ":admission")
        unsettled = value(operation + ":unsettled")
        if tool.startswith("context."):
            arguments = json.loads(raw_arguments)
            if not isinstance(arguments, dict) or (tool == "context.list_sources" and arguments):
                raise ValueError("native retry contains malformed context-read arguments")
            allowed = {"producerStepId", "fields"} | ({"cursor", "pageTokens"} if tool == "context.read_page" else set())
            if (set(arguments) - allowed or "cursor" in arguments and arguments["cursor"] is not None and not isinstance(arguments["cursor"], str)
                    or "pageTokens" in arguments and (type(arguments["pageTokens"]) is not int or arguments["pageTokens"] <= 0)):
                raise ValueError("native retry contains malformed context-read arguments")
            if tool != "context.list_sources" and (not isinstance(arguments.get("producerStepId"), str)
                    or not arguments["producerStepId"] or not isinstance(arguments.get("fields"), list)
                    or not arguments["fields"] or any(not isinstance(field, str) or not field for field in arguments["fields"])):
                raise ValueError("native retry contains malformed context-read scope")
            if any(item is not None for item in (request_wal, receipt, cached, admission, unsettled)):
                raise ValueError("context-read declaration contains unexplained external tool activity")
            continue
        if request_wal is None:
            if any(item is not None for item in (receipt, cached, admission, unsettled)):
                raise ValueError("read-only retry has tool activity without its request")
            if tool not in {"fs.read", "fs.list"}:
                if not callable(non_invocation_prover):
                    raise ValueError("read-only retry contains a write, shell or unknown tool declaration without a trusted non-invocation proof")
                proof = non_invocation_prover(run=run, node=node, operation=operation, tool=tool,
                    raw_arguments=raw_arguments, workspace=frozen_workspace, connection=conn,
                    execution_value_store=execution_value_store)
                expected = {"source": "formal-workspace-write-ahead.v1", "identity": identity,
                    "operationKey": operation, "capabilityId": tool,
                    "declarationHash": stable_checksum({"tool": tool, "arguments": raw_arguments}),
                    "workspaceId": workspace["workspaceId"], "grantId": workspace["grantId"],
                    "dispatched": False}
                if proof != expected:
                    raise ValueError("tool non-invocation proof does not match its frozen declaration or identity")
                non_invocations.append(proof)
            continue  # The known adapter can prove a declaration never reached dispatch.
        if tool not in {"fs.read", "fs.list"} and not settled:
            raise ValueError("read-only retry contains a write, shell or unknown tool request")
        request = LocalRuntimeExecutionRequest.model_validate(request_wal["request"])
        arguments = json.loads(raw_arguments)
        if not isinstance(arguments, dict) or tool != "shell.exec" and "path" not in arguments:
            raise ValueError("read-only retry request lacks its declared relative input")
        path_key = "workdir" if tool == "shell.exec" else "path"
        arguments = {**arguments, path_key: workspace_relative_path(arguments.get(path_key, "."))}
        if (request_wal.get("identity") != identity or request.capability_id.value != tool
                or request.invocation_id != operation or request.idempotency_key != operation
                or request.request_id != operation or request.input != arguments
                or request.authorization.model_dump(by_alias=True, mode="json") != {
                    "workspaceId": workspace["workspaceId"], "grantId": workspace["grantId"]}
                or (workspace.get("resourceId") and request.resource_id != workspace["resourceId"])):
            raise ValueError("read-only retry request identity or authority does not match")
        requests += 1
        if settled and (unsettled is not None or receipt is None or cached is None):
            raise ValueError("settled-session retry requires every request's receipt and result without unsettled outcomes")
        for auxiliary in (admission, unsettled):
            if auxiliary is not None and any(auxiliary.get(key) != item for key, item in identity.items()):
                raise ValueError("read-only retry activity belongs to another Attempt")
        if receipt is None:
            if cached is not None:
                raise ValueError("read-only retry cached result lacks its authentic receipt")
            unconfirmed += 1
            continue  # Safe to repeat a read; its outcome remains explicitly unknown.
        started, ended = datetime.fromisoformat(receipt["startedAt"]), datetime.fromisoformat(receipt["completedAt"])
        if (receipt.get("protocolVersion") != "1" or receipt.get("checksum") != stable_checksum({
                key: item for key, item in receipt.items() if key != "checksum"})
                or receipt.get("status") not in ({"completed"} if settled else {"completed", "failed", "cancelled"})
                or receipt.get("identity") != identity or receipt.get("capabilityId") != tool
                or receipt.get("grantId") != workspace["grantId"]
                or receipt.get("invocationId") != request.invocation_id
                or receipt.get("idempotencyKey") != request.idempotency_key
                or receipt.get("requestId") != str(uuid5(NAMESPACE_URL, request.idempotency_key))
                or started.tzinfo is None or ended.tzinfo is None or ended < started):
            raise ValueError("read-only retry has an invalid or uncorrelated Hands receipt")
        if cached is not None:
            record = cached.get("record") or {}
            if (any(record.get(key) != item for key, item in identity.items())
                    or record.get("tool") != tool or record.get("resourceId") != request.resource_id
                    or record.get("grantId") != workspace["grantId"]
                    or record.get("workspaceId") != workspace["workspaceId"]
                    or record.get("requestRef") != _tool_reference(run.run_id, operation + ":request")
                    or record.get("receiptRef") != _tool_reference(run.run_id, operation + ":receipt")
                    or record.get("receiptChecksum") != receipt["checksum"]
                    or not record.get("executionId")
                    or (admission is not None and admission.get("executionId") != record["executionId"])):
                raise ValueError("read-only retry cached result does not match its Hands receipt")
            if settled:
                expected_data = _settled_result_data(receipt, record["executionId"], tool)
                if cached.get("data") != expected_data or record.get("status") != "completed":
                    raise ValueError("settled-session result content does not match its authenticated receipt")
                effects += tool in {"fs.write", "fs.patch", "shell.exec"}
                tool_evidence.append({"operationKey": operation, "record": record,
                    "requestRef": record["requestRef"], "receiptRef": record["receiptRef"]})
        confirmed += 1
    for ref, _invocation in activity:
        if ref not in expected_refs:
            raise ValueError("read-only retry contains unexplained tool activity")
    evidence = {ref: payload for ref, payload in values.items() if payload is not None}
    if non_invocations:
        evidence["nonInvocationProofs"] = non_invocations
    return {"operationId": node.operation_id, "attemptId": node.attempt_id, "stepId": node.step_id,
            "modelTurnCount": turns, "toolDeclarationCount": len(declared),
            "readRequestCount": requests, "confirmedReadCount": confirmed,
            "unconfirmedReadCount": unconfirmed, "retrySafe": True,
            **({"kind": "native_session_not_dispatched"} if not turns else {}),
            **({"nonInvocationProofs": non_invocations} if non_invocations else {}),
            **({"kind": "settled_native_session", "authorization": settled_authorization,
                "settledActionCount": effects, "toolEvidence": tool_evidence} if settled and turns else {}),
            "evidenceFingerprint": stable_checksum(evidence)}


def _settled_result_data(receipt, execution_id, tool):
    """Verify the existing Hands-to-tool projection against its sealed receipt."""
    output = dict(receipt.get("output") or {})
    if tool == "fs.read" and "text" in output:
        output["content"] = output["text"]
    if tool == "fs.list" and isinstance(output.get("entries"), list):
        output["entries"] = [{"path": str((item.get("target") or {}).get("displayPath") or item.get("name") or ""),
            "name": item.get("name"), "type": item.get("type"),
            **({"size": item["size"]} if isinstance(item.get("size"), int) else {})}
            for item in output["entries"] if isinstance(item, dict)]
    for channel in ("stdout", "stderr"):
        if isinstance(output.get(channel), dict):
            stream = output[channel]
            output[channel], output[channel + "Truncated"] = stream.get("text", ""), bool(stream.get("truncated", False))
    output.update(executionId=execution_id, receiptChecksum=receipt["checksum"], handsReceipt=receipt, status="completed")
    return output


def assert_replay_safe_operations(services, run, *, readonly_proofs=None, operator_recovery=None, settled_proofs=None):
    """Require committed work, proven non-invocation or a failed read-only session.

    Retry-safe reads may remain unconfirmed. Their existing WAL is retained as
    such; this admission proof does not create a terminal execution receipt.
    """
    receipts = services.execution_value_store.list_node_commits(run_id=run.run_id)
    with sqlite3.connect(services.execution_value_store.db_path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        operations = {row[0] for row in conn.execute("SELECT operation_id FROM acg_node_executions WHERE run_id=?", (run.run_id,))}
        if operations != {item["commitId"] for item in receipts}:
            raise ValueError("unexplained execution operations block Permit recovery")
        for receipt in receipts:
            row = conn.execute("SELECT payload_json FROM acg_node_executions WHERE run_id=? AND operation_id=?",
                               (run.run_id, receipt["commitId"])).fetchone()
            node = NodeExecutionRecord.model_validate_json(row[0]) if row else None
            if receipt.get("stage") == "committed":
                if (node is None or node.phase.value != "committed"
                        or node.model_dump(mode="json", by_alias=True) != receipt.get("nodeExecution")
                        or node.operation_id != receipt["commitId"] or node.commit_id != receipt["commitId"]
                        or node.run_id != run.run_id or node.step_id not in run.completed_step_ids):
                    raise ValueError("committed operation lacks confirmed Workflow completion or execution evidence")
                if receipt.get("outputRef") != run.execution_state.get("outputRefs", {}).get(node.step_id):
                    raise ValueError("committed operation is not the current completed output")
                # A promoted prefix seals inherited work. Only an exact sealed
                # output may bypass the current generation identity check.
                initial = {}
                if run.execution_state.get("executionGeneration"):
                    authority = services.execution_permit_authority
                    record = authority.store.get_permit(run.execution_state["executionPermitId"])
                    initial = services.checkpoint_store.load(run_id=run.run_id, checkpoint_id=record.promoted_checkpoint_id)
                if node.step_id not in initial.get("completedStepIds", ()):
                    attempt_number = run.get_step(node.step_id).attempt
                    generation = run.execution_state.get("executionGeneration")
                    instance = f"{run.run_id}:{node.step_id}:{attempt_number}:root"
                    if generation:
                        instance = generation + ":" + instance
                    if (node.operation_id != ACGNodeRunner._commit_id(run.run_id, node.step_id, attempt_number,
                                                                   execution_generation=generation)
                            or node.execution_instance_id != instance):
                        raise ValueError("committed operation belongs to another generation or Attempt")
                elif receipt.get("outputRef") != initial.get("outputRefs", {}).get(node.step_id):
                    raise ValueError("inherited operation differs from its promoted output")
                continue
            attempt = services.identity_lifecycle.repositories.attempts.get(node.attempt_id) if node else None
            if receipt.get("stage") != "prepared":
                raise ValueError("unrecognized execution receipt stage blocks Permit recovery")
            proven_not_invoked = (
                node is not None and node.phase.value == "failed"
                and node.failure_code == "AGENT_NOT_IN_SCOPE"
                and node.run_id == run.run_id
                and node.operation_id == receipt["commitId"]
                and attempt is not None and attempt.run_id == run.run_id and attempt.status.value == "failed"
            )
            if proven_not_invoked:
                _unsuccessful_operation_generation(run, node, attempt, allow_historical=True)
                continue
            if node is None or node.phase.value != "prepared":
                raise ValueError("unsettled external operation requires explicit side-effect reconciliation")
            registered = (run.execution_state.get("settledSessionRetryProofs") or {}).get(node.operation_id)
            authorization = registered.get("authorization") if registered else None
            if registered:
                proof = _registered_settled_proof(services, run, node, registered, connection=conn)
            else:
                try:
                    proof = assert_native_readonly_retry_safe(services, run, node, connection=conn, allow_historical=True)
                except ValueError:
                    if not operator_recovery or operator_recovery.get("stepId") != node.step_id:
                        raise
                    authorization = operator_recovery
                    proof = _assert_native_readonly_retry_safe(services, run, node, connection=conn,
                        allow_historical=True, settled_authorization=authorization)
            if authorization:
                if settled_proofs is not None:
                    settled_proofs.append(proof)
            else:
                if readonly_proofs is not None:
                    readonly_proofs.append(proof)
    return receipts


def assert_settled_operations(services, run):
    """Compatibility name; retry-safe read requests need not claim settlement."""
    return assert_replay_safe_operations(services, run)


def settled_retry_observations(services, run, step_id):
    """Revalidate old evidence for this retry; never relabel it as a new action."""
    if not run.execution_state.get("settledSessionRetryProofs"):
        return []
    observations = []
    # A fresh Attempt can already be active when its model context is assembled.
    # Revalidate only admitted historical operations, never demand its new WAL
    # be terminal before it has had an opportunity to execute.
    with sqlite3.connect(services.execution_value_store.db_path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        for operation, registered in run.execution_state["settledSessionRetryProofs"].items():
            if registered.get("stepId") != step_id:
                continue
            row = conn.execute("SELECT payload_json FROM acg_node_executions WHERE run_id=? AND operation_id=?",
                               (run.run_id, operation)).fetchone()
            if row is None:
                raise ValueError("settled-session observation lacks its historical execution")
            node = NodeExecutionRecord.model_validate_json(row[0])
            proof = _registered_settled_proof(services, run, node, registered, connection=conn)
            for item in proof["toolEvidence"]:
                result = services.execution_value_store.get_tool_value(run_id=run.run_id, key=item["operationKey"] + ":result")
                observations.append({"kind": "previous_attempt_tool_observation", **item, "result": result["data"]})
    return observations


def _registered_settled_proof(services, run, node, registered, *, connection):
    authorization = registered.get("authorization") or {}
    key = authorization.get("operationId")
    if (run.execution_state.get("inPlaceRetryRequests") or {}).get(key) != authorization.get("requestFingerprint"):
        raise ValueError("settled-session recovery proof lacks its admitted operator request")
    immutable = services.execution_value_store.get_tool_value(run_id=run.run_id,
        key=str(key) + ":settled-session-authorization")
    expected_ref = _tool_reference(run.run_id, str(key) + ":settled-session-authorization")
    owner = connection.execute("SELECT step_id,kind FROM execution_values WHERE run_id=? AND reference=?",
                               (run.run_id, expected_ref)).fetchone()
    if (registered.get("authorizationRef") != expected_ref or not immutable
            or owner is None or owner[0] != node.step_id or owner[1] != "output"
            or immutable.get("authorization") != authorization
            or {"operationId": node.operation_id, "evidenceFingerprint": registered.get("evidenceFingerprint")}
                not in immutable.get("proofs", [])):
        raise ValueError("settled-session authorization differs from its immutable operator receipt")
    proof = _assert_native_readonly_retry_safe(services, run, node, connection=connection,
        allow_historical=True, settled_authorization=authorization)
    if proof != {key: value for key, value in registered.items() if key != "authorizationRef"}:
        raise ValueError("settled-session recovery evidence changed after operator authorization")
    return {**proof, "authorizationRef": expected_ref}


def _evidence(authority, run, candidate, record):
    rt = authority.runtime
    initial = rt.checkpoint_store.load(run_id=run.run_id, checkpoint_id=record.promoted_checkpoint_id)
    handoff = authority.store.get_handoff(record.handoff_id)
    if initial != authority._promoted_checkpoint_payload(record, handoff):
        raise ValueError("Permit recovery initial checkpoint is corrupt")
    state = ACGExecutionState.model_validate(candidate)
    projected = acg_execution_state_from_run(run)
    if (state.active_step_ids or state.skipped_step_ids or state.review_payload
            or state.control_frames or state.loop_paths or state.loop_iterations
            or state.blackboard_snapshots or state.debate_sessions
            or state.control_review_decisions or state.consensus_results):
        raise ValueError("Permit reconciliation supports only a settled plain DAG superstep")
    # The new checkpoint must be exactly the already-persisted projection,
    # apart from the superstep's settled active list and its new checkpoint ID.
    expected = projected.model_copy(deep=True)
    if not set(expected.active_step_ids) <= set(state.completed_step_ids):
        raise ValueError("Permit recovery contains an unfinished active operation")
    expected.active_step_ids = []
    expected.checkpoint_id = state.checkpoint_id
    if expected != state or set(run.completed_step_ids) != set(state.completed_step_ids):
        raise ValueError("Checkpoint differs from the confirmed Workflow execution projection")
    package = run.execution_state["compiledACGPackage"]
    from contracts.compiled_acg import load_compiled_acg_package
    compiled = load_compiled_acg_package(package)
    if any(n.node_type.value != "step" for n in RuntimeBlueprintSpec.model_validate(run.acg_blueprint).nodes):
        raise ValueError("control graph recovery is unsupported")
    complete = set(state.completed_step_ids)
    if any(edge.target_id in complete and edge.source_id not in complete for edge in compiled.edges):
        raise ValueError("recovered execution prefix is not dependency closed")
    for field in ("outputRefs", "contextRefs", "memoryRefs", "traceRefs", "outputSummaries", "provenanceRefs"):
        if any(candidate[field].get(key) != value for key, value in initial[field].items()):
            raise ValueError("Permit recovery changed the promoted execution prefix")
    if not set(initial["completedStepIds"]) <= complete:
        raise ValueError("Permit recovery lost the promoted completed prefix")
    ledger = rt.provenance_store.load_ledger(run_id=run.run_id, mission_id=run.mission_id)
    rt.acg_execution_service.validate_state_references(run=run, state=state, ledger=ledger)
    receipts = assert_settled_operations(rt, run)
    if any(item.get("stage") == "committed" and (item.get("nodeExecution") or {}).get("stepId") not in complete for item in receipts):
        raise ValueError("unprojected committed work requires separate evidence reconciliation")
    repos = rt.identity_lifecycle.repositories
    identity = repos.runs.get(run.run_id)
    with sqlite3.connect(rt.execution_value_store.db_path.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        for key in complete - set(initial["completedStepIds"]):
            step = run.get_step(key)
            commit_id = ACGNodeRunner._commit_id(run.run_id, key, step.attempt,
                                               execution_generation=record.attempt_generation)
            receipt = next((item for item in receipts if item.get("commitId") == commit_id), None)
            if receipt is None or receipt.get("reviewRequired") or receipt.get("auditOutcome") != "allow":
                raise ValueError("missing committed, unreviewed execution receipt")
            node = NodeExecutionRecord.model_validate(receipt.get("nodeExecution"))
            row = conn.execute("SELECT payload_json FROM acg_node_executions WHERE run_id=? AND operation_id=?",
                               (run.run_id, commit_id)).fetchone()
            if (row is None or NodeExecutionRecord.model_validate_json(row[0]) != node
                    or node.phase.value != "committed" or node.commit_id != commit_id
                    or node.run_id != run.run_id or node.step_id != key
                    or node.audit_ref != receipt.get("auditDecisionRef")
                    or node.artifact_refs.get("output") != receipt.get("outputRef")
                    or node.artifact_refs.get("context") != receipt.get("contextRef")
                    or node.execution_instance_id != f"{record.attempt_generation}:{run.run_id}:{key}:{step.attempt}:root"):
                raise ValueError("receipt and durable NodeExecutionRecord disagree")
            attempt = repos.attempts.get(node.attempt_id)
            task = IdentityResolver(repos).resolve_semantic_task(blueprint_id=identity.blueprint_id, acg_node_id=key)
            executions = repos.step_executions.list_for_attempt(node.attempt_id)
            binding = repos.execution_bindings.get_for_attempt(node.attempt_id)
            selected = run.execution_state.get("executionBindings", {}).get(key, {})
            runtime_binding = ExecutionBinding.model_validate(selected)
            if (attempt is None or attempt.run_id != run.run_id or attempt.task_id != task.task_id
                    or attempt.status.value != "succeeded" or len(executions) != 1
                    or executions[0].status.value != "succeeded" or executions[0].run_id != run.run_id
                    or executions[0].task_id != task.task_id or executions[0].output.get("nodeExecution") != receipt["nodeExecution"]
                    or binding is None or binding.resource_id != selected.get("resourceId")
                    or binding.metadata.get("agentRegistration") != selected.get("agentRegistration")
                    or binding.metadata.get("agentLeaseId") != selected.get("agentLeaseId")
                    or binding.metadata.get("modelBinding") != runtime_binding.identity_metadata.get("modelBinding")
                    or binding.acg_node_id != key or binding.attempt_id != node.attempt_id
                    or selected.get("attemptId") != node.attempt_id
                    or selected.get("runId") != run.run_id or selected.get("stepId") != key):
                raise ValueError("Identity success or Scheduler resource identity is not settled")
            for channel, field in ((state.output_refs, "outputRef"), (state.context_refs, "contextRef"),
                                   (state.memory_refs, "memoryRef"), (state.trace_refs, "traceRef"),
                                   (state.output_summaries, "outputSummary")):
                if channel.get(key) != receipt.get(field):
                    raise ValueError("checkpoint execution references differ from the committed receipt")
            rt.decision_store.assert_decision(run_id=run.run_id, step_id=key,
                                             decision_ref=receipt["auditDecisionRef"], outcomes={"allow"})
            output = rt.execution_value_store.get_output(run_id=run.run_id, output_ref=receipt["outputRef"])
            pack = ContextPack.model_validate(rt.execution_value_store.get_context_pack(
                run_id=run.run_id, context_ref=receipt["contextRef"]))
            if (pack.run_id != run.run_id or pack.step_id != key or pack.contract_status != "valid"
                    or not any(event.operation_id == commit_id and event.producer_step_id == key
                               and event.checksum == provenance_checksum(output) for event in ledger.productions)
                    or not any(event.operation_id == commit_id + ":consume" and event.consumer_step_id == key
                               and event.checksum == provenance_checksum(pack.data) for event in ledger.consumptions)):
                raise ValueError("execution values differ from sealed Provenance")
            if not any(event.event_type == TraceEventType.STEP_SUCCEEDED and event.step_id == key
                       and event.payload.get("commitId") == commit_id for event in run.trace):
                raise ValueError("Workflow success Trace is missing")
    return state, stable_checksum(receipts)


def reconcile_checkpoint(authority, run_id):
    rt = authority.runtime
    with rt.run_lock_manager.lock_for(run_id), acquire_run_fence(authority.store.db_path, run_id):
        run = authority._workflow_run(run_id)
        projection = run.execution_state.get("graphActivation", {}).get("executionPermit") or {}
        record = authority.store.get_permit(projection.get("permitId"))
        if record is None or record.status != "ISSUED":
            raise ValueError("an issued Permit is required for checkpoint reconciliation")
        authority._assert_dispatch_authority(record, check_checkpoint=False)
        head, payload = rt.checkpoint_store.load_latest(run_id=run_id)
        if head == run.execution_state.get("checkpointId"):
            authority.assert_dispatchable(run)
            # Even without a new checkpoint, unknown prepared work must never
            # silently become an automatic retry after process death.
            assert_settled_operations(rt, run)
            return run
        version = rt.checkpoint_store.version(run_id=run_id, checkpoint_id=head)
        if run.status not in {WorkflowStatus.RUNNING, WorkflowStatus.RETRYING}:
            raise ValueError("review or terminal Run cannot automatically acknowledge a checkpoint")
        state, _ = _evidence(authority, run, payload, record)
        candidate = run.model_copy(deep=True)
        candidate.execution_state.update(state.model_dump(by_alias=True, mode="json"))
        candidate.active_step_ids = []
        candidate.runtime_revision += 1
        candidate.updated_at = utc_now()
        # Use the same current-head validation as dispatch on the proposed Run,
        # without persisting or relaxing that public safety gate.
        authority._assert_recovery_head(record, authority.store.get_handoff(record.handoff_id), candidate)
        with authority.store._transaction():
            if content_fingerprint(authority._workflow_run(run_id)) != content_fingerprint(run):
                raise ValueError("Run changed during Permit checkpoint reconciliation")
            authority._assert_dispatch_authority(record, check_checkpoint=False)
            _evidence(authority, run, payload, record)
            if (rt.checkpoint_store.load_latest(run_id=run_id) != (head, payload)
                    or rt.checkpoint_store.latest_version(run_id=run_id) != version):
                raise ValueError("Checkpoint head changed during reconciliation")
            if not SQLiteWorkflowStore._upsert_run(authority.store._local.connection, candidate):
                raise ValueError("Run rejected checkpoint acknowledgement")
        return candidate
