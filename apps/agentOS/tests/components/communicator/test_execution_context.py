"""执行节点通过引用装配严格合同上下文的测试。"""

from __future__ import annotations

import asyncio

import pytest

from components.communicator import (
    CommunicatorService, CommunicationBroker, CommunicationManifest,
    CommunicationRule, CommunicationAccessError,
)
from components.executor.value_store import InMemoryExecutionValueStore
from support.acg.models import build_default_capability_catalog

def _assemble_context(*, run_id, step_id, input_spec, upstream_refs, value_store,
                      service=None, operation_id=""):
    broker = CommunicationBroker(
        manifest=CommunicationManifest(run_id=run_id, rules=tuple(
            CommunicationRule(producer_step_id=source, consumer_step_id=step_id,
                              allowed_fields=tuple(fields), channel=f"{source}:{step_id}")
            for source, fields in input_spec.get("from", {}).items())),
        value_store=value_store,
    )
    pack = asyncio.run(broker.assemble_context(run_id=run_id, step_id=step_id,
        input_spec=input_spec, upstream_refs=upstream_refs, operation_id=operation_id))
    if service is not None:
        service.record_context_consumption(pack, operation_id=operation_id)
    return pack


class _TrackedValues(InMemoryExecutionValueStore):
    def __init__(self):
        super().__init__()
        self.reads: list[str] = []

    def get_output(self, *, run_id, output_ref):
        self.reads.append(output_ref)
        return super().get_output(run_id=run_id, output_ref=output_ref)


def _source_broker(store, fields):
    return CommunicationBroker(
        manifest=CommunicationManifest(run_id="run-1", rules=tuple(
            CommunicationRule(producer_step_id=source, consumer_step_id="summarize",
                              allowed_fields=tuple(names), channel=f"{source}:summarize")
            for source, names in fields.items()
        )), value_store=store,
    )


def test_strict_contract_reads_only_declared_upstream_fields() -> None:
    """下游只能读取 inputSpec.from 声明字段，未声明字段不得进入 ContextPack。"""
    store = InMemoryExecutionValueStore()
    source_ref = store.put_output(
        run_id="run-1",
        step_id="extract",
        payload={"title": "A", "secret": "must-not-pass"},
    )

    pack = _assemble_context(
        run_id="run-1",
        step_id="summarize",
        input_spec={"from": {"extract": ["title"]}},
        upstream_refs={"extract": source_ref},
        value_store=store,
    )

    assert pack.data == {"title": "A"}
    assert pack.source_data == {"extract": {"title": "A"}}


def test_execution_context_rejects_reference_from_another_run() -> None:
    """通信服务读取引用时必须继承仓库的 run 隔离，不得把越权数据装入上下文。"""
    store = InMemoryExecutionValueStore()
    source_ref = store.put_output(
        run_id="run-a",
        step_id="extract",
        payload={"title": "private"},
    )

    with pytest.raises(CommunicationAccessError) as caught:
        _assemble_context(
            run_id="run-b",
            step_id="summarize",
            input_spec={"from": {"extract": ["title"]}},
            upstream_refs={"extract": source_ref},
            value_store=store,
        )

    assert caught.value.code == "TOPOLOGY_DENIED"


def test_execution_context_marks_missing_required_slot_invalid() -> None:
    """声明为必填但上游未产出的字段必须在调用 Adapter 前标记为合同不完整。"""
    store = InMemoryExecutionValueStore()
    source_ref = store.put_output(run_id="run-1", step_id="extract", payload={"title": "A"})

    pack = _assemble_context(
        run_id="run-1",
        step_id="summarize",
        input_spec={
            "from": {"extract": ["title", "abstract"]},
            "schema": {"type": "object", "required": ["abstract"]},
        },
        upstream_refs={"extract": source_ref},
        value_store=store,
    )

    assert pack.contract_status == "invalid"
    assert pack.missing_fields == ["abstract"]


def test_run_deliverable_context_keeps_all_declared_leaf_sources() -> None:
    """The final synthesis contract must accept a complete multi-source pack."""
    store = InMemoryExecutionValueStore()
    refs = {
        f"leaf-{index}": store.put_output(
            run_id="run-1", step_id=f"leaf-{index}",
            payload={f"result_{index}": f"source-{index}"},
        )
        for index in range(5)
    }
    descriptor = build_default_capability_catalog().get("artifact_generation")
    pack = _assemble_context(
        run_id="run-1",
        step_id="final",
        input_spec={
            "from": {step_id: [f"result_{index}"] for index, step_id in enumerate(refs)},
            "schema": descriptor.input_contract,
        },
        upstream_refs=refs,
        value_store=store,
    )

    assert pack.contract_status == "valid"
    assert len(pack.source_data) == 5
    assert pack.data == {f"result_{index}": f"source-{index}" for index in range(5)}


def test_execution_context_reuses_consumption_and_interaction_for_same_commit() -> None:
    """同一节点提交重试时，消费和交互各自保留一条，不能互相冲突或重复追加。"""
    store = InMemoryExecutionValueStore()
    source_ref = store.put_output(
        run_id="run-1",
        step_id="extract",
        payload={"title": "safe"},
    )
    service = CommunicatorService(run_id="run-1", mission_id="task-1")

    for _ in range(2):
        _assemble_context(service=service,
            run_id="run-1",
            step_id="summarize",
            input_spec={"from": {"extract": ["title"]}},
            upstream_refs={"extract": source_ref},
            value_store=store,
            operation_id="commit:run-1:summarize:0",
        )

    assert len(service.provenance.consumptions) == 1
    assert len(service.provenance.interactions) == 1


