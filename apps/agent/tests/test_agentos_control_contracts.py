from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.api.agentos_contracts import (
    AgentOsErrorResponse,
    MissionResponse,
    ReviewResponse,
    RunResponse,
)
from app.api.agentos_v2 import (
    MissionCreateRequest,
    MissionRunCreateRequest,
    ReviewApplyRequest,
    SingleStepRetryRequest,
)
from app.middleware.errorhandler import (
    agentos_http_exception_handler,
    general_exception_handler,
    validation_exception_handler,
)


FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "agentos-v2"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_shared_control_contract_fixtures_are_canonical() -> None:
    assert MissionResponse.model_validate(_fixture("mission-response.json")).run_id
    assert RunResponse.model_validate(_fixture("run-response.json")).status.value == "waiting_review"
    assert ReviewResponse.model_validate(_fixture("review-response.json")).operation_id
    assert SingleStepRetryRequest.model_validate(_fixture("retry-request.json")).mode == "successor_run"
    assert AgentOsErrorResponse.model_validate(_fixture("error-response.json")).code == "AGENTOS_CONFLICT"


def test_control_response_rejects_internal_runtime_fields_and_enum_drift() -> None:
    payload = _fixture("run-response.json")
    with pytest.raises(ValidationError):
        RunResponse.model_validate({**payload, "compiledACGPackage": {"packageVersion": 4}})
    with pytest.raises(ValidationError):
        RunResponse.model_validate({**payload, "executionBindings": {}})
    with pytest.raises(ValidationError):
        RunResponse.model_validate({**payload, "status": "paused"})
    with pytest.raises(ValidationError):
        RunResponse.model_validate({key: value for key, value in payload.items() if key != "runId"})


def test_retry_request_rejects_semantic_and_resource_authority_fields() -> None:
    payload = _fixture("retry-request.json")
    for forbidden in ("taskPlanPatch", "graphPatch", "resourceId", "workerId"):
        with pytest.raises(ValidationError):
            SingleStepRetryRequest.model_validate({**payload, forbidden: {}})


def test_all_core_commands_reject_direct_acg_and_resource_authority() -> None:
    cases = (
        (MissionCreateRequest, {"title": "mission"}),
        (MissionRunCreateRequest, {
            "clientRequestId": "rerun-1", "sourceRunId": "run-1", "rerunReason": "manual"
        }),
        (ReviewApplyRequest, {
            "stepId": "review", "decision": "approved", "operationId": "review-1"
        }),
    )
    for model, payload in cases:
        for forbidden in ("taskPlanPatch", "graphPatch", "resourceId", "workerId"):
            with pytest.raises(ValidationError):
                model.model_validate({**payload, forbidden: {}})


@pytest.mark.asyncio
async def test_agentos_error_envelope_is_stable_for_validation_and_conflict() -> None:
    app = FastAPI()
    app.add_exception_handler(HTTPException, agentos_http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    @app.post("/agentos/v2/missions")
    async def create(request: MissionCreateRequest):
        if request.title == "conflict":
            raise HTTPException(status_code=409, detail="clientRequestId conflict")
        return {}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        invalid = await client.post("/agentos/v2/missions", json={"title": "", "resourceId": "x"})
        conflict = await client.post("/agentos/v2/missions", json={"title": "conflict"})

    assert invalid.status_code == 422
    assert invalid.json()["code"] == "AGENTOS_VALIDATION_ERROR"
    assert set(invalid.json()) == {"code", "message", "requestId"}
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "AGENTOS_CONFLICT"
    assert conflict.json()["message"] == "clientRequestId conflict"


@pytest.mark.asyncio
async def test_agentos_internal_error_is_opaque() -> None:
    app = FastAPI()
    app.add_exception_handler(Exception, general_exception_handler)

    @app.get("/agentos/v2/failure")
    async def fail():
        raise RuntimeError("PRIVATE prompt secret credential C:/internal/path")

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.get("/agentos/v2/failure")

    assert response.status_code == 500
    assert response.json()["code"] == "AGENTOS_INTERNAL_ERROR"
    assert set(response.json()) == {"code", "message", "requestId"}
    assert "PRIVATE" not in response.text
    assert "secret" not in response.text
