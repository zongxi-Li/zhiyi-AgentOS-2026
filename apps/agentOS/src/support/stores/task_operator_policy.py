"""Shared synchronous policy serialization and adapter-independent CAS logic."""

import threading
from weakref import WeakValueDictionary

from contracts.task_operator_policy import (
    TaskOperatorPolicy, TaskOperatorPolicyChange, TaskOperatorPolicyConflict,
)
from contracts.workflow import utc_now


_locks = WeakValueDictionary()
_registry_lock = threading.Lock()


def policy_lock(namespace, mission_id):
    """Keep locks alive only while a caller holds them; never hold across await."""
    key = (namespace, mission_id)
    with _registry_lock:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _locks[key] = lock
        return lock


def prepare_policy(current, change: TaskOperatorPolicyChange, receipt=None):
    submitted = change.model_dump(mode="json")
    if receipt is not None:
        if receipt["request"] != submitted:
            raise TaskOperatorPolicyConflict("task approval operation id has different content")
        return TaskOperatorPolicy.model_validate(receipt["policy"]), True
    if (change.expected_policy_revision is not None
            and change.expected_policy_revision != current.policy_revision):
        raise TaskOperatorPolicyConflict("task approval policy revision changed")
    if (change.operation_id is None and current.permission == change.permission
            and current.approval_mode == change.approval_mode
            and current.workspace_scope == change.workspace_scope):
        return current, True
    return TaskOperatorPolicy(mission_id=current.mission_id,
        permission=change.permission, approval_mode=change.approval_mode,
        policy_revision=current.policy_revision + 1, workspace_scope=change.workspace_scope,
        updated_by=change.actor, updated_at=utc_now(), operation_id=change.operation_id), False


def policy_receipt(change, policy):
    return {"request": change.model_dump(mode="json"),
        "policy": policy.model_dump(by_alias=True, mode="json")}
