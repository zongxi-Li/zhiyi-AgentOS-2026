"""受信manifest/会话驱动的激活编解码用例；不执行模型、网络或DP。

本服务核实格式/边界，不创建会话、不检查owner凭据；上层先认证再传入会话上下文。
TODO(P3)：会话管理器在锁内取得ActivationContext，幂等查回执先于next_step验证。
TODO(P4)：隐私发布完成后将固定字节/回执交签名传输；禁止直接当作DP出站接口。
"""

from collections.abc import Iterable

from pydantic import ValidationError

from components.safe.contracts.errors import ErrorCode, SafeError
from components.safe.contracts.manifest import SplitModelManifest
from components.safe.contracts.session import ActivationContext, StepRequest
from components.safe.domain.activation_policy import require_activation_boundary
from components.safe.domain.compatibility import require_manifest_digest
from components.safe.domain.session_state import require_next_step
from components.safe.ports.activation_codec import ActivationCodec


class ActivationService:
    def __init__(self, *, codec: ActivationCodec, manifest: SplitModelManifest, approved_digest: str):
        self._manifest = require_manifest_digest(manifest, approved_digest)
        self._digest = approved_digest
        self._codec = codec

    def _context(self, context: ActivationContext) -> ActivationContext:
        try:
            value = ActivationContext.model_validate(context.model_dump())
        except (ValidationError, AttributeError):
            raise SafeError(ErrorCode.SESSION_INVALID) from None
        if value.manifest_digest != self._digest:
            raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
        return value

    def encode(self, values: Iterable[float], shape: tuple[int, int, int], *,
               context: ActivationContext, request_id: str) -> StepRequest:
        trusted = self._context(context)
        require_activation_boundary(shape, self._manifest, trusted)
        envelope = self._codec.encode(values, shape)
        try:
            return StepRequest(request_id=request_id, session_id=trusted.session_id,
                manifest_digest=self._digest, step=trusted.next_step, phase=trusted.phase,
                position_offset=trusted.position_offset, activation=envelope)
        except ValidationError:
            raise SafeError(ErrorCode.ACTIVATION_INVALID) from None

    def decode(self, request: StepRequest, *, context: ActivationContext) -> tuple[float, ...]:
        trusted = self._context(context)
        try:
            value = StepRequest.model_validate(request.model_dump())
        except (ValidationError, AttributeError):
            raise SafeError(ErrorCode.ACTIVATION_INVALID) from None
        if value.session_id != trusted.session_id:
            raise SafeError(ErrorCode.SESSION_INVALID)
        if value.manifest_digest != self._digest:
            raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
        require_next_step(expected=trusted.next_step, received=value.step)
        if value.phase != trusted.phase or value.position_offset != trusted.position_offset:
            raise SafeError(ErrorCode.STEP_OUT_OF_ORDER)
        require_activation_boundary(value.activation.shape, self._manifest, trusted)
        return self._codec.decode(value.activation)
