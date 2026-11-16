"""本机多进程共享的专用 SQLite nonce 存储；导入模块不触发文件 I/O。

仅 ``create`` 显式初始化全新文件；普通打开及消费始终使用 ``mode=rw``，
文件丢失、未知版本、结构或容量不符均拒绝，不自动建库、迁移或重置。
数据库只保存凭据标识符、nonce、期限和容量/时钟元数据，不保存密钥或激活。

文件位于可信本机存储；不提供防篡改、防文件回滚或跨主机一致性保证。
为保留 SQLite REAL 的整数精度，时间绝对值不得超过 ``2**53 - 1``；
容量为 SQLite INTEGER 范围内的正整数。初始化失败可能留下已独占保留的
新文件，调用方须明确检查处置；这里绝不因失败而删除可能属于别人的文件。
"""

from collections.abc import Callable
from contextlib import closing
import math
from os import PathLike
from pathlib import Path
import sqlite3
import time

from components.safe.contracts.errors import ErrorCode, SafeError
from components.safe.infrastructure.security.signing import NONCE_PATTERN
from components.safe.ports.credentials import validate_identifier


_APPLICATION_ID = 0x5341464E
_VERSION = 1
_MAX_INTEGER = 2 ** 63 - 1
_MAX_EXACT_TIME = 2 ** 53 - 1
_VALIDITY_SECONDS = 120
_META_SQL = (
    "CREATE TABLE nonce_meta ("
    "singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
    "max_entries INTEGER NOT NULL CHECK (max_entries > 0), "
    "max_per_credential INTEGER NOT NULL CHECK (max_per_credential > 0), "
    "clock_high_watermark REAL)"
)
_NONCES_SQL = (
    "CREATE TABLE nonces ("
    "credential_id TEXT NOT NULL, nonce TEXT NOT NULL, expires_at REAL NOT NULL, "
    "PRIMARY KEY (credential_id, nonce))"
)
_INDEX_SQL = "CREATE INDEX nonces_expiry ON nonces (expires_at)"
_EXPECTED_SCHEMA = {
    ("table", "nonce_meta", "nonce_meta", _META_SQL),
    ("table", "nonces", "nonces", _NONCES_SQL),
    ("index", "nonces_expiry", "nonces", _INDEX_SQL),
    ("index", "sqlite_autoindex_nonces_1", "nonces", None),
}


def _finite_time(value: object) -> bool:
    """沿用端口的有限 int/float 规则，并拒绝超出 SQLite 精度范围的时间。"""
    try:
        return type(value) in (int, float) and math.isfinite(value) and abs(value) <= _MAX_EXACT_TIME
    except OverflowError:
        return False


