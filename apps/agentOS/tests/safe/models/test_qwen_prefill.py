"""小型随机Qwen2核验适配语义；不下载模型，不作为真实模型质量验收。"""

import json

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("safetensors")

from transformers import Qwen2Config, Qwen2ForCausalLM
from safetensors.torch import save_file

from safe.contracts.errors import SafeError
from safe.infrastructure.artifacts.export import export_qwen_artifacts
from safe.infrastructure.artifacts.local_store import LocalArtifactStore
from safe.infrastructure.models.qwen import QwenPrefixRunner, QwenSuffixRunner
from safe.contracts.errors import ErrorCode


@pytest.fixture
def exported(tmp_path):
    torch.manual_seed(1234)
    config = Qwen2Config(vocab_size=32, hidden_size=16, intermediate_size=32,
        num_hidden_layers=4, num_attention_heads=4, num_key_value_heads=2,
        tie_word_embeddings=True, max_position_embeddings=256)
    config._attn_implementation = "eager"
    model = Qwen2ForCausalLM(config).float().eval()
    source = tmp_path / "source"
    source.mkdir()
    # 与真实Qwen发布格式一致：tied lm_head不重复保存在源权重中。
    save_file({k: v.detach().clone() for k, v in model.state_dict().items()
               if k != "lm_head.weight"}, str(source / "model.safetensors"))
    (source / "config.json").write_text(config.to_json_string(), encoding="utf-8")
    (source / "LICENSE").write_text("synthetic Apache-2.0 fixture", encoding="utf-8")
    (source / "tokenizer.json").write_text("{}", encoding="utf-8")
    (source / "tokenizer_config.json").write_text(json.dumps({"chat_template": "{{ messages }}"}), encoding="utf-8")
    target = tmp_path / "roles"
    result = export_qwen_artifacts(source, target, model_id="synthetic/qwen2",
                                   revision="a" * 40, cut_layer=2, license_id="Apache-2.0")
    return model, source, target, result


def test_roles_load_only_their_own_weights_and_match_full_logits(exported):
    oracle, source, root, digest = exported
    prefix_dir = root / "prefix"
    suffix_dir = root / "suffix"
    # 模拟两机独立角色：每个runner只拿本角色目录，不能通过另一角色文件补全。
    prefix = QwenPrefixRunner(prefix_dir, approved_digest=digest)
    suffix = QwenSuffixRunner(suffix_dir, approved_digest=digest)
    for ids in ((1,), (1, 2, 3, 4), (7, 8, 9)):
        flat, shape = prefix.prefill(ids)
        logits = suffix.prefill(flat, shape)
        with torch.inference_mode():
            expected = oracle(torch.tensor([ids]), use_cache=False).logits[0, -1]
        torch.testing.assert_close(torch.tensor(logits), expected, atol=1e-5, rtol=1e-4)
    assert not any("lm_head" in name or name.startswith("layers.2.") for name in prefix.parameter_names)
    assert not any("embed_tokens" in name or name.startswith("layers.0.") for name in suffix.parameter_names)
    prefix.close()
    suffix.close()
    with pytest.raises(SafeError):
        prefix.prefill((1,))


def test_artifact_tampering_and_wrong_role_are_rejected(exported):
    _, _, root, digest = exported
    with pytest.raises(SafeError):
        QwenPrefixRunner(root / "suffix", approved_digest=digest)
    with pytest.raises(SafeError):
        LocalArtifactStore(root / "prefix").verified_manifest("0" * 64)
    config = root / "prefix/config.json"
    config.write_bytes(config.read_bytes() + b" ")
    with pytest.raises(SafeError):
        QwenPrefixRunner(root / "prefix", approved_digest=digest)


def test_export_refuses_existing_destination_and_invalid_cut(exported, tmp_path):
    _, source, target, _ = exported
    with pytest.raises(SafeError):
        export_qwen_artifacts(source, target, model_id="synthetic/qwen2", revision="a" * 40,
                              cut_layer=2, license_id="Apache-2.0")
    with pytest.raises(SafeError):
        export_qwen_artifacts(source, tmp_path / "bad", model_id="synthetic/qwen2", revision="a" * 40,
                              cut_layer=4, license_id="Apache-2.0")
    assert not (tmp_path / "bad").exists()


def test_runner_rejects_invalid_tokens_shapes_and_values(exported):
    _, _, root, digest = exported
    prefix = QwenPrefixRunner(root / "prefix", approved_digest=digest)
    suffix = QwenSuffixRunner(root / "suffix", approved_digest=digest)
    for ids in ((), (True,), (-1,), (32,), (1,) * 129):
        with pytest.raises(SafeError):
            prefix.prefill(ids)
    for values, shape in (((1.0,) * 16, (1, 1, 32)), ((float("nan"),) * 16, (1, 1, 16)),
                          ((1.0,), (1, 1, 16))):
        with pytest.raises(SafeError):
            suffix.prefill(values, shape)


