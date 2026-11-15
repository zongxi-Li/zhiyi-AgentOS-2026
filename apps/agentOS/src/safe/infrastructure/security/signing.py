"""独立的 safe-v1 HMAC-SHA256 签名；输入必须为实际发送的最终字节。"""

import hashlib
import hmac
import re

from safe.ports.credentials import Credential, validate_identifier


PROTOCOL = "safe-v1"
DOMAIN = "SAFE-HMAC-SHA256-V1"
NONCE_PATTERN = re.compile(r"[0-9a-f]{32}")
SIGNATURE_PATTERN = re.compile(r"[0-9a-f]{64}")
_ROUTE_ID = r"[A-Za-z0-9_-]{1,128}"
_ROUTES = {
    "GET": re.compile(rf"/safe/v1/(?:capabilities|sessions/{_ROUTE_ID}/requests/{_ROUTE_ID})"),
    "POST": re.compile(rf"/safe/v1/sessions(?:/{_ROUTE_ID}/steps)?"),
    "DELETE": re.compile(rf"/safe/v1/sessions/{_ROUTE_ID}"),
}


def canonical_request(
    *, credential_id: str, method: str, path: str, timestamp: int, nonce: str, body: bytes,
) -> bytes:
    """按域、凭据、方法、路径、整数时间、nonce、原文字节摘要以换行拼接。

    路径采用唯一 ASCII 白名单，不解析或修复 query、百分号编码及路径穿越。
    时间戳是十进制 UTC Unix 秒，拼接结果末尾没有换行。
    """
    validate_identifier(credential_id)
    if not isinstance(method, str) or not method.isascii() or not isinstance(path, str):
        raise ValueError("签名路由无效")
    method = method.upper()
    route = _ROUTES.get(method)
    if route is None or route.fullmatch(path) is None:
        raise ValueError("签名路由无效")
    if type(timestamp) is not int or timestamp < 0:
        raise ValueError("签名时间戳无效")
    if not isinstance(nonce, str) or NONCE_PATTERN.fullmatch(nonce) is None:
        raise ValueError("签名 nonce 无效")
    if not isinstance(body, bytes):
        raise ValueError("签名正文必须为最终字节串")
    return "\n".join((DOMAIN, credential_id, method, path, str(timestamp), nonce, hashlib.sha256(body).hexdigest())).encode("ascii")


def sign_request(
    *, credential: Credential, method: str, path: str, timestamp: int, nonce: str, body: bytes,
) -> dict[str, str]:
    """签名最终请求字节并返回必须原样发送的五个认证头。"""
    canonical = canonical_request(
        credential_id=credential.credential_id, method=method, path=path,
        timestamp=timestamp, nonce=nonce, body=body,
    )
    return {
        "X-Safe-Protocol": PROTOCOL,
        "X-Safe-Credential": credential.credential_id,
        "X-Safe-Timestamp": str(timestamp),
        "X-Safe-Nonce": nonce,
        "X-Safe-Signature": hmac.new(credential.secret, canonical, hashlib.sha256).hexdigest(),
    }
