from __future__ import annotations

import asyncio
import json

from adapters.audited_tool_runtime import AuditedToolRuntime, ToolAuthorizationError
from app.execution.tool_calls import execute_read_only_tool, network_tools_enabled
from app.tools.contracts import SourceReference, ToolPayload
from app.tools.runtime import AgentsToolRuntime


class _FixtureCatalog:
    TOOL_NAMES = ("web_search", "knowledge_search")

    def availability(self):
        return {
            "web_search": {"available": True, "provider": "fixture", "readOnly": True},
            "knowledge_search": {"available": True, "provider": "fixture", "readOnly": True},
        }

    async def execute(self, name, arguments, *, role_id=None):
        assert name == "web_search"
        assert arguments == {"query": "current law", "max_results": 3}
        source = SourceReference(
            citationId="src_fixture_law",
            title="Current law",
            url="https://example.test/law",
            snippet="Fixture evidence",
            provider="fixture",
            retrievedAt="2026-08-15T00:00:00+00:00",
        )
        return ToolPayload(
            summary="one cited result",
            data={"results": [{"citationId": source.citation_id, "url": source.url}]},
            sources=[source],
        )


def test_injected_read_only_web_tool_preserves_citation_and_safe_audit_metadata() -> None:
    runtime = AgentsToolRuntime(catalog=_FixtureCatalog())
    audited = AuditedToolRuntime(delegate=runtime, allowed_tools={"web_search"})

    outcome = asyncio.run(
        execute_read_only_tool(audited, "web_search", {"query": "current law", "max_results": 3})
    )

    assert outcome.ok is True
    assert outcome.results == [{"citationId": "src_fixture_law", "url": "https://example.test/law"}]
    assert outcome.sources[0]["citationId"] == "src_fixture_law"
    assert outcome.executions[0]["sourceRefs"] == ["src_fixture_law"]
    assert audited.events == [{"type": "tool_called", "tool": "web_search"}]
    assert "current law" not in json.dumps(audited.events)


def test_offline_and_authorization_policy_do_not_reach_network_delegate() -> None:
    assert network_tools_enabled({"webSearchEnabled": False}) is False
    runtime = AgentsToolRuntime(catalog=_FixtureCatalog())
    offline = AuditedToolRuntime(delegate=runtime, allowed_tools={"knowledge_search"})

    try:
        asyncio.run(offline.execute("web_search", {"query": "must not run"}))
    except ToolAuthorizationError as exc:
        assert exc.code == "TOOL_NOT_AUTHORIZED"
    else:
        raise AssertionError("offline web search must be rejected")
    assert offline.events == []
