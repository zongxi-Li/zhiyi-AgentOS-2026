from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from contracts.local_runtime import (
    LocalRuntimeAuthorizationRef,
    LocalRuntimeExecutionEvent,
    LocalRuntimeExecutionRequest,
    LocalRuntimeExecutionResult,
)


def request_payload():
    return {
        "protocolVersion": "1",
        "requestId": "req-1",
        "invocationId": "inv-1",
        "resourceId": "local-worker-1",
        "capabilityId": "fs.patch",
        "authorization": {"grantId": "grant-1", "workspaceId": "workspace-1"},
        "input": {"path": "src/app.py", "patch": "..."},
        "limits": {"timeoutSeconds": 10, "maxStdoutBytes": 1024, "maxStderrBytes": 1024},
        "idempotencyKey": "attempt-1",
    }


def test_request_uses_versioned_capability_and_opaque_grant():
    request = LocalRuntimeExecutionRequest.model_validate(request_payload())
    assert request.authorization == LocalRuntimeAuthorizationRef(
        grantId="grant-1", workspaceId="workspace-1"
    )
    assert request.capability_id.value == "fs.patch"
    assert request.model_dump(by_alias=True)["authorization"] == {
        "grantId": "grant-1", "workspaceId": "workspace-1"
    }


@pytest.mark.parametrize("change", [
    {"protocolVersion": "2"},
    {"capabilityId": "terminal"},
    {"authorization": {}},
    {"allowedRoot": "C:\\"},
    {"authorization": {"grantId": "grant-1", "workspaceId": "workspace-1", "allowedRoot": "C:\\"}},
    {"input": {"allowedRoot": "C:\\"}},
    {"input": {"options": [{"allowed_root": "C:\\"}]}},
])
def test_request_rejects_unsupported_or_caller_selected_scope(change):
    payload = request_payload()
    payload.update(change)
    with pytest.raises(ValidationError):
        LocalRuntimeExecutionRequest.model_validate(payload)


@pytest.mark.parametrize("field", [
    "requestId", "invocationId", "resourceId", "idempotencyKey",
])
def test_request_rejects_empty_identifiers(field):
    payload = request_payload()
    payload[field] = ""
    with pytest.raises(ValidationError):
        LocalRuntimeExecutionRequest.model_validate(payload)


@pytest.mark.parametrize("field", ["grantId", "workspaceId"])
def test_authorization_rejects_empty_identifiers(field):
    payload = request_payload()
    payload["authorization"][field] = ""
    with pytest.raises(ValidationError):
        LocalRuntimeExecutionRequest.model_validate(payload)


def test_result_and_event_are_correlated_and_validate_outcome():
    now = datetime.now(timezone.utc)
    result = LocalRuntimeExecutionResult(
        requestId="req-1", invocationId="inv-1", status="completed",
        output={"changed": True}, startedAt=now, completedAt=now,
    )
    event = LocalRuntimeExecutionEvent(
        protocolVersion="1", requestId=result.request_id,
        invocationId=result.invocation_id, eventType="file_changed", sequence=1,
    )
    assert event.request_id == result.request_id
    with pytest.raises(ValidationError):
        LocalRuntimeExecutionResult(
            requestId="req-1", invocationId="inv-1", status="failed",
            startedAt=now, completedAt=now,
        )


def test_all_envelopes_forbid_unknown_fields():
    payload = request_payload()
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        LocalRuntimeExecutionRequest.model_validate(payload)
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        LocalRuntimeExecutionResult(
            requestId="req-1", invocationId="inv-1", status="completed",
            startedAt=now, completedAt=now, unexpected=True,
        )
    with pytest.raises(ValidationError):
        LocalRuntimeExecutionEvent(
            protocolVersion="1", requestId="req-1", invocationId="inv-1",
            eventType="started", sequence=0, unexpected=True,
        )
