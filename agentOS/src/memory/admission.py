"""记忆准入规则。"""

from contracts.memory import MemoryPolicy, MemoryRecord


def admitted(record: MemoryRecord, policy: MemoryPolicy | None = None) -> bool:
    """判断记忆记录是否可按可选策略写入。

    未提供策略时允许所有记录；提供策略时仅允许 ``memory_type`` 位于允许集合的
    记录。函数不改变记录或策略，也不校验容量、权限与过期时间，复杂度 O(1)。
    """
    return policy is None or record.memory_type in policy.allowed_types
