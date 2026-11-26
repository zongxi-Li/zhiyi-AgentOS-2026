"""Frozen memory inputs owned by one execution operation, never external actions."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from components.communicator.contracts import estimate_tokens
from components.memory.models import MemoryRetrievalEvent
from contracts import stable_checksum
from contracts.compiled_acg import MemoryManifest, load_compiled_acg_package
from contracts.memory import MemoryRecord, MemoryType


def memory_retrieval_key(operation_id: str) -> str:
    return operation_id + ":memory-retrieval"


def memory_retrieval_reference(run_id: str, operation_id: str) -> str:
    return "tool:" + hashlib.sha256((run_id + ":" + memory_retrieval_key(operation_id)).encode()).hexdigest()


def memory_retrieval_identity(execution) -> dict[str, str]:
    return {"runId": execution.run_id, "stepId": execution.step_id,
            "attemptId": execution.attempt_id, "commitId": execution.operation_id}


def normalize_memory_policy(step_input: object) -> dict[str, Any]:
    """Normalize the frozen Step policy, retaining the historical input format."""
    raw = step_input.get("memoryPolicy") if isinstance(step_input, dict) else None
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("memoryPolicy must be an object")
    read = raw.get("read", True)
    write = raw.get("write", True)
    require_audit = raw.get("requireAudit", False)
    if not all(isinstance(item, bool) for item in (read, write, require_audit)):
        raise ValueError("memoryPolicy read, write and requireAudit must be booleans")
    uses_new_types = "readTypes" in raw or "writeType" in raw
    if uses_new_types and "allowedTypes" in raw:
        raise ValueError("memoryPolicy cannot mix allowedTypes with readTypes or writeType")
    if uses_new_types:
        read_raw = raw.get("readTypes", [])
        if not isinstance(read_raw, list):
            raise ValueError("memoryPolicy.readTypes must be a list")
        if read and not read_raw:
            raise ValueError("memoryPolicy.readTypes must not be empty when read is enabled")
        if write and raw.get("writeType") is None:
            raise ValueError("memoryPolicy.writeType is required when write is enabled")
        if not write and raw.get("writeType") is not None:
            raise ValueError("memoryPolicy.writeType requires write to be enabled")
        write_raw = raw.get("writeType")
    else:
        read_raw = raw.get("allowedTypes", [])
        if not isinstance(read_raw, list):
            raise ValueError("memoryPolicy.allowedTypes must be a list")
        if "allowedTypes" in raw and not read_raw:
            raise ValueError("memoryPolicy.allowedTypes must not be empty when declared")
        write_raw = MemoryType.EPISODIC if write else None
    try:
        read_types = [item if isinstance(item, MemoryType) else MemoryType(str(item)) for item in read_raw]
        write_type = (write_raw if isinstance(write_raw, MemoryType)
                      else MemoryType(str(write_raw)) if write_raw is not None else None)
    except ValueError as exc:
        raise ValueError("memoryPolicy readTypes or writeType contains an unsupported memory type") from exc
    limit = raw.get("limit", 10)
    token_budget = raw.get("tokenBudget")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("memoryPolicy.limit must be an integer between 1 and 100")
    if token_budget is not None and (
        not isinstance(token_budget, int) or isinstance(token_budget, bool) or token_budget < 0
    ):
        raise ValueError("memoryPolicy.tokenBudget must be a non-negative integer or null")
    policy_id = raw.get("policyId", "default")
    if not isinstance(policy_id, str) or not policy_id:
        raise ValueError("memoryPolicy.policyId must be a non-empty string")
    return {"policyId": policy_id, "read": read, "write": write,
            "readTypes": read_types, "writeType": write_type, "limit": limit,
            "tokenBudget": token_budget, "requireAudit": require_audit}


def effective_memory_policy(step_id: str, step_input: object, manifest: MemoryManifest) -> dict[str, Any]:
    policy = normalize_memory_policy(step_input)
    rules = manifest.for_step(step_id)
    if rules:
        access = {rule.access for rule in rules}
        policy.update(read="read" in access, write="write" in access)
    return policy


def projected_memory_manifest(run) -> MemoryManifest:
    raw = run.execution_state.get("compiledACGPackage")
    return load_compiled_acg_package(raw).memory_manifest if raw is not None else MemoryManifest()


def frozen_memory_policy(policy) -> dict[str, Any]:
    return {**policy, "readTypes": [item.value for item in policy["readTypes"]],
            "writeType": policy["writeType"].value if policy["writeType"] else None}


def validate_memory_retrieval_snapshot(snapshot, *, execution, policy):
    """Validate admitted context without recalling memory or rewriting its WAL."""
    if (not isinstance(snapshot, dict)
            or set(snapshot) != {"schemaVersion", "identity", "policy", "records", "retrievalEvent"}
            or type(snapshot.get("schemaVersion")) is not int or snapshot["schemaVersion"] != 1
            or snapshot.get("identity") != memory_retrieval_identity(execution)
            or stable_checksum(snapshot.get("policy")) != stable_checksum(frozen_memory_policy(policy))
            or not isinstance(snapshot.get("records"), list)):
        raise ValueError("memory retrieval snapshot identity or policy changed")
    records = [MemoryRecord.model_validate(record) for record in snapshot["records"]]
    event = (MemoryRetrievalEvent.model_validate(snapshot["retrievalEvent"])
             if snapshot["retrievalEvent"] is not None else None)
    refs = [record.memory_id for record in records]
    if (len(set(refs)) != len(refs) or len(records) > policy["limit"]
            or any(record.scope != execution.run_id or (
                policy["readTypes"] and record.memory_type not in policy["readTypes"]) for record in records)
            or (policy["tokenBudget"] is not None and
                sum(estimate_tokens(record.content) for record in records) > policy["tokenBudget"])
            or (not policy["read"] and (records or event is not None))
            or (policy["read"] and (event is None or event.scope != execution.run_id
                or event.hit_refs != refs or event.budget != policy["tokenBudget"]))):
        raise ValueError("memory retrieval snapshot violates frozen admission")
    return records, event


def read_frozen_memory_retrieval(connection, *, run, execution, policy=None):
    """Recognize only the exact owned internal WAL slot; unknown activity stays external.

    The legacy tool:* namespace also stores immutable execution inputs. A matching
    JSON shape elsewhere grants no exemption from external-action reconciliation.
    """
    reference = memory_retrieval_reference(run.run_id, execution.operation_id)
    row = connection.execute(
        "SELECT run_id,step_id,kind,operation_id,payload_json FROM execution_values WHERE reference=?",
        (reference,),
    ).fetchone()
    if row is None:
        return None
    if tuple(row[:4]) != (run.run_id, execution.step_id, "output", None):
        raise ValueError("memory retrieval snapshot has a different ledger owner or kind")
    from .value_storage import decode_body
    snapshot = decode_body(connection, run_id=run.run_id, reference=reference, encoded=row[4])
    if policy is None:
        policy = effective_memory_policy(execution.step_id, run.get_step(execution.step_id).input,
                                         projected_memory_manifest(run))
    validate_memory_retrieval_snapshot(snapshot, execution=execution, policy=policy)
    return reference, snapshot
