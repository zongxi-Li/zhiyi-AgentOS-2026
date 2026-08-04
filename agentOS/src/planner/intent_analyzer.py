"""不调用远程模型的基础意图分析。"""


def analyze_intent(text: str) -> dict[str, object]:
    """提取最小关键词事实；复杂语义应由应用层注入模型适配器。"""
    tokens = [token for token in text.lower().split() if token]
    return {"text": text, "keywords": sorted(set(tokens)), "has_question": "?" in text or "？" in text}


# TODO: 注入 adapters.model 的远程结构化模型，实现多语言语义意图识别。
