"""Legal basis retrieval backed by bounded public-web and local read-only tools."""

import hashlib

from app.execution.tool_calls import network_tools_enabled
from service.agents.base import AgentOutput, AgentProfile, BaseAgent
from contracts.workflow import utc_now
from app.execution.tool_calls import execute_read_only_tool
from packs.legal.agents.common import case_text


class StatuteAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            AgentProfile(
                agentName="statute",
                domain="legal",
                capabilities=["statute_retrieval", "legal_basis"],
                allowedSkills=["statute_retrieval", "case_retrieval"],
                allowedTools=[
                    "web_search",
                    "knowledge_search",
                    "current_datetime",
                ],
                description="Finds legal basis for the current dispute and preserves its sources.",
            )
        )

    async def run(self, context):
        text = case_text(context.task.input)
        web = None
        if network_tools_enabled(context.task.input):
            web = await execute_read_only_tool(
                context.tool_runtime,
                "web_search",
                {"query": text[:500], "max_results": 5, "topic": "general"},
            )
        local = None
        if web is None or not web.ok or not web.sources:
            local = await execute_read_only_tool(
                context.tool_runtime,
                "knowledge_search",
                {"query": text[:500], "top_k": 5},
            )
        selected = (
            web
            if web is not None and web.ok and web.sources
            else local
            if local is not None and local.ok and local.sources
            else None
        )
        sources = list(selected.sources) if selected is not None else []
        evidence_refs = [
            str(item.get("citationId"))
            for item in sources
            if item.get("citationId")
        ]
        legal_basis = [
            str(item.get("snippet") or item.get("content") or "").strip()
            for item in (selected.results if selected is not None else [])
            if str(item.get("snippet") or item.get("content") or "").strip()
        ]
        if not evidence_refs:
            citation_id = "src_task_input_" + hashlib.sha256(
                text.encode("utf-8")
            ).hexdigest()[:16]
            sources = [{
                "citationId": citation_id,
                "title": "User-provided legal case facts",
                "content": text[:4000],
                "provider": "task-input",
                "retrievedAt": utc_now().isoformat(),
                "provisional": True,
            }]
            evidence_refs = [citation_id]
            legal_basis = [text]
        tool_executions = [
            execution
            for outcome in (web, local)
            if outcome is not None
            for execution in outcome.executions
        ]
        retrieval_mode = (
            "web_search"
            if selected is web and selected is not None
            else "local_knowledge"
            if selected is local and selected is not None
            else "task_input_only"
        )
        return AgentOutput(
            output={
                "legal_basis": legal_basis,
                "query": text[:500],
                "retrieval_status": "completed" if selected is not None else "degraded",
                "retrieval_mode": retrieval_mode,
                "retrieval_errors": [
                    {"tool": outcome.name, "error": outcome.error_code}
                    for outcome in (web, local)
                    if outcome is not None and outcome.error_code
                ],
                "sources": sources,
                "evidence_refs": evidence_refs,
            },
            summary=f"Retrieved legal basis from {len(evidence_refs)} source(s).",
            sources=sources,
            toolExecutions=tool_executions,
            evidenceRefs=evidence_refs,
        )
