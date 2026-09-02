"""Execution adapters for local and remote AgentOS resources."""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from service.agents.base import AgentOutput, AgentRunContext, BaseAgent


class ResourceExecutionError(RuntimeError):
    """A bound resource could not execute a step safely."""


class ResourceExecutionAdapter(Protocol):
    async def run(self, context: AgentRunContext) -> AgentOutput:
        """Execute one already-bound step using the target resource."""


class LocalResourceExecutionAdapter:
    """Keep existing in-process Agent execution behind the resource seam."""

    def __init__(self, agent: BaseAgent) -> None:
        self.agent = agent

    async def run(self, context: AgentRunContext) -> AgentOutput:
        return await self.agent.run(context)


class ResourceAgentProxy(BaseAgent):
    """Expose a remote resource as a profile-bearing target for the node runner."""

    def __init__(self, *, profile, adapter: ResourceExecutionAdapter) -> None:
        super().__init__(profile)
        self.adapter = adapter

    async def run(self, context: AgentRunContext) -> AgentOutput:
        return await self.adapter.run(context)


class HttpResourceExecutionAdapter:
    """Call a terminal, edge or cloud execution endpoint with a safe context subset."""

    def __init__(
        self,
        *,
        address: str,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        if not address.strip():
            raise ValueError("remote execution address is required")
        if timeout_seconds <= 0:
            raise ValueError("remote execution timeout must be positive")
        self.address = address.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None

    async def run(self, context: AgentRunContext) -> AgentOutput:
        payload = build_remote_execution_payload(context)
        headers = {
            "Idempotency-Key": str(context.commit_id or payload["attemptId"]),
            "X-AgentOS-Run-Id": str(payload["runId"]),
            "X-AgentOS-Step-Id": str(payload["stepId"]),
        }
        try:
            response = await self._client.post(
                f"{self.address}/execute",
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ResourceExecutionError("REMOTE_EXECUTION_FAILED: timeout") from exc
        except httpx.HTTPError as exc:
            raise ResourceExecutionError(f"REMOTE_EXECUTION_FAILED: {exc}") from exc
        if response.is_error:
            detail = response.text[:500]
            raise ResourceExecutionError(
                f"REMOTE_EXECUTION_FAILED: HTTP {response.status_code}: {detail}"
            )
        try:
            body = response.json()
            if not isinstance(body, dict):
                raise TypeError("response JSON must be an object")
            return AgentOutput.model_validate(body)
        except Exception as exc:
            raise ResourceExecutionError("REMOTE_EXECUTION_FAILED: invalid AgentOutput") from exc

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def build_remote_execution_payload(context: AgentRunContext) -> dict[str, Any]:
    """Serialize only the step contract, never the full Runtime or Agent context."""
    pack = context.context_pack
    return {
        "runId": context.run.run_id,
        "missionId": context.task.mission_id,
        "stepId": context.step.step_id,
        "attemptId": str(getattr(pack, "attempt_id", "") or context.commit_id or ""),
        "commitId": str(context.commit_id or ""),
        "agentName": context.step.agent_name,
        "capability": context.step.capability,
        "goal": context.step.goal,
        "input": dict(getattr(pack, "data", {}) or {}),
        "evidenceRefs": list(getattr(pack, "evidence_refs", []) or []),
    }


__all__ = [
    "HttpResourceExecutionAdapter",
    "LocalResourceExecutionAdapter",
    "ResourceAgentProxy",
    "ResourceExecutionAdapter",
    "ResourceExecutionError",
    "build_remote_execution_payload",
]
