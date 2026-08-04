"""消息负载来源摘要。"""

from contracts import stable_checksum


def provenance_checksum(payload: dict[str, object]) -> str:
    """计算稳定校验和，供外部审计存储关联。"""
    return stable_checksum(payload)
