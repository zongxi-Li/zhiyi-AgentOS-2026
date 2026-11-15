"""真实权重本机生成对照：预热、配对重复、稳态计时和激活字节计量。

只使用固定合成输入；不下载模型，不保存输入、输出文本、激活或完整logits。
同机JSON循环传输不代表网络，组件测量包含Python仪器开销，详见生成报告。
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import random
import statistics
import struct
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from evals.safe.exam.verify_qwen_kv import PROMPTS


def milliseconds(start: int) -> float:
    return (time.perf_counter_ns() - start) / 1e6


class Meter:
    def reset(self):
        self.rows = []
        self.started = time.perf_counter_ns()
        self.received = []


class ObservedPrefix:
    def __init__(self, runner, meter):
        self.runner, self.meter, self.manifest = runner, meter, runner.manifest

    def create_kv(self, session_id):
        return self.runner.create_kv(session_id)

    def release_kv(self, handle):
        self.runner.release_kv(handle)

    def _run(self, name, *args, **kwargs):
        started = time.perf_counter_ns()
        value = getattr(self.runner, name)(*args, **kwargs)
        self.meter.rows.append(dict(step=len(self.meter.rows), phase=name,
            prefix_ms=milliseconds(started), started_ns=started))
        return value

    def prefill(self, *args, **kwargs):
        return self._run("prefill", *args, **kwargs)

    def decode(self, *args, **kwargs):
        return self._run("decode", *args, **kwargs)


class ObservedSuffix:
    def __init__(self, runner, meter):
        self.runner, self.meter, self.manifest = runner, meter, runner.manifest

    def create_kv(self, session_id):
        return self.runner.create_kv(session_id)

    def release_kv(self, handle):
        self.runner.release_kv(handle)

    def _run(self, name, *args, **kwargs):
        started = time.perf_counter_ns()
        value = getattr(self.runner, name)(*args, **kwargs)
        self.meter.rows[-1]["suffix_ms"] = milliseconds(started)
        return value

    def prefill(self, *args, **kwargs):
        return self._run("prefill", *args, **kwargs)

    def decode(self, *args, **kwargs):
        return self._run("decode", *args, **kwargs)


class ObservedCodec:
    def __init__(self, codec, meter):
        self.codec, self.meter = codec, meter

    def encode(self, *args, **kwargs):
        started = time.perf_counter_ns()
        value = self.codec.encode(*args, **kwargs)
        self.meter.rows[-1]["client_codec_ms"] = milliseconds(started)
        return value

    def decode(self, envelope):
        return self.codec.decode(envelope)


class ObservedSampler:
    def __init__(self, sampler, meter):
        self.sampler, self.meter = sampler, meter

    def sample(self, logits):
        started = time.perf_counter_ns()
        value = self.sampler.sample(logits)
        self.meter.rows[-1]["sampling_ms"] = milliseconds(started)
        return value


class ObservedTokenizer:
    def __init__(self, tokenizer):
        self.tokenizer = tokenizer
        self.manifest = tokenizer.manifest
        self.eos_token_ids = tokenizer.eos_token_ids
        self.vocab_size = tokenizer.vocab_size
        self.output_ids = ()

    def encode_prompt(self, prompt):
        self.prompt_tokens = len(ids := self.tokenizer.encode_prompt(prompt))
        return ids

    def decode(self, ids):
        self.output_ids = ids
        return self.tokenizer.decode(ids)


class ObservedTransport:
    def __init__(self, transport, meter):
        self.transport, self.meter = transport, meter

    def create_session(self, digest):
        return self.transport.create_session(digest)

    def close_session(self, session_id):
        return self.transport.close_session(session_id)

    def query(self, session_id, request_id):
        return self.transport.query(session_id, request_id)

    def step(self, request):
        row = self.meter.rows[-1]
        # 额外序列化只用于精确计量；其开销计入本机端到端和协议剩余项。
        row["request_json_bytes"] = len(request.model_dump_json().encode("utf-8"))
        row["activation_raw_bytes"] = request.activation.raw_bytes
        receipt = self.transport.step(request)
        received = time.perf_counter_ns()
        self.meter.received.append(received)
        row["step_wall_ms"] = (received - row.pop("started_ns")) / 1e6
        components = sum(row[key] for key in ("prefix_ms", "client_codec_ms", "suffix_ms", "sampling_ms"))
        row["protocol_other_ms"] = row["step_wall_ms"] - components
        if row["protocol_other_ms"] < 0:
            raise AssertionError("组件时间发生重叠，不能生成分解图")
        row["inter_token_ms"] = (received - self.meter.received[-2]) / 1e6 if request.step else None
        return receipt


def run_full(model, tokenizer, prompt, limit):
    import torch
    from transformers.cache_utils import DynamicCache

    started = time.perf_counter_ns()
    ids = tokenizer.encode_prompt(prompt)
    cache = DynamicCache()
    current = torch.tensor([ids])
    output_ids, rows, received = [], [], []
    try:
        with torch.inference_mode():
            for step in range(limit):
                forward_started = time.perf_counter_ns()
                output = model(current, past_key_values=cache, use_cache=True, num_logits_to_keep=1)
                token = int(output.logits[0, -1].argmax())
                finished = time.perf_counter_ns()
                rows.append(dict(step=step, phase="prefill" if step == 0 else "decode",
                    full_model_ms=(finished - forward_started) / 1e6,
                    inter_token_ms=(finished - received[-1]) / 1e6 if step else None))
                received.append(finished)
                output_ids.append(token)
                if token in tokenizer.eos_token_ids:
                    break
                current = torch.tensor([[token]])
        text = tokenizer.decode(tuple(output_ids))
    finally:
        cache.key_cache.clear()
        cache.value_cache.clear()
    elapsed = milliseconds(started)
    return dict(output_ids=tuple(output_ids), text=text, prompt_tokens=len(ids),
        generated_tokens=len(output_ids), finish_reason="eos" if output_ids[-1] in tokenizer.eos_token_ids else "length",
        ttft_ms=(received[0] - started) / 1e6,
        tpot_ms=(received[-1] - received[0]) / 1e6 / (len(received) - 1) if len(received) > 1 else None,
        e2e_ms=elapsed), rows


def run_split(service, tokenizer, meter, prompt, limit):
    from safe.contracts.inference import GenerationOptions, InferenceRequest

    request = InferenceRequest(prompt=prompt, generation=GenerationOptions(max_new_tokens=limit))
    meter.reset()
    result = service.infer(request)
    elapsed = milliseconds(meter.started)
    received = meter.received
    if len(received) != result.generated_tokens:
        raise AssertionError("回执数与输出数不一致")
    return dict(output_ids=tokenizer.output_ids, text=result.text, prompt_tokens=tokenizer.prompt_tokens,
        generated_tokens=result.generated_tokens, finish_reason=result.finish_reason,
        ttft_ms=(received[0] - meter.started) / 1e6,
        tpot_ms=(received[-1] - received[0]) / 1e6 / (len(received) - 1) if len(received) > 1 else None,
        e2e_ms=elapsed), meter.rows


def write_csv(path, records):
    if not records:
        return
    fields = list(dict.fromkeys(key for row in records for key in row))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--manifest-digest", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--max-new-tokens", type=int, default=32)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--seed", type=int, default=20261115)
    args = parser.parse_args()
    if not (1 <= args.samples <= len(PROMPTS) and 1 <= args.repeats <= 10
            and 1 <= args.max_new_tokens <= 32 and 1 <= args.threads <= 32 and 1 <= args.warmup <= 10):
        parser.error("samples须为1–20；repeats/warmup为1–10；tokens/threads为1–32")
    if args.output.exists():
        parser.error("输出目录已存在，请使用新路径以保留历史证据")
    args.output.mkdir(parents=True)
    report = dict(status="failed", created_at=datetime.now(timezone.utc).isoformat(),
        schema_version="safe-local-benchmark-v1", manifest_digest=args.manifest_digest,
        samples=args.samples, repeats=args.repeats, max_new_tokens=args.max_new_tokens,
        threads=args.threads, warmup_runs_per_method=args.warmup, warmup_max_tokens=min(4, args.max_new_tokens),
        seed=args.seed, device="cpu", dtype="float32", attention="eager", batch_size=1,
        actual_network=False, authenticated=False, dp=False, compression=False,
        method_order="seeded-random-within-each-pair", sample_order="seeded-shuffle-per-repeat",
        latency_scope="steady-state; loading excluded; e2e includes local decode and KV cleanup",
        tpot_definition="(last_token_received-first_token_received)/(generated_tokens-1)",
        instrumentation="timers plus one extra request JSON serialization for exact byte counting",
        full_baseline="manual HF DynamicCache + torch argmax; no Python full-vocabulary validation",
        wire_scope="step JSON UTF-8 body only; excludes HTTP/TLS/session/response bytes")
    runs, steps = [], []
    prefix = suffix = remote = None
    experiment_started = time.perf_counter_ns()
    try:
        import torch
        import transformers
        import psutil
        from transformers import AutoModelForCausalLM
        from safe.application.inference import SplitInferenceService
        from safe.bootstrap.cloud import InProcessTransport
        from safe.infrastructure.artifacts.local_store import file_digest
        from safe.infrastructure.codecs.fp32 import FP32Codec
        from safe.infrastructure.models.qwen import QwenPrefixRunner, QwenSuffixRunner
        from safe.infrastructure.models.sampling import GreedySampler
        from safe.infrastructure.models.tokenizer import HuggingFaceTokenizer

        torch.set_num_threads(args.threads)
        torch.set_num_interop_threads(1)
        torch.manual_seed(args.seed)
        report.update(python=platform.python_version(), torch=torch.__version__, transformers=transformers.__version__,
            platform=platform.platform(), cpu=platform.processor(), cpu_logical=psutil.cpu_count(),
            cpu_physical=psutil.cpu_count(logical=False), interop_threads=1)
        report["runtime_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        report["benchmark_script_sha256"] = file_digest(Path(__file__))
        prefix = QwenPrefixRunner(args.artifacts / "prefix", approved_digest=args.manifest_digest)
        suffix = QwenSuffixRunner(args.artifacts / "suffix", approved_digest=args.manifest_digest)
        tokenizer = HuggingFaceTokenizer(args.artifacts / "prefix", approved_digest=args.manifest_digest)
        if file_digest(args.source / "config.json") != prefix.manifest.config_digest:
            raise ValueError("oracle配置与批准制品不一致")
        report.update(model_id=prefix.manifest.model_id, model_revision=prefix.manifest.revision,
            cut_layer=prefix.manifest.cut_layer, total_layers=prefix.manifest.total_layers,
            hidden_size=prefix.manifest.hidden_size, eos_token_ids=sorted(tokenizer.eos_token_ids),
            source_weights_sha256=file_digest(args.source / "model.safetensors"))
        oracle = AutoModelForCausalLM.from_pretrained(str(args.source.resolve()), local_files_only=True,
            trust_remote_code=False, torch_dtype=torch.float32, attn_implementation="eager").eval()
        meter = Meter()
        observed_tokenizer = ObservedTokenizer(tokenizer)
        remote = InProcessTransport(runner=ObservedSuffix(suffix, meter), codec=FP32Codec(),
            sampler=ObservedSampler(GreedySampler(vocab_size=tokenizer.vocab_size,
                eos_token_ids=tokenizer.eos_token_ids), meter), manifest=prefix.manifest,
            approved_digest=args.manifest_digest, owner_id="synthetic-benchmark-owner")
        service = SplitInferenceService(prefix=ObservedPrefix(prefix, meter), tokenizer=observed_tokenizer,
            transport=ObservedTransport(remote, meter), codec=ObservedCodec(FP32Codec(), meter),
            manifest=prefix.manifest, approved_digest=args.manifest_digest)
        methods = dict(full=lambda prompt, limit: run_full(oracle, tokenizer, prompt, limit),
            split=lambda prompt, limit: run_split(service, observed_tokenizer, meter, prompt, limit))
        for _ in range(args.warmup):
            for method in ("full", "split"):
                methods[method](PROMPTS[0], min(4, args.max_new_tokens))
        print("预热完成；开始配对实验（不输出输入/生成文本）。", flush=True)
        rng = random.Random(args.seed)
        matched_tokens = matched_pairs = 0
        for repeat in range(args.repeats):
            indices = list(range(args.samples))
            rng.shuffle(indices)
            for case in indices:
                order = ["full", "split"]
                rng.shuffle(order)
                pair = {}
                for order_index, method in enumerate(order):
                    metrics, events = methods[method](PROMPTS[case], args.max_new_tokens)
                    pair[method] = metrics
                    identifiers = dict(case_id=f"synthetic-{case:02d}", repeat=repeat, method=method,
                        method_order=order_index)
                    for event in events:
                        steps.append(dict(**identifiers, **event))
                    public = {key: value for key, value in metrics.items() if key not in ("text", "output_ids")}
                    digest = hashlib.sha256(struct.pack("<" + "I" * len(metrics["output_ids"]), *metrics["output_ids"])).hexdigest()
                    runs.append(dict(**identifiers, **public, output_ids_sha256=digest))
                if (pair["full"]["output_ids"] != pair["split"]["output_ids"]
                        or pair["full"]["text"] != pair["split"]["text"]
                        or pair["full"]["finish_reason"] != pair["split"]["finish_reason"]):
                    raise AssertionError(f"配对输出不一致：repeat={repeat} case={case}")
                matched_tokens += pair["full"]["generated_tokens"]
                matched_pairs += 1
                if prefix._caches._entries or suffix._caches._entries:
                    raise AssertionError("配对实验结束后仍残留角色KV")
                print(f"轮次 {repeat + 1}/{args.repeats}，样本 {case + 1:02d}："
                      f"{pair['full']['generated_tokens']} token一致", flush=True)
        summary = {}
        for method in methods:
            records = [run for run in runs if run["method"] == method]
            summary[method] = {metric: dict(median=statistics.median(row[metric] for row in records if row[metric] is not None),
                mean=statistics.mean(row[metric] for row in records if row[metric] is not None))
                for metric in ("ttft_ms", "tpot_ms", "e2e_ms")
                if any(row[metric] is not None for row in records)}
        report.update(status="passed", paired_runs=matched_pairs, matched_tokens=matched_tokens,
            exact_sequence_matches=matched_pairs, summary=summary,
            kv_empty_after_each_pair=True,
            split_eos_runs=sum(r["finish_reason"] == "eos" for r in runs if r["method"] == "split"),
            split_length_runs=sum(r["finish_reason"] == "length" for r in runs if r["method"] == "split"))
    except Exception as exc:
        report.update(failure_type=type(exc).__name__)
        print("实验失败：" + type(exc).__name__ + " " + str(exc)[:160], file=sys.stderr)
    finally:
        for resource in (remote, prefix, suffix):
            if resource is not None:
                try:
                    resource.close()
                except Exception as exc:
                    report.update(status="failed", cleanup_failure_type=type(exc).__name__)
        report["experiment_seconds_including_loading"] = milliseconds(experiment_started) / 1000
        write_csv(args.output / "runs.csv", runs)
        write_csv(args.output / "steps.csv", steps)
        report["data_sha256"] = {name: hashlib.sha256((args.output / name).read_bytes()).hexdigest()
            for name in ("runs.csv", "steps.csv") if (args.output / name).exists()}
        (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
