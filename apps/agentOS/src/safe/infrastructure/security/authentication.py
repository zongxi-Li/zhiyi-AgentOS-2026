"""实时凭据认证、固定失败码及有界原子 nonce 防重放。"""

from collections import Counter
from collections.abc import Callable, Mapping
import hashlib
import hmac
import math
import re
import threading
import time

from safe.contracts.errors import ErrorCode, SafeError
from safe.contracts.identity import AuthenticatedIdentity
from safe.infrastructure.security.signing import NONCE_PATTERN, PROTOCOL, SIGNATURE_PATTERN, canonical_request
from safe.ports.credentials import Credential, CredentialSource, NonceStore, validate_identifier


WINDOW_SECONDS = 60
_HEADERS = frozenset({"x-safe-protocol", "x-safe-credential", "x-safe-timestamp", "x-safe-nonce", "x-safe-signature"})


def _finite_time(value: float) -> bool:
    """时钟与过期时间必须为有限实数，拒绝布尔值。"""
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


class InMemoryNonceStore:
    """进程内防重放；多进程部署须替换为共享、原子且有界的存储实现。

    在锁内记录有效消费尝试的 UTC 高水位；回拨时拒绝消费，直到时钟恢复。
    只有格式及期限有效的消费尝试才推进高水位，重复或容量拒绝也保留观测。
    外部无效过期时间不改变高水位，也不触发过期清理。
    """

    def __init__(
        self, *, clock: Callable[[], float] = time.time,
        max_entries: int = 10000, max_per_credential: int = 1000,
    ) -> None:
        if any(type(limit) is not int or limit < 1 for limit in (max_entries, max_per_credential)):
            raise ValueError("nonce 容量必须为正整数")
        self._clock = clock
        self._max_entries = max_entries
        self._max_per_credential = max_per_credential
        self._entries: dict[tuple[str, str], float] = {}
        self._counts: Counter[str] = Counter()
        self._clock_high_watermark: float | None = None
        self._lock = threading.Lock()

    def consume(self, credential_id: str, nonce: str, expires_at: float) -> bool:
        """清理已过期条目后原子插入；有效 nonce 永不因容量压力被驱逐。"""
        validate_identifier(credential_id)
        if not isinstance(nonce, str) or NONCE_PATTERN.fullmatch(nonce) is None:
            return False
        with self._lock:
            now = self._clock()
            if not _finite_time(now) or not _finite_time(expires_at):
                return False
            if not now <= expires_at <= now + 2 * WINDOW_SECONDS:
                return False
            if self._clock_high_watermark is not None and now < self._clock_high_watermark:
                return False
            self._clock_high_watermark = now
            for key, expiry in list(self._entries.items()):
                # 验签时间窗含边界，因此只有严格早于当前时间才可删除。
                if expiry < now:
                    del self._entries[key]
                    self._counts[key[0]] -= 1
                    if self._counts[key[0]] == 0:
                        del self._counts[key[0]]
            key = (credential_id, nonce)
            if key in self._entries or len(self._entries) >= self._max_entries:
                return False
            if self._counts[credential_id] >= self._max_per_credential:
                return False
            self._entries[key] = expires_at
            self._counts[credential_id] += 1
            return True


class HmacAuthenticator:
    """先验证完整请求，再消费 nonce；仅凭据源决定 owner 和作用域。"""

    def __init__(self, *, credentials: CredentialSource, nonces: NonceStore, clock: Callable[[], float] = time.time) -> None:
        self._credentials = credentials
        self._nonces = nonces
        self._clock = clock

    def authenticate(self, *, method: str, path: str, headers: Mapping[str, str], body: bytes) -> AuthenticatedIdentity:
        """返回凭据绑定身份；所有失败仅暴露固定码。

        HTTP 层必须在构建 Mapping 前拒绝重复原始认证头，本层同时拒绝大小写别名。
        正文不解析，不信任其中任何 owner 字段。
        """
        try:
            return self._authenticate(method=method, path=path, headers=headers, body=body)
        except Exception:
            pass
        # 在异常处理块外抛出，避免原始凭据源异常进入异常上下文。
        raise SafeError(ErrorCode.AUTHENTICATION_FAILED)

    def _authenticate(self, *, method: str, path: str, headers: Mapping[str, str], body: bytes) -> AuthenticatedIdentity:
        normalized: dict[str, str] = {}
        for key, value in headers.items():
            name = key.lower()
            if name in _HEADERS:
                if name in normalized or not isinstance(value, str):
                    raise ValueError("认证头无效")
                normalized[name] = value
        if normalized.keys() != _HEADERS or normalized["x-safe-protocol"] != PROTOCOL:
            raise ValueError("认证头无效")
        timestamp_text = normalized["x-safe-timestamp"]
        if len(timestamp_text) > 20 or re.fullmatch(r"(?:0|[1-9][0-9]*)", timestamp_text) is None:
            raise ValueError("认证时间戳无效")
        timestamp = int(timestamp_text)
        now = self._clock()
        if not _finite_time(now) or not now - WINDOW_SECONDS <= timestamp <= now + WINDOW_SECONDS:
            raise ValueError("认证时间窗无效")
        credential_id = normalized["x-safe-credential"]
        nonce = normalized["x-safe-nonce"]
        signature = normalized["x-safe-signature"]
        if SIGNATURE_PATTERN.fullmatch(signature) is None:
            raise ValueError("认证签名无效")
        canonical = canonical_request(
            credential_id=credential_id, method=method, path=path,
            timestamp=timestamp, nonce=nonce, body=body,
        )
        credential = self._credentials.get(credential_id)
        if not isinstance(credential, Credential) or credential.credential_id != credential_id:
            raise ValueError("认证凭据无效")
        if credential.revoked or "safe:infer" not in credential.scopes:
            raise ValueError("认证凭据无效")
        expected = hmac.new(credential.secret, canonical, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("认证签名无效")
        if not self._nonces.consume(credential_id, nonce, timestamp + WINDOW_SECONDS):
            raise ValueError("认证 nonce 无效")
        return AuthenticatedIdentity(
            owner_id=credential.owner_id, credential_id=credential.credential_id,
            scopes=tuple(sorted(credential.scopes)),
        )
