"""独立后段进程的真实 HTTPS 回环验收；仅使用固定合成输入，不下载权重。

临时证书和随机实验凭据不进入报告。回环延迟不能代表公网；正文计量不含
HTTP 头、TLS 记录、握手或 TCP 重传。完整模型只作为父进程内的评估 oracle。
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import random
import secrets
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from evals.safe.exam.benchmark_local_generation import ObservedTokenizer, run_full, write_csv
from evals.safe.exam.verify_qwen_kv import PROMPTS


def require(condition, message="实验验收条件不成立"):
    """不能用 assert 承担验收；python -O 下也必须执行检查及其中的请求。"""
    if not condition:
        raise AssertionError(message)


class TrackedRunner:
    """实验计数器；只记录句柄集合和次数，不保存激活或 token。"""

    def __init__(self, runner):
        self.runner, self.manifest = runner, runner.manifest
        self.active, self.created, self.released, self.forwards = set(), 0, 0, 0
        self.lock = threading.Lock()

    def create_kv(self, session_id):
        handle = self.runner.create_kv(session_id)
        with self.lock:
            self.active.add(handle)
            self.created += 1
        return handle

    def release_kv(self, handle):
        self.runner.release_kv(handle)
        with self.lock:
            if handle in self.active:
                self.active.remove(handle)
                self.released += 1

    def _run(self, method, *args, **kwargs):
        with self.lock:
            self.forwards += 1
        return getattr(self.runner, method)(*args, **kwargs)

    def prefill(self, *args, **kwargs):
        return self._run("prefill", *args, **kwargs)

    def decode(self, *args, **kwargs):
        return self._run("decode", *args, **kwargs)


def credentials(config):
    from safe.ports.credentials import Credential
    return [Credential(credential_id=f"eval-credential-{index}", owner_id=f"eval-owner-{index}",
        secret=bytes.fromhex(secret), scopes=frozenset({"safe:infer"}))
        for index, secret in enumerate(config["secrets"])]


async def serve_worker(config, directory):
    import torch
    import uvicorn
    from safe.bootstrap.cloud import create_http_cloud_app
    from safe.infrastructure.codecs.fp32 import FP32Codec
    from safe.infrastructure.models.qwen import QwenSuffixRunner
    from safe.infrastructure.models.sampling import GreedySampler

    torch.set_num_threads(config["threads"])
    torch.set_num_interop_threads(1)
    runner = QwenSuffixRunner(Path(config["artifacts"]) / "suffix", approved_digest=config["digest"])
    tracked = TrackedRunner(runner)
    known = {item.credential_id: item for item in credentials(config)}

    class Source:
        def get(self, credential_id):
            return known.get(credential_id)

    result = dict(status="failed", pid=os.getpid())
    try:
        app = create_http_cloud_app(runner=tracked, codec=FP32Codec(),
            sampler=GreedySampler(vocab_size=config["vocab_size"], eos_token_ids=frozenset(config["eos"])),
            manifest=runner.manifest, approved_digest=config["digest"], credentials=Source(),
            max_sessions=128, max_active_per_owner=1, purge_interval=0.2)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(128)
            port = sock.getsockname()[1]

            class ReadyServer(uvicorn.Server):
                async def startup(self, sockets=None):
                    await super().startup(sockets=sockets)
                    if self.started:
                        pending = directory / "ready.pending"
                        pending.write_text(json.dumps(dict(port=port, pid=os.getpid())), encoding="utf-8")
                        pending.replace(directory / "ready.json")

            server = ReadyServer(uvicorn.Config(app, ssl_certfile=str(directory / "cert.pem"),
                ssl_keyfile=str(directory / "key.pem"), host="127.0.0.1", port=port,
                access_log=False, log_level="critical", proxy_headers=False,
                timeout_graceful_shutdown=30))

            async def watch_stop():
                deadline = time.monotonic() + 600
                while not (directory / "stop").exists() and time.monotonic() < deadline:
                    await asyncio.sleep(0.05)
                server.should_exit = True

            watcher = asyncio.create_task(watch_stop())
            try:
                await server.serve(sockets=[sock])
            finally:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
        result.update(status="passed" if not tracked.active and server.started else "failed",
            active_kv=len(tracked.active), created_kv=tracked.created,
            released_kv=tracked.released, forwards=tracked.forwards)
    finally:
        runner.close()
        (directory / "worker-result.json").write_text(json.dumps(result), encoding="utf-8")
    return 0 if result["status"] == "passed" else 1


def make_certificate(directory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "safe-loopback-evaluation")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .sign(key, hashes.SHA256()))
    (directory / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (directory / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))


class MeteredTransport:
    def __init__(self, delegate, wire):
        self.delegate, self.received, self.wire = delegate, [], wire
        self.probe = None

    def create_session(self, digest):
        return self.delegate.create_session(digest)

    def close_session(self, session_id):
        return self.delegate.close_session(session_id)

    def query(self, session_id, request_id):
        return self.delegate.query(session_id, request_id)

    def step(self, request):
        self.wire.update(step=request.step, phase=request.phase, position_offset=request.position_offset,
            activation_raw_bytes=request.activation.raw_bytes)
        try:
            receipt = self.delegate.step(request)
        finally:
            self.wire.clear()
        self.received.append(time.perf_counter_ns())
        if self.probe is not None:
            probe, self.probe = self.probe, None
            probe(request, receipt)
        return receipt


def verify_protocol(transport, origin, context, config, request, receipt):
    """真实 TCP/TLS 上检查幂等、重放、篡改和 owner 隔离，不能多推进一次。"""
    import httpx
    from safe.infrastructure.security.signing import sign_request

    # 实际握手应拒绝未信任的自签服务证书，而非只检查客户端构造参数。
    try:
        with httpx.Client(verify=ssl.create_default_context(), trust_env=False, timeout=5) as untrusted:
            untrusted.get(origin + "/safe/v1/capabilities")
    except httpx.ConnectError:
        pass
    else:
        raise AssertionError("未信任证书竟被接受")
    require(transport.query(request.session_id, request.request_id) == receipt)
    require(transport.step(request) == receipt)
    path = f"/safe/v1/sessions/{request.session_id}/steps"
    body = request.model_dump_json().encode()
    first, other = credentials(config)

    def sign(credential, method, path, payload=b""):
        return sign_request(credential=credential, method=method, path=path, body=payload,
            timestamp=int(time.time()), nonce=secrets.token_hex(16))

    with httpx.Client(base_url=origin, verify=context, trust_env=False, follow_redirects=False, timeout=20) as client:
        headers = {**sign(first, "POST", path, body), "Content-Type": "application/json"}
        require(client.post(path, content=body, headers=headers).json() == receipt.model_dump())
        replay = client.post(path, content=body, headers=headers)
        require(replay.status_code == 401 and replay.json() == {"code": "AUTHENTICATION_FAILED"})
        tampered = client.post(path, content=body + b" ", headers={**sign(first, "POST", path, body),
            "Content-Type": "application/json"})
        require(tampered.status_code == 401)
        replies = []
        for sid in (request.session_id, "unknown-session"):
            query = f"/safe/v1/sessions/{sid}/requests/{request.request_id}"
            response = client.get(query, headers=sign(other, "GET", query))
            replies.append((response.status_code, response.json()))
        require(replies[0] == replies[1] == (404, {"code": "SESSION_INVALID"}))
    require(transport.query(request.session_id, request.request_id) == receipt)


def run_https(service, tokenizer, meter, prompt, limit):
    from safe.contracts.inference import GenerationOptions, InferenceRequest

    meter.received = []
    start = time.perf_counter_ns()
    result = service.infer(InferenceRequest(prompt=prompt, generation=GenerationOptions(max_new_tokens=limit)))
    end = time.perf_counter_ns()
    require(len(meter.received) == result.generated_tokens)
    return dict(output_ids=tokenizer.output_ids, text=result.text, prompt_tokens=tokenizer.prompt_tokens,
        generated_tokens=result.generated_tokens, finish_reason=result.finish_reason,
        ttft_ms=(meter.received[0] - start) / 1e6, e2e_ms=(end - start) / 1e6,
        tpot_ms=(meter.received[-1] - meter.received[0]) / 1e6 / (len(meter.received) - 1)
            if len(meter.received) > 1 else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--manifest-digest")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--max-new-tokens", type=int, default=16)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20261115)
    parser.add_argument("--worker-config", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker_config:
        try:
            return asyncio.run(serve_worker(json.loads(args.worker_config.read_text(encoding="utf-8")), args.worker_config.parent))
        except Exception:
            return 1  # 子进程不输出凭据、路径、激活或异常上下文。
    if not all((args.source, args.artifacts, args.manifest_digest, args.output)):
        parser.error("必须指定 source/artifacts/manifest-digest/output")
    if not (1 <= args.samples <= 20 and 1 <= args.repeats <= 10 and 2 <= args.max_new_tokens <= 32 and 1 <= args.threads <= 32):
        parser.error("samples/repeats/token/threads 超出实验范围")
    if args.output.exists():
        parser.error("输出目录已存在，请保留历史证据并指定新目录")
    args.output.mkdir(parents=True)
    report = dict(schema_version="safe-https-loopback-v1", status="failed",
        created_at=datetime.now(timezone.utc).isoformat(), samples=args.samples, repeats=args.repeats,
        max_new_tokens=args.max_new_tokens, threads=args.threads, seed=args.seed,
        network="real-tcp-tls-loopback", dp=False, public_network=False,
        byte_scope="actual HTTP request/response bodies only; excludes headers/TLS/TCP",
        latency_scope="warmed generation including session creation/close; excludes model loading",
        oracle_scope="parent also holds full model solely for evaluation; child holds suffix only",
        tpot_definition="(last_token_received-first_token_received)/(generated_tokens-1)")
    runs, events = [], []
    prefix = remote = oracle = None
    try:
        import torch
        import transformers
        from transformers import AutoModelForCausalLM
        from safe.application.inference import SplitInferenceService
        from safe.infrastructure.artifacts.local_store import file_digest
        from safe.infrastructure.codecs.fp32 import FP32Codec
        from safe.infrastructure.models.qwen import QwenPrefixRunner
        from safe.infrastructure.models.tokenizer import HuggingFaceTokenizer
        from safe.infrastructure.transport.http_client import HttpRemoteTransport

        torch.set_num_threads(args.threads)
        torch.set_num_interop_threads(1)
        torch.manual_seed(args.seed)
        prefix = QwenPrefixRunner(args.artifacts / "prefix", approved_digest=args.manifest_digest)
        tokenizer = HuggingFaceTokenizer(args.artifacts / "prefix", approved_digest=args.manifest_digest)
        if file_digest(args.source / "config.json") != prefix.manifest.config_digest:
            raise ValueError("oracle配置不匹配")
        oracle = AutoModelForCausalLM.from_pretrained(str(args.source.resolve()), local_files_only=True,
            trust_remote_code=False, torch_dtype=torch.float32, attn_implementation="eager").eval()
        report.update(python=platform.python_version(), torch=torch.__version__, transformers=transformers.__version__,
            platform=platform.platform(), manifest_digest=args.manifest_digest, model_id=prefix.manifest.model_id,
            revision=prefix.manifest.revision, cut_layer=prefix.manifest.cut_layer,
            total_layers=prefix.manifest.total_layers, hidden_size=prefix.manifest.hidden_size,
            eos_token_ids=sorted(tokenizer.eos_token_ids), source_weights_sha256=file_digest(args.source / "model.safetensors"),
            runtime_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            script_sha256=file_digest(Path(__file__)),
            http_lock_sha256=file_digest(Path(__file__).resolve().parents[3] / "requirements.safe.http.lock"))
        with tempfile.TemporaryDirectory(prefix="safe-tls-eval-") as temporary:
            directory = Path(temporary)
            make_certificate(directory)
            config = dict(artifacts=str(args.artifacts.resolve()), digest=args.manifest_digest,
                threads=args.threads, vocab_size=tokenizer.vocab_size, eos=sorted(tokenizer.eos_token_ids),
                secrets=[secrets.token_hex(32), secrets.token_hex(32)])
            config_path = directory / "worker-config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            child = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--worker-config", str(config_path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            try:
                deadline = time.monotonic() + 60
                while not (directory / "ready.json").exists():
                    if child.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("后段进程启动失败或超时")
                    time.sleep(0.05)
                ready = json.loads((directory / "ready.json").read_text(encoding="utf-8"))
                if ready["pid"] == os.getpid():
                    raise AssertionError("后段必须是独立进程")
                origin = f"https://127.0.0.1:{ready['port']}"
                context = ssl.create_default_context(cafile=str(directory / "cert.pem"))
                current, wire = {}, {}

                def observe(value):
                    events.append(dict(**current, **wire, **asdict(value)))

                remote = HttpRemoteTransport(origin=origin, credential=credentials(config)[0],
                    ssl_context=context, timeout=30, observer=observe)
                require(remote.capabilities().available)
                meter = MeteredTransport(remote, wire)
                observed = ObservedTokenizer(tokenizer)
                service = SplitInferenceService(prefix=prefix, tokenizer=observed, transport=meter,
                    codec=FP32Codec(), manifest=prefix.manifest, approved_digest=args.manifest_digest)
                meter.probe = lambda req, rec: verify_protocol(remote, origin, context, config, req, rec)
                warmup = run_https(service, observed, meter, PROMPTS[0], 4)
                run_full(oracle, tokenizer, PROMPTS[0], 4)
                expected_forwards = warmup["generated_tokens"]
                events.clear()
                matched = 0
                rng = random.Random(args.seed)
                for repeat in range(args.repeats):
                    cases = list(range(args.samples))
                    rng.shuffle(cases)
                    for case in cases:
                        pair = {}
                        methods = ["full", "https"]
                        rng.shuffle(methods)
                        for order, method in enumerate(methods):
                            current.clear()
                            current.update(case_id=f"synthetic-{case:02d}", repeat=repeat)
                            metrics = (run_full(oracle, tokenizer, PROMPTS[case], args.max_new_tokens)[0] if method == "full"
                                else run_https(service, observed, meter, PROMPTS[case], args.max_new_tokens))
                            pair[method] = metrics
                            public = {k: v for k, v in metrics.items() if k not in ("text", "output_ids")}
                            digest = hashlib.sha256(struct.pack("<" + "I" * len(metrics["output_ids"]), *metrics["output_ids"])).hexdigest()
                            runs.append(dict(**current, method=method, method_order=order, **public, output_ids_sha256=digest))
                        for key in ("output_ids", "text", "finish_reason", "prompt_tokens"):
                            if pair["full"][key] != pair["https"][key]:
                                raise AssertionError("HTTPS生成与完整模型不一致")
                        if prefix._caches._entries:
                            raise AssertionError("前段会话结束后残留KV")
                        expected_forwards += pair["https"]["generated_tokens"]
                        matched += pair["https"]["generated_tokens"]
                        print(f"第 {repeat + 1}/{args.repeats} 轮，合成样本 {case + 1:02d}：token一致", flush=True)
                # 故意留下未执行会话，验证应用停机而非客户端关闭负责释放。
                remote.create_session(args.manifest_digest)
                remote.close()
                (directory / "stop").touch()
                child.wait(timeout=40)
                worker = json.loads((directory / "worker-result.json").read_text(encoding="utf-8"))
                if child.returncode or worker["status"] != "passed" or worker["forwards"] != expected_forwards:
                    raise AssertionError("后段清理或幂等前向次数核验失败")
                if worker["created_kv"] != worker["released_kv"] or worker["active_kv"]:
                    raise AssertionError("后段KV未全部释放")
                # 排除停机探针的创建请求；仅保留配对生成的完整控制流。
                events.pop()
                report.update(status="passed", exact_sequence_matches=args.samples * args.repeats,
                    matched_tokens=matched, warmup_tokens=warmup["generated_tokens"], worker=worker,
                    protocol_checks=["receipt-query", "business-idempotency", "nonce-replay-rejected",
                        "body-tampering-rejected", "cross-owner-hidden", "untrusted-certificate-rejected",
                        "shutdown-releases-abandoned-kv"],
                    prefix_kv_empty=True, independent_suffix_process=True)
            finally:
                if child.poll() is None:
                    (directory / "stop").touch()
                    try:
                        child.wait(timeout=40)
                    except subprocess.TimeoutExpired:
                        child.terminate()
                        child.wait(timeout=10)
    except Exception as exc:
        report.update(status="failed", failure_type=type(exc).__name__)
        print("HTTPS实验失败：" + type(exc).__name__, file=sys.stderr)
    finally:
        for resource in (remote, prefix):
            if resource is not None:
                try:
                    resource.close()
                except Exception as exc:
                    report.update(status="failed", cleanup_failure_type=type(exc).__name__)
        for name, records in (("runs.csv", runs), ("http.csv", events)):
            write_csv(args.output / name, records)
        report["data_sha256"] = {name: hashlib.sha256((args.output / name).read_bytes()).hexdigest()
            for name in ("runs.csv", "http.csv") if (args.output / name).exists()}
        (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
