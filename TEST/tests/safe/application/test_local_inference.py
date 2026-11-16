"""本机生成用例：只向传输端口发送激活，模型数值由独立集成测试验证。"""

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from components.safe.application.inference import SplitInferenceService
from components.safe.contracts.errors import ErrorCode, SafeError
from components.safe.contracts.inference import GenerationOptions, InferenceRequest
from components.safe.contracts.manifest import SplitModelManifest
from components.safe.contracts.session import SessionStatus, SessionView, StepReceipt, StepRequest
from components.safe.domain.compatibility import manifest_digest
from components.safe.infrastructure.codecs.fp32 import FP32Codec
from components.safe.ports.model_runner import KVHandle


class Tokenizer:
    vocab_size = 4
    eos_token_ids = frozenset({3})

    def __init__(self, manifest):
        self.manifest = manifest
        self.ids = (0, 2, 1)
        self.decoded = None

    def encode_prompt(self, prompt):
        assert prompt == "只留本机的原始文本"
        return self.ids

    def decode(self, tokens):
        self.decoded = tokens
        return "".join({0: "零", 1: "甲", 2: "乙", 3: ""}[t] for t in tokens)


class Prefix:
    def __init__(self, manifest):
        self.manifest = manifest
        self.calls, self.released = [], []
        self.entered = self.resume = None
        self.after_prefill = None
        self.broken = False

    def create_kv(self, session_id):
        self.calls.append(("create", session_id))
        return KVHandle("local-kv")

    def prefill(self, tokens, *, kv_handle, session_id):
        self.calls.append(("prefill", tokens, kv_handle, session_id))
        if self.entered is not None:
            self.entered.set()
            assert self.resume.wait(timeout=5)
        if self.broken:
            raise RuntimeError("合成前段故障")
        if self.after_prefill:
            self.after_prefill()
        return (1.0,) * (len(tokens) * 4), (1, len(tokens), 4)

    def decode(self, handle, session_id, token):
        self.calls.append(("decode", token, handle, session_id))
        return (1.0,) * 4, (1, 1, 4)

    def release_kv(self, handle):
        self.released.append(handle)


class Transport:
    """模拟响应丢失；query只返回已提交回执，不以None证明尚未执行。"""
    def __init__(self, digest):
        self.digest = digest
        self.created, self.requests, self.events, self.closed = [], [], [], []
        self.receipts = {}
        self.tokens = [1, 2, 3]
        self.failure = None
        self.change = {}
        self.after_step = None
        self.close_fails = False

    def create_session(self, digest):
        self.created.append(digest)
        return SessionView(session_id="session-local", manifest_digest=self.digest,
                           status=SessionStatus.CREATED, next_step=0)

    def step(self, request):
        self.events.append("step")
        request = StepRequest.model_validate_json(request.model_dump_json())
        self.requests.append(request)
        if self.failure == "unknown":
            raise TimeoutError()
        token = self.tokens[request.step % len(self.tokens)]
        receipt = StepReceipt(request_id=request.request_id, session_id=request.session_id,
            step=request.step, token_id=token, finished=token == 3)
        self.receipts[request.request_id] = receipt
        if self.failure == "lost":
            raise TimeoutError()
        if self.after_step:
            self.after_step()
        return receipt.model_copy(update=self.change)

    def query(self, session_id, request_id):
        self.events.append("query")
        return self.receipts.get(request_id)

    def close_session(self, session_id):
        self.closed.append(session_id)
        if self.close_fails:
            raise ConnectionError()


def setup():
    manifest = SplitModelManifest(model_id="synthetic/qwen", revision="a" * 40,
        config_digest="b" * 64, tokenizer_digest="c" * 64, template_digest="d" * 64,
        prefix_digest="e" * 64, suffix_digest="f" * 64, total_layers=4,
        cut_layer=2, hidden_size=4, license_id="Apache-2.0")
    digest = manifest_digest(manifest)
    prefix, tokenizer, transport = Prefix(manifest), Tokenizer(manifest), Transport(digest)
    service = SplitInferenceService(prefix=prefix, tokenizer=tokenizer, transport=transport,
        codec=FP32Codec(), manifest=manifest, approved_digest=digest)
    return service, prefix, tokenizer, transport


def request(limit=32):
    return InferenceRequest(prompt="只留本机的原始文本", generation=GenerationOptions(max_new_tokens=limit))


def test_eos_generation_sends_only_activation_and_releases_both_roles():
    service, prefix, tokenizer, transport = setup()
    result = service.infer(request())
    assert (result.text, result.generated_tokens, result.finish_reason) == ("甲乙", 3, "eos")
    assert tokenizer.decoded == (1, 2, 3)
    assert [v.position_offset for v in transport.requests] == [0, 3, 4]
    assert [v.activation.shape for v in transport.requests] == [(1, 3, 4), (1, 1, 4), (1, 1, 4)]
    assert len({v.request_id for v in transport.requests}) == 3
    assert all("只留本机" not in v.model_dump_json() and "prompt" not in v.model_dump() for v in transport.requests)
    assert [v[1] for v in prefix.calls if v[0] == "decode"] == [1, 2]
    assert prefix.released == [KVHandle("local-kv")]
    assert transport.closed == ["session-local"]


