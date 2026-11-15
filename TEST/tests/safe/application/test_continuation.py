"""后段用例闭环：真实codec/会话存储/采样，模型端口使用合成执行器。"""

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from safe.application import continuation
from safe.application.activation import ActivationService
from safe.application.manifest import ManifestService
from safe.application.session import SessionService
from safe.contracts.errors import ErrorCode, SafeError
from safe.contracts.manifest import SplitModelManifest
from safe.contracts.session import ActivationContext, SessionStatus, StepRequest
from safe.infrastructure.codecs.fp32 import FP32Codec
from safe.infrastructure.models.sampling import GreedySampler
from safe.infrastructure.storage.memory_sessions import MemorySessionStore
from safe.ports.model_runner import KVHandle


def manifest():
    return SplitModelManifest(model_id="synthetic/qwen", revision="a" * 40,
        config_digest="b" * 64, tokenizer_digest="c" * 64, template_digest="d" * 64,
        prefix_digest="e" * 64, suffix_digest="f" * 64, total_layers=4,
        cut_layer=2, hidden_size=4, license_id="Apache-2.0")


class FakeSuffix:
    """只接收激活的后段端口；记录实际调用，明确不冒充数值模型。"""
    def __init__(self, approved):
        self.manifest = approved
        self.calls = []
        self.released = []
        self.handles = {}
        self.logits = (0.0, 2.0, 1.0, -1.0)
        self.entered = self.resume = None

    def create_kv(self, session_id):
        handle = KVHandle(f"kv-{session_id}")
        self.handles[handle] = session_id
        return handle

    def release_kv(self, handle):
        self.handles.pop(handle, None)
        self.released.append(handle)

    def _forward(self, phase, activation, shape, handle, session_id):
        assert self.handles[handle] == session_id
        assert len(activation) == shape[1] * self.manifest.hidden_size
        self.calls.append((phase, shape, handle, session_id))
        if self.entered is not None:
            self.entered.set()
            assert self.resume.wait(timeout=5), "测试执行器等待超时"
        return self.logits

    def prefill(self, activation, shape, *, kv_handle, session_id):
        return self._forward("prefill", activation, shape, kv_handle, session_id)

    def decode(self, kv_handle, session_id, activation, shape):
        return self._forward("decode", activation, shape, kv_handle, session_id)

    def close(self):
        self.handles.clear()


def setup_service(*, max_new_tokens=32, eos=frozenset(), with_kv=True):
    approved = manifest()
    digest = ManifestService.digest(approved)
    runner = FakeSuffix(approved)
    store = MemorySessionStore(runner=runner if with_kv else None)
    sessions = SessionService(store)
    service = continuation.ContinuationService(sessions=sessions, runner=runner,
        codec=FP32Codec(), sampler=GreedySampler(vocab_size=4, eos_token_ids=eos),
        manifest=approved, approved_digest=digest, max_new_tokens=max_new_tokens)
    activation = ActivationService(codec=FP32Codec(), manifest=approved, approved_digest=digest)
    return service, sessions, store, runner, activation, digest


def step_request(activation, digest, *, step=0, position=0, length=3, session_id="session-1"):
    context = ActivationContext(session_id=session_id, manifest_digest=digest, next_step=step,
        phase="prefill" if step == 0 else "decode", position_offset=position)
    value = activation.encode((1.0,) * (length * 4), (1, length, 4), context=context,
        request_id=f"request-{step}")
    # 真正经过JSON/UTF-8往返；用例层不收prompt或token IDs。
    return StepRequest.model_validate_json(value.model_dump_json().encode("utf-8"))


def test_prefill_decode_commit_and_retries_share_one_owned_kv():
    service, sessions, _, runner, activation, digest = setup_service(max_new_tokens=2)
    service.create("owner-1", session_id="session-1")
    first = step_request(activation, digest)
    receipt = service.step("owner-1", first)
    assert (receipt.token_id, receipt.finished) == (1, False)
    assert service.step("owner-1", first) == receipt
    second = step_request(activation, digest, step=1, position=3, length=1)
    last = service.step("owner-1", second)
    assert last.finished is True
    assert [call[0] for call in runner.calls] == ["prefill", "decode"]
    assert {call[2] for call in runner.calls} == {KVHandle("kv-session-1")}
    assert sessions.view("owner-1", "session-1").status is SessionStatus.CLOSED
    assert runner.released == [KVHandle("kv-session-1")]
    assert service.step("owner-1", second) == last
    assert sessions.receipt("owner-1", "session-1", "request-0") == receipt


