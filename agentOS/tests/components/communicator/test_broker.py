"""受控通信 Broker 的拓扑、字段与预算边界测试。"""

from __future__ import annotations

import asyncio

import pytest

from components.communicator.broker import CommunicationAccessError, CommunicationBroker, EntropyBudgetExceededError
from components.communicator.manifest import CommunicationManifest, CommunicationRule
from components.executor.value_store import InMemoryExecutionValueStore


def _broker(*, channel_budget: int = 100) -> tuple[CommunicationBroker, str]:
    """创建只有 extract -> analyze 单向读取许可的最小通信环境。"""
    values = InMemoryExecutionValueStore()
    output_ref = values.put_output(
        run_id="run-1",
        step_id="extract",
        payload={"title": "AgentOS", "secret": "must-not-read"},
    )
    manifest = CommunicationManifest(
        run_id="run-1",
        rules=(
            CommunicationRule(
                producer_step_id="extract",
                consumer_step_id="analyze",
                allowed_fields=("title",),
                channel="extract:analyze",
                max_tokens=channel_budget,
            ),
        ),
        run_budget=channel_budget,
        step_budgets={"analyze": channel_budget},
        channel_budgets={"extract:analyze": channel_budget},
    )
    return CommunicationBroker(manifest=manifest, value_store=values), output_ref


def test_broker_returns_only_manifest_allowed_fields() -> None:
    """下游即使请求更多字段，也只能得到 Manifest 许可的字段。"""
    broker, output_ref = _broker()

    pack = asyncio.run(
        broker.read_reference(
            run_id="run-1",
            consumer_step_id="analyze",
            output_ref=output_ref,
            requested_fields=["title"],
            max_tokens=100,
            reason="analyze title",
        )
    )

    assert pack.data == {"title": "AgentOS"}
    assert pack.source_data == {"extract": {"title": "AgentOS"}}
    assert "secret" not in pack.model_dump_json()
    assert broker.drain_events() == [{
        "type": "communication_read",
        "runId": "run-1",
        "consumerStepId": "analyze",
        "producerStepId": "extract",
        "outputRef": output_ref,
        "fields": ["title"],
        "tokens": pack.tokens_delivered,
        "channel": "extract:analyze",
    }]


def test_broker_rejects_reference_without_topology_edge() -> None:
    """没有 producer -> consumer 拓扑边时不得因知道引用而读取正文。"""
    broker, output_ref = _broker()

    with pytest.raises(CommunicationAccessError) as captured:
        asyncio.run(
            broker.read_reference(
                run_id="run-1",
                consumer_step_id="unrelated",
                output_ref=output_ref,
                requested_fields=["title"],
                max_tokens=10,
                reason="bypass",
            )
        )

    assert captured.value.code == "TOPOLOGY_DENIED"


def test_broker_rejects_unapproved_field_before_reading_body() -> None:
    """字段白名单是读取前检查，不能先取完整输出再由 Agent 自行过滤。"""
    broker, output_ref = _broker()

    with pytest.raises(CommunicationAccessError) as captured:
        asyncio.run(
            broker.read_reference(
                run_id="run-1",
                consumer_step_id="analyze",
                output_ref=output_ref,
                requested_fields=["secret"],
                max_tokens=10,
                reason="bypass",
            )
        )

    assert captured.value.code == "FIELD_DENIED"


def test_broker_rejects_read_exceeding_budget_without_charging_it() -> None:
    """三级预算不足时拒绝读取，失败请求不能消耗已成功通信的额度。"""
    broker, output_ref = _broker(channel_budget=0)

    with pytest.raises(EntropyBudgetExceededError):
        asyncio.run(
            broker.read_reference(
                run_id="run-1",
                consumer_step_id="analyze",
                output_ref=output_ref,
                requested_fields=["title"],
                max_tokens=10,
                reason="budget",
            )
        )

    assert broker.drain_events() == []
