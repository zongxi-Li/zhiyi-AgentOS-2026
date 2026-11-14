"""基础数据边界测试；不下载模型、不访问网络。"""

import hashlib
import math

import pytest
from pydantic import ValidationError

from safe.contracts.activation import ActivationEnvelope
from safe.contracts.errors import SafeError
from safe.infrastructure.codecs.fp32 import FP32Codec
from safe.infrastructure.privacy.clipping import clip_global_l2


def test_fp32_roundtrip_has_explicit_little_endian_layout():
    codec = FP32Codec()
    envelope = codec.encode([1.0, -2.0], (1, 1, 2))
    assert envelope.sha256 == hashlib.sha256(b'\x00\x00\x80\x3f\x00\x00\x00\xc0').hexdigest()
    assert codec.decode(envelope) == (1.0, -2.0)


def test_codec_rejects_integrity_failure():
    codec = FP32Codec()
    envelope = codec.encode([1.0], (1, 1, 1))
    corrupt = envelope.model_copy(update={"sha256": "0" * 64})
    with pytest.raises(SafeError, match="ACTIVATION_INVALID"):
        codec.decode(corrupt)


@pytest.mark.parametrize("value", [float('nan'), float('inf'), -float('inf'), 1e40])
def test_codec_rejects_non_finite_or_unrepresentable_fp32(value):
    with pytest.raises(SafeError):
        FP32Codec().encode([value], (1, 1, 1))


def test_codec_checks_shape_before_consuming_input():
    def forbidden():
        pytest.fail("越界 shape 不应读取张量")
        yield 1.0

    with pytest.raises(SafeError):
        FP32Codec().encode(forbidden(), (1, 1, 3_000_000))


def test_codec_rejects_size_mismatch_and_noncanonical_base64():
    codec = FP32Codec()
    with pytest.raises(SafeError):
        codec.encode([1.0, 2.0], (1, 1, 1))
    envelope = codec.encode([1.0], (1, 1, 1))
    with pytest.raises(SafeError):
        codec.decode(envelope.model_copy(update={"data": envelope.data + "\n"}))


def test_wire_contract_rejects_extra_fields_and_coercion():
    good = FP32Codec().encode([1.0], (1, 1, 1)).model_dump()
    for updates in ({"raw_bytes": "4"}, {"shape": (True, 1, 1)}, {"prompt": "禁止上云"}):
        with pytest.raises(ValidationError):
            ActivationEnvelope(**(good | updates))


def test_clipping_bounds_full_vector_and_handles_large_finite_values():
    assert clip_global_l2((3.0, 4.0), 2.0) == pytest.approx((1.2, 1.6))
    large = clip_global_l2((1e308, 1e308), 1.0)
    assert math.hypot(*large) == pytest.approx(1.0)
    assert clip_global_l2((0.0, 0.0), 1.0) == (0.0, 0.0)
    with pytest.raises(SafeError):
        clip_global_l2((float('nan'),), 1.0)
    with pytest.raises(SafeError):
        clip_global_l2((1.0,), 0.0)
