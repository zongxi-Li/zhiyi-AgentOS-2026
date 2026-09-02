from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from adapters.resource_execution import HttpResourceExecutionAdapter, ResourceExecutionError
from service.agents.base import AgentOutput


def _context() -> SimpleNamespace:
    return SimpleNamespace(
        task=SimpleNamespace(mission_id="mission-1"),
        run=SimpleNamespace(run_id="run-1"),
        step=SimpleNamespace(step_id="step-1", agent_name="edge-vision", capability="vision.infer", goal="classify"),
        context_pack=SimpleNamespace(
            data={"imageRef": "artifact://image-1"},
            evidence_refs=["evidence-1"],
            attempt_id="attempt-1",
        ),
        commit_id="commit-1",
    )


@pytest.mark.asyncio
async def test_http_adapter_sends_controlled_context_and_returns_agent_output() -> None:
    received: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        received["headers"] = dict(request.headers)
        received["json"] = json.loads(request.content)
        return httpx.Response(200, json={"output": {"label": "cat"}, "summary": "classified"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://edge")
    adapter = HttpResourceExecutionAdapter(address="http://edge", client=client)

    result = await adapter.run(_context())

    assert isinstance(result, AgentOutput)
    assert result.output == {"label": "cat"}
    assert received["headers"]["idempotency-key"] == "commit-1"
    assert received["json"] == {
        "runId": "run-1",
        "missionId": "mission-1",
        "stepId": "step-1",
        "attemptId": "attempt-1",
        "commitId": "commit-1",
        "agentName": "edge-vision",
        "capability": "vision.infer",
        "goal": "classify",
        "input": {"imageRef": "artifact://image-1"},
        "evidenceRefs": ["evidence-1"],
    }
    await client.aclose()


@pytest.mark.asyncio
async def test_http_adapter_reports_remote_failure_without_returning_fake_output() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "edge unavailable"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://edge")
    adapter = HttpResourceExecutionAdapter(address="http://edge", client=client)

    with pytest.raises(ResourceExecutionError, match="REMOTE_EXECUTION_FAILED"):
        await adapter.run(_context())

    await client.aclose()