def test_assembly_never_reads_incidental_references_outside_the_manifest() -> None:
    store = _TrackedValues()
    allowed = store.put_output(run_id="run-1", step_id="extract", payload={"title": "approved"})
    unrelated = store.put_output(run_id="run-1", step_id="unrelated", payload={"title": "private"})
    broker = _source_broker(store, {"extract": ["title"]})

    pack = asyncio.run(broker.assemble_context(
        run_id="run-1", step_id="summarize", input_spec={"from": {"extract": ["title"]}},
        upstream_refs={"extract": allowed, "unrelated": unrelated},
    ))

    assert store.reads == [allowed]
    assert pack.source_data == {"extract": {"title": "approved"}}
    assert pack.source_step_ids == ["extract"]


@pytest.mark.parametrize("entrypoint", ["read", "page", "assemble", "describe"])
def test_legal_producer_cannot_be_relabelled_as_another_legal_producer(entrypoint) -> None:
    """Both sources are permitted, but each reference must retain its true producer."""
    store = _TrackedValues()
    foreign_label = store.put_output(run_id="run-1", step_id="B", payload={"summary": "B content"})
    fields = {"A": ["summary"], "B": ["summary"]}
    broker = _source_broker(store, fields)

    with pytest.raises(CommunicationAccessError) as captured:
        if entrypoint == "assemble":
            asyncio.run(broker.assemble_context(
                run_id="run-1", step_id="summarize", input_spec={"from": fields},
                upstream_refs={"A": foreign_label},
            ))
        elif entrypoint == "describe":
            broker.describe_reference(run_id="run-1", consumer_step_id="summarize",
                                      output_ref=foreign_label, producer_step_id="A")
        else:
            request = dict(run_id="run-1", consumer_step_id="summarize", output_ref=foreign_label,
                           producer_step_id="A", requested_fields=["summary"], reason="read A")
            if entrypoint == "read":
                asyncio.run(broker.read_reference(**request, max_tokens=None))
            else:
                asyncio.run(broker.read_reference_page(**request, cursor=None, page_tokens=100))

    assert captured.value.code == "TOPOLOGY_DENIED"
    assert store.reads == []
    assert broker.drain_events() == []


def test_multisource_delivery_keeps_long_text_and_revisions_of_shadowed_fields() -> None:
    store = InMemoryExecutionValueStore()
    original = "原始证据\n" * 10000 + "END-OF-A"
    first = store.put_output(run_id="run-1", step_id="A", payload={"summary": original})
    second = store.put_output(run_id="run-1", step_id="B", payload={"summary": "B result"})
    fields = {"A": ["summary"], "B": ["summary"]}
    broker = _source_broker(store, fields)

    def assemble(first_ref):
        return asyncio.run(broker.assemble_context(
            run_id="run-1", step_id="summarize", input_spec={"from": fields},
            upstream_refs={"A": first_ref, "B": second},
        ))

    pack = assemble(first)
    assert pack.source_data == {"A": {"summary": original}, "B": {"summary": "B result"}}
    assert pack.source_data["A"]["summary"].endswith("END-OF-A")
    changed = store.put_output(run_id="run-1", step_id="A", payload={"summary": original + "\nupdated evidence"})
    updated = assemble(changed)
    assert updated.data == pack.data  # The legacy flat projection is shadowed by B.
    assert updated.input_revision != pack.input_revision


def test_all_prefetch_permissions_are_checked_before_reading_any_body() -> None:
    store = _TrackedValues()
    refs = {source: store.put_output(run_id="run-1", step_id=source, payload={"summary": source})
            for source in ("A", "B")}
    fields = {source: ["summary"] for source in refs}
    broker = _source_broker(store, fields)

    with pytest.raises(ValueError, match="prefetch fields must be a subset"):
        asyncio.run(broker.assemble_context(
            run_id="run-1", step_id="summarize", upstream_refs=refs,
            input_spec={"from": fields, "prefetch": {"A": ["summary"], "B": ["secret"]}},
        ))

    assert store.reads == []
    assert broker.drain_events() == []
    assert broker.usage_snapshot()["run"] == 0


def test_root_context_is_empty_and_read_receipts_survive_broker_restore() -> None:
    store = _TrackedValues()
    reference = store.put_output(run_id="run-1", step_id="A", payload={"summary": "source evidence"})
    broker = _source_broker(store, {"A": ["summary"]})
    root = asyncio.run(broker.assemble_context(
        run_id="run-1", step_id="root", input_spec={}, upstream_refs={"A": reference},
    ))
    assert root.contract_status == "valid"
    assert root.data == root.source_data == {}
    assert root.source_step_ids == []
    assert root.tokens_delivered == 0
    assert store.reads == []

    request = dict(run_id="run-1", step_id="summarize", input_spec={"from": {"A": ["summary"]}},
                   upstream_refs={"A": reference}, operation_id="commit:run-1:summarize:0")
    original = asyncio.run(broker.assemble_context(**request))
    usage = broker.usage_snapshot()
    assert usage["run"] > 0
    restored = CommunicationBroker(manifest=broker.manifest, value_store=store, usage=usage)
    replayed = asyncio.run(restored.assemble_context(**request))
    assert replayed == original
    assert restored.usage_snapshot() == usage
