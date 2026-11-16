"""SQLite nonce 的重启、并发、容量和失败关闭验收；不依赖网络或模型。"""

from concurrent.futures import ThreadPoolExecutor
import importlib
from pathlib import Path
import sqlite3
import threading
import time

import pytest

from components.safe.contracts.errors import ErrorCode, SafeError
from components.safe.infrastructure.storage import sqlite_nonces


NOW = 1700000000
NONCE = "0123456789abcdef0123456789abcdef"


def create(tmp_path, *, now=None, **kwargs):
    now = [NOW] if now is None else now
    path = tmp_path / "dedicated-nonces.sqlite3"
    store = sqlite_nonces.SqliteNonceStore.create(path, clock=lambda: now[0], **kwargs)
    return store, path, now


def assert_unavailable(operation):
    with pytest.raises(SafeError) as caught:
        operation()
    error = caught.value
    assert error.code is ErrorCode.TRANSPORT_UNAVAILABLE
    assert str(error) == "TRANSPORT_UNAVAILABLE"
    assert error.__cause__ is None
    assert error.__context__ is None
    assert error.args == ("TRANSPORT_UNAVAILABLE",)


def edit_database(path, sql, args=()):
    connection = sqlite3.connect(path)
    try:
        connection.execute(sql, args)
        connection.commit()
    finally:
        connection.close()


def test_reopening_keeps_replay_consumed_and_credentials_are_independent(tmp_path):
    store, path, now = create(tmp_path)
    assert store.consume("cred:one", NONCE, NOW + 60)
    reopened = sqlite_nonces.SqliteNonceStore(path, clock=lambda: now[0])
    assert not reopened.consume("cred:one", NONCE, NOW + 60)
    assert reopened.consume("cred:two", NONCE, NOW + 60)


def test_two_instances_racing_have_exactly_one_success(tmp_path):
    first, path, now = create(tmp_path)
    second = sqlite_nonces.SqliteNonceStore(path, clock=lambda: now[0])
    barrier = threading.Barrier(2)

    def attempt(store):
        barrier.wait()
        return store.consume("cred:one", NONCE, NOW + 60)

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sum(workers.map(attempt, (first, second))) == 1


def test_exact_expiration_boundary_is_retained_then_cleaned_before_replay_check(tmp_path):
    store, _, now = create(tmp_path, max_entries=1)
    assert store.consume("cred:one", NONCE, NOW + 1)
    now[0] = NOW + 1
    assert not store.consume("cred:one", NONCE, NOW + 60)
    assert not store.consume("cred:two", "a" * 32, NOW + 60)
    now[0] += 0.001
    assert store.consume("cred:one", NONCE, NOW + 60)


def test_capacity_and_per_credential_pressure_never_evict_live_nonces(tmp_path):
    store, path, now = create(tmp_path, max_entries=2, max_per_credential=1)
    assert store.consume("cred:one", "a" * 32, NOW + 1)
    assert not store.consume("cred:one", "b" * 32, NOW + 1)
    assert store.consume("cred:two", "b" * 32, NOW + 1)
    assert not store.consume("cred:three", "c" * 32, NOW + 1)
    store = sqlite_nonces.SqliteNonceStore(path, clock=lambda: now[0], max_entries=2, max_per_credential=1)
    assert not store.consume("cred:one", "a" * 32, NOW + 1)
    now[0] = NOW + 1.001
    assert store.consume("cred:three", "c" * 32, NOW + 60)


def test_reopening_during_clock_rollback_rejects_until_high_watermark_recovers(tmp_path):
    store, path, now = create(tmp_path, now=[1000])
    assert store.consume("cred:one", NONCE, 1060)
    now[0] = 1061
    assert store.consume("cred:one", "a" * 32, 1121)
    now[0] = 1030
    reopened = sqlite_nonces.SqliteNonceStore(path, clock=lambda: now[0])
    assert not reopened.consume("cred:one", NONCE, 1060)
    assert not reopened.consume("cred:one", "b" * 32, 1090)
    now[0] = 1061
    assert reopened.consume("cred:one", "b" * 32, 1121)


