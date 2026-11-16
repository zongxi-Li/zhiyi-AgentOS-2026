"""后段激活续算用例：会话事务、受信边界、suffix KV与采样回执。

owner必须由上层认证后提供；本用例不实现认证、HTTP或本机原文处理。
TODO(P2)：在专用认证路由内装配，并保证会话存储与本用例注入同一个suffix runner。
TODO(P3)：本机生成用例接入远端回执查询、EOS解码和双端终态协商。
TODO(P6)：增加容量配额和无内容审计；同步执行不构成异步GPU强制取消能力。
"""

from components.safe.application.activation import ActivationService
from components.safe.application.session import SessionService
from components.safe.contracts.errors import ErrorCode, SafeError
from components.safe.contracts.manifest import SplitModelManifest
from components.safe.contracts.session import ActivationContext, SessionView, StepReceipt, StepRequest
from components.safe.domain.compatibility import require_manifest_digest
from components.safe.ports.activation_codec import ActivationCodec
from components.safe.ports.model_runner import KVHandle, SuffixRunner, TokenSampler


class ContinuationService:
    """每次仅接受一步激活，不提供prompt/token IDs入口，也不返回完整词表。"""

    def __init__(self, *, sessions: SessionService, runner: SuffixRunner, codec: ActivationCodec,
                 sampler: TokenSampler, manifest: SplitModelManifest, approved_digest: str,
                 max_new_tokens: int = 32):
        if type(max_new_tokens) is not int or not 1 <= max_new_tokens <= 32:
            raise ValueError("每次会话的输出上限必须位于1–32")
        require_manifest_digest(manifest, approved_digest)
        require_manifest_digest(runner.manifest, approved_digest)
        self._sessions = sessions
        self._runner = runner
        self._sampler = sampler
        self._digest = approved_digest
        self._max_new_tokens = max_new_tokens
        self._activation = ActivationService(codec=codec, manifest=manifest, approved_digest=approved_digest)

    def create(self, owner_id: str, *, session_id: str | None = None) -> SessionView:
        """只创建批准manifest的会话；模型路径和身份不允许请求方覆盖。"""
        return self._sessions.create(owner_id, self._digest, session_id=session_id)

    def step(self, owner_id: str, request: StepRequest) -> StepReceipt:
        """先查已提交回执，再核验/执行；幂等重试不再次解码、计算或采样。"""
        return self._sessions.execute_with_context(owner_id, request, self._forward)

    def _forward(self, request: StepRequest, context: ActivationContext,
                 handle: KVHandle | None) -> tuple[int, bool]:
        if handle is None:
            raise SafeError(ErrorCode.MODEL_PARTITION_UNAVAILABLE)
        activation = self._activation.decode(request, context=context)
        if context.phase == "prefill":
            logits = self._runner.prefill(activation, request.activation.shape,
                kv_handle=handle, session_id=context.session_id)
        else:
            logits = self._runner.decode(handle, context.session_id, activation, request.activation.shape)
        token_id, eos = self._sampler.sample(logits)
        return token_id, eos or context.next_step + 1 >= self._max_new_tokens


__all__ = ["ContinuationService"]
