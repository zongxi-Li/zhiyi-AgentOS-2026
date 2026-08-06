"""失败分类的确定性规则。"""

from contracts.recovery import FailureEvent


def classify_failure(event: FailureEvent) -> str:
    """以合同中的 retryable 声明为优先事实，避免猜测底层异常。"""
    return "retryable" if event.retryable else "terminal"
