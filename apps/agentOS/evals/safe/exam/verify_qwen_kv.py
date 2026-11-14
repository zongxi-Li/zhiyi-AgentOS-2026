"""显式核验Qwen2双角色KV逐token续算；不下载模型，不保存输入文本。"""

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
        report["model_revision"] = manifest.revision
        report["process_rss_before_models"] = process.memory_info().rss
        max_error = 0.0
        greedy_matches = 0
        total_steps = 0
        for index, prompt in enumerate(PROMPTS[:args.samples]):
            session_id = f"synthetic-kv-{index:02d}"
            prefix_handle = prefix.create_kv(session_id)
            suffix_handle = suffix.create_kv(session_id)
            case_started = time.perf_counter()
            try:
                input_ids = list(tokenizer.apply_chat_template(
                    [{"role": "user", "content": prompt}], tokenize=True, add_generation_prompt=True
                ))
                if len(input_ids) > 128 or len(input_ids) + args.steps - 1 > min(160, manifest.max_context):
                    raise ValueError("合成样本超过固定上下文边界")
                with torch.inference_mode():
                    hidden, shape = prefix.prefill(
                        tuple(input_ids), kv_handle=prefix_handle, session_id=session_id
                    )
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
                for step in range(args.steps):
                    with torch.inference_mode():
                        expected = oracle_output.logits[0, -1]
                    try:
                        torch.testing.assert_close(logits, expected, atol=1e-5, rtol=1e-4)
                    except AssertionError:
                        raise AssertionError(f"logits偏差超限：case={index} step={step}") from None
                    error = float((logits - expected).abs().max())
                    case_error = max(case_error, error)
                    max_error = max(max_error, error)
                    token = int(logits.argmax())
                    matched = token == int(expected.argmax())
                    if not matched:
                        raise AssertionError(f"greedy token不一致：case={index} step={step}")
                    case_matches += 1
                    greedy_matches += 1
                    total_steps += 1
                    input_ids.append(token)
                    if step + 1 < args.steps:
                        with torch.inference_mode():
                            oracle_output = oracle(
                                torch.tensor([[token]]), past_key_values=oracle_cache,
                                use_cache=True, num_logits_to_keep=1,
                            )
                            hidden, shape = prefix.decode(prefix_handle, session_id, token)
                            logits = torch.tensor(suffix.decode(suffix_handle, session_id, hidden, shape))
                report["cases"].append(dict(
                    case_id=f"synthetic-{index:02d}",
                    prompt_tokens=len(input_ids) - args.steps,
                    checked_steps=case_matches,
                    max_absolute_logit_error=case_error,
                    seconds=time.perf_counter() - case_started,
                ))
                print(
                    f"样本 {index + 1}/{args.samples}：{case_matches}步一致，"
                    f"最大logits误差={case_error:.3g}", flush=True
                )
            finally:
                prefix.release_kv(prefix_handle)
                suffix.release_kv(suffix_handle)
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
