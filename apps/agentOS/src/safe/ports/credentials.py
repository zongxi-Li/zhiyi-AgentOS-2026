"""凭据与nonce存储端口；不在普通DTO或全局变量内保存密钥。

TODO(P1)：冻结凭据查询/轮转/撤销方法和秘密内存清理策略。
TODO(P1)：nonce消费必须原子，限制每主体数量并覆盖签名时间窗后的TTL。
TODO(P1)：认证请求与业务幂等分别处理；每次重传nonce必须不同。
"""

from typing import Protocol


class NonceStore(Protocol):
    def consume(self, credential_id: str, nonce: str, expires_at: float) -> bool:
        """原子插入首次出现的nonce返回True；重复/容量不足均拒绝。"""
        ...
