"""Offline backup/restore rehearsal on fresh ledgers, never real application data."""
from contextlib import closing
import sqlite3

import pytest

from support.stores import c2_schema_upgrade as ops
from support.stores.execution_dispatch_store import SQLiteExecutionDispatchStore
from test_c2_schema_upgrade import contents


def backup(source, target):
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)


def test_c2_then_dispatch_upgrade_and_closed_ledger_backup_restore(tmp_path):
    paths = {role: tmp_path / f'{role}.sqlite' for role in ('workflow', 'checkpoint', 'identity')}
    for role, path in paths.items():
        ops._initialize(role, path)
    before = contents(paths)
    copies = {role: tmp_path / f'{role}.backup.sqlite' for role in paths}
    for role in paths:
        backup(paths[role], copies[role])
    # Dispatch must not install itself over the missing C2 parent schema.
    with pytest.raises((RuntimeError, sqlite3.Error)):
        SQLiteExecutionDispatchStore.upgrade_schema(paths['workflow'])
    assert contents(paths) == before
    assert ops.upgrade_databases(**paths)['status'] == 'READY'
    SQLiteExecutionDispatchStore.upgrade_schema(paths['workflow'])
    assert SQLiteExecutionDispatchStore(paths['workflow']).commands() == []
    assert all(v['status'] == 'READY' for v in ops.inspect_databases(**paths).values())
    # All connections/authorities are closed before offline restore. This is
    # per-file restoration, deliberately not a cross-database transaction.
    for role in paths:
        backup(copies[role], paths[role])
    assert contents(paths) == before
    with pytest.raises((RuntimeError, sqlite3.Error)):
        SQLiteExecutionDispatchStore(paths['workflow'])
    assert contents(paths) == before
