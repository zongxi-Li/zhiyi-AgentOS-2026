"""本机推理编排；目前只有明确拒绝入口，不执行真实前导网络。

TODO(P2)：注入 prefix runner、tokenizer 与已验证 manifest；不得由本层导入 Torch。
TODO(P3)：固定模板后检查128 token；prefill→远端 token→本机 decode，最多32次。
TODO(P3)：两端各持有本角色 KV；异常/取消/超时均释放或隔离，不回退传原文。
TODO(P3)：查回执优先于重发；不确定 KV 状态使会话 FAILED。
验收：与完整模型 greedy token 对照，逐步 logits 容差、取消、断网分别覆盖。
"""

from safe.contracts.errors import ErrorCode, SafeError
from safe.contracts.inference import InferenceRequest, InferenceResult


class SplitInferenceService:
    """尚未接入端口；显式拒绝以防将骨架当成可用推理。"""

    def infer(self, request: InferenceRequest) -> InferenceResult:
        raise SafeError(ErrorCode.MODEL_PARTITION_UNAVAILABLE)
