import pytest

from app.api.model_usage import cache_usage, cache_summary, cache_groups


@pytest.mark.parametrize("usage,expected", [
    ({"prompt_cache_hit_tokens": 20}, (20, True)),
    ({"prompt_tokens_details": {"cached_tokens": 0}}, (0, True)),
    ({"cache_read_tokens": 0, "prompt_cache_hit_tokens": 20}, (0, True)),
    ({"prompt_tokens_details": {}, "input_tokens_details": {"cached_tokens": 8}}, (8, True)),
    ({"prompt_cache_hit_tokens": 20, "prompt_tokens_details": {"cached_tokens": 20}}, (20, True)),
    ({}, (0, False)),
    ({"cached_tokens": None}, (0, False)),
    ({"cached_tokens": -1}, (0, False)),
])
def test_cache_usage_preserves_zero_missing_and_aliases(usage, expected):
    assert cache_usage(usage) == expected


def call(tokens, hits, reported=True, prefix="p", capability="analysis"):
    return {"provider": "deepseek", "model": "model", "capabilityId": capability,
            "cacheUsageReported": reported, "usage": {"inputTokens": tokens, "cacheReadTokens": hits},
            "requestDiagnostics": {"layoutVersion": "shared-execution.v1", "sharedPrefixHash": prefix}}


def test_cache_summary_is_weighted_and_missing_is_not_zero():
    items = [call(100, 80), call(900, 20)]
    assert cache_summary(items)["cacheHitRatio"] == .1
    assert cache_summary(items)["cacheMissTokens"] == 900
    assert cache_summary(items + [call(10, 0, False)])["cacheHitRatio"] is None
    assert cache_summary([call(10, 0)])["cacheHitRatio"] == 0


def test_cache_groups_keep_prefix_and_capability_boundaries():
    groups = cache_groups([call(100, 80), call(900, 20), call(100, 0, prefix="other"), call(10, 0, capability="verify")])
    assert len(groups) == 3
    assert groups[0]["callCount"] == 2
    assert groups[0]["cacheHitRatio"] == .1


@pytest.mark.asyncio
async def test_resource_usage_routes_project_reported_and_missing_cache(tmp_path):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from app.api.agentos_v2 import create_router
    from app.execution.coordinator import RunExecutionCoordinator
    from components.content import SQLiteContentManifestStore
    from components.mission_manager.store import WorkflowRegistry
    from components.recovery.checkpoint import ACGCheckpointStore
    from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord, TraceEvent
    from runtime import ExecutionRuntime
    from service.agents import AgentRegistry
    from support.stores.memory_workflow_store import MemoryWorkflowStore

    store = MemoryWorkflowStore()
    mission = RuntimeMissionRecord(title="Usage test")
    store.save_mission(mission)
    run = RuntimeRunRecord(missionId=mission.mission_id, workflowId="usage-test", domain="general", runtimeEngine="acg")
    run.trace.append(TraceEvent(eventType="model_called", stepId="step", payload={
        "provider": "deepseek", "model": "model", "capabilityId": "analysis",
        "usage": {"prompt_tokens": 100, "prompt_cache_hit_tokens": 25},
        "requestDiagnostics": {"layoutVersion": "shared-execution.v1", "sharedPrefixHash": "hash"},
    }))
    store.save_run(run)
    content = SQLiteContentManifestStore(tmp_path / "content.sqlite3")
    runtime = ExecutionRuntime(agent_registry=AgentRegistry(), workflow_registry=WorkflowRegistry(),
        workflow_store=store, checkpoint_store=ACGCheckpointStore(db_path=tmp_path / "checkpoint.sqlite3"),
        content_manifest_store=content)
    app = FastAPI()
    app.include_router(create_router(runtime, RunExecutionCoordinator(runtime)))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            result = await client.get(f"/agentos/v2/runs/{run.run_id}/resource-usage")
            assert result.status_code == 200, result.text
            assert result.json()["usage"]["cacheHitRatio"] == .25
            assert result.json()["usage"]["cacheMissTokens"] == 75
            assert result.json()["cacheGroups"][0]["capabilityId"] == "analysis"
            calls = await client.get(f"/agentos/v2/runs/{run.run_id}/resource-usage/calls")
            assert calls.json()["items"][0]["requestDiagnostics"]["sharedPrefixHash"] == "hash"
            latest = store.get_run(run.run_id)
            latest.trace[0].payload["usage"] = {"prompt_tokens": 100}
            store.save_run(latest)
            missing = await client.get(f"/agentos/v2/runs/{run.run_id}/resource-usage")
            assert missing.json()["usage"]["cacheHitRatio"] is None
            assert missing.json()["usage"]["cacheUsageMissingCalls"] == 1
    finally:
        content.close()
