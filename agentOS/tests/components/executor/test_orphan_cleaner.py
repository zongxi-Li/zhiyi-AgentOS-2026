"""执行值孤儿清理器的延迟删除与运行隔离测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from components.executor.orphan_cleaner import ExecutionOrphanCleaner
from components.executor.value_store import ExecutionValueAccessError, InMemoryExecutionValueStore


def test_cleaner_removes_only_expired_unprotected_values() -> None:
    """过期且没有提交或状态引用保护的正文可清理，受保护正文必须保留。"""
    store = InMemoryExecutionValueStore()
    orphan_ref = store.put_output(
        run_id="run-a", step_id="draft", payload={"body": "orphan"}
    )
    protected_ref = store.put_context_pack(
        run_id="run-a", step_id="review", payload={"body": "protected"}
    )
    cleaner = ExecutionOrphanCleaner(value_store=store)

    stats = cleaner.clean(
        run_id="run-a",
        protected_refs={protected_ref},
        older_than=datetime.now(timezone.utc) + timedelta(seconds=1),
    )

    assert stats.scanned == 2
    assert stats.protected == 1
    assert stats.deleted == 1
    with pytest.raises(ExecutionValueAccessError, match="does not exist"):
        store.get_output(run_id="run-a", output_ref=orphan_ref)
    assert store.get_context_pack(run_id="run-a", context_ref=protected_ref) == {
        "body": "protected"
    }


def test_cleaner_never_deletes_another_run_reference() -> None:
    """以 runId 发起的清理必须只影响当前运行，不能依赖全局孤儿扫描。"""
    store = InMemoryExecutionValueStore()
    own_ref = store.put_output(run_id="run-a", step_id="draft", payload={"body": "own"})
    other_ref = store.put_output(run_id="run-b", step_id="draft", payload={"body": "other"})
    cleaner = ExecutionOrphanCleaner(value_store=store)

    stats = cleaner.clean(
        run_id="run-a",
        protected_refs=set(),
        older_than=datetime.now(timezone.utc) + timedelta(seconds=1),
    )

    assert stats.deleted == 1
    with pytest.raises(ExecutionValueAccessError):
        store.get_output(run_id="run-a", output_ref=own_ref)
    assert store.get_output(run_id="run-b", output_ref=other_ref) == {"body": "other"}
