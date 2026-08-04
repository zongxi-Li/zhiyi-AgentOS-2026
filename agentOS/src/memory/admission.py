"""记忆准入规则。"""

from contracts.memory import MemoryPolicy, MemoryRecord


def admitted(record: MemoryRecord, policy: MemoryPolicy | None = None) -> bool:
    """无策略时允许写入；有策略时必须属于允许类别。"""
    return policy is None or record.memory_type in policy.allowed_types
