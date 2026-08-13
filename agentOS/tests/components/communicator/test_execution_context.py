"""执行节点通过引用装配严格合同上下文的测试。"""

from __future__ import annotations

import pytest

from components.communicator import CommunicatorService
from components.executor.value_store import ExecutionValueAccessError
from components.executor.value_store import InMemoryExecutionValueStore


def test_strict_contract_reads_only_declared_upstream_fields() -> None:
    """下游只能读取 inputSpec.from 声明字段，未声明字段不得进入 ContextPack。"""
    store = InMemoryExecutionValueStore()
    source_ref = store.put_output(
        run_id="run-1",
        step_id="extract",
        payload={"title": "A", "secret": "must-not-pass"},
    )

    pack = CommunicatorService().assemble_execution_context(
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

    with pytest.raises(ExecutionValueAccessError, match="run-a"):
        CommunicatorService().assemble_execution_context(
            run_id="run-b",
            step_id="summarize",
            input_spec={"from": {"extract": ["title"]}},
            upstream_refs={"extract": source_ref},
            value_store=store,
        )


def test_execution_context_marks_missing_required_slot_invalid() -> None:
    """声明为必填但上游未产出的字段必须在调用 Adapter 前标记为合同不完整。"""
    store = InMemoryExecutionValueStore()
    source_ref = store.put_output(run_id="run-1", step_id="extract", payload={"title": "A"})

    pack = CommunicatorService().assemble_execution_context(
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