class SqliteNonceStore:
    """以持久 UTC 高水位拒绝时钟回拨，直到时钟恢复；有效条目不因容量驱逐。"""

    def __init__(
        self, path: str | PathLike[str], *, clock: Callable[[], float] = time.time,
        max_entries: int = 10000, max_per_credential: int = 1000,
        timeout: float = 0.25,
    ) -> None:
        self._configure(clock, max_entries, max_per_credential, timeout)
        try:
            self._set_path(path)
            with closing(self._connect()) as connection:
                connection.execute("PRAGMA synchronous = FULL")
                # 显式读事务保证结构与元数据来自同一数据库快照。
                connection.execute("BEGIN")
                self._verify(connection)
                connection.commit()
            return
        except Exception:
            # 在 except 块外抛出固定错误，连 __context__ 也不保留文件或 SQL。
            pass
        raise SafeError(ErrorCode.TRANSPORT_UNAVAILABLE)

    @classmethod
    def create(
        cls, path: str | PathLike[str], *, clock: Callable[[], float] = time.time,
        max_entries: int = 10000, max_per_credential: int = 1000,
        timeout: float = 0.25,
    ) -> "SqliteNonceStore":
        """独占保留并初始化新专用文件；存在的文件即使为空也绝不覆盖。"""
        store = cls.__new__(cls)
        store._configure(clock, max_entries, max_per_credential, timeout)
        try:
            store._set_path(path)
            with store._path.open("xb"):
                pass
            with closing(store._connect()) as connection:
                connection.execute("PRAGMA synchronous = FULL")
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
                connection.execute(f"PRAGMA user_version = {_VERSION}")
                for statement in (_META_SQL, _NONCES_SQL, _INDEX_SQL):
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO nonce_meta VALUES (1, ?, ?, NULL)",
                    (max_entries, max_per_credential),
                )
                store._verify(connection)
                connection.commit()
            return store
        except Exception:
            pass
        raise SafeError(ErrorCode.TRANSPORT_UNAVAILABLE)

    def _configure(self, clock, max_entries, max_per_credential, timeout) -> None:
        """配置错误独立于存储错误，且在创建任何文件前报告固定中文文案。"""
        if any(type(limit) is not int or not 1 <= limit <= _MAX_INTEGER for limit in (max_entries, max_per_credential)):
            raise ValueError("nonce 容量必须为正整数")
        if not _finite_time(timeout) or not 0 <= timeout <= 5:
            raise ValueError("nonce 锁等待时间必须为 0 到 5 秒的有限实数")
        if not callable(clock):
            raise ValueError("nonce 时钟必须可调用")
        self._clock = clock
        self._max_entries = max_entries
        self._max_per_credential = max_per_credential
        self._timeout = timeout

    def _set_path(self, path: str | PathLike[str]) -> None:
        """路径转 URI 时转义特殊字符，避免路径被解释为 SQLite URI 参数。"""
        self._path = Path(path).resolve()
        self._uri = self._path.as_uri() + "?mode=rw"

    def _connect(self) -> sqlite3.Connection:
        # 每次消费单独连接，避免在线程/进程间共享连接状态，也不缓存丢失文件。
        return sqlite3.connect(self._uri, uri=True, timeout=self._timeout, isolation_level=None)

    def _verify(self, connection: sqlite3.Connection) -> float | None:
        """仅接受本适配器精确创建的格式；未知对象、缺失索引等均不自动修复。"""
        if connection.execute("PRAGMA application_id").fetchone() != (_APPLICATION_ID,):
            raise ValueError("nonce 数据库格式无效")
        if connection.execute("PRAGMA user_version").fetchone() != (_VERSION,):
            raise ValueError("nonce 数据库格式无效")
        schema = set(connection.execute("SELECT type, name, tbl_name, sql FROM sqlite_schema"))
        if schema != _EXPECTED_SCHEMA:
            raise ValueError("nonce 数据库结构无效")
        if connection.execute("PRAGMA quick_check(1)").fetchall() != [("ok",)]:
            raise ValueError("nonce 数据库结构无效")
        rows = connection.execute(
            "SELECT singleton, max_entries, max_per_credential, clock_high_watermark FROM nonce_meta"
        ).fetchall()
        if len(rows) != 1:
            raise ValueError("nonce 数据库配置无效")
        singleton, max_entries, max_per_credential, watermark = rows[0]
        if (
            type(singleton) is not int or singleton != 1
            or type(max_entries) is not int or max_entries != self._max_entries
            or type(max_per_credential) is not int or max_per_credential != self._max_per_credential
            or watermark is not None and not _finite_time(watermark)
        ):
            raise ValueError("nonce 数据库配置无效")
        return watermark

    def consume(self, credential_id: str, nonce: str, expires_at: float) -> bool:
        """检查、清理、首次消费和高水位在同一事务提交后才可返回 True。"""
        validate_identifier(credential_id)
        if not isinstance(nonce, str) or NONCE_PATTERN.fullmatch(nonce) is None:
            return False
        try:
            with closing(self._connect()) as connection:
                connection.execute("PRAGMA synchronous = FULL")
                connection.execute("BEGIN IMMEDIATE")
                watermark = self._verify(connection)
                now = self._clock()
                if not _finite_time(now) or not _finite_time(expires_at):
                    return False
                if not now <= expires_at <= now + _VALIDITY_SECONDS:
                    return False
                if watermark is not None and now < watermark:
                    return False
                # 有效重复/容量拒绝也必须提交观测；非法时间则完全不改动数据库。
                connection.execute("UPDATE nonce_meta SET clock_high_watermark = ? WHERE singleton = 1", (now,))
                # 验签时间窗含边界，因此只清理严格早于当前 UTC 时间的条目。
                connection.execute("DELETE FROM nonces WHERE expires_at < ?", (now,))
                duplicate = connection.execute(
                    "SELECT 1 FROM nonces WHERE credential_id = ? AND nonce = ?", (credential_id, nonce),
                ).fetchone()
                total = connection.execute("SELECT count(*) FROM nonces").fetchone()[0]
                per_credential = connection.execute(
                    "SELECT count(*) FROM nonces WHERE credential_id = ?", (credential_id,),
                ).fetchone()[0]
                accepted = duplicate is None and total < self._max_entries and per_credential < self._max_per_credential
                if accepted:
                    connection.execute(
                        "INSERT INTO nonces (credential_id, nonce, expires_at) VALUES (?, ?, ?)",
                        (credential_id, nonce, expires_at),
                    )
                connection.commit()
                return accepted
        except Exception:
            # 包含 SQLite 锁/磁盘/I/O/提交故障及不可用时钟；连接关闭会回滚未提交事务。
            return False
