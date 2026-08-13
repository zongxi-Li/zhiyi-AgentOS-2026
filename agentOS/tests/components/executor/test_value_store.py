"""执行值引用仓库的隔离与不可变性测试。"""

from __future__ import annotations

import pytest

from components.executor.value_store import (
    ExecutionValueAccessError,
    InMemoryExecutionValueStore,
    SQLiteExecutionValueStore,
)


def test_value_store_rejects_cross_run_reference() -> None:
    """同一引用不得被不同 run 读取，避免执行数据越权泄漏。"""
    store = InMemoryExecutionValueStore()
    output_ref = store.put_output(
        run_id="run-a",
        step_id="extract",
        payload={"text": "safe"},
    )

    with pytest.raises(ExecutionValueAccessError, match="run-a"):
        store.get_output(run_id="run-b", output_ref=output_ref)


def test_value_store_returns_defensive_output_copy() -> None:
    """读取出的嵌套数据被调用方修改后，仓库中原始受控产物必须保持不变。"""
    store = InMemoryExecutionValueStore()
    output_ref = store.put_output(
        run_id="run-a",
        step_id="extract",
        payload={"result": {"title": "original"}},
    )

    retrieved = store.get_output(run_id="run-a", output_ref=output_ref)
    retrieved["result"]["title"] = "mutated"

    assert store.get_output(run_id="run-a", output_ref=output_ref) == {
        "result": {"title": "original"},
    }


def test_value_store_rejects_unknown_reference() -> None:
    """未知引用必须明确失败，禁止以空字典悄悄降级并掩盖数据丢失。"""
    store = InMemoryExecutionValueStore()

    with pytest.raises(ExecutionValueAccessError, match="does not exist"):
        store.get_output(run_id="run-a", output_ref="output:run-a:missing")


def test_context_pack_reference_is_isolated_by_run() -> None:
    """ContextPack 与节点输出一样以 runId 为第一隔离键。"""
    store = InMemoryExecutionValueStore()
    context_ref = store.put_context_pack(
        run_id="run-a",
        step_id="summarize",
        payload={"title": "safe"},
    )

    assert store.get_context_pack(run_id="run-a", context_ref=context_ref) == {"title": "safe"}
    with pytest.raises(ExecutionValueAccessError, match="run-a"):
        store.get_context_pack(run_id="run-b", context_ref=context_ref)


def test_sqlite_value_store_survives_reopen_and_keeps_run_isolation(tmp_path) -> None:
    """审核续跑重建运行时时，旧 outputRef 必须仍可按原 runId 读取。"""
    db_path = tmp_path / "values.sqlite3"
    first = SQLiteExecutionValueStore(db_path=db_path)
    output_ref = first.put_output(
        run_id="run-a",
        step_id="extract",
        payload={"title": "persisted"},
    )
    first.close()

    reopened = SQLiteExecutionValueStore(db_path=db_path)
    assert reopened.get_output(run_id="run-a", output_ref=output_ref) == {"title": "persisted"}
    with pytest.raises(ExecutionValueAccessError, match="run-a"):
        reopened.get_output(run_id="run-b", output_ref=output_ref)
    reopened.close()