@pytest.mark.parametrize("reject_kind", ["duplicate", "global_capacity", "credential_capacity"])
def test_valid_rejected_attempt_also_persists_high_watermark(tmp_path, reject_kind):
    limits = {"max_entries": 1} if reject_kind == "global_capacity" else {"max_per_credential": 1}
    store, path, now = create(tmp_path, now=[1000], **limits)
    assert store.consume("cred:one", NONCE, 1120)
    now[0] = 1050
    nonce = NONCE if reject_kind == "duplicate" else "a" * 32
    credential_id = "cred:two" if reject_kind == "global_capacity" else "cred:one"
    assert not store.consume(credential_id, nonce, 1120)
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("SELECT clock_high_watermark FROM nonce_meta").fetchone() == (1050,)
    finally:
        connection.close()
    reopened = sqlite_nonces.SqliteNonceStore(path, clock=lambda: now[0], **limits)
    now[0] = 1049
    # 新凭据在非全局容量场景没有容量压力，回拨仍须拒绝。
    assert not reopened.consume("cred:three", "b" * 32, 1100)
    now[0] = 1121
    assert reopened.consume("cred:three", "b" * 32, 1181)


@pytest.mark.parametrize("expiry", [999, 1300, float("nan"), float("inf"), True, "1150", 10 ** 400])
def test_invalid_expiry_does_not_advance_high_watermark_or_cleanup(tmp_path, expiry):
    store, path, now = create(tmp_path, now=[1000])
    assert store.consume("cred:one", NONCE, 1060)
    now[0] = 1100
    assert not store.consume("cred:one", "a" * 32, expiry)
    now[0] = 1030
    reopened = sqlite_nonces.SqliteNonceStore(path, clock=lambda: now[0])
    assert not reopened.consume("cred:one", NONCE, 1060)
    assert reopened.consume("cred:one", "b" * 32, 1090)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "1000", None, 10 ** 400])
def test_invalid_clock_value_fails_closed_without_consumption(tmp_path, value):
    store, _, now = create(tmp_path, now=[value])
    assert not store.consume("cred:one", NONCE, NOW + 60)
    now[0] = NOW
    assert store.consume("cred:one", NONCE, NOW + 60)


def test_clock_exception_is_redacted_as_rejection(tmp_path):
    def broken_clock():
        raise RuntimeError("secret from clock")

    store, _, _ = create(tmp_path)
    reopened = sqlite_nonces.SqliteNonceStore(tmp_path / "dedicated-nonces.sqlite3", clock=broken_clock)
    assert not reopened.consume("cred:one", NONCE, NOW + 60)


@pytest.mark.parametrize("kwargs,message", [
    ({"max_entries": 0}, "nonce 容量必须为正整数"),
    ({"max_entries": True}, "nonce 容量必须为正整数"),
    ({"max_entries": 1.0}, "nonce 容量必须为正整数"),
    ({"max_entries": 2 ** 63}, "nonce 容量必须为正整数"),
    ({"max_per_credential": -1}, "nonce 容量必须为正整数"),
    ({"max_per_credential": False}, "nonce 容量必须为正整数"),
    ({"max_per_credential": "1"}, "nonce 容量必须为正整数"),
    ({"max_per_credential": 2 ** 63}, "nonce 容量必须为正整数"),
    ({"timeout": -0.01}, "nonce 锁等待时间必须为 0 到 5 秒的有限实数"),
    ({"timeout": 5.01}, "nonce 锁等待时间必须为 0 到 5 秒的有限实数"),
    ({"timeout": True}, "nonce 锁等待时间必须为 0 到 5 秒的有限实数"),
    ({"timeout": float("nan")}, "nonce 锁等待时间必须为 0 到 5 秒的有限实数"),
    ({"timeout": float("inf")}, "nonce 锁等待时间必须为 0 到 5 秒的有限实数"),
    ({"timeout": "1"}, "nonce 锁等待时间必须为 0 到 5 秒的有限实数"),
    ({"clock": 1000}, "nonce 时钟必须可调用"),
])
def test_invalid_configuration_is_fixed_value_error_and_creates_nothing(tmp_path, kwargs, message):
    path = tmp_path / "absent.sqlite3"
    for factory in (sqlite_nonces.SqliteNonceStore, sqlite_nonces.SqliteNonceStore.create):
        with pytest.raises(ValueError, match=f"^{message}$") as caught:
            factory(path, **kwargs)
        assert caught.value.__context__ is None
        assert not path.exists()


