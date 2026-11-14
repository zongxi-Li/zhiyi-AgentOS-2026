"""已认证身份下的幂等匹配规则；摘要应覆盖 manifest、phase、step 与激活。

TODO(P3)：会话存储必须原子占用 key；先查已完成回执，再检查 next_step。
TODO(P3)：nonce 防重放和 request_id 幂等分别处理，跨 owner 永远拒绝复用。
"""

from safe.contracts.errors import ErrorCode, SafeError

RequestIdentity = tuple[str, str, str, str]  # owner / session / request / 请求摘要


def require_same_request(stored: RequestIdentity, received: RequestIdentity) -> None:
    if stored != received:
        raise SafeError(ErrorCode.IDEMPOTENCY_CONFLICT)