def test_eos_ends_first_step_and_prevents_new_forward():
    service, sessions, _, runner, activation, digest = setup_service(eos=frozenset({3}))
    runner.logits = (0.0, 1.0, 2.0, 3.0)
    service.create("owner-1", session_id="session-1")
    first = step_request(activation, digest)
    receipt = service.step("owner-1", first)
    assert (receipt.token_id, receipt.finished) == (3, True)
    assert service.step("owner-1", first) == receipt
    with pytest.raises(SafeError, match="SESSION_INVALID"):
        service.step("owner-1", step_request(activation, digest, step=1, position=3, length=1))
    assert len(runner.calls) == 1
    assert sessions.view("owner-1", "session-1").status is SessionStatus.CLOSED


def test_full_32_steps_close_session_without_eos():
    service, sessions, _, runner, activation, digest = setup_service()
    service.create("owner-1", session_id="session-1")
    for step in range(32):
        value = step_request(activation, digest, step=step,
            position=0 if step == 0 else step + 2, length=3 if step == 0 else 1)
        assert service.step("owner-1", value).finished is (step == 31)
    assert len(runner.calls) == 32
    assert sessions.view("owner-1", "session-1").next_step == 32
    assert runner.released == [KVHandle("kv-session-1")]


@pytest.mark.parametrize("update,code", [({"step": 1}, ErrorCode.STEP_OUT_OF_ORDER),
    ({"phase": "decode"}, ErrorCode.STEP_OUT_OF_ORDER),
    ({"position_offset": 1}, ErrorCode.STEP_OUT_OF_ORDER),
    ({"manifest_digest": "0" * 64}, ErrorCode.MANIFEST_INCOMPATIBLE)])
def test_untrusted_step_metadata_is_rejected_before_model(update, code):
    service, sessions, _, runner, activation, digest = setup_service()
    service.create("owner-1", session_id="session-1")
    with pytest.raises(SafeError) as error:
        service.step("owner-1", step_request(activation, digest).model_copy(update=update))
    assert error.value.code is code
    assert runner.calls == []
    assert sessions.view("owner-1", "session-1").next_step == 0


def test_owner_is_checked_before_processing_activation():
    service, _, _, runner, activation, digest = setup_service()
    service.create("owner-1", session_id="session-1")
    with pytest.raises(SafeError, match="SESSION_INVALID"):
        service.step("owner-2", step_request(activation, digest))
    assert runner.calls == []


def test_corrupt_activation_fails_session_before_suffix_forward():
    service, sessions, _, runner, activation, digest = setup_service()
    service.create("owner-1", session_id="session-1")
    first = step_request(activation, digest)
    bad = first.model_copy(update={"activation": first.activation.model_copy(update={"sha256": "0" * 64})})
    with pytest.raises(SafeError, match="ACTIVATION_INVALID"):
        service.step("owner-1", bad)
    assert runner.calls == []
    assert sessions.view("owner-1", "session-1").status is SessionStatus.FAILED
    assert runner.released == [KVHandle("kv-session-1")]


def test_sampler_failure_after_forward_cleans_kv_without_committing_receipt():
    service, sessions, _, runner, activation, digest = setup_service()
    runner.logits = (float("nan"), 1.0, 2.0, 3.0)
    service.create("owner-1", session_id="session-1")
    with pytest.raises(SafeError, match="MODEL_OUTPUT_INVALID"):
        service.step("owner-1", step_request(activation, digest))
    assert len(runner.calls) == 1
    assert sessions.receipt("owner-1", "session-1", "request-0") is None
    assert sessions.view("owner-1", "session-1").status is SessionStatus.FAILED
    assert runner.released == [KVHandle("kv-session-1")]


