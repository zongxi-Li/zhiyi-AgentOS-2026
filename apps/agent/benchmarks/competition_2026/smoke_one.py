#!/usr/bin/env python3
"""Single-sample LongBench-E smoke benchmark for the AgentOS HTTP boundary.

This script intentionally treats AgentOS as a black box. It does not import the
runtime, planner, scheduler, provider, or storage implementations. It submits
one public LongBench-E sample through the production V2 HTTP API, waits for the
real Run to reach a terminal state, and then reads the final output, model usage,
and communication provenance projections.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import string
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:8000/ai/agentos/v2"
DATASET_SERVER_ROWS = "https://datasets-server.huggingface.co/rows"
DATASET_REPO = "THUDM/LongBench"
DATASET_CONFIG = "hotpotqa_e"
DATASET_SPLIT = "test"
DATASET_NAME = "hotpotqa"
PROMPT_VERSION = "longbench-hotpotqa-v1"
DEFAULT_SEED = 20260913
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "superseded"}
STOP_STATUSES = TERMINAL_STATUSES | {"waiting_review"}

HOTPOT_INSTRUCTION = (
    "Answer the question based on the given passages. "
    "Only give me the answer and do not output any other words."
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    raw_body = None
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "zhiyi-competition-benchmark/0.1",
        **(headers or {}),
    }
    if body is not None:
        raw_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=raw_body, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {url}: {error_body[:2000]}") from exc
    except URLError as exc:
        raise RuntimeError(f"request failed for {url}: {exc}") from exc
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"non-JSON response from {url}: {payload[:1000]}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"unexpected JSON shape from {url}: {type(parsed).__name__}")
    return parsed


def _read_first_nonempty(*values: str | None) -> str | None:
    for value in values:
        if value and value.strip():
            return value.strip()
    return None


def _read_secret_file(path_value: str | None) -> str | None:
    if not path_value:
        return None
    path = Path(path_value)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return value or None


def build_auth_headers(args: argparse.Namespace) -> dict[str, str]:
    internal_token = _read_first_nonempty(
        args.internal_token,
        os.getenv("BENCH_AGENTOS_INTERNAL_TOKEN"),
        os.getenv("AI_INTERNAL_TOKEN"),
        _read_secret_file(args.internal_token_file),
        _read_secret_file(os.getenv("BENCH_AGENTOS_INTERNAL_TOKEN_FILE")),
        _read_secret_file(os.getenv("AI_INTERNAL_TOKEN_FILE")),
    )
    bearer_token = _read_first_nonempty(
        args.bearer_token,
        os.getenv("BENCH_AGENTOS_BEARER_TOKEN"),
    )
    if internal_token:
        return {"X-Internal-Service-Token": internal_token}
    if bearer_token:
        return {"Authorization": f"Bearer {bearer_token}"}
    raise RuntimeError(
        "no AgentOS auth credential found; set BENCH_AGENTOS_INTERNAL_TOKEN, "
        "BENCH_AGENTOS_INTERNAL_TOKEN_FILE, BENCH_AGENTOS_BEARER_TOKEN, or pass "
        "--internal-token/--internal-token-file/--bearer-token"
    )


def load_longbench_e_sample(row_index: int) -> dict[str, Any]:
    if row_index < 0:
        raise ValueError("row index must be >= 0")
    query = urlencode(
        {
            "dataset": DATASET_REPO,
            "config": DATASET_CONFIG,
            "split": DATASET_SPLIT,
            "offset": row_index,
            "length": 1,
        }
    )
    payload = _json_request(f"{DATASET_SERVER_ROWS}?{query}", timeout=90.0)
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(
            f"LongBench-E returned no row for {DATASET_CONFIG}/{DATASET_SPLIT} index {row_index}"
        )
    item = rows[0]
    if not isinstance(item, dict) or not isinstance(item.get("row"), dict):
        raise RuntimeError("LongBench-E rows endpoint returned an unexpected row shape")
    row = dict(item["row"])
    row["_row_index"] = int(item.get("row_idx", row_index))
    required = ("input", "context", "answers", "length")
    missing = [key for key in required if key not in row]
    if missing:
        raise RuntimeError(f"LongBench-E row is missing required fields: {missing}")
    return row


def length_bucket(length: int) -> str:
    if length < 4000:
        return "0-4k"
    if length < 8000:
        return "4-8k"
    return "8k+"


def build_client_request_id(sample: dict[str, Any], *, seed: int, force_new_run: bool) -> str:
    sample_id = str(sample.get("_id") or sample.get("_row_index"))
    material = f"{DATASET_CONFIG}:{sample_id}:{PROMPT_VERSION}:{seed}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    suffix = f":{time.time_ns()}" if force_new_run else ""
    return f"bench2026:{digest}{suffix}"


def build_mission_payload(
    sample: dict[str, Any],
    *,
    seed: int,
    force_new_run: bool,
) -> tuple[dict[str, Any], str]:
    sample_id = str(sample.get("_id") or sample.get("_row_index"))
    question = str(sample["input"]).strip()
    request_id = build_client_request_id(sample, seed=seed, force_new_run=force_new_run)
    title = f"LongBench-E smoke · hotpotqa · {sample_id}"
    task_goal = f"{HOTPOT_INSTRUCTION}\n\nQuestion: {question}"
    return (
        {
            "title": title,
            "domain": "general",
            "intent": "general",
            "reviewMode": "auto",
            "securityLevel": "internal",
            "priority": "normal",
            "enabledPluginIds": [],
            "clientRequestId": request_id,
            "input": {
                "taskName": title,
                "taskGoal": task_goal,
                "userIntent": task_goal,
                "materialText": str(sample["context"]),
                "constraints": [
                    "Use only the provided material.",
                    "Return only the answer text, with no explanation.",
                    "Do not use web search or external retrieval.",
                ],
                "expectedArtifacts": ["A concise final answer containing only the answer text."],
                "planningSeed": seed,
                "webSearchEnabled": False,
                "source": "competition_2026_longbench_e",
            },
        },
        request_id,
    )


class AgentOSClient:
    def __init__(self, base_url: str, headers: dict[str, str]) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = headers

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def get(self, path: str, *, timeout: float = 60.0) -> dict[str, Any]:
        return _json_request(self._url(path), headers=self.headers, timeout=timeout)

    def post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        return _json_request(
            self._url(path),
            method="POST",
            headers=self.headers,
            body=body,
            timeout=timeout,
        )

    def submit_mission(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post("/missions", payload, timeout=90.0)

    def wait_for_run(
        self,
        run_id: str,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        last: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            last = self.get(f"/runs/{run_id}", timeout=60.0)
            status = str(last.get("status") or "").lower()
            if status in STOP_STATUSES:
                return last
            time.sleep(poll_interval_seconds)
        raise TimeoutError(
            f"run {run_id} did not reach a terminal/review state within "
            f"{timeout_seconds:.0f}s; last status={None if last is None else last.get('status')}"
        )

    def get_output(self, run_id: str, output_ref: str) -> dict[str, Any]:
        return self.get(f"/runs/{run_id}/outputs/{output_ref}", timeout=60.0)

    def get_resource_usage(self, run_id: str) -> dict[str, Any]:
        return self.get(f"/runs/{run_id}/resource-usage", timeout=60.0)

    def get_provenance(self, run_id: str) -> dict[str, Any]:
        return self.get(f"/runs/{run_id}/provenance", timeout=60.0)

    def get_model_calls(self, run_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            suffix = "?pageSize=100"
            if cursor is not None:
                suffix += f"&cursor={cursor}"
            payload = self.get(
                f"/runs/{run_id}/resource-usage/calls{suffix}",
                timeout=60.0,
            )
            page_items = payload.get("items")
            if isinstance(page_items, list):
                items.extend(item for item in page_items if isinstance(item, dict))
            next_cursor = payload.get("nextCursor")
            if next_cursor in (None, ""):
                return items
            cursor = str(next_cursor)


def _normalize_answer(text: str) -> str:
    def remove_articles(value: str) -> str:
        return re.sub(r"\b(a|an|the)\b", " ", value)

    def remove_punctuation(value: str) -> str:
        excluded = set(string.punctuation)
        return "".join(character for character in value if character not in excluded)

    return " ".join(remove_articles(remove_punctuation(text.lower())).split())


def qa_f1(prediction: str, ground_truth: str) -> float:
    prediction_tokens = _normalize_answer(prediction).split()
    ground_truth_tokens = _normalize_answer(ground_truth).split()
    if not prediction_tokens and not ground_truth_tokens:
        return 1.0
    if not prediction_tokens or not ground_truth_tokens:
        return 0.0
    common = Counter(prediction_tokens) & Counter(ground_truth_tokens)
    same = sum(common.values())
    if same == 0:
        return 0.0
    precision = same / len(prediction_tokens)
    recall = same / len(ground_truth_tokens)
    return 2.0 * precision * recall / (precision + recall)


def score_hotpotqa(prediction: str, answers: Any) -> float | None:
    if not isinstance(answers, list) or not answers:
        return None
    scores = [
        qa_f1(prediction, str(answer))
        for answer in answers
        if answer is not None
    ]
    return max(scores) if scores else None


PREFERRED_OUTPUT_KEYS = (
    "answer",
    "finalAnswer",
    "final_answer",
    "final",
    "finalOutput",
    "final_output",
    "result",
    "deliverable",
    "artifact",
    "content",
    "summary",
    "report",
    "response",
    "text",
    "output",
)


def extract_prediction(value: Any, *, depth: int = 0) -> str | None:
    if depth > 5:
        return None
    if isinstance(value, str):
        result = value.strip()
        return result or None
    if isinstance(value, dict):
        for key in PREFERRED_OUTPUT_KEYS:
            if key not in value:
                continue
            candidate = extract_prediction(value[key], depth=depth + 1)
            if candidate:
                return candidate
        if len(value) == 1:
            candidate = extract_prediction(next(iter(value.values())), depth=depth + 1)
            if candidate:
                return candidate
        return None
    if isinstance(value, list) and len(value) == 1:
        return extract_prediction(value[0], depth=depth + 1)
    return None


def communication_metrics(provenance: dict[str, Any]) -> dict[str, Any]:
    consumptions: list[dict[str, Any]] = []
    events = provenance.get("events")
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, dict) or event.get("eventType") != "data_consumed":
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            event_id = str(payload.get("eventId") or "")
            # ContextAssembler records both DataConsumptionEvent (cons_*) and a
            # RuntimeInteraction mirror (int_*). Count only cons_* so the same
            # communication fact is not doubled.
            if not event_id.startswith("cons_") or "interactionId" in payload:
                continue
            consumptions.append(payload)
    else:
        legacy = provenance.get("consumptions")
        if isinstance(legacy, list):
            consumptions = [item for item in legacy if isinstance(item, dict)]

    delivered = sum(max(0, int(item.get("tokensDelivered") or 0)) for item in consumptions)
    available = sum(max(0, int(item.get("tokensAvailable") or 0)) for item in consumptions)
    reduction = None
    if available > 0:
        reduction = 1.0 - (delivered / available)
    return {
        "communication_event_count": len(consumptions),
        "comm_tokens_available_est": available,
        "comm_tokens_delivered_est": delivered,
        "comm_payload_reduction": reduction,
        "provenance_integrity_status": provenance.get("integrityStatus"),
    }


def usage_metrics(
    resource_usage: dict[str, Any],
    calls: list[dict[str, Any]],
) -> dict[str, Any]:
    usage = resource_usage.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    observed = 0
    model_names: list[str] = []
    providers: list[str] = []
    for call in calls:
        call_usage = call.get("usage")
        call_usage = call_usage if isinstance(call_usage, dict) else {}
        if any(
            int(call_usage.get(key) or 0) > 0
            for key in ("inputTokens", "outputTokens", "totalTokens", "cacheReadTokens", "reasoningTokens")
        ):
            observed += 1
        model = call.get("model")
        provider = call.get("provider")
        if model and str(model) not in model_names:
            model_names.append(str(model))
        if provider and str(provider) not in providers:
            providers.append(str(provider))
    call_count = int(usage.get("callCount") or len(calls))
    coverage = observed / call_count if call_count > 0 else None
    return {
        "llm_input_tokens": int(usage.get("inputTokens") or 0),
        "llm_output_tokens": int(usage.get("outputTokens") or 0),
        "llm_cache_read_tokens": int(usage.get("cacheReadTokens") or 0),
        "llm_cache_write_tokens": int(usage.get("cacheWriteTokens") or 0),
        "llm_reasoning_tokens": int(usage.get("reasoningTokens") or 0),
        "llm_total_tokens": int(usage.get("totalTokens") or 0),
        "model_call_count": call_count,
        "retry_count": int(usage.get("retryCount") or 0),
        "model_latency_ms": int(usage.get("latencyMs") or 0),
        "usage_observed_call_count": observed,
        "usage_coverage": coverage,
        "usage_complete": bool(call_count > 0 and observed == call_count),
        "models": model_names,
        "providers": providers,
    }


def build_result(
    *,
    sample: dict[str, Any],
    request_id: str,
    run: dict[str, Any],
    output: dict[str, Any] | None,
    resource_usage: dict[str, Any] | None,
    calls: list[dict[str, Any]],
    provenance: dict[str, Any] | None,
    wall_latency_ms: int,
    started_at: str,
    finished_at: str,
) -> dict[str, Any]:
    context = str(sample["context"])
    content = None if output is None else output.get("content")
    prediction = extract_prediction(content)
    score = None
    if str(run.get("status") or "").lower() == "completed" and prediction is not None:
        score = score_hotpotqa(prediction, sample.get("answers"))
    length_value = int(sample.get("length") or len(context.split()))
    result: dict[str, Any] = {
        "schema_version": "competition_2026_smoke_v1",
        "dataset_repo": DATASET_REPO,
        "dataset_config": DATASET_CONFIG,
        "dataset": DATASET_NAME,
        "split": DATASET_SPLIT,
        "sample_id": str(sample.get("_id") or sample.get("_row_index")),
        "row_index": int(sample.get("_row_index") or 0),
        "length": length_value,
        "length_bucket": length_bucket(length_value),
        "context_sha256": hashlib.sha256(context.encode("utf-8")).hexdigest(),
        "question": str(sample.get("input") or ""),
        "answers": sample.get("answers"),
        "prompt_version": PROMPT_VERSION,
        "client_request_id": request_id,
        "mission_id": run.get("missionId"),
        "run_id": run.get("runId"),
        "run_status": run.get("status"),
        "run_completed": str(run.get("status") or "").lower() == "completed",
        "terminal_reason": run.get("lifecycleMessage"),
        "prediction": prediction,
        "prediction_extraction_status": "ok" if prediction is not None else "failed",
        "quality_metric": "LongBench HotpotQA F1",
        "quality_score": score,
        "wall_latency_ms": wall_latency_ms,
        "benchmark_started_at": started_at,
        "benchmark_finished_at": finished_at,
    }
    if resource_usage is not None:
        result.update(usage_metrics(resource_usage, calls))
    else:
        result.update(
            {
                "llm_input_tokens": None,
                "llm_output_tokens": None,
                "llm_cache_read_tokens": None,
                "llm_cache_write_tokens": None,
                "llm_reasoning_tokens": None,
                "llm_total_tokens": None,
                "model_call_count": None,
                "retry_count": None,
                "model_latency_ms": None,
                "usage_observed_call_count": None,
                "usage_coverage": None,
                "usage_complete": False,
                "models": [],
                "providers": [],
            }
        )
    if provenance is not None:
        result.update(communication_metrics(provenance))
    else:
        result.update(
            {
                "communication_event_count": None,
                "comm_tokens_available_est": None,
                "comm_tokens_delivered_est": None,
                "comm_payload_reduction": None,
                "provenance_integrity_status": None,
            }
        )
    return result


def print_summary(result: dict[str, Any], result_path: Path) -> None:
    reduction = result.get("comm_payload_reduction")
    quality = result.get("quality_score")
    usage_coverage = result.get("usage_coverage")
    print("\n=== Competition benchmark: single-sample smoke result ===")
    print(f"dataset/sample : {result['dataset_config']} / {result['sample_id']}")
    print(f"run            : {result['run_id']} ({result['run_status']})")
    print(f"length bucket  : {result['length_bucket']} ({result['length']})")
    print("quality F1      : " + ("n/a" if quality is None else f"{float(quality):.4f}"))
    print(f"wall latency   : {result['wall_latency_ms']} ms")
    print(f"model latency  : {result.get('model_latency_ms')} ms")
    print(f"LLM tokens     : {result.get('llm_total_tokens')}")
    print(
        "usage coverage : "
        + ("n/a" if usage_coverage is None else f"{float(usage_coverage):.1%}")
    )
    print("comm reduction : " + ("n/a" if reduction is None else f"{float(reduction):.1%}"))
    print(
        "comm est units : "
        f"{result.get('comm_tokens_delivered_est')} delivered / "
        f"{result.get('comm_tokens_available_est')} available"
    )
    print(f"result file    : {result_path}")
    print("=========================================================\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run one public LongBench-E HotpotQA sample through the real AgentOS "
            "HTTP API and collect quality, latency, LLM usage, and communication metrics."
        )
    )
    parser.add_argument("--row", type=int, default=0, help="LongBench-E row index (default: 0)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--base-url", default=os.getenv("BENCH_AGENTOS_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--internal-token", default=None)
    parser.add_argument("--internal-token-file", default=None)
    parser.add_argument("--bearer-token", default=None)
    parser.add_argument("--timeout-seconds", type=float, default=1200.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    parser.add_argument(
        "--force-new-run",
        action="store_true",
        help="append a nonce to clientRequestId and force a fresh Run instead of idempotent reuse",
    )
    parser.add_argument(
        "--output",
        default=os.getenv(
            "BENCH_RESULT_PATH",
            "/app/data/agentos/benchmarks/competition_2026/smoke_result.json",
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    sample = load_longbench_e_sample(args.row)
    auth_headers = build_auth_headers(args)
    client = AgentOSClient(args.base_url, auth_headers)
    mission_payload, request_id = build_mission_payload(
        sample,
        seed=args.seed,
        force_new_run=args.force_new_run,
    )

    started_iso = _utc_now()
    started = time.monotonic()
    submitted = client.submit_mission(mission_payload)
    run_id = str(submitted.get("runId") or "")
    if not run_id:
        raise RuntimeError(f"mission submission returned no runId: {submitted}")

    print(
        f"[smoke] submitted {DATASET_CONFIG} row={args.row} "
        f"sample={sample.get('_id') or args.row} run={run_id}"
    )
    run = client.wait_for_run(
        run_id,
        timeout_seconds=args.timeout_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
    )
    wall_latency_ms = int(round((time.monotonic() - started) * 1000))
    finished_iso = _utc_now()

    output: dict[str, Any] | None = None
    output_ref = run.get("outputRef")
    if output_ref:
        try:
            output = client.get_output(run_id, str(output_ref))
        except RuntimeError as exc:
            print(f"[smoke] warning: final output fetch failed: {exc}", file=sys.stderr)

    resource_usage: dict[str, Any] | None = None
    calls: list[dict[str, Any]] = []
    try:
        resource_usage = client.get_resource_usage(run_id)
        calls = client.get_model_calls(run_id)
    except RuntimeError as exc:
        print(f"[smoke] warning: resource usage fetch failed: {exc}", file=sys.stderr)

    provenance: dict[str, Any] | None = None
    try:
        provenance = client.get_provenance(run_id)
    except RuntimeError as exc:
        print(f"[smoke] warning: provenance fetch failed: {exc}", file=sys.stderr)

    result = build_result(
        sample=sample,
        request_id=request_id,
        run=run,
        output=output,
        resource_usage=resource_usage,
        calls=calls,
        provenance=provenance,
        wall_latency_ms=wall_latency_ms,
        started_at=started_iso,
        finished_at=finished_iso,
    )
    result_path = Path(args.output)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print_summary(result, result_path)

    # Smoke is infrastructure-successful when the system reaches a terminal or
    # review state and the result is persisted. Benchmark answer quality is a
    # measured value, not a process exit-code condition.
    return 0 if str(run.get("status") or "").lower() in STOP_STATUSES else 2


if __name__ == "__main__":
    raise SystemExit(main())
