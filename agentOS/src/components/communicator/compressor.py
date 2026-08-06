"""上下文压缩的保守本地实现。"""


def compress_text(text: str, limit: int = 512) -> str:
    """以字符上限保守截取文本，并在截断时追加省略号。

    长度不超过 ``limit`` 时原样返回；负上限被保护为零长度前缀后仍追加标记。
    本地实现不做语义摘要或模型调用，时间与空间复杂度均为 O(min(n, limit))。
    """
    return text if len(text) <= limit else f"{text[:max(0, limit - 1)]}…"


# TODO: 注入可溯源的模型摘要器，输出引用保留率与压缩决策证据。