def test_missing_owned_kv_refuses_execution():
    service, sessions, _, runner, activation, digest = setup_service(with_kv=False)
    service.create("owner-1", session_id="session-1")
    with pytest.raises(SafeError, match="MODEL_PARTITION_UNAVAILABLE"):
        service.step("owner-1", step_request(activation, digest))
    assert runner.calls == []
    assert sessions.view("owner-1", "session-1").status is SessionStatus.FAILED


def test_concurrent_same_request_advances_suffix_once():
    service, _, _, runner, activation, digest = setup_service()
    runner.entered, runner.resume = threading.Event(), threading.Event()
    service.create("owner-1", session_id="session-1")
    first = step_request(activation, digest)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(service.step, "owner-1", first)
        try:
            assert runner.entered.wait(timeout=5)
            two = pool.submit(service.step, "owner-1", first)
        finally:
            runner.resume.set()
        assert one.result(timeout=5) == two.result(timeout=5)
    assert len(runner.calls) == 1


@pytest.mark.parametrize("limit", [0, 33, True])
def test_invalid_generation_limit_is_refused(limit):
    with pytest.raises(ValueError):
        setup_service(max_new_tokens=limit)


def test_runner_with_other_manifest_is_rejected_at_construction():
    approved = manifest()
    runner = FakeSuffix(approved.model_copy(update={"revision": "0" * 40}))
    with pytest.raises(SafeError, match="MANIFEST_INCOMPATIBLE"):
        continuation.ContinuationService(sessions=SessionService(MemorySessionStore(runner=runner)),
            runner=runner, codec=FP32Codec(), sampler=GreedySampler(vocab_size=4),
            manifest=approved, approved_digest=ManifestService.digest(approved))


def test_commit_failure_after_sampling_never_reexecutes_suffix():
    class BrokenReceipts(dict):
        def __setitem__(self, key, value):
            raise MemoryError("synthetic commit failure")

    service, sessions, store, runner, activation, digest = setup_service()
    service.create("owner-1", session_id="session-1")
    store._sessions["session-1"].receipts = BrokenReceipts()
    first = step_request(activation, digest)
    with pytest.raises(MemoryError):
        service.step("owner-1", first)
    assert sessions.view("owner-1", "session-1").status is SessionStatus.FAILED
    assert sessions.receipt("owner-1", "session-1", "request-0") is None
    with pytest.raises(SafeError, match="SESSION_INVALID"):
        service.step("owner-1", first)
    assert len(runner.calls) == 1
    assert runner.released == [KVHandle("kv-session-1")]


def test_inprocess_transport_uses_one_runner_and_json_receipts():
    from safe.bootstrap import cloud

    approved = manifest()
    digest = ManifestService.digest(approved)
    runner = FakeSuffix(approved)
    transport = cloud.InProcessTransport(runner=runner, codec=FP32Codec(),
        sampler=GreedySampler(vocab_size=4), manifest=approved,
        approved_digest=digest, owner_id="research-owner")
    session = transport.create_session(digest)
    activation = ActivationService(codec=FP32Codec(), manifest=approved, approved_digest=digest)
    first = step_request(activation, digest, session_id=session.session_id)
    receipt = transport.step(first)
    assert transport.step(first) == receipt
    assert transport.query(session.session_id, first.request_id) == receipt
    assert len(runner.calls) == 1
    assert transport.close_session(session.session_id).status is SessionStatus.CLOSED
    assert transport.close_session(session.session_id).status is SessionStatus.CLOSED
    transport.close()
    assert len(runner.released) == 1
    with pytest.raises(SafeError, match="TRANSPORT_UNAVAILABLE"):
        transport.create_session(digest)


def test_inprocess_transport_rejects_other_manifest_before_creating_kv():
    from safe.bootstrap import cloud

    approved = manifest()
    runner = FakeSuffix(approved)
    transport = cloud.InProcessTransport(runner=runner, codec=FP32Codec(),
        sampler=GreedySampler(vocab_size=4), manifest=approved,
        approved_digest=ManifestService.digest(approved), owner_id="research-owner")
    with pytest.raises(SafeError, match="MANIFEST_INCOMPATIBLE"):
        transport.create_session("0" * 64)
    assert runner.handles == {}
