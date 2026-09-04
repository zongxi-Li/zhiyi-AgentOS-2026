from __future__ import annotations

import asyncio
from threading import Lock
import time

import pytest

from adapters.model_adapter import StructuredGenerationError
from app.execution.model_runtime import GatewayStructuredGenerationRuntime


class _Gateway:
    provider_name = "test-provider"
    model = "test-model"

    def __init__(self, *, delay: float = 0.0):
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.kwargs = []
        self._lock = Lock()

    def generate_json(self, prompt, schema, **kwargs):
        self.kwargs.append(dict(kwargs))
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(self.delay)
            return {
                "data": {"answer": prompt},
                "provider": self.provider_name,
                "model": self.model,
                "latency_ms": int(self.delay * 1000),
            }
        finally:
            with self._lock:
                self.active -= 1


class _InvalidJsonGateway(_Gateway):
    def generate_json(self, prompt, schema, **kwargs):
        raise RuntimeError(
            "Invalid JSON returned by provider: Unterminated string starting at column 7080"
        )


def test_structured_runtime_rejects_unavailable_provider(monkeypatch):
    gateway = _Gateway()
    gateway.provider_name = "unavailable"
    monkeypatch.setattr(
        "app.execution.model_runtime.get_llm_gateway", lambda: gateway
    )

    runtime = GatewayStructuredGenerationRuntime(max_concurrency=1)
    with pytest.raises(StructuredGenerationError) as raised:
        asyncio.run(
            runtime.generate_json(
                prompt="task",
                schema={"type": "object", "required": ["answer"]},
            )
        )

    assert raised.value.code == "MODEL_UNAVAILABLE"


def test_structured_runtime_is_nonblocking_and_bounded(monkeypatch):
    gateway = _Gateway(delay=0.05)
    monkeypatch.setattr(
        "app.execution.model_runtime.get_llm_gateway", lambda: gateway
    )
    runtime = GatewayStructuredGenerationRuntime(max_concurrency=2)

    async def execute():
        ticked = False

        async def tick():
            nonlocal ticked
            await asyncio.sleep(0.01)
            ticked = True

        calls = [
            runtime.generate_json(
                prompt=f"task-{index}",
                schema={"type": "object", "required": ["answer"]},
            )
            for index in range(4)
        ]
        results = await asyncio.gather(tick(), *calls)
        return ticked, results[1:]

    ticked, results = asyncio.run(execute())

    assert ticked is True
    assert gateway.max_active == 2
    assert [item.data["answer"] for item in results] == [
        "task-0",
        "task-1",
        "task-2",
        "task-3",
    ]
    assert all(item.audit_record()["model"] == "test-model" for item in results)


def test_structured_runtime_classifies_truncated_json(monkeypatch):
    gateway = _InvalidJsonGateway()
    monkeypatch.setattr(
        "app.execution.model_runtime.get_llm_gateway", lambda: gateway
    )
    runtime = GatewayStructuredGenerationRuntime(max_concurrency=1)

    with pytest.raises(StructuredGenerationError) as raised:
        asyncio.run(
            runtime.generate_json(
                prompt="task",
                schema={"type": "object", "required": ["answer"]},
            )
        )

    assert raised.value.code == "MODEL_OUTPUT_INVALID_JSON"


def test_structured_runtime_propagates_stable_commit_id(monkeypatch):
    gateway = _Gateway()
    monkeypatch.setattr(
        "app.execution.model_runtime.get_llm_gateway", lambda: gateway
    )
    runtime = GatewayStructuredGenerationRuntime(max_concurrency=1)

    asyncio.run(
        runtime.generate_json(
            prompt="task",
            schema={"type": "object", "required": ["answer"]},
            commit_id="commit:run:step:0",
        )
    )

    assert gateway.kwargs[0]["commit_id"] == "commit:run:step:0"


def test_structured_runtime_forwards_timeout_budget_to_gateway(monkeypatch):
    """档位守护预算必须下探到 provider 层：内层留 5 秒余量先于守护触发。

    历史缺陷：native 侧已给执行节点 300/600s 守护，但 gateway/provider 层
    仍是构造期固定 120s 读超时——外层守护从未真正生效。
    """
    gateway = _Gateway()
    monkeypatch.setattr(
        "app.execution.model_runtime.get_llm_gateway", lambda: gateway
    )
    runtime = GatewayStructuredGenerationRuntime(max_concurrency=1)

    asyncio.run(
        runtime.generate_json(
            prompt="task",
            schema={"type": "object", "required": ["answer"]},
            timeout_seconds=300,
        )
    )

    assert gateway.kwargs[0]["timeout_seconds"] == 295.0


def test_structured_runtime_timeout_budget_has_positive_floor(monkeypatch):
    """极小守护预算下内层不得低于 1 秒，避免非法超时值。"""
    gateway = _Gateway()
    monkeypatch.setattr(
        "app.execution.model_runtime.get_llm_gateway", lambda: gateway
    )
    runtime = GatewayStructuredGenerationRuntime(max_concurrency=1)

    asyncio.run(
        runtime.generate_json(
            prompt="task",
            schema={"type": "object", "required": ["answer"]},
            timeout_seconds=3,
        )
    )

    assert gateway.kwargs[0]["timeout_seconds"] == 1.0