@pytest.mark.parametrize("corruption", ["missing", "extra", "shape", "nonfinite"])
def test_export_missing_layer_parameter_does_not_publish(exported, tmp_path, corruption):
    from safetensors.torch import load_file

    _, source, _, _ = exported
    weights = source / "model.safetensors"
    state = {k: v.clone() for k, v in load_file(str(weights)).items()}
    if corruption == "missing":
        del state["model.layers.1.mlp.up_proj.weight"]
    elif corruption == "extra":
        state["model.layers.1.bad.weight"] = torch.zeros(1)
    elif corruption == "shape":
        state["model.norm.weight"] = torch.zeros(3)
    else:
        state["model.norm.weight"][0] = float("nan")
    save_file(state, str(weights))
    target = tmp_path / "incomplete"
    with pytest.raises(SafeError):
        export_qwen_artifacts(source, target, model_id="synthetic/qwen2", revision="a" * 40,
                              cut_layer=2, license_id="Apache-2.0")
    assert not target.exists()


def test_export_rejects_conflicting_tied_head(exported, tmp_path):
    from safetensors.torch import load_file

    _, source, _, _ = exported
    weights = source / "model.safetensors"
    state = {k: v.clone() for k, v in load_file(str(weights)).items()}
    state["lm_head.weight"] = torch.zeros_like(state["model.embed_tokens.weight"])
    save_file(state, str(weights))
    target = tmp_path / "conflict"
    with pytest.raises(SafeError):
        export_qwen_artifacts(source, target, model_id="synthetic/qwen2", revision="a" * 40,
                              cut_layer=2, license_id="Apache-2.0")
    assert not target.exists()


def test_kv_decode_matches_full_model_and_released_handles_cannot_decode(exported):
    """prefix/suffix 各自只保留本角色 KV，逐 token 续算应与完整模型对齐。"""
    oracle, _, root, digest = exported
    prefix = QwenPrefixRunner(root / "prefix", approved_digest=digest)
    suffix = QwenSuffixRunner(root / "suffix", approved_digest=digest)
    prefix_handle = prefix.create_kv("session-1")
    suffix_handle = suffix.create_kv("session-1")
    ids = [1, 2, 3, 4]

    def expected(current):
        with torch.inference_mode():
            return oracle(torch.tensor([current]), use_cache=False).logits[0, -1]

    hidden, shape = prefix.prefill(tuple(ids), kv_handle=prefix_handle, session_id="session-1")
    logits = suffix.prefill(hidden, shape, kv_handle=suffix_handle, session_id="session-1")
    torch.testing.assert_close(torch.tensor(logits), expected(ids), atol=1e-5, rtol=1e-4)
    for token_id in (5, 6, 7):
        ids.append(token_id)
        hidden, shape = prefix.decode(prefix_handle, "session-1", token_id)
        logits = suffix.decode(suffix_handle, "session-1", hidden, shape)
        torch.testing.assert_close(torch.tensor(logits), expected(ids), atol=1e-5, rtol=1e-4)

    prefix.release_kv(prefix_handle)
    suffix.release_kv(suffix_handle)
    # release 要求幂等，但已释放句柄不能再次执行或创建隐藏状态。
    prefix.release_kv(prefix_handle)
    suffix.release_kv(suffix_handle)
    with pytest.raises(SafeError) as error:
        prefix.decode(prefix_handle, "session-1", 8)
    assert error.value.code is ErrorCode.MODEL_PARTITION_UNAVAILABLE


def test_kv_handle_is_bound_to_session_and_prefill_cannot_restart(exported):
    _, _, root, digest = exported
    prefix = QwenPrefixRunner(root / "prefix", approved_digest=digest)
    suffix = QwenSuffixRunner(root / "suffix", approved_digest=digest)
    prefix_handle = prefix.create_kv("session-a")
    suffix_handle = suffix.create_kv("session-a")
    hidden, shape = prefix.prefill((1, 2), kv_handle=prefix_handle, session_id="session-a")
    suffix.prefill(hidden, shape, kv_handle=suffix_handle, session_id="session-a")
    with pytest.raises(SafeError) as error:
        prefix.prefill((3,), kv_handle=prefix_handle, session_id="session-b")
    assert error.value.code is ErrorCode.MODEL_PARTITION_UNAVAILABLE
    with pytest.raises(SafeError) as error:
        prefix.prefill((3,), kv_handle=prefix_handle, session_id="session-a")
    assert error.value.code is ErrorCode.STEP_OUT_OF_ORDER


def test_close_releases_all_kv_handles_and_rejects_new_sessions(exported):
    _, _, root, digest = exported
    prefix = QwenPrefixRunner(root / "prefix", approved_digest=digest)
    first = prefix.create_kv("session-a")
    prefix.create_kv("session-b")
    prefix.close()
    prefix.release_kv(first)
    with pytest.raises(SafeError) as error:
        prefix.create_kv("session-c")
    assert error.value.code is ErrorCode.MODEL_PARTITION_UNAVAILABLE


