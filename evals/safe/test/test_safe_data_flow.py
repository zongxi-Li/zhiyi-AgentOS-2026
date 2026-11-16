"""safe 第一阶段功能与数据转换测试，仅使用固定或可复现的合成数据。

从仓库根目录运行：
    python -B evals/safe/test/test_safe_data_flow.py

链路：合成激活 → FP32编码 → step合同 → JSON/UTF-8字节 → 解析 → 解码。
此处的字节往返只测试协议数据转换，不代替真实网络、认证、模型或DP验收。
依赖为项目已用的Pydantic；测试运行器使用标准库unittest，不要求Torch/NumPy。

TODO(P1)：wire schema冻结后补充位置、profile、隐私回执绑定及跨语言测试向量。
TODO(P2)：模型runner完成后，在evals/safe/exam中另加真实激活/logits对照。
TODO(P3/P4)：会话事务和预算可用后，添加故障注入；不可用断言届时按能力更新。
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
from pathlib import Path
import random
import struct
import sys
import unittest

# 使用脚本位置定位src，保证从任意工作目录启动，也不会载入整个Agent应用。
SRC = Path(__file__).resolve().parents[3] / "apps/agentOS/src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pydantic import ValidationError  # noqa: E402

from components.safe.application.inference import SplitInferenceService  # noqa: E402
from components.safe.application.privacy import PrivacyReleaseService  # noqa: E402
from components.safe.contracts.activation import ActivationEnvelope, MAX_RAW_BYTES  # noqa: E402
from components.safe.contracts.errors import ErrorCode, SafeError  # noqa: E402
from components.safe.contracts.inference import InferenceRequest  # noqa: E402
from components.safe.contracts.session import SessionStatus, StepRequest  # noqa: E402
from components.safe.domain.activation_policy import checked_raw_bytes  # noqa: E402
from components.safe.domain.idempotency import require_same_request  # noqa: E402
from components.safe.domain.session_state import require_next_step, transition  # noqa: E402
from components.safe.infrastructure.codecs.fp32 import FP32Codec  # noqa: E402
from components.safe.infrastructure.privacy.clipping import clip_global_l2  # noqa: E402


class SafeDataFlowTests(unittest.TestCase):
    """逐段验证字节格式、JSON传递、边界拒绝与基础功能。"""

    def setUp(self) -> None:
        self.codec = FP32Codec()

    def assert_safe_error(self, code: ErrorCode, operation, *args, **kwargs) -> None:
        """只认可指定稳定错误码，普通异常不能当作正确的拒绝行为。"""
        with self.assertRaises(SafeError) as captured:
            operation(*args, **kwargs)
        self.assertEqual(captured.exception.code, code)

    def make_step(self, values=(1.0, -2.0), *, phase="prefill", step=0) -> StepRequest:
        return StepRequest(
            request_id="synthetic-request",
            session_id="synthetic-session",
            manifest_digest="a" * 64,
            phase=phase,
            step=step,
            activation=self.codec.encode(values, (1, 1, len(values))),
        )

    def test_01_known_fp32_wire_vector(self):
        """已知向量固定字节序、base64、长度与SHA256，防止编码/解码同时写错。"""
        envelope = self.codec.encode([1.0, -2.0], (1, 1, 2))
        expected_bytes = b"\x00\x00\x80\x3f\x00\x00\x00\xc0"
        self.assertEqual(envelope.data, "AACAPwAAAMA=")
        self.assertEqual(envelope.raw_bytes, 8)
        self.assertEqual(base64.b64decode(envelope.data), expected_bytes)
        self.assertEqual(envelope.sha256, hashlib.sha256(expected_bytes).hexdigest())
        self.assertEqual(self.codec.decode(envelope), (1.0, -2.0))

    def test_02_prefill_and_decode_json_byte_roundtrip(self):
        """step经过真实JSON/UTF-8字节转换，shape和阶段信息仍准确保留。"""
        for phase, step, shape in (("prefill", 0, (1, 3, 4)), ("decode", 1, (1, 1, 4))):
            with self.subTest(phase=phase):
                values = tuple(float(i) / 4 for i in range(math.prod(shape)))
                request = self.make_step(phase=phase, step=step).model_copy(
                    update={"activation": self.codec.encode(values, shape)}
                )
                wire_bytes = request.model_dump_json().encode("utf-8")
                restored = StepRequest.model_validate_json(wire_bytes)
                self.assertEqual(restored, request)
                self.assertEqual(restored.activation.shape, shape)
                self.assertEqual(self.codec.decode(restored.activation), values)

    def test_03_float64_input_uses_fp32_rounding(self):
        """Python浮点转FP32允许舍入，不能要求0.1等输入逐位不变。"""
        source = (0.1, -0.2, 1.0 / 3.0, 16777217.0)
        result = self.codec.decode(self.codec.encode(source, (1, 1, 4)))
        reference = tuple(struct.unpack("<f", struct.pack("<f", value))[0] for value in source)
        self.assertEqual(result, reference)
        self.assertEqual(result[-1], 16777216.0)
        self.assertNotEqual(result[0], source[0])

    def test_04_zero_sign_and_small_fp32_values(self):
        """正负零、最小非正规数、最小正规数往返不丢失FP32表示。"""
        source = (0.0, -0.0, 2.0 ** -149, 2.0 ** -126)
        result = self.codec.decode(self.codec.encode(source, (1, 1, 4)))
        self.assertEqual(struct.pack("<4f", *result), struct.pack("<4f", *source))

    def test_05_repeatable_synthetic_roundtrips(self):
        """固定种子的多形状数据与独立FP32参考比较；不消耗全局随机状态。"""
        rng = random.Random(20261114)
        for sequence, hidden in ((1, 1), (1, 7), (7, 16), (128, 8)):
            shape = (1, sequence, hidden)
            source = tuple(rng.uniform(-100, 100) for _ in range(math.prod(shape)))
            reference = struct.unpack(f"<{len(source)}f", struct.pack(f"<{len(source)}f", *source))
            with self.subTest(shape=shape):
                first = self.codec.encode(source, shape)
                self.assertEqual(self.codec.decode(first), reference)
                self.assertEqual(self.codec.encode(source, shape), first)

    def test_06_reject_non_finite_and_overflow_input(self):
        """NaN、正负Inf、FP32溢出及布尔值不能编码为合法激活。"""
        for value in (math.nan, math.inf, -math.inf, 1e40, True):
            with self.subTest(value=value):
                self.assert_safe_error(ErrorCode.ACTIVATION_INVALID, self.codec.encode, [value], (1, 1, 1))

    def test_07_reject_invalid_shapes_before_reading_values(self):
        """越界batch/序列/维数/字节数必须在消费输入前拒绝。"""
        shapes = ((2, 1, 1), (1, 129, 1), (1, 0, 1), (1, 1, -1),
                  (True, 1, 1), (1, 1), (1, 1, 1, 1), (1, 1, MAX_RAW_BYTES // 4 + 1))
        for shape in shapes:
            with self.subTest(shape=shape):
                def forbidden_input():
                    self.fail("非法形状在读取输入之前未被拒绝")
                    yield 0.0

                self.assert_safe_error(ErrorCode.ACTIVATION_INVALID, self.codec.encode, forbidden_input(), shape)

    def test_08_accept_exact_raw_size_boundary_without_allocating_tensor(self):
        """8MiB恰好允许，多一个FP32元素拒绝；此用例只验证分配前规则。"""
        self.assertEqual(checked_raw_bytes((1, 128, 16384)), MAX_RAW_BYTES)
        self.assert_safe_error(ErrorCode.ACTIVATION_INVALID, checked_raw_bytes, (1, 128, 16385))

    def test_09_reject_element_count_mismatch_with_bounded_consumption(self):
        """元素不足或过多拒绝，过长迭代器最多读取期望元素数加一。"""
        self.assert_safe_error(ErrorCode.ACTIVATION_INVALID, self.codec.encode, (), (1, 1, 1))
        consumed = []

        def endless_values():
            while True:
                consumed.append(1)
                yield 1.0

        self.assert_safe_error(ErrorCode.ACTIVATION_INVALID, self.codec.encode, endless_values(), (1, 1, 2))
        self.assertEqual(len(consumed), 3)

    def test_10_reject_digest_shape_length_and_payload_tampering(self):
        """摘要、形状、声明长度或载荷任意不一致均不得进入后续计算。"""
        original = self.codec.encode([1.0, -2.0], (1, 1, 2))
        for update in ({"sha256": "0" * 64}, {"shape": (1, 1, 1)},
                       {"raw_bytes": 4}, {"data": "AACAPwAAAAA="}):
            with self.subTest(field=next(iter(update))):
                self.assert_safe_error(ErrorCode.ACTIVATION_INVALID, self.codec.decode,
                                       original.model_copy(update=update))

    def test_11_reject_noncanonical_base64(self):
        """非法字符、空白、额外padding以及非零pad bits均拒绝。"""
        original = self.codec.encode([1.0], (1, 1, 1))
        for payload in ("!ACAPw==", "AACAPw==\n", "AACAPw===", "AACAPx=="):
            with self.subTest(payload=payload):
                self.assert_safe_error(ErrorCode.ACTIVATION_INVALID, self.codec.decode,
                                       original.model_copy(update={"data": payload}))

    def test_12_reject_non_finite_wire_even_with_matching_digest(self):
        """攻击者重算了合法摘要，也不能让NaN/Inf载荷通过有限值检查。"""
        for bits in (0x7FC00000, 0x7F800000, 0xFF800000):
            raw = struct.pack("<I", bits)
            envelope = ActivationEnvelope(shape=(1, 1, 1), raw_bytes=4,
                sha256=hashlib.sha256(raw).hexdigest(), data=base64.b64encode(raw).decode("ascii"))
            with self.subTest(bits=bits):
                self.assert_safe_error(ErrorCode.ACTIVATION_INVALID, self.codec.decode, envelope)

    def test_13_reject_unknown_fields_types_and_protocol_versions(self):
        """线上JSON不接受自报owner、prompt、未知版本或字符串形式的长度。"""
        data = self.make_step().model_dump(mode="json")
        # 必须经过JSON解析；Python严格合同要求tuple，而JSON中的shape是数组。
        self.assertEqual(StepRequest.model_validate_json(json.dumps(data)), self.make_step())
        for update in ({"owner": "synthetic-owner"}, {"prompt": "合成原文"}, {"step": "0"}):
            with self.subTest(update=update):
                with self.assertRaises(ValidationError):
                    StepRequest.model_validate_json(json.dumps(data | update))
        envelope = self.codec.encode([1.0], (1, 1, 1)).model_dump()
        for update in ({"protocol_version": "safe-v999"}, {"dtype": "float16"},
                       {"raw_bytes": "4"}, {"shape": (True, 1, 1)}):
            with self.subTest(update=update):
                with self.assertRaises(ValidationError):
                    ActivationEnvelope.model_validate(envelope | update)

    def test_14_clipping_then_wire_roundtrip(self):
        """裁剪→编码→JSON→解码可串联；FP32舍入后使用数值容差。"""
        clipped = clip_global_l2((3.0, 4.0), 2.0)
        self.assertAlmostEqual(clipped[0], 1.2)
        self.assertAlmostEqual(clipped[1], 1.6)
        envelope = self.codec.encode(clipped, (1, 1, 2))
        restored = ActivationEnvelope.model_validate_json(envelope.model_dump_json())
        decoded = self.codec.decode(restored)
        self.assertAlmostEqual(math.hypot(*decoded), 2.0, places=6)
        # 这里只证明转换与数值裁剪；不能推出DP、机制校准或预算记账完成。

    def test_15_clipping_zero_large_values_and_invalid_bound(self):
        """零向量、大有限值与非法阈值均有明确结果，不让中间平方溢出。"""
        self.assertEqual(clip_global_l2((0.0, 0.0), 1.0), (0.0, 0.0))
        self.assertAlmostEqual(math.hypot(*clip_global_l2((1e308, 1e308), 1.0)), 1.0)
        for bound in (0.0, -1.0, math.inf, math.nan):
            with self.subTest(bound=bound):
                self.assert_safe_error(ErrorCode.ACTIVATION_INVALID, clip_global_l2, (1.0,), bound)

    def test_16_terminal_sessions_and_step_order(self):
        """基础状态与step检查；此处不宣称已存在KV、锁或TTL执行器。"""
        self.assertEqual(transition(SessionStatus.CREATED, SessionStatus.ACTIVE), SessionStatus.ACTIVE)
        for terminal in (SessionStatus.CLOSED, SessionStatus.FAILED, SessionStatus.EXPIRED):
            self.assert_safe_error(ErrorCode.SESSION_INVALID, transition, terminal, SessionStatus.ACTIVE)
        require_next_step(expected=0, received=0)
        for received in (-1, 1, True):
            self.assert_safe_error(ErrorCode.STEP_OUT_OF_ORDER, require_next_step, expected=0, received=received)

    def test_17_idempotency_identity_cannot_change(self):
        """owner/session/request/digest任一变化均冲突，不是完整幂等存储测试。"""
        key = ("owner", "session", "request", "a" * 64)
        require_same_request(key, key)
        for index in range(4):
            changed = list(key)
            changed[index] += "x"
            with self.subTest(index=index):
                self.assert_safe_error(ErrorCode.IDEMPOTENCY_CONFLICT, require_same_request, key, tuple(changed))

    def test_18_unimplemented_model_and_privacy_refuse_execution(self):
        """当前未实现的模型/隐私发布明确拒绝，拒绝不计作真实推理/DP通过。"""
        self.assert_safe_error(ErrorCode.MODEL_PARTITION_UNAVAILABLE,
                               SplitInferenceService().infer, InferenceRequest(prompt="合成输入"))
        self.assert_safe_error(ErrorCode.PRIVACY_UNAVAILABLE, PrivacyReleaseService().release)


if __name__ == "__main__":
    # Windows重定向输出时也统一UTF-8，避免中文测试说明在终端/日志中乱码。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    # unittest支持-v/-q及按测试方法过滤，失败或意外异常会自动返回非零退出码。
    unittest.main(verbosity=2)