@pytest.mark.parametrize("timeout", [0, 0.25, 5])
def test_timeout_endpoints_are_valid(tmp_path, timeout):
    store, _, _ = create(tmp_path, timeout=timeout)
    assert store.consume("cred:one", NONCE, NOW + 60)


def test_maximum_integer_capacities_round_trip_without_overflow(tmp_path):
    limits = {"max_entries": 2 ** 63 - 1, "max_per_credential": 2 ** 63 - 1}
    store, path, now = create(tmp_path, **limits)
    assert store.consume("cred:one", NONCE, NOW + 60)
    reopened = sqlite_nonces.SqliteNonceStore(path, clock=lambda: now[0], **limits)
    assert not reopened.consume("cred:one", NONCE, NOW + 60)


@pytest.mark.parametrize("value", [2 ** 53, -(2 ** 53), 10 ** 100, -(10 ** 100)])
def test_finite_times_outside_exact_sqlite_real_integer_range_fail_closed(tmp_path, value):
    store, _, now = create(tmp_path, now=[value])
    assert not store.consume("cred:one", NONCE, value)
    now[0] = 1000
    assert not store.consume("cred:one", NONCE, value)
    assert store.consume("cred:one", NONCE, 1060)


@pytest.mark.parametrize("value", [2 ** 53 - 1, -(2 ** 53 - 1)])
def test_exact_sqlite_real_integer_range_endpoints_remain_usable(tmp_path, value):
    store, _, _ = create(tmp_path, now=[value])
    assert store.consume("cred:one", NONCE, value)
    assert not store.consume("cred:one", NONCE, value)


@pytest.mark.parametrize("nonce", ["A" * 32, "a" * 31, "a" * 33, "g" * 32, None, 1])
def test_invalid_nonce_does_not_advance_high_watermark(tmp_path, nonce):
    store, _, now = create(tmp_path, now=[1000])
    assert store.consume("cred:one", NONCE, 1060)
    now[0] = 1050
    assert not store.consume("cred:one", nonce, 1110)
    now[0] = 1030
    assert store.consume("cred:one", "b" * 32, 1090)


@pytest.mark.parametrize("identifier", ["bad/name", "bad\nname", "", "a" * 129, None])
def test_invalid_identifier_keeps_port_value_error(tmp_path, identifier):
    store, _, _ = create(tmp_path)
    with pytest.raises(ValueError, match="凭据标识符无效"):
        store.consume(identifier, NONCE, NOW + 60)


def test_opening_missing_database_does_not_create_it(tmp_path):
    path = tmp_path / "missing-sensitive-path.sqlite3"
    assert_unavailable(lambda: sqlite_nonces.SqliteNonceStore(path))
    assert not path.exists()


def test_runtime_file_loss_does_not_recreate_database(tmp_path):
    store, path, _ = create(tmp_path)
    path.unlink()
    assert not store.consume("cred:one", NONCE, NOW + 60)
    assert not path.exists()


def test_create_uses_exclusive_new_file_and_never_overwrites_existing_data(tmp_path):
    path = tmp_path / "existing-sensitive.sqlite3"
    content = b"private unrelated data"
    path.write_bytes(content)
    assert_unavailable(lambda: sqlite_nonces.SqliteNonceStore.create(path))
    assert path.read_bytes() == content


def test_create_cannot_reset_a_valid_database(tmp_path):
    store, path, _ = create(tmp_path)
    assert store.consume("cred:one", NONCE, NOW + 60)
    assert_unavailable(lambda: sqlite_nonces.SqliteNonceStore.create(path))
    assert not store.consume("cred:one", NONCE, NOW + 60)


def test_unknown_business_database_is_rejected_and_left_unchanged(tmp_path):
    path = tmp_path / "business.sqlite3"
    edit_database(path, "CREATE TABLE business(secret TEXT)")
    edit_database(path, "INSERT INTO business VALUES ('sensitive-data')")
    original = path.read_bytes()
    assert_unavailable(lambda: sqlite_nonces.SqliteNonceStore(path))
    assert path.read_bytes() == original


