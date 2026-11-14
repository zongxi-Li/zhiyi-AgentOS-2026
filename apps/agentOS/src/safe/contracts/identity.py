"""经认证的身份值；凭据本体、签名和 nonce 不进入普通 DTO 或 repr。

TODO(P1)：认证适配器生成主体，验证 tenant、凭据撤销与操作作用域。
TODO(P1)：区分请求验签时间与会话 TTL；凭据轮转后旧会话策略必须明确。
"""

from safe.contracts.base import Identifier, SafeContract


class AuthenticatedIdentity(SafeContract):
    owner_id: Identifier
    credential_id: Identifier
    scopes: tuple[str, ...]
