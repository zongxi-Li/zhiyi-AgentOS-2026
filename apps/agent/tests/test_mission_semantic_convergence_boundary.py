"""Application activation and trusted identity, using temporary databases only."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace

from test_execution_runtime_application_wiring import _environment, _InjectedToolRuntime, _InjectedModelRuntime, _InjectedIntentLLM
from app.execution.wiring import build_default_runtime, close_runtime
from app.security.internal_auth import TrustedUserContext, _trusted_user_context, current_semantic_principal
from app.api.agentos_v2 import _actor_input, create_router
from contracts.mission_semantic import MissionSemanticRequest, SemanticPrincipal, run_intent_basis
from support.stores.sqlite_workflow_store import SQLiteWorkflowStore


def test_principal_is_trusted_context_and_unscoped_tenant_cannot_be_spoofed():
    token = _trusted_user_context.set(TrustedUserContext(user_id="owner", subject="owner", role="user"))
    try:
        principal = current_semantic_principal()
        assert principal.actor_id == "owner" and principal.tenant_id == "__unscoped__"
        stamped = _actor_input({"authenticatedUserId": "attacker", "authenticatedTenantId": "attacker"})
        assert stamped["authenticatedUserId"] == "owner"
        assert "authenticatedTenantId" not in stamped
    finally:
        _trusted_user_context.reset(token)
    assert current_semantic_principal() is None


def test_application_activation_uses_same_store_without_semantic_migration(tmp_path):
    env = {**_environment(tmp_path), "AGENTOS_MISSION_SEMANTIC_CONVERGENCE": "true"}
    SQLiteWorkflowStore(env["AGENTOS_WORKFLOW_DB_PATH"], enable_mission_semantics=True)
    runtime = build_default_runtime(environment=env, tool_runtime=_InjectedToolRuntime(),
        model_runtime=_InjectedModelRuntime(), intent_llm=_InjectedIntentLLM())
    token = _trusted_user_context.set(TrustedUserContext(user_id="owner", tenant_id="tenant", subject="owner", role="user"))
    try:
        assert runtime.mission_semantic_service.store is runtime.workflow_store
        mission = runtime.create_mission("untrusted title", input=_actor_input({"userIntent": "legacy"}),
            defer_identity_projection=True)
        principal = current_semantic_principal()
        runtime.mission_semantic_service.commit(principal, MissionSemanticRequest(missionId=mission.mission_id,
            operationId="formal", expectedMissionRevision=0, objective="formal objective", constraints=[]))
        _, run = runtime.prepare_run(mission.mission_id, defer_acg_planning=True)
        assert run_intent_basis(run).objective == "formal objective"
        intruder = SemanticPrincipal(actorId="intruder", tenantId="tenant")
        with pytest.raises(PermissionError):
            runtime.mission_semantic_service.get_effective_snapshot(intruder, mission.mission_id)
        with pytest.raises(PermissionError):
            runtime.prepare_run(mission.mission_id, semantic_principal=intruder, defer_acg_planning=True)
        with pytest.raises(PermissionError):
            runtime.prepare_run(mission.mission_id,
                semantic_principal=SemanticPrincipal(actorId="owner", tenantId="other"), defer_acg_planning=True)
    finally:
        _trusted_user_context.reset(token)
        close_runtime(runtime)


def test_application_activation_requires_explicitly_installed_schema(tmp_path):
    env = {**_environment(tmp_path), "AGENTOS_MISSION_SEMANTIC_CONVERGENCE": "true"}
    with pytest.raises(RuntimeError, match="upgraded explicitly"):
        build_default_runtime(environment=env, tool_runtime=_InjectedToolRuntime(),
            model_runtime=_InjectedModelRuntime(), intent_llm=_InjectedIntentLLM())


@pytest.mark.parametrize("trusted, payload, expected", [
    (False, {"authenticatedUserId": "owner", "userIntent": "forged"}, 403),
    (True, {"missionIntentBasis": {"objective": "forged"}}, 422),
])
def test_http_boundary_rejects_untrusted_authority_before_mission_creation(tmp_path, trusted, payload, expected):
    env = {**_environment(tmp_path), "AGENTOS_MISSION_SEMANTIC_CONVERGENCE": "true"}
    SQLiteWorkflowStore(env["AGENTOS_WORKFLOW_DB_PATH"], enable_mission_semantics=True)
    runtime = build_default_runtime(environment=env, tool_runtime=_InjectedToolRuntime(),
        model_runtime=_InjectedModelRuntime(), intent_llm=_InjectedIntentLLM())
    app = FastAPI()
    app.include_router(create_router(runtime, SimpleNamespace()))
    actor = TrustedUserContext(user_id="owner", tenant_id="tenant", subject="owner", role="user") if trusted else None
    token = _trusted_user_context.set(actor)
    try:
        before = runtime.workflow_store.list_missions()
        response = TestClient(app).post("/agentos/v2/missions", json={"title": "legacy", "input": payload})
        assert response.status_code == expected
        assert runtime.workflow_store.list_missions() == before
    finally:
        _trusted_user_context.reset(token)
        close_runtime(runtime)