@pytest.mark.parametrize("sql", [
    "PRAGMA application_id = 0",
    "PRAGMA user_version = 2",
    "DROP INDEX nonces_expiry",
    "ALTER TABLE nonces ADD COLUMN secret TEXT",
    "CREATE TABLE unexpected(payload TEXT)",
    "DELETE FROM nonce_meta",
    "UPDATE nonce_meta SET clock_high_watermark = 'NaN'",
])
def test_unknown_or_damaged_schema_is_never_repaired(tmp_path, sql):
    store, path, _ = create(tmp_path)
    edit_database(path, sql)
    original = path.read_bytes()
    assert_unavailable(lambda: sqlite_nonces.SqliteNonceStore(path))
    assert not store.consume("cred:one", NONCE, NOW + 60)
    assert path.read_bytes() == original


@pytest.mark.parametrize("kwargs", [{"max_entries": 9999}, {"max_per_credential": 999}])
def test_instances_cannot_disagree_about_capacity(tmp_path, kwargs):
    _, path, _ = create(tmp_path)
    assert_unavailable(lambda: sqlite_nonces.SqliteNonceStore(path, **kwargs))


def test_changed_persisted_capacity_fails_closed_for_existing_instance(tmp_path):
    store, path, _ = create(tmp_path)
    edit_database(path, "UPDATE nonce_meta SET max_entries = 1")
    assert not store.consume("cred:one", NONCE, NOW + 60)


def test_corrupt_database_fails_closed_without_exception_details(tmp_path):
    store, path, _ = create(tmp_path)
    path.write_bytes(b"corrupt sensitive db and SQL text")
    assert not store.consume("cred:one", NONCE, NOW + 60)
    assert_unavailable(lambda: sqlite_nonces.SqliteNonceStore(path))


def test_lock_wait_is_bounded_and_later_recovery_works(tmp_path):
    store, path, _ = create(tmp_path, timeout=0.02)
    blocker = sqlite3.connect(path, isolation_level=None)
    try:
        blocker.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        assert not store.consume("cred:one", NONCE, NOW + 60)
        assert time.monotonic() - started < 1
    finally:
        blocker.rollback()
        blocker.close()
    assert store.consume("cred:one", NONCE, NOW + 60)


def test_constructor_lock_error_is_fixed_and_redacted(tmp_path):
    _, path, _ = create(tmp_path)
    blocker = sqlite3.connect(path, isolation_level=None)
    try:
        blocker.execute("BEGIN EXCLUSIVE")
        assert_unavailable(lambda: sqlite_nonces.SqliteNonceStore(path, timeout=0))
    finally:
        blocker.rollback()
        blocker.close()


def test_create_io_failure_is_fixed_and_does_not_create_parent_directories(tmp_path):
    path = tmp_path / "missing-sensitive-dir" / "nonces.sqlite3"
    assert_unavailable(lambda: sqlite_nonces.SqliteNonceStore.create(path))
    assert not path.parent.exists()


def test_sqlite_fault_closes_connection_and_commit_must_succeed_before_true(tmp_path, monkeypatch):
    store, _, now = create(tmp_path, now=[1000])
    assert store.consume("cred:one", "a" * 32, 1001)
    now[0] = 1002
    real_connect = sqlite3.connect
    connections = []

    class FailedCommit(sqlite3.Connection):
        closed = False

        def commit(self):
            raise sqlite3.OperationalError("sensitive path SQL secret")

        def close(self):
            self.closed = True
            return super().close()

    def connect(*args, **kwargs):
        connection = real_connect(*args, factory=FailedCommit, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite_nonces.sqlite3, "connect", connect)
    assert not store.consume("cred:one", NONCE, 1062)
    assert connections and all(connection.closed for connection in connections)
    monkeypatch.setattr(sqlite_nonces.sqlite3, "connect", real_connect)
    # 清理、插入和高水位必须一起回滚，失败不能丢失旧防重放记录。
    now[0] = 1000
    assert not store.consume("cred:one", "a" * 32, 1060)
    assert store.consume("cred:one", NONCE, 1060)


