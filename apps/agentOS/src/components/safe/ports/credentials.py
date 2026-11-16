"""凭据查询与原子 nonce 消费端口；密钥不进入身份 DTO 或 repr。"""

from dataclasses import dataclass, field
import re
from typing import Protocol


def validate_identifier(value: str) -> None:
    """验证与 contracts.base.Identifier 一致的完整 ASCII 标识符。"""
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value) is None:
        raise ValueError("凭据标识符无效")


@dataclass(frozen=True)
class Credential:
    """凭据源返回的不可变快照；撤销状态须在每次请求重新读取。"""

    credential_id: str
    owner_id: str
    secret: bytes = field(repr=False)
    scopes: frozenset[str]
    revoked: bool = False

    def __post_init__(self) -> None:
        validate_identifier(self.credential_id)
        validate_identifier(self.owner_id)
        if not isinstance(self.secret, bytes) or len(self.secret) < 32:
            raise ValueError("凭据密钥必须为至少 32 字节的不可变字节串")
        if isinstance(self.scopes, str):
            raise ValueError("凭据作用域无效")
        try:
            scopes = frozenset(self.scopes)
        except TypeError:
            raise ValueError("凭据作用域无效") from None
        if any(not isinstance(scope, str) or not scope for scope in scopes):
            raise ValueError("凭据作用域无效")
        if type(self.revoked) is not bool:
            raise ValueError("凭据撤销状态无效")
        object.__setattr__(self, "scopes", scopes)


class CredentialSource(Protocol):
    def get(self, credential_id: str) -> Credential | None:
        """实时查询凭据；未知或已删除的凭据返回 None。"""
        ...


class NonceStore(Protocol):
    def consume(self, credential_id: str, nonce: str, expires_at: float) -> bool:
        """原子首次消费返回 True；重复/容量不足拒绝，过期边界包含在有效期内。"""
        ...