@pytest.mark.parametrize("role", ["prefix", "suffix"])
@pytest.mark.parametrize("failure", ["exception", "nonfinite"])
@pytest.mark.parametrize("phase", ["prefill", "decode"])
def test_partial_forward_failure_invalidates_only_affected_cache(exported, monkeypatch, role, failure, phase):
    """实际更新合成模型KV后再注入异常/NaN，失败句柄必须失效且不影响其他会话。"""
    from safe.infrastructure.models import qwen

    _, _, root, digest = exported
    prefix = QwenPrefixRunner(root / "prefix", approved_digest=digest)
    runner = prefix if role == "prefix" else QwenSuffixRunner(root / "suffix", approved_digest=digest)
    handle = runner.create_kv("session-a")
    other_handle = runner.create_kv("session-b")
    flat, shape = prefix.prefill((1, 2))
    if phase == "decode":
        if role == "prefix":
            runner.prefill((1, 2), kv_handle=handle, session_id="session-a")
        else:
            runner.prefill(flat, shape, kv_handle=handle, session_id="session-a")

    original_layers = qwen._layers

    def broken_layers(*args, **kwargs):
        hidden = original_layers(*args, **kwargs)
        if failure == "exception":
            raise RuntimeError("synthetic partial forward failure")
        return torch.full_like(hidden, float("nan"))

    with monkeypatch.context() as patch:
        patch.setattr(qwen, "_layers", broken_layers)
        with pytest.raises((RuntimeError, SafeError)):
            if phase == "prefill":
                if role == "prefix":
                    runner.prefill((1, 2), kv_handle=handle, session_id="session-a")
                else:
                    runner.prefill(flat, shape, kv_handle=handle, session_id="session-a")
            elif role == "prefix":
                runner.decode(handle, "session-a", 3)
            else:
                runner.decode(handle, "session-a", (0.0,) * 16, (1, 1, 16))

    with pytest.raises(SafeError) as error:
        if role == "prefix":
            runner.decode(handle, "session-a", 3)
        else:
            runner.decode(handle, "session-a", (0.0,) * 16, (1, 1, 16))
    assert error.value.code is ErrorCode.MODEL_PARTITION_UNAVAILABLE
    if role == "prefix":
        runner.prefill((3, 4), kv_handle=other_handle, session_id="session-b")
    else:
        runner.prefill(flat, shape, kv_handle=other_handle, session_id="session-b")
    runner.close()
    prefix.close()


def test_session_continuation_roundtrip_matches_real_qwen_layers(exported):
    """合成权重使用真实Qwen层，贯通JSON激活、会话KV和greedy回执。"""
    from safe.application.activation import ActivationService
    from safe.application.continuation import ContinuationService
    from safe.application.session import SessionService
    from safe.contracts.session import ActivationContext, SessionStatus, StepRequest
    from safe.infrastructure.codecs.fp32 import FP32Codec
    from safe.infrastructure.models.sampling import GreedySampler
    from safe.infrastructure.storage.memory_sessions import MemorySessionStore

    oracle, _, root, digest = exported
    prefix = QwenPrefixRunner(root / "prefix", approved_digest=digest)
    suffix = QwenSuffixRunner(root / "suffix", approved_digest=digest)
    store = MemorySessionStore(runner=suffix)
    sessions = SessionService(store)
    cloud = ContinuationService(sessions=sessions, runner=suffix, codec=FP32Codec(),
        sampler=GreedySampler(vocab_size=32), manifest=suffix.manifest,
        approved_digest=digest, max_new_tokens=4)
    activation = ActivationService(codec=FP32Codec(), manifest=prefix.manifest, approved_digest=digest)
    session_id = cloud.create("owner-1").session_id
    prefix_handle = prefix.create_kv(session_id)
    ids = [1, 2, 3]
    prompt_length = len(ids)
    try:
        flat, shape = prefix.prefill(tuple(ids), kv_handle=prefix_handle, session_id=session_id)
        for step in range(4):
            context = ActivationContext(session_id=session_id, manifest_digest=digest,
                next_step=step, phase="prefill" if step == 0 else "decode",
                position_offset=0 if step == 0 else prompt_length + step - 1)
            request = activation.encode(flat, shape, context=context, request_id=f"request-{step}")
            request = StepRequest.model_validate_json(request.model_dump_json().encode("utf-8"))
            receipt = cloud.step("owner-1", request)
            with torch.inference_mode():
                expected = oracle(torch.tensor([ids]), use_cache=False).logits[0, -1]
            assert receipt.token_id == int(expected.argmax())
            assert cloud.step("owner-1", request) == receipt
            assert sessions.view("owner-1", session_id).next_step == step + 1
            assert receipt.finished is (step == 3)
            ids.append(receipt.token_id)
            if not receipt.finished:
                flat, shape = prefix.decode(prefix_handle, session_id, receipt.token_id)
        assert sessions.view("owner-1", session_id).status is SessionStatus.CLOSED
        assert store._sessions[session_id].kv_released is True
    finally:
        prefix.release_kv(prefix_handle)
        prefix.close()
        suffix.close()