def test_initialization_sqlite_failure_is_redacted_and_closes_connection(tmp_path, monkeypatch):
    real_connect = sqlite3.connect
    connections = []

    class FailedInitialize(sqlite3.Connection):
        closed = False

        def execute(self, sql, parameters=()):
            if sql.startswith("CREATE TABLE"):
                raise sqlite3.OperationalError("sensitive SQLite SQL and path")
            return super().execute(sql, parameters)

        def close(self):
            self.closed = True
            return super().close()

    def connect(*args, **kwargs):
        connection = real_connect(*args, factory=FailedInitialize, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite_nonces.sqlite3, "connect", connect)
    path = tmp_path / "reserved-new.sqlite3"
    assert_unavailable(lambda: sqlite_nonces.SqliteNonceStore.create(path))
    assert path.exists()
    assert connections and all(connection.closed for connection in connections)


def test_synchronous_pragma_failure_closes_connection_and_fails_closed(tmp_path, monkeypatch):
    store, _, _ = create(tmp_path)
    real_connect = sqlite3.connect
    connections = []

    class FailedPragma(sqlite3.Connection):
        closed = False

        def execute(self, sql, parameters=()):
            if sql == "PRAGMA synchronous = FULL":
                raise sqlite3.OperationalError("sensitive SQLite setting and path")
            return super().execute(sql, parameters)

        def close(self):
            self.closed = True
            return super().close()

    def connect(*args, **kwargs):
        connection = real_connect(*args, factory=FailedPragma, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite_nonces.sqlite3, "connect", connect)
    assert not store.consume("cred:one", NONCE, NOW + 60)
    assert_unavailable(lambda: sqlite_nonces.SqliteNonceStore(tmp_path / "dedicated-nonces.sqlite3"))
    assert len(connections) == 2 and all(connection.closed for connection in connections)


def test_importing_module_never_connects_or_opens_storage(monkeypatch):
    def unexpected_io(*args, **kwargs):
        pytest.fail("导入 nonce 适配器不应访问存储")

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", unexpected_io)
        patch.setattr(Path, "open", unexpected_io)
        importlib.reload(sqlite_nonces)


def test_uri_escaping_keeps_special_path_characters_literal(tmp_path):
    path = tmp_path / "dedicated #percent% 中文.sqlite3"
    store = sqlite_nonces.SqliteNonceStore.create(path, clock=lambda: NOW)
    assert path.is_file()
    assert store.consume("cred:one", NONCE, NOW + 60)
    reopened = sqlite_nonces.SqliteNonceStore(path, clock=lambda: NOW)
    assert not reopened.consume("cred:one", NONCE, NOW + 60)


def test_each_consumption_uses_and_closes_its_own_full_sync_connection(tmp_path, monkeypatch):
    store, _, _ = create(tmp_path)
    real_connect = sqlite3.connect
    connections = []

    class ObservedConnection(sqlite3.Connection):
        closed = False
        statements = None

        def execute(self, sql, parameters=()):
            if self.statements is None:
                self.statements = []
            self.statements.append(sql)
            return super().execute(sql, parameters)

        def close(self):
            self.closed = True
            return super().close()

    def connect(database, *args, **kwargs):
        assert kwargs["uri"] is True
        assert "mode=rw" in database
        connection = real_connect(database, *args, factory=ObservedConnection, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite_nonces.sqlite3, "connect", connect)
    assert store.consume("cred:one", NONCE, NOW + 60)
    assert not store.consume("cred:one", NONCE, NOW + 60)
    assert len(connections) == 2
    assert all(connection.closed for connection in connections)
    assert all("BEGIN IMMEDIATE" in connection.statements for connection in connections)
    assert all("PRAGMA synchronous = FULL" in connection.statements for connection in connections)


def test_database_contains_only_nonce_identifiers_expiry_and_metadata(tmp_path):
    _, path, _ = create(tmp_path)
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA application_id").fetchone()[0] == 0x5341464E
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert [row[1] for row in connection.execute("PRAGMA table_info(nonces)")] == [
            "credential_id", "nonce", "expires_at",
        ]
    finally:
        connection.close()
