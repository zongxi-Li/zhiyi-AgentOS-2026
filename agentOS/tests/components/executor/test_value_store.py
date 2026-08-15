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


def test_value_store_rejects_reference_owned_by_another_step() -> None:
    """同一运行内也必须核验步骤归属，不能把上游输出伪装成当前步骤产物。"""
    store = InMemoryExecutionValueStore()
    output_ref = store.put_output(
        run_id="run-a",
        step_id="extract",
        payload={"title": "safe"},
    )

    with pytest.raises(ExecutionValueAccessError, match="belongs to step extract"):
        store.assert_reference(
            kind="output",
            run_id="run-a",
            step_id="summarize",
            reference=output_ref,
        )


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


def test_sqlite_value_store_keeps_step_ownership_after_reopen(tmp_path) -> None:
    """持久化引用重启后也必须保留其来源步骤，不能只校验 runId。"""
    db_path = tmp_path / "values.sqlite3"
    first = SQLiteExecutionValueStore(db_path=db_path)
    output_ref = first.put_output(
        run_id="run-a",
        step_id="extract",
        payload={"title": "persisted"},
    )
    first.close()

    reopened = SQLiteExecutionValueStore(db_path=db_path)
    with pytest.raises(ExecutionValueAccessError, match="belongs to step extract"):
        reopened.assert_reference(
            kind="output",
            run_id="run-a",
            step_id="summarize",
            reference=output_ref,
        )
    reopened.close()


def test_sqlite_value_store_persists_node_commit_without_output_body(tmp_path) -> None:
    """节点提交记录重启后仍可读取，但只能保存引用和安全元数据。"""
    db_path = tmp_path / "values.sqlite3"
    first = SQLiteExecutionValueStore(db_path=db_path)
    first.prepare_node_commit(
        run_id="run-a",
        commit_id="commit:run-a:extract:0",
    )
    first.complete_node_commit(
        run_id="run-a",
        commit_id="commit:run-a:extract:0",
        payload={"commitId": "commit:run-a:extract:0", "outputRef": "output:run-a:extract:1"},
    )
    first.close()

    reopened = SQLiteExecutionValueStore(db_path=db_path)

    assert reopened.get_node_commit(
        run_id="run-a",
        commit_id="commit:run-a:extract:0",
    ) == {
        "commitId": "commit:run-a:extract:0",
        "stage": "committed",
        "outputRef": "output:run-a:extract:1",
    }
    reopened.close()


def test_node_commit_transitions_from_prepared_to_committed_once() -> None:
    """提交日志先登记可重试的 prepared，再仅允许一次完成为 committed。"""
    store = InMemoryExecutionValueStore()

    first = store.prepare_node_commit(
        run_id="run-a",
        commit_id="commit:run-a:extract:0",
    )
    repeated = store.prepare_node_commit(
        run_id="run-a",
        commit_id="commit:run-a:extract:0",
    )
    store.complete_node_commit(
        run_id="run-a",
        commit_id="commit:run-a:extract:0",
        payload={"outputRef": "output:run-a:extract:1"},
    )

    assert first == {"commitId": "commit:run-a:extract:0", "stage": "prepared"}
    assert repeated == first
    assert store.get_node_commit(
        run_id="run-a",
        commit_id="commit:run-a:extract:0",
    ) == {
        "commitId": "commit:run-a:extract:0",
        "stage": "committed",
        "outputRef": "output:run-a:extract:1",
    }
