"""本机非流式生成：固定模板、前段KV、激活发送、回执恢复与本机解码。

无配置保持明确不可用；只允许显式注入批准角色，不回退到普通聊天。
TODO(P3)：引入跨进程deadline/取消协议；当前取消只在同步调用之间协作检查。
TODO(P5)：通过本机可信接口接入产品；当前不提供HTTP、UI或DP保证。
"""

from collections.abc import Callable
import secrets
import threading

from pydantic import ValidationError

from components.safe.application.activation import ActivationService
from components.safe.contracts.errors import ErrorCode, SafeError
from components.safe.contracts.inference import InferenceRequest, InferenceResult
from components.safe.contracts.manifest import SplitModelManifest
from components.safe.contracts.session import ActivationContext, SessionStatus, SessionView, StepReceipt, StepRequest
from components.safe.domain.compatibility import require_manifest_digest
from components.safe.ports.activation_codec import ActivationCodec
from components.safe.ports.model_runner import LocalTokenizer, PrefixRunner
from components.safe.ports.remote_transport import RemoteTransport


class SplitInferenceService:
    """每个实例至多一个活动生成；连接/模型由装配者创建和关闭。"""

    def __init__(self, *, prefix: PrefixRunner | None = None, tokenizer: LocalTokenizer | None = None,
                 transport: RemoteTransport | None = None, codec: ActivationCodec | None = None,
                 manifest: SplitModelManifest | None = None, approved_digest: str | None = None):
        supplied = (prefix, tokenizer, transport, codec, manifest, approved_digest)
        self._available = all(value is not None for value in supplied)
        if any(value is not None for value in supplied) and not self._available:
            raise ValueError("本机生成依赖必须全部注入")
        self._lock = threading.Lock()
        if not self._available:
            return
        require_manifest_digest(manifest, approved_digest)
        require_manifest_digest(prefix.manifest, approved_digest)
        require_manifest_digest(tokenizer.manifest, approved_digest)
        self._prefix, self._tokenizer, self._transport = prefix, tokenizer, transport
        self._digest = approved_digest
        self._activation = ActivationService(codec=codec, manifest=manifest, approved_digest=approved_digest)

    def infer(self, request: InferenceRequest, *,
              cancelled: Callable[[], bool] | None = None) -> InferenceResult:
        if not self._available:
            raise SafeError(ErrorCode.MODEL_PARTITION_UNAVAILABLE)
        if not self._lock.acquire(blocking=False):
            raise SafeError(ErrorCode.SESSION_INVALID)
        try:
            try:
                checked = InferenceRequest.model_validate(request.model_dump())
            except (ValidationError, AttributeError):
                raise SafeError(ErrorCode.INFERENCE_INVALID) from None
            return self._generate(checked, cancelled or (lambda: False))
        finally:
            self._lock.release()

    def _generate(self, request: InferenceRequest, cancelled: Callable[[], bool]) -> InferenceResult:
        tokens: list[int] = []
        if cancelled():
            return self._result(tokens, "cancelled")
        ids = self._tokenizer.encode_prompt(request.prompt)
        if (not isinstance(ids, tuple) or not 1 <= len(ids) <= 128
                or any(type(token) is not int or not 0 <= token < self._tokenizer.vocab_size for token in ids)):
            raise SafeError(ErrorCode.INFERENCE_INVALID)
        session_id = handle = None
        failed = False
        try:
            try:
                view = SessionView.model_validate(self._transport.create_session(self._digest).model_dump())
            except (ValidationError, AttributeError):
                raise SafeError(ErrorCode.SESSION_INVALID) from None
            session_id = view.session_id
            if view.manifest_digest != self._digest:
                raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
            if view.status is not SessionStatus.CREATED or view.next_step != 0:
                raise SafeError(ErrorCode.SESSION_INVALID)
            handle = self._prefix.create_kv(session_id)
            flat, shape = self._prefix.prefill(ids, kv_handle=handle, session_id=session_id)
            for step in range(request.generation.max_new_tokens):
                if cancelled():
                    return self._result(tokens, "cancelled")
                context = ActivationContext(session_id=session_id, manifest_digest=self._digest,
                    next_step=step, phase="prefill" if step == 0 else "decode",
                    position_offset=0 if step == 0 else len(ids) + step - 1)
                outbound = self._activation.encode(flat, shape, context=context,
                                                  request_id="request-" + secrets.token_urlsafe(18))
                receipt = self._send(outbound)
                tokens.append(receipt.token_id)
                eos = receipt.token_id in self._tokenizer.eos_token_ids
                at_limit = step + 1 == request.generation.max_new_tokens
                if eos and not receipt.finished or receipt.finished and not eos and not at_limit:
                    raise SafeError(ErrorCode.MODEL_OUTPUT_INVALID)
                if eos or at_limit:
                    return self._result(tokens, "eos" if eos else "length")
                if cancelled():
                    return self._result(tokens, "cancelled")
                flat, shape = self._prefix.decode(handle, session_id, receipt.token_id)
            raise AssertionError("输出上限合同被绕过")
        except BaseException:
            failed = True
            raise
        finally:
            # 一个清理失败不跳过另一个，也不掩盖原始计算/取消异常。
            cleanup_error = None
            if session_id is not None:
                try:
                    self._transport.close_session(session_id)
                except BaseException:
                    cleanup_error = SafeError(ErrorCode.TRANSPORT_UNAVAILABLE)
            if handle is not None:
                try:
                    self._prefix.release_kv(handle)
                except BaseException:
                    cleanup_error = cleanup_error or SafeError(ErrorCode.MODEL_PARTITION_UNAVAILABLE)
            if cleanup_error is not None and not failed:
                raise cleanup_error from None

    def _send(self, request: StepRequest) -> StepReceipt:
        try:
            receipt = self._transport.step(request)
        except (TimeoutError, ConnectionError):
            receipt = self._recover(request)
        except SafeError as exc:
            if exc.code is not ErrorCode.TRANSPORT_UNAVAILABLE:
                raise
            receipt = self._recover(request)
        try:
            checked = StepReceipt.model_validate(receipt.model_dump())
        except (ValidationError, AttributeError):
            raise SafeError(ErrorCode.MODEL_OUTPUT_INVALID) from None
        if (checked.request_id != request.request_id or checked.session_id != request.session_id
                or checked.step != request.step or checked.token_id >= self._tokenizer.vocab_size):
            raise SafeError(ErrorCode.MODEL_OUTPUT_INVALID)
        return checked

    def _recover(self, request: StepRequest) -> StepReceipt:
        try:
            receipt = self._transport.query(request.session_id, request.request_id)
        except Exception:
            raise SafeError(ErrorCode.TRANSPORT_UNAVAILABLE) from None
        if receipt is None:
            raise SafeError(ErrorCode.TRANSPORT_UNAVAILABLE)
        return receipt

    def _result(self, tokens: list[int], reason: str) -> InferenceResult:
        return InferenceResult(text=self._tokenizer.decode(tuple(tokens)),
                               generated_tokens=len(tokens), finish_reason=reason)