def test_local_output_limit_closes_remote_even_when_cloud_has_not_finished():
    service, prefix, _, transport = setup()
    result = service.infer(request(2))
    assert (result.text, result.generated_tokens, result.finish_reason) == ("甲乙", 2, "length")
    assert len(transport.requests) == 2
    assert transport.closed == ["session-local"]
    assert len(prefix.released) == 1


@pytest.mark.parametrize("length", [0, 129])
def test_prompt_token_limit_is_checked_before_session_creation(length):
    service, prefix, tokenizer, transport = setup()
    tokenizer.ids = (1,) * length
    with pytest.raises(SafeError, match="INFERENCE_INVALID"):
        service.infer(request())
    assert transport.created == prefix.calls == []


def test_exact_128_prompt_tokens_are_allowed():
    service, _, tokenizer, transport = setup()
    tokenizer.ids = (1,) * 128
    assert service.infer(request(1)).generated_tokens == 1
    assert transport.requests[0].activation.shape == (1, 128, 4)


def test_copied_invalid_generation_options_are_revalidated():
    service, prefix, _, transport = setup()
    bad = request().model_copy(update={"generation": GenerationOptions().model_copy(update={"max_new_tokens": 33})})
    with pytest.raises(SafeError, match="INFERENCE_INVALID"):
        service.infer(bad)
    assert transport.created == prefix.calls == []


def test_lost_response_is_queried_without_reexecuting_step_or_prefix():
    service, prefix, _, transport = setup()
    transport.failure = "lost"
    assert service.infer(request()).finish_reason == "eos"
    assert transport.events == ["step", "query"] * 3
    assert len(transport.requests) == 3
    assert len([v for v in prefix.calls if v[0] == "decode"]) == 2


def test_unknown_timeout_result_fails_without_blind_resend():
    service, prefix, _, transport = setup()
    transport.failure = "unknown"
    with pytest.raises(SafeError, match="TRANSPORT_UNAVAILABLE"):
        service.infer(request())
    assert transport.events == ["step", "query"]
    assert len(transport.requests) == 1
    assert transport.closed == ["session-local"]
    assert prefix.released == [KVHandle("local-kv")]


@pytest.mark.parametrize("change", [{"request_id": "other"}, {"session_id": "other"},
    {"step": 1}, {"token_id": 4}, {"token_id": True}, {"finished": True}])
def test_receipt_must_match_request_and_expected_generation(change):
    service, prefix, _, transport = setup()
    transport.change = change
    with pytest.raises(SafeError, match="MODEL_OUTPUT_INVALID"):
        service.infer(request())
    assert not [v for v in prefix.calls if v[0] == "decode"]
    assert prefix.released == [KVHandle("local-kv")]
    assert transport.closed == ["session-local"]


def test_prefix_failure_still_closes_remote_and_releases_local():
    service, prefix, _, transport = setup()
    prefix.broken = True
    with pytest.raises(RuntimeError, match="合成前段故障"):
        service.infer(request())
    assert transport.requests == []
    assert transport.closed == ["session-local"]
    assert len(prefix.released) == 1


def test_cancellation_before_start_creates_no_resources():
    service, prefix, _, transport = setup()
    result = service.infer(request(), cancelled=lambda: True)
    assert (result.text, result.generated_tokens, result.finish_reason) == ("", 0, "cancelled")
    assert transport.created == prefix.calls == []


def test_cancellation_after_prefill_sends_no_activation():
    service, prefix, _, transport = setup()
    cancelled = threading.Event()
    prefix.after_prefill = cancelled.set
    result = service.infer(request(), cancelled=cancelled.is_set)
    assert result.finish_reason == "cancelled"
    assert result.generated_tokens == 0
    assert transport.requests == []
    assert len(prefix.released) == len(transport.closed) == 1


def test_cancellation_after_receipt_preserves_partial_local_text():
    service, prefix, _, transport = setup()
    cancelled = threading.Event()
    transport.after_step = cancelled.set
    result = service.infer(request(), cancelled=cancelled.is_set)
    assert (result.text, result.generated_tokens, result.finish_reason) == ("甲", 1, "cancelled")
    assert len(prefix.released) == len(transport.closed) == 1


def test_remote_cleanup_failure_does_not_skip_local_release_or_mask_primary_error():
    service, prefix, _, transport = setup()
    prefix.broken = transport.close_fails = True
    with pytest.raises(RuntimeError, match="合成前段故障"):
        service.infer(request())
    assert len(prefix.released) == 1


def test_second_inference_cannot_share_active_local_runner():
    service, prefix, _, _ = setup()
    prefix.entered, prefix.resume = threading.Event(), threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(service.infer, request(1))
        try:
            assert prefix.entered.wait(timeout=5)
            with pytest.raises(SafeError, match="SESSION_INVALID"):
                service.infer(request(1))
        finally:
            prefix.resume.set()
        assert first.result(timeout=5).generated_tokens == 1
