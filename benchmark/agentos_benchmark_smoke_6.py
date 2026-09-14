"""Run the fixed six-sample LongBench-E smoke test through AgentOS HTTP API.

This harness is deliberately outside AgentOS. It maps each LongBench-E task to
its own official task semantics, then reads only the formal final_answer output
for scoring. It does not inspect facts, intermediate nodes, or references while
building a Mission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import string
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

import httpx
from rouge import Rouge


SEED = 20260913
THINKING_MODE = "max"
CONFIGS = ("hotpotqa_e", "gov_report_e", "passage_retrieval_en_e")
SAMPLES_PER_DATASET = 2
SPLIT = "test"
DEFAULT_DATA_ZIP = Path("tmp/longbench_data.zip")
DEFAULT_RESULT_PATH = Path("tmp/benchmark_smoke_6.jsonl")
DEFAULT_SUMMARY_PATH = Path("tmp/benchmark_smoke_6_summary.json")
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "superseded"}
KNOWN_STATUSES = {
    "pending", "planning", "running", "retrying", "waiting_review",
    "completed", "failed", "cancelled", "superseded",
}


class SmokeFailure(RuntimeError):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.message = message


def as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def as_answers(value: Any) -> list[str]:
    if isinstance(value, list):
        return [as_text(item) for item in value if as_text(item).strip()]
    text = as_text(value).strip()
    return [text] if text else []


def integer(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def length_bucket(length: int) -> str:
    if length < 4000:
        return "0-4k"
    if length < 8000:
        return "4-8k"
    return "8k+"


def load_rows(data_zip: Path, config: str) -> list[dict[str, Any]]:
    member = f"data/{config}.jsonl"
    try:
        with zipfile.ZipFile(data_zip) as archive:
            raw = archive.read(member).decode("utf-8")
    except (OSError, KeyError, zipfile.BadZipFile, UnicodeDecodeError) as exc:
        raise SmokeFailure("DATASET", f"unable to read official {member}: {type(exc).__name__}: {exc}") from exc
    try:
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        raise SmokeFailure("DATASET", f"invalid JSONL in {member}: {exc}") from exc
    if not rows or not all(isinstance(row, dict) for row in rows):
        raise SmokeFailure("DATASET", f"{member} did not contain object rows")
    return rows


def select_samples(data_zip: Path) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for config in CONFIGS:
        rows = load_rows(data_zip, config)
        indices = random.Random(SEED).sample(range(len(rows)), SAMPLES_PER_DATASET)
        for index in indices:
            row = rows[index]
            context = as_text(row.get("context"))
            official_length = integer(row.get("length"))
            selected.append({
                "dataset": f"THUDM/LongBench-E/{config}/{SPLIT}",
                "config": config,
                "selection_index": index,
                "sample_id": as_text(row.get("_id")),
                "question": as_text(row.get("input")),
                "answers": as_answers(row.get("answers")),
                "context": context,
                # LongBench-E's official bucket is based on the row's length field.
                "context_length": official_length,
                "context_char_length": len(context),
                "context_hash": hashlib.sha256(context.encode("utf-8")).hexdigest(),
                "length_bucket": length_bucket(official_length),
            })
    return selected


def task_semantics(config: str, question: str) -> tuple[str, str, list[str]]:
    if config == "hotpotqa_e":
        text = (
            "Answer the question based on the given passages. Only give me the answer "
            "and do not output any other words.\n\n"
            f"Question: {question}"
        )
        return text, text, [
            "Use only the given passages.",
            "Return only the direct answer to the question.",
            "Do not output explanations, reasoning, Markdown, reports, or additional text.",
            "Do not use external search.",
        ]
    if config == "gov_report_e":
        text = "You are given a report by a government agency. Write a one-page summary of the report."
        return text, text, [
            "Summarize only the given government report.",
            "Return the requested one-page summary.",
            "Do not use external search.",
        ]
    if config == "passage_retrieval_en_e":
        text = (
            "Here are 30 paragraphs from Wikipedia, along with an abstract. Please determine "
            "which paragraph the abstract is from. Return only the paragraph identifier in the "
            f"format \"Paragraph 1\", \"Paragraph 2\", etc.\n\nAbstract:\n{question}"
        )
        return text, text, [
            "Use only the given paragraphs and abstract.",
            "Return only the paragraph identifier in the format Paragraph N.",
            "Do not output explanations, reasoning, Markdown, or additional text.",
            "Do not use external search.",
        ]
    raise SmokeFailure("DATASET", f"unsupported LongBench-E config: {config}")


def build_payload(sample: dict[str, Any], *, client_request_id: str) -> dict[str, Any]:
    task_goal, user_intent, constraints = task_semantics(sample["config"], sample["question"])
    title = f"LongBench-E {sample['config']} Smoke Test"
    return {
        "title": title,
        "domain": "general",
        "intent": "general",
        "reviewMode": "auto",
        "enabledPluginIds": [],
        "clientRequestId": client_request_id,
        "input": {
            "taskName": title,
            "taskGoal": task_goal,
            "userIntent": user_intent,
            "question": sample["question"],
            "materialText": sample["context"],
            "constraints": constraints,
            "expectedArtifacts": ["final_answer"],
            "planningMode": "dynamic",
            "planningSeed": SEED,
            "thinkingMode": THINKING_MODE,
            "webSearchEnabled": False,
        },
    }


def error_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = response.text[:300]
    if isinstance(body, dict):
        for key in ("message", "detail", "error"):
            if body.get(key):
                return str(body[key])[:300]
    return str(body)[:300]


def request_json(client: httpx.Client, method: str, path: str, *, json_body: Any = None) -> dict[str, Any]:
    try:
        response = client.request(method, path, json=json_body)
    except httpx.HTTPError as exc:
        raise SmokeFailure("HTTP", f"{method} {path} transport error: {type(exc).__name__}: {exc}") from exc
    if response.status_code in {401, 403}:
        raise SmokeFailure("AUTH", f"{method} {path} returned HTTP {response.status_code}: {error_text(response)}")
    if response.status_code < 200 or response.status_code >= 300:
        raise SmokeFailure("HTTP", f"{method} {path} returned HTTP {response.status_code}: {error_text(response)}")
    try:
        body = response.json()
    except ValueError as exc:
        raise SmokeFailure("HTTP", f"{method} {path} returned non-JSON response") from exc
    if not isinstance(body, dict):
        raise SmokeFailure("HTTP", f"{method} {path} returned a non-object JSON response")
    return body


def formal_final_answer(output_payload: Any) -> tuple[str | None, str, list[str]]:
    """Read only the formal final_answer field or a directly returned string."""
    content = output_payload.get("content") if isinstance(output_payload, dict) else output_payload
    content_type = type(content).__name__
    keys = sorted(content.keys()) if isinstance(content, dict) else []
    if isinstance(content, str):
        return content, content_type, keys
    if isinstance(content, dict) and isinstance(content.get("final_answer"), str):
        return content["final_answer"], content_type, keys
    return None, content_type, keys


def normalize_answer(value: str) -> str:
    text = value.lower()
    text = "".join(" " if char in string.punctuation else char for char in text)
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    return " ".join(text.split())


def token_f1(prediction: str, reference: str) -> float:
    predicted = normalize_answer(prediction).split()
    expected = normalize_answer(reference).split()
    if not predicted and not expected:
        return 1.0
    if not predicted or not expected:
        return 0.0
    overlap = sum((Counter(predicted) & Counter(expected)).values())
    if not overlap:
        return 0.0
    precision = overlap / len(predicted)
    recall = overlap / len(expected)
    return 2 * precision * recall / (precision + recall)


def rouge_l(prediction: str, reference: str) -> float:
    return float(Rouge().get_scores(prediction, reference, avg=True)["rouge-l"]["f"])


def retrieval_accuracy(prediction: str, reference: str) -> float:
    target = re.search(r"Paragraph (\d+)", reference)
    if target is None:
        return 0.0
    numbers = re.findall(r"\d+", prediction)
    return 1.0 if target.group(1) in numbers and len(numbers) == 1 else 0.0


def score(config: str, prediction: str | None, answers: list[str]) -> tuple[str, float | None]:
    if not isinstance(prediction, str):
        return {
            "hotpotqa_e": "hotpotqa_f1",
            "gov_report_e": "gov_report_rouge_l",
            "passage_retrieval_en_e": "passage_retrieval_en_accuracy",
        }[config], None
    if config == "hotpotqa_e":
        return "hotpotqa_f1", max((token_f1(prediction, answer) for answer in answers), default=0.0)
    if config == "gov_report_e":
        return "gov_report_rouge_l", max((rouge_l(prediction, answer) for answer in answers), default=0.0)
    if config == "passage_retrieval_en_e":
        return "passage_retrieval_en_accuracy", max(
            (retrieval_accuracy(prediction, answer) for answer in answers), default=0.0
        )
    raise SmokeFailure("SCORER", f"unsupported scorer config: {config}")


def provenance_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    raw_events = payload.get("events")
    if isinstance(raw_events, list):
        for item in raw_events:
            if not isinstance(item, dict):
                continue
            event_payload = item.get("payload") if isinstance(item.get("payload"), dict) else item
            if str(event_payload.get("eventId") or "").startswith("cons_"):
                events.append(event_payload)
    elif isinstance(payload.get("consumptions"), list):
        events = [item for item in payload["consumptions"] if isinstance(item, dict)]
    available = sum(integer(item.get("tokensAvailable")) for item in events)
    delivered = sum(integer(item.get("tokensDelivered")) for item in events)
    return {
        "event_count": len(events),
        "tokens_available_est": available,
        "tokens_delivered_est": delivered,
        "payload_reduction": None if available == 0 else 1 - delivered / available,
        "integrity": payload.get("integrityStatus", "unknown"),
    }


def model_usage(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("usage") if isinstance(payload.get("usage"), dict) else payload
    return {
        "input_tokens": integer(raw.get("inputTokens", raw.get("input_tokens"))),
        "output_tokens": integer(raw.get("outputTokens", raw.get("output_tokens"))),
        "cache_read_tokens": integer(raw.get("cacheReadTokens", raw.get("cache_read_tokens"))),
        "cache_write_tokens": integer(raw.get("cacheWriteTokens", raw.get("cache_write_tokens"))),
        "reasoning_tokens": integer(raw.get("reasoningTokens", raw.get("reasoning_tokens"))),
        "total_tokens": integer(raw.get("totalTokens", raw.get("total_tokens"))),
        "call_count": integer(raw.get("callCount", raw.get("call_count"))),
        "retry_count": integer(raw.get("retryCount", raw.get("retry_count"))),
        "latency_ms": integer(raw.get("latencyMs", raw.get("latency_ms"))),
        "usage_complete": bool(raw.get("usageComplete", raw.get("usage_complete"))),
    }


def call_usage_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    nonempty = 0
    for item in items:
        usage = item.get("usage") if isinstance(item, dict) and isinstance(item.get("usage"), dict) else {}
        if any(integer(usage.get(key)) > 0 for key in ("inputTokens", "outputTokens", "totalTokens")):
            nonempty += 1
    return {
        "usage_call_items": len(items),
        "usage_calls_with_nonempty_usage": nonempty,
        "provider_usage_all_nonempty": bool(items) and nonempty == len(items),
        "calls": [
            {
                "provider": item.get("provider"),
                "model": item.get("model"),
                "usage": item.get("usage"),
                "latencyMs": item.get("latencyMs"),
                "finishReason": item.get("finishReason"),
            }
            for item in items if isinstance(item, dict)
        ],
    }


def base_result(sample: dict[str, Any]) -> dict[str, Any]:
    metric, _ = score(sample["config"], None, sample["answers"])
    return {
        "dataset": sample["dataset"],
        "config": sample["config"],
        "split": SPLIT,
        "seed": SEED,
        "thinking_mode": THINKING_MODE,
        "selection_index": sample["selection_index"],
        "sample_id": sample["sample_id"],
        "context_length": sample["context_length"],
        "context_char_length": sample["context_char_length"],
        "context_hash": sample["context_hash"],
        "length_bucket": sample["length_bucket"],
        "question": sample["question"],
        "reference": sample["answers"],
        "mission_id": None,
        "run_id": None,
        "run_status": None,
        "prediction": None,
        "output_content_type": None,
        "output_content_keys": [],
        "quality_metric": metric,
        "quality_score": None,
        "prediction_extraction_status": None,
        "wall_latency_ms": None,
        "model_usage": {},
        "provider_usage": {},
        "communication": {},
        "provenance_integrity": None,
        "error_stage": None,
        "error": None,
    }


def run_one(client: httpx.Client, sample: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    result = base_result(sample)
    started = time.monotonic()
    try:
        request_id = f"longbench-e-smoke-{SEED}-{sample['config']}-index-{sample['selection_index']}-p0-correctness"
        payload = build_payload(sample, client_request_id=request_id)
        created = request_json(client, "POST", "/ai/agentos/v2/missions", json_body=payload)
        result["mission_id"] = created.get("missionId")
        result["run_id"] = created.get("runId")
        if not result["mission_id"] or not result["run_id"]:
            raise SmokeFailure("MISSION_CREATE", "Mission response did not contain missionId and runId")

        deadline = time.monotonic() + args.timeout_seconds
        while True:
            run_payload = request_json(client, "GET", f"/ai/agentos/v2/runs/{result['run_id']}")
            status = str(run_payload.get("status") or "").strip().lower()
            result["run_status"] = status or None
            if status in TERMINAL_STATUSES:
                break
            if status not in KNOWN_STATUSES:
                raise SmokeFailure("RUNTIME", f"Run returned unknown status: {status or '<missing>'}")
            if time.monotonic() >= deadline:
                raise SmokeFailure("TIMEOUT", f"Run did not reach a terminal state within {args.timeout_seconds} seconds")
            time.sleep(args.poll_interval_seconds)

        if result["run_status"] != "completed":
            raise SmokeFailure("RUNTIME", f"Run ended in {result['run_status']} state")
        output_ref = run_payload.get("outputRef")
        if not output_ref:
            raise SmokeFailure("OUTPUT", "completed Run did not contain outputRef")
        output_payload = request_json(client, "GET", f"/ai/agentos/v2/runs/{result['run_id']}/outputs/{output_ref}")
        prediction, content_type, content_keys = formal_final_answer(output_payload)
        result["prediction"] = prediction
        result["output_content_type"] = content_type
        result["output_content_keys"] = content_keys
        if isinstance(prediction, str) and prediction.strip():
            result["prediction_extraction_status"] = "PASS"
        else:
            result["prediction_extraction_status"] = "MISSING_FINAL_ANSWER"
            result["error_stage"] = "OUTPUT_EXTRACTION"
        metric, quality = score(sample["config"], prediction, sample["answers"])
        result["quality_metric"] = metric
        result["quality_score"] = quality if quality is not None else 0.0
    except SmokeFailure as exc:
        result["error_stage"] = result["error_stage"] or exc.stage
        result["error"] = exc.message
    except Exception as exc:  # keep this sample in the output instead of deleting it
        result["error_stage"] = "ENVIRONMENT"
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        result["wall_latency_ms"] = int((time.monotonic() - started) * 1000)

    run_id = result.get("run_id")
    if run_id:
        try:
            result["model_usage"] = model_usage(
                request_json(client, "GET", f"/ai/agentos/v2/runs/{run_id}/resource-usage")
            )
        except SmokeFailure as exc:
            result["usage_error"] = exc.message
        try:
            result["provider_usage"] = call_usage_metrics(
                request_json(client, "GET", f"/ai/agentos/v2/runs/{run_id}/resource-usage/calls")
            )
        except SmokeFailure as exc:
            result["provider_usage_error"] = exc.message
        try:
            provenance = provenance_metrics(
                request_json(client, "GET", f"/ai/agentos/v2/runs/{run_id}/provenance")
            )
            result["communication"] = {
                key: provenance[key]
                for key in ("event_count", "tokens_available_est", "tokens_delivered_est", "payload_reduction")
            }
            result["provenance_integrity"] = provenance["integrity"]
        except SmokeFailure as exc:
            result["provenance_error"] = exc.message
    if result.get("error") is None and result.get("prediction_extraction_status") != "PASS":
        result["error"] = "formal final_answer was not available"
    return result


def mean_or_none(values: list[float | int]) -> float | None:
    return float(mean(values)) if values else None


def summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [item for item in results if item.get("run_status") == "completed"]
    scorable = [item for item in results if item.get("prediction_extraction_status") == "PASS"]
    by_dataset: dict[str, Any] = {}
    for config in CONFIGS:
        items = [item for item in results if item.get("config") == config]
        completed_items = [item for item in items if item.get("run_status") == "completed"]
        scores = [item["quality_score"] for item in items if isinstance(item.get("quality_score"), (int, float))]
        e2e = [item["wall_latency_ms"] for item in items if isinstance(item.get("wall_latency_ms"), (int, float))]
        tokens = [item["model_usage"].get("total_tokens") for item in items if isinstance(item.get("model_usage", {}).get("total_tokens"), (int, float))]
        reductions = [item["communication"].get("payload_reduction") for item in items if isinstance(item.get("communication", {}).get("payload_reduction"), (int, float))]
        by_dataset[config] = {
            "submitted": len(items),
            "completed": len(completed_items),
            "scorable": len([item for item in items if item.get("prediction_extraction_status") == "PASS"]),
            "completion_rate": len(completed_items) / SAMPLES_PER_DATASET,
            "mean_quality_score": mean_or_none(scores),
            "mean_e2e_latency_ms": mean_or_none(e2e),
            "mean_total_tokens": mean_or_none(tokens),
            "mean_communication_reduction": mean_or_none(reductions),
            "provider_usage_all_nonempty_rate": mean_or_none([
                1 if item.get("provider_usage", {}).get("provider_usage_all_nonempty") else 0
                for item in items if item.get("provider_usage")
            ]),
            "provenance_valid_rate": mean_or_none([
                1 if item.get("provenance_integrity") == "valid" else 0
                for item in items if item.get("provenance_integrity") is not None
            ]),
        }
    all_usage_ok = all(
        item.get("provider_usage", {}).get("provider_usage_all_nonempty")
        for item in results if item.get("run_id")
    ) and any(item.get("run_id") for item in results)
    all_provenance_valid = all(item.get("provenance_integrity") == "valid" for item in results)
    smoke_pass = len(results) == 6 and len(completed) == 6 and len(scorable) == 6 and all_usage_ok and all_provenance_valid
    return {
        "status": "SMOKE_6_PASS" if smoke_pass else "SMOKE_6_FAIL",
        "seed": SEED,
        "thinking_mode": THINKING_MODE,
        "submitted": len(results),
        "completed": len(completed),
        "scorable": len(scorable),
        "by_dataset": by_dataset,
        "provider_usage_all_model_calls_nonempty": all_usage_ok,
        "provenance_all_valid": all_provenance_valid,
        "error_stages": dict(Counter(item["error_stage"] for item in results if item.get("error_stage"))),
    }


def print_selection(samples: list[dict[str, Any]]) -> None:
    print("FIXED_LONG_BENCH_E_SELECTION")
    for sample in samples:
        print(json.dumps({key: sample[key] for key in (
            "config", "selection_index", "sample_id", "context_length", "context_hash", "length_bucket",
        )}, ensure_ascii=True))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    parser.add_argument("--data-zip", type=Path, default=DEFAULT_DATA_ZIP)
    parser.add_argument("--result-path", type=Path, default=DEFAULT_RESULT_PATH)
    parser.add_argument("--summary-path", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--token-file", default=".secrets/kinlin-win-p1-001/ai_internal_token")
    parser.add_argument("--user-id", default="user_local")
    parser.add_argument("--user-subject", default="local")
    parser.add_argument("--user-role", default="user")
    parser.add_argument("--poll-interval-seconds", type=float, default=3.0)
    parser.add_argument("--timeout-seconds", type=float, default=20 * 60)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    samples = select_samples(args.data_zip)
    if len(samples) != 6:
        raise SmokeFailure("DATASET", f"expected 6 selected samples, got {len(samples)}")
    print_selection(samples)
    if args.dry_run:
        return 0

    args.result_path.parent.mkdir(parents=True, exist_ok=True)
    args.summary_path.parent.mkdir(parents=True, exist_ok=True)
    headers: dict[str, str]
    try:
        token = Path(args.token_file).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SmokeFailure("AUTH", f"unable to read internal service token: {type(exc).__name__}") from exc
    if len(token) < 32:
        raise SmokeFailure("AUTH", "internal service token is missing or invalid")
    headers = {
        "X-Internal-Service-Token": token,
        "X-Authenticated-User-Id": args.user_id,
        "X-Authenticated-User-Subject": args.user_subject,
        "X-Authenticated-User-Role": args.user_role,
        "Accept": "application/json",
    }
    timeout = httpx.Timeout(connect=15.0, read=120.0, write=120.0, pool=15.0)
    results: list[dict[str, Any]] = []
    with args.result_path.open("w", encoding="utf-8") as output_file:
        with httpx.Client(base_url=args.base_url.rstrip("/"), headers=headers, timeout=timeout) as client:
            for ordinal, sample in enumerate(samples, start=1):
                print(f"RUN {ordinal}/6 {sample['config']} index={sample['selection_index']} id={sample['sample_id']}")
                result = run_one(client, sample, args)
                results.append(result)
                output_file.write(json.dumps(result, ensure_ascii=False) + "\n")
                output_file.flush()
                print(json.dumps({
                    "run_id": result.get("run_id"),
                    "status": result.get("run_status"),
                    "quality_score": result.get("quality_score"),
                    "error_stage": result.get("error_stage"),
                    "error": result.get("error"),
                }, ensure_ascii=False))
    report = summary(results)
    args.summary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "SMOKE_6_PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SmokeFailure as exc:
        print(f"{exc.stage}: {exc.message}", file=sys.stderr)
        raise SystemExit(1)
