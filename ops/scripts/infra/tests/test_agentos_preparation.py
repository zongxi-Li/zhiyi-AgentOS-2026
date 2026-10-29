"""Maintenance uses real temporary SQLite files and the actual Runtime OS lock."""
from contextlib import closing
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location("prepare_agentos_runtime", ROOT / "scripts/prepare_agentos_runtime.py")
prepare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare)


@pytest.fixture
def paths(tmp_path):
    return {role: tmp_path / f"{role}.sqlite" for role in ("workflow", "checkpoint", "identity")}


def args(paths, *extra):
    return [part for role, path in paths.items() for part in (f"--{role}-db", str(path))] + list(extra)


def receipt(paths, capsys, *extra):
    code = prepare.main(args(paths, *extra))
    return code, json.loads(capsys.readouterr().out)


def dump(paths):
    result = {}
    for role, path in paths.items():
        if path.exists():
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
                result[role] = tuple(conn.iterdump())
        else:
            result[role] = None
    return result


def base(paths):
    from support.stores.c2_schema_upgrade import _initialize
    for role, path in paths.items():
        _initialize(role, path)


def test_inspection_does_not_create_missing_databases(paths, capsys):
    code, report = receipt(paths, capsys)
    assert code == 1 and report['stage'] == 'preflight'
    assert not any(path.exists() for path in paths.values())


def test_explicit_initialization_and_repeat_are_idempotent(paths, capsys):
    assert receipt(paths, capsys, '--apply')[0] == 1
    code, report = receipt(paths, capsys, '--apply', '--initialize-empty')
    assert code == 0 and report['status'] == 'READY'
    before = dump(paths)
    assert receipt(paths, capsys, '--apply')[0] == 0
    assert receipt(paths, capsys)[0] == 0
    assert dump(paths) == before


def test_base_database_check_is_nonmutating_then_upgrade_preserves_records(paths, capsys):
    base(paths)
    with closing(sqlite3.connect(paths['workflow'])) as conn, conn:
        conn.execute("INSERT INTO tasks VALUES('keep','{}','2026-10-28')")
    before = dump(paths)
    assert receipt(paths, capsys)[0] == 2
    assert dump(paths) == before
    assert receipt(paths, capsys, '--apply')[0] == 0
    with closing(sqlite3.connect(paths['workflow'])) as conn:
        assert conn.execute("SELECT mission_id FROM tasks WHERE mission_id='keep'").fetchone() == ('keep',)


def test_incompatible_database_rejected_before_any_schema_write(paths, capsys):
    base(paths)
    with closing(sqlite3.connect(paths['identity'])) as conn:
        conn.execute('PRAGMA user_version=99')
    before = dump(paths)
    assert receipt(paths, capsys, '--apply')[0] == 1
    assert dump(paths) == before


def test_damaged_dispatch_rejected_before_c2_upgrade(paths, capsys):
    base(paths)
    with closing(sqlite3.connect(paths['workflow'])) as conn, conn:
        conn.execute('CREATE TABLE execution_dispatch_schema(version INTEGER PRIMARY KEY)')
        conn.execute('INSERT INTO execution_dispatch_schema VALUES(99)')
    before = dump(paths)
    code, report = receipt(paths, capsys, '--apply')
    assert code == 1 and report['stage'] == 'preflight'
    assert dump(paths) == before


def test_active_runtime_os_lock_refuses_maintenance(paths, capsys):
    base(paths)
    lock_path = ROOT / 'apps/agent/app/execution/instance_lock.py'
    code = ("import importlib.util,sys; s=importlib.util.spec_from_file_location('lock',sys.argv[1]);"
            "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
            "m.acquire_workflow_instance_lock(sys.argv[2]);print('locked',flush=True);sys.stdin.readline()")
    process = subprocess.Popen([sys.executable, '-u', '-c', code, str(lock_path), str(paths['workflow'])],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == 'locked'
        before = dump(paths)
        code, report = receipt(paths, capsys, '--apply')
        assert code == 1 and report['stage'] == 'instance_lock'
        assert dump(paths) == before
    finally:
        process.communicate('\n', timeout=15)


def test_c2_failure_never_proceeds_to_dispatch_and_releases_lock(paths, capsys, monkeypatch):
    base(paths)
    def fail(**kwargs):
        raise RuntimeError('injected c2 failure')
    with monkeypatch.context() as patch:
        patch.setattr(prepare, 'upgrade_databases', fail)
        code, report = receipt(paths, capsys, '--apply')
        assert code == 1 and report['stage'] == 'c2_upgrade'
        assert prepare.inspect_dispatch(paths['workflow'])['status'] == 'UPGRADE_REQUIRED'
    assert receipt(paths, capsys, '--apply')[0] == 0


def test_agent_test_bootstrap_preserves_old_evidence(tmp_path):
    fake_file = tmp_path / 'apps/agent/tests/conftest.py'
    evidence = tmp_path / '.tmp-tests/old-evidence/checks.json'
    evidence.parent.mkdir(parents=True)
    evidence.write_text('{"keep":true}', encoding='utf-8')
    os.utime(evidence.parent, (1, 1))
    source = (ROOT / 'apps/agent/tests/conftest.py').read_text(encoding='utf-8')
    prelude = source.split('_TEST_CHROMA_DIR =', 1)[0]
    exec(compile(prelude, str(fake_file), 'exec'), {'__file__': str(fake_file)})
    assert evidence.read_text(encoding='utf-8') == '{"keep":true}'


def test_official_alter_column_identity_layout_is_accepted_without_rewrite(paths, capsys):
    import re
    from storage.v2.schema import SCHEMA_SQL
    from storage.v2.sqlite import SQLiteV2Storage
    from support.stores.c2_schema_upgrade import _initialize
    for role in ('workflow', 'checkpoint'):
        _initialize(role, paths[role])
    old_table = re.search(r'CREATE TABLE IF NOT EXISTS semantic_tasks \(.*?\n\);', SCHEMA_SQL, re.S).group()
    with closing(sqlite3.connect(paths['identity'])) as conn:
        conn.execute(old_table.replace('    semantic_key TEXT,\n', '', 1))
    with SQLiteV2Storage(paths['identity']):
        pass  # The existing official migration appends the compatibility column.
    before = paths['identity'].read_bytes()
    assert receipt(paths, capsys, '--apply')[0] == 0
    assert paths['identity'].read_bytes() == before


def test_pre_c2_revision_table_upgrade_is_additive_but_missing_installed_table_is_damage(paths, capsys):
    base(paths)
    with closing(sqlite3.connect(paths['workflow'])) as conn, conn:
        conn.execute('DROP TABLE mission_revision_decisions')
    assert receipt(paths, capsys, '--apply')[0] == 0
    with closing(sqlite3.connect(paths['workflow'])) as conn, conn:
        conn.execute('DROP TABLE mission_revision_decisions')
    before = dump(paths)
    assert receipt(paths, capsys, '--apply')[0] == 1
    assert dump(paths) == before
