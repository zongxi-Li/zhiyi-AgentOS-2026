"""显式核验Qwen2双角色KV续算；可启用会话/JSON/回执闭环，不下载模型。"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import platform
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

PROMPTS = (
    "你好，请用一句话介绍你自己。", "一加一等于多少？", "请把hello翻译成中文。",
    "请列出三种常见水果。", "什么是机器学习？用一句话回答。", "请写一句关于春天的短句。",
    "北京是哪个国家的首都？", "请把数字三写成阿拉伯数字。", "水在标准大气压下多少度沸腾？",
    "请用一句话解释保护隐私的重要性。", "Say hello in one short sentence.",
    "What is two plus three?", "Name three primary colors.", "Translate cat into Chinese.",
    "Complete this sequence: 1, 2, 3,", "Explain a neural network in one sentence.",
    "Write a short sentence about the moon.", "What is the capital of France?",
    "Return the opposite of hot.", "Give one example of a renewable energy source.",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Qwen2双角色KV逐token数值对照")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--manifest-digest", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--steps", type=int, default=32)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--continuation", action="store_true",
                        help="经过JSON激活、会话事务和greedy/EOS回执，最长steps步")
    args = parser.parse_args()
    if not 1 <= args.samples <= len(PROMPTS) or not 1 <= args.steps <= 32:
        parser.error("samples须为1–20，steps须为1–32")
    if not 1 <= args.threads <= 32:
        parser.error("threads须位于1–32")
    if args.report.exists():
        parser.error("报告已存在；请使用新文件名保留历史证据")

    import torch
    import transformers
    import safetensors
    import psutil
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from transformers.cache_utils import DynamicCache
    from safe.contracts.manifest import SplitModelManifest
    from safe.domain.compatibility import manifest_digest
    from safe.infrastructure.artifacts.local_store import LocalArtifactStore
    from safe.infrastructure.models.qwen import QwenPrefixRunner, QwenSuffixRunner

    torch.set_num_threads(args.threads)
    process = psutil.Process()
    started = time.perf_counter()
    report = dict(
        status="failed",
        created_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
        manifest_digest=args.manifest_digest,
        python=platform.python_version(),
        platform=platform.platform(),
        torch=torch.__version__,
        transformers=transformers.__version__,
        safetensors=safetensors.__version__,
        threads=args.threads,
        device="cpu",
        dtype="float32",
        attention="eager",
        kv_cache=True,
        network=False,
        dp=False,
        atol=1e-5,
        rtol=1e-4,
        oracle_cache="DynamicCache",
        execution="session-json-continuation" if args.continuation else "direct-runner",
        expected_cases=args.samples,
        steps_per_case=args.steps,
        cases=[],
    )
    prefix = suffix = oracle = None
    try:
        manifest = SplitModelManifest.model_validate_json(
            (args.artifacts / "manifest.json").read_text(encoding="utf-8")
        )
        if manifest_digest(manifest) != args.manifest_digest:
            raise ValueError("manifest digest mismatch")
        prefix = QwenPrefixRunner(args.artifacts / "prefix", approved_digest=args.manifest_digest)
        suffix = QwenSuffixRunner(args.artifacts / "suffix", approved_digest=args.manifest_digest)
        store = LocalArtifactStore(args.artifacts / "prefix")
        store.verified_manifest(args.manifest_digest)
        tokenizer = AutoTokenizer.from_pretrained(
            str(store.directory / "tokenizer"), local_files_only=True, trust_remote_code=False
        )
        oracle = AutoModelForCausalLM.from_pretrained(
            str(args.source.resolve()), local_files_only=True, trust_remote_code=False,
            torch_dtype=torch.float32, attn_implementation="eager",
        ).eval()
        cloud = sessions = activation = sampler = None
        if args.continuation:
            from safe.application.activation import ActivationService
            from safe.application.continuation import ContinuationService
            from safe.application.session import SessionService
            from safe.contracts.session import ActivationContext, SessionStatus, StepRequest
            from safe.infrastructure.codecs.fp32 import FP32Codec
            from safe.infrastructure.models.sampling import GreedySampler
            from safe.infrastructure.storage.memory_sessions import MemorySessionStore

            class ObservedSampler:
                """仅评估使用：保留本步logits作oracle对照，不写入报告或wire回执。"""
                def __init__(self):
                    config = json.loads((store.directory / "config.json").read_text(encoding="utf-8"))
                    eos = tokenizer.eos_token_id
                    self.delegate = GreedySampler(vocab_size=config["vocab_size"],
                        eos_token_ids=frozenset() if eos is None else frozenset({eos}))
                    self.logits = None
                    self.calls = 0

                def sample(self, logits):
                    result = self.delegate.sample(logits)
                    self.logits = logits
                    self.calls += 1
                    return result

            sampler = ObservedSampler()
            sessions = SessionService(MemorySessionStore(runner=suffix))
            cloud = ContinuationService(sessions=sessions, runner=suffix, codec=FP32Codec(),
                sampler=sampler, manifest=manifest, approved_digest=args.manifest_digest,
                max_new_tokens=args.steps)
            activation = ActivationService(codec=FP32Codec(), manifest=manifest,
                                           approved_digest=args.manifest_digest)
            report["eos_policy"] = "verified-tokenizer-eos"
            report["eos_token_id"] = tokenizer.eos_token_id
            report["idempotent_retries_checked"] = 0
        report["model_revision"] = manifest.revision
        report["process_rss_before_models"] = process.memory_info().rss
        max_error = 0.0
        greedy_matches = 0
        total_steps = 0
        for index, prompt in enumerate(PROMPTS[:args.samples]):
            session_id = f"synthetic-kv-{index:02d}"
            prefix_handle = prefix.create_kv(session_id)
            suffix_handle = None
            session_created = False
            case_started = time.perf_counter()
            try:
                if cloud is None:
                    suffix_handle = suffix.create_kv(session_id)
                else:
                    cloud.create("eval-owner", session_id=session_id)
                    session_created = True
                input_ids = list(tokenizer.apply_chat_template(
                    [{"role": "user", "content": prompt}], tokenize=True, add_generation_prompt=True
                ))
                if len(input_ids) > 128 or len(input_ids) + args.steps - 1 > min(160, manifest.max_context):
                    raise ValueError("合成样本超过固定上下文边界")
                with torch.inference_mode():
                    hidden, shape = prefix.prefill(
                        tuple(input_ids), kv_handle=prefix_handle, session_id=session_id
                    )
                    if cloud is None:
                        logits = torch.tensor(suffix.prefill(
                            hidden, shape, kv_handle=suffix_handle, session_id=session_id
                        ))
                    oracle_cache = DynamicCache()
                    oracle_output = oracle(
                        torch.tensor([input_ids]), past_key_values=oracle_cache,
                        use_cache=True, num_logits_to_keep=1,
                    )
                case_error = 0.0
                case_matches = 0
                prompt_tokens = len(input_ids)
                ended_on_eos = False
                for step in range(args.steps):
                    receipt = None
                    if cloud is not None:
                        context = ActivationContext(session_id=session_id,
                            manifest_digest=args.manifest_digest, next_step=step,
                            phase="prefill" if step == 0 else "decode",
                            position_offset=0 if step == 0 else prompt_tokens + step - 1)
                        request = activation.encode(hidden, shape, context=context,
                                                    request_id=f"request-{index}-{step}")
                        request = StepRequest.model_validate_json(request.model_dump_json().encode("utf-8"))
                        calls_before = sampler.calls
                        receipt = cloud.step("eval-owner", request)
                        assert sampler.calls == calls_before + 1, "每个新请求必须只采样一次"
                        logits = torch.tensor(sampler.logits)
                        # 包括终态请求；重复请求不得再次执行或推进KV。
                        assert cloud.step("eval-owner", request) == receipt
                        assert sampler.calls == calls_before + 1, "幂等重试不应重复计算/采样"
                        assert sessions.view("eval-owner", session_id).next_step == step + 1
                        report["idempotent_retries_checked"] += 1
                    with torch.inference_mode():
                        expected = oracle_output.logits[0, -1]
                    try:
                        torch.testing.assert_close(logits, expected, atol=1e-5, rtol=1e-4)
                    except AssertionError:
                        raise AssertionError(f"logits偏差超限：case={index} step={step}") from None
                    error = float((logits - expected).abs().max())
                    case_error = max(case_error, error)
                    max_error = max(max_error, error)
                    token = int(logits.argmax()) if receipt is None else receipt.token_id
                    matched = token == int(expected.argmax())
                    if not matched:
                        raise AssertionError(f"greedy token不一致：case={index} step={step}")
                    case_matches += 1
                    greedy_matches += 1
                    total_steps += 1
                    input_ids.append(token)
                    if receipt is not None and receipt.finished:
                        ended_on_eos = token == tokenizer.eos_token_id
                        assert ended_on_eos or step + 1 == args.steps, "会话意外提前终止"
                        assert sessions.view("eval-owner", session_id).status is SessionStatus.CLOSED
                        break
                    if step + 1 < args.steps:
                        with torch.inference_mode():
                            oracle_output = oracle(
                                torch.tensor([[token]]), past_key_values=oracle_cache,
                                use_cache=True, num_logits_to_keep=1,
                            )
                            hidden, shape = prefix.decode(prefix_handle, session_id, token)
                            if cloud is None:
                                logits = torch.tensor(suffix.decode(suffix_handle, session_id, hidden, shape))
                report["cases"].append(dict(
                    case_id=f"synthetic-{index:02d}",
                    prompt_tokens=prompt_tokens,
                    checked_steps=case_matches,
                    ended_on_eos=ended_on_eos,
                    max_absolute_logit_error=case_error,
                    seconds=time.perf_counter() - case_started,
                ))
                print(
                    f"样本 {index + 1}/{args.samples}：{case_matches}步一致，"
                    f"最大logits误差={case_error:.3g}", flush=True
                )
            finally:
                prefix.release_kv(prefix_handle)
                if suffix_handle is not None:
                    suffix.release_kv(suffix_handle)
                if session_created:
                    if sessions.view("eval-owner", session_id).status in (SessionStatus.CREATED, SessionStatus.ACTIVE):
                        sessions.close("eval-owner", session_id)
        report.update(
            status="passed",
            total_checked_steps=total_steps,
            greedy_matches=greedy_matches,
            max_absolute_logit_error=max_error,
        )
        return 0
    except Exception as exc:
        report["failure_type"] = type(exc).__name__
        print("验证失败：" + type(exc).__name__ + " " + str(exc)[:160], file=sys.stderr)
        return 1
    finally:
        if prefix is not None:
            prefix.close()
        if suffix is not None:
            suffix.close()
        if oracle is not None:
            del oracle
        report["total_seconds"] = time.perf_counter() - started
        report["process_rss_after"] = process.memory_info().rss
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
