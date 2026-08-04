"""上下文压缩的保守本地实现。"""


def compress_text(text: str, limit: int = 512) -> str:
    """只截取字符前缀并标记截断，避免未接入模型时篡改语义。"""
    return text if len(text) <= limit else f"{text[:max(0, limit - 1)]}…"


# TODO: 注入可溯源的模型摘要器，输出引用保留率与压缩决策证据。
