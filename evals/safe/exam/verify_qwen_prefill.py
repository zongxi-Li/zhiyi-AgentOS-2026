"""真实Qwen2.5模型的P0无扰动同进程对照；显式运行，不下载、不写真实用户数据。

每一步分别执行完整模型和prefix→FP32/JSON→suffix，比较最后位置全词表logits及greedy。
当前每步重算全序列，无KV缓存；不是P3的高效逐token会话，也不代表远程网络验收。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import platform
import sys
import time

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "apps/agentOS/src"))

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
    parser = argparse.ArgumentParser(description="真实模型20条合成中英文输入、每条16步无KV数值对照")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--manifest-digest", required=True)
    parser.add_argument("--report", type=Path, required=True, help="显式指定无用户内容的JSON证据文件")
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.threads <= 32:
        parser.error("threads须位于1–32")
    if args.report.exists():
        parser.error("报告已存在；请使用新文件名保留历史证据")

    import torch
    import transformers
    import safetensors
    import psutil
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from components.safe.application.activation import ActivationService
    from components.safe.contracts.session import ActivationContext, StepRequest
    from components.safe.infrastructure.artifacts.local_store import LocalArtifactStore
    from components.safe.infrastructure.codecs.fp32 import FP32Codec
    from components.safe.infrastructure.models.qwen import QwenPrefixRunner, QwenSuffixRunner

    torch.set_num_threads(args.threads)
    started = time.perf_counter()
    process = psutil.Process()
    baseline_rss = process.memory_info().rss
    prefix = suffix = oracle = None
    report = dict(status="failed", created_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
        model_revision="7ae557604adf67be50417f59c2c2f167def9a775", manifest_digest=args.manifest_digest,
        python=platform.python_version(), platform=platform.platform(), torch=torch.__version__,
        transformers=transformers.__version__, safetensors=safetensors.__version__, threads=args.threads,
        device="cpu", dtype="float32", attention="eager", kv_cache=False, network=False, dp=False,
        atol=1e-5, rtol=1e-4, expected_cases=20, steps_per_case=16, cases=[])
    try:
        prefix = QwenPrefixRunner(args.artifacts / "prefix", approved_digest=args.manifest_digest)
        rss_prefix = process.memory_info().rss
        suffix = QwenSuffixRunner(args.artifacts / "suffix", approved_digest=args.manifest_digest)
        rss_roles = process.memory_info().rss
        store = LocalArtifactStore(args.artifacts / "prefix")
        manifest = store.verified_manifest(args.manifest_digest)
        report["model_revision"] = manifest.revision
        tokenizer = AutoTokenizer.from_pretrained(str(store.directory / "tokenizer"), local_files_only=True,
                                                  trust_remote_code=False)
        oracle = AutoModelForCausalLM.from_pretrained(str(args.source.resolve()), local_files_only=True,
            trust_remote_code=False, torch_dtype=torch.float32, attn_implementation="eager").eval()
        service = ActivationService(codec=FP32Codec(), manifest=manifest, approved_digest=args.manifest_digest)
        report.update(rss_before_models=baseline_rss, rss_after_prefix=rss_prefix,
            rss_after_roles=rss_roles, rss_with_oracle=process.memory_info().rss,
            prefix_parameter_count=sum(p.numel() for p in prefix._module.parameters()),
            suffix_parameter_count=sum(p.numel() for p in suffix._module.parameters()),
            prefix_parameter_names=list(prefix.parameter_names), suffix_parameter_names=list(suffix.parameter_names))
        for index, prompt in enumerate(PROMPTS):
            ids = tuple(tokenizer.apply_chat_template([{"role": "user", "content": prompt}],
                                                      tokenize=True, add_generation_prompt=True))
            if len(ids) + 15 > 128:
                raise ValueError("合成样本超过当前完整prefill重算上限")
            initial_length = len(ids)
            max_error = 0.0
            generated = []
            uploaded_bytes = 0
            case_start = time.perf_counter()
            for step in range(16):
                # 同进程P0参考每次完整重算，不假装已推进真实会话step/KV。
                flat, shape = prefix.prefill(ids)
                context = ActivationContext(session_id=f"synthetic-{index}-{step}",
                    manifest_digest=args.manifest_digest, next_step=0, phase="prefill", position_offset=0)
                request = service.encode(flat, shape, context=context, request_id=f"reference-{step}")
                wire = request.model_dump_json().encode("utf-8")
                restored = StepRequest.model_validate_json(wire)
                logits = torch.tensor(suffix.prefill(service.decode(restored, context=context), shape))
                with torch.inference_mode():
                    expected = oracle(torch.tensor([ids]), use_cache=False, num_logits_to_keep=1).logits[0, -1]
                torch.testing.assert_close(logits, expected, atol=1e-5, rtol=1e-4)
                max_error = max(max_error, (logits - expected).abs().max().item())
                token = int(logits.argmax())
                if token != int(expected.argmax()):
                    raise AssertionError("greedy token不一致")
                generated.append(token)
                ids += (token,)
                uploaded_bytes += len(wire)
            report["cases"].append(dict(case_id=f"synthetic-{index:02d}", prompt_tokens=initial_length,
                greedy_tokens=generated, matched_steps=16, max_absolute_logit_error=max_error,
                serialized_bytes=uploaded_bytes, seconds=time.perf_counter() - case_start))
            print(f"样本 {index + 1}/20：16步一致，最大logits误差={max_error:.3g}", flush=True)
        report["status"] = "passed"
        return 0
    except Exception as exc:
        # 不输出用户内容/载荷或异常repr；运行用合成数据，错误类型足以定位测试失败。
        report["failure_type"] = type(exc).__name__
        print("验证失败：" + type(exc).__name__, file=sys.stderr)
        return 1
    finally:
        if prefix is not None:
            prefix.close()
        if suffix is not None:
            suffix.close()
        peak = process.memory_info()
        report.update(total_seconds=time.perf_counter() - started,
                      peak_working_set_bytes=getattr(peak, "peak_wset", peak.rss), completed_cases=len(report["cases"]))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
