"""manifest绑定和受信会话驱动的激活流程，全部使用合成制品身份。"""

import pytest

from safe.application.activation import ActivationService
from safe.application.manifest import ManifestService
from safe.contracts.errors import ErrorCode, SafeError
from safe.contracts.manifest import SplitModelManifest
from safe.contracts.session import ActivationContext
from safe.infrastructure.codecs.fp32 import FP32Codec


def manifest():
    return SplitModelManifest(model_id="synthetic/qwen", revision="a" * 40,
        config_digest="b" * 64, tokenizer_digest="c" * 64, template_digest="d" * 64,
        prefix_digest="e" * 64, suffix_digest="f" * 64,
        total_layers=4, cut_layer=2, hidden_size=4, license_id="Apache-2.0")


def setup_service(codec=None):
    approved = manifest()
    digest = ManifestService.digest(approved)
    service = ActivationService(codec=codec or FP32Codec(), manifest=approved, approved_digest=digest)
    context = ActivationContext(session_id="session-1", manifest_digest=digest,
        next_step=0, phase="prefill", position_offset=0)
    return service, context


def test_manifest_canonical_identity_and_all_fields_compatibility():
    value = manifest()
    reordered = SplitModelManifest(**dict(reversed(list(value.model_dump().items()))))
    digest = ManifestService.digest(value)
    assert digest == ManifestService.digest(reordered)
    assert ManifestService.verify(value, digest) == value
    for update in ({"revision": "0" * 40}, {"cut_layer": 1}, {"hidden_size": 8},
                   {"config_digest": "0" * 64}, {"max_context": 161}, {"license_id": "MIT"}):
        changed = value.model_copy(update=update)
        assert ManifestService.digest(changed) != digest
        with pytest.raises(SafeError) as error:
            ManifestService.require_compatible(value, changed)
        assert error.value.code == ErrorCode.MANIFEST_INCOMPATIBLE
    with pytest.raises(SafeError):
        ManifestService.verify(value, "0" * 64)
    with pytest.raises(SafeError):
        ManifestService.digest(value.model_copy(update={"cut_layer": 99}))


def test_activation_prefill_and_decode_roundtrip_with_trusted_context():
    service, context = setup_service()
    request = service.encode(tuple(float(i) for i in range(12)), (1, 3, 4),
                             context=context, request_id="request-0")
    assert service.decode(request, context=context) == tuple(float(i) for i in range(12))
    assert request.position_offset == 0
    decode = context.model_copy(update={"next_step": 1, "phase": "decode", "position_offset": 3})
    request = service.encode((1.0, 2.0, 3.0, 4.0), (1, 1, 4), context=decode, request_id="request-1")
    assert service.decode(request, context=decode) == (1.0, 2.0, 3.0, 4.0)


def test_invalid_outbound_shape_does_not_consume_values_or_call_codec():
    class NeverCodec:
        def encode(self, *args):
            pytest.fail("边界验证失败时不能调用codec")

    service, context = setup_service(NeverCodec())
    for shape in ((1, 1, 8), (2, 1, 4), (1, 129, 4)):
        with pytest.raises(SafeError):
            service.encode(iter(()), shape, context=context, request_id="request-0")


@pytest.mark.parametrize("update", [
    {"session_id": "other"}, {"manifest_digest": "0" * 64}, {"step": 1},
    {"phase": "decode"}, {"position_offset": 1},
])
def test_inbound_binding_rejected_before_codec(update):
    service, context = setup_service()
    valid = service.encode((1.0,) * 4, (1, 1, 4), context=context, request_id="request-0")

    class NeverCodec:
        def decode(self, envelope):
            pytest.fail("身份/步骤不符时不能解码或分配tensor")

    guarded, _ = setup_service(NeverCodec())
    with pytest.raises(SafeError):
        guarded.decode(valid.model_copy(update=update), context=context)


def test_decode_single_position_and_fixed_context_limit():
    service, context = setup_service()
    decode = context.model_copy(update={"next_step": 1, "phase": "decode", "position_offset": 159})
    service.encode((1.0,) * 4, (1, 1, 4), context=decode, request_id="last-valid")
    for change in ({"position_offset": 160}, {"position_offset": 0}, {"next_step": 0}):
        with pytest.raises(SafeError):
            service.encode((1.0,) * 4, (1, 1, 4), context=decode.model_copy(update=change), request_id="bad")
    with pytest.raises(SafeError):
        service.encode((1.0,) * 8, (1, 2, 4), context=decode, request_id="bad-shape")


def test_wrong_context_and_bypassed_contract_validation_are_refused():
    service, context = setup_service()
    for change in ({"manifest_digest": "0" * 64}, {"next_step": True}, {"position_offset": -1}):
        with pytest.raises(SafeError):
            service.encode((1.0,) * 4, (1, 1, 4), context=context.model_copy(update=change), request_id="bad")
    with pytest.raises(SafeError):
        ActivationService(codec=FP32Codec(), manifest=manifest(), approved_digest="0" * 64)
