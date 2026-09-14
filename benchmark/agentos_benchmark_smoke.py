"""Run one public LongBench sample through the AgentOS HTTP API.

This is intentionally an external harness.  It does not import AgentOS
runtime code or call Planner/Runtime directly.  The default URL is suitable
for an ephemeral runner sharing the AI service network namespace; the host
gateway can be used by passing --base-url and its own authentication headers
if an authenticated gateway session is available.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
from datasets import load_dataset


DATASET = "THUDM/LongBench"
CONFIG = "hotpotqa_e"
SPLIT = "test"
SEED = 20260913
SAMPLE_INDEX = 0
TITLE = "LongBench HotpotQA Smoke Test"
CLIENT_REQUEST_ID = f"longbench-hotpotqa-smoke-{SEED}-row-{SAMPLE_INDEX}"
POLL_INTERVAL_SECONDS = 3.0
RUN_TIMEOUT_SECONDS = 20 * 60
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "superseded"}
KNOWN_STATUSES = {
    "pending",
    "planning",
    "running",
    "retrying",
    "waiting_review",
    "completed",
    "failed",
    "cancelled",
    "superseded",
}
ANSWER_FIELDS = ("answer", "finalAnswer", "final_answer", "result", "content", "summary", "report")


class SmokeFailure(RuntimeError):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.message = message


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def _as_answers(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_as_text(item) for item in value if _as_text(item).strip()]
    text = _as_text(value).strip()
    return [text] if text else []


def load_sample() -> dict[str, Any]:
    try:
        # LongBench is a public dataset repository with its own loader script;
        # datasets 2.x requires this explicit opt-in for custom dataset code.
        dataset = load_dataset(DATASET, CONFIG, split=SPLIT, trust_remote_code=True)
        row = dataset[SAMPLE_INDEX]
    except Exception as exc:
        raise SmokeFailure("DATASET", f"unable to load {DATASET}/{CONFIG}/{SPLIT}: {type(exc).__name__}: {exc}") from exc

    context = _as_text(row.get("context"))
    question = _as_text(row.get("input") or row.get("question") or row.get("query"))
    answers = _as_answers(row.get("answers") if row.get("answers") is not None else row.get("answer"))
    sample_id = _as_text(row.get("_id") or row.get("id") or f"row-{SAMPLE_INDEX}")
    if not context or not question or not answers:
        raise SmokeFailure("DATASET", "sample is missing context, input/question, or reference answers")

    return {
        "sample_id": sample_id,
        "context": context,
        "question": question,
        "answers": answers,
        "context_length": len(context),
        "context_hash": hashlib.sha256(context.encode("utf-8")).hexdigest(),
    }


def build_payload(
    sample: dict[str, Any], *, client_request_id: str = CLIENT_REQUEST_ID
) -> dict[str, Any]:
    """Map the sampled question into both Planner-facing semantic fields."""
    question = sample["question"]
    protocol_instruction = (
        "Answer the question based on the given passages.\n"
        f"Question: {question}\n"
        "Only give me the answer itself and do not output any other words. "
        "Do not output explanations, reasoning, Markdown, reports, or additional text. "
        "Do not use external search."
    )
    task_goal = protocol_instruction
    user_intent = protocol_instruction
    return {
        "title": TITLE,
        "domain": "general",
        "intent": "general",
        "reviewMode": "auto",
        "enabledPluginIds": [],
        "clientRequestId": client_request_id,
        "input": {
            "taskName": TITLE,
            "taskGoal": task_goal,
            "userIntent": user_intent,
            "question": question,
            "materialText": sample["context"],
            "constraints": ["仅使用给定材料", "不要使用外部搜索", "直接回答问题"],
            "expectedArtifacts": ["final_answer"],
            "planningMode": "dynamic",
            "planningSeed": SEED,
            "webSearchEnabled": False,
        },
    }


def normalize_answer(value: str) -> str:
    text = value.lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    return " ".join(text.split())


def token_f1(prediction: str, reference: str) -> float:
    predicted_tokens = normalize_answer(prediction).split()
    reference_tokens = normalize_answer(reference).split()
    if not predicted_tokens and not reference_tokens:
        return 1.0
    if not predicted_tokens or not reference_tokens:
        return 0.0
    overlap = sum((Counter(predicted_tokens) & Counter(reference_tokens)).values())
    if not overlap:
        return 0.0
    precision = overlap / len(predicted_tokens)
    recall = overlap / len(reference_tokens)
    return 2 * precision * recall / (precision + recall)


def extract_prediction(payload: Any) -> str | None:
    """Deterministic one-level extractor for the final output contract."""
    content = payload.get("content") if isinstance(payload, dict) and "content" in payload else payload
    if isinstance(content, str):
        return content
    if not isinstance(content, dict):
        return None
    for field in ANSWER_FIELDS:
        value = content.get(field)
        if isinstance(value, str):
            return value
    return None


def _integer(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _error_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = response.text[:300]
    if isinstance(body, dict):
        for key in ("message", "detail", "error"):
            if body.get(key):
                return str(body[key])[:300]
    return str(body)[:300]


def _request_json(client: httpx.Client, method: str, path: str, *, json_body: Any = None) -> dict[str, Any]:
    try:
        response = client.request(method, path, json=json_body)
    except httpx.HTTPError as exc:
        raise SmokeFailure("HTTP", f"{method} {path} transport error: {type(exc).__name__}: {exc}") from exc
    if response.status_code in {401, 403}:
        raise SmokeFailure("AUTH", f"{method} {path} returned HTTP {response.status_code}: {_error_text(response)}")
    if response.status_code < 200 or response.status_code >= 300:
        raise SmokeFailure("HTTP", f"{method} {path} returned HTTP {response.status_code}: {_error_text(response)}")
    try:
        body = response.json()
    except ValueError as exc:
        raise SmokeFailure("HTTP", f"{method} {path} returned non-JSON response") from exc
    if not isinstance(body, dict):
        raise SmokeFailure("HTTP", f"{method} {path} returned a non-object JSON response")
    return body


def _provenance_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    raw_events = payload.get("events")
    if isinstance(raw_events, list):
        for item in raw_events:
            if not isinstance(item, dict):
                continue
            event_payload = item.get("payload") if isinstance(item.get("payload"), dict) else item
            event_id = str(event_payload.get("eventId") or "")
            if event_id.startswith("cons_"):
                events.append(event_payload)
    elif isinstance(payload.get("consumptions"), list):
        events = [item for item in payload["consumptions"] if isinstance(item, dict)]

    available = sum(_integer(item.get("tokensAvailable")) for item in events)
    delivered = sum(_integer(item.get("tokensDelivered")) for item in events)
    reduction = None if available == 0 else 1 - delivered / available
    return {
        "event_count": len(events),
        "tokens_available_est": available,
        "tokens_delivered_est": delivered,
        "payload_reduction": reduction,
        "integrity": payload.get("integrityStatus", "unknown"),
    }


def _model_usage(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("usage") if isinstance(payload.get("usage"), dict) else payload
    usage_complete = raw.get("usageComplete", raw.get("usage_complete"))
    usage_complete = usage_complete if isinstance(usage_complete, bool) else False
    call_count = _integer(raw.get("callCount", raw.get("call_count")))
    return {
        "input_tokens": _integer(raw.get("inputTokens", raw.get("input_tokens"))),
        "output_tokens": _integer(raw.get("outputTokens", raw.get("output_tokens"))),
        "cache_read_tokens": _integer(raw.get("cacheReadTokens", raw.get("cache_read_tokens"))),
        "cache_write_tokens": _integer(raw.get("cacheWriteTokens", raw.get("cache_write_tokens"))),
        "reasoning_tokens": _integer(raw.get("reasoningTokens", raw.get("reasoning_tokens"))),
        "total_tokens": _integer(raw.get("totalTokens", raw.get("total_tokens"))),
        "call_count": call_count,
        "retry_count": _integer(raw.get("retryCount", raw.get("retry_count"))),
        "latency_ms": _integer(raw.get("latencyMs", raw.get("latency_ms"))),
        "usage_complete": usage_complete,
        "usage_observed": call_count > 0,
    }


def _question_pipeline_status(
    *, question: str, history_payload: dict[str, Any]
) -> str:
    """Verify only that the persisted Planner-facing objective contains the question."""
    history_input = (
        history_payload.get("input")
        if isinstance(history_payload.get("input"), dict)
        else {}
    )
    objective = history_input.get("userIntent") or history_input.get("taskGoal") or ""
    return "PASS" if question in _as_text(objective) else "BROKEN"


def _scorable_output_pipeline_status(prediction: str | None) -> str:
    """Require a direct textual answer from the formal final output boundary."""
    return "PASS" if isinstance(prediction, str) and prediction.strip() else "BROKEN"


def _usage_pipeline_status(usage: dict[str, Any]) -> str:
    observed_tokens = sum(
        _integer(usage.get(key))
        for key in ("input_tokens", "output_tokens", "total_tokens")
    )
    return "PASS" if observed_tokens > 0 else "BROKEN"


def _print_mission_preflight(sample: dict[str, Any], payload: dict[str, Any]) -> None:
    mission_input = payload["input"]
    print("LONG_BENCH_QUESTION")
    print(sample["question"])
    print("MISSION_TASK_GOAL")
    print(mission_input["taskGoal"])
    print("MISSION_USER_INTENT")
    print(mission_input["userIntent"])
    print("MISSION_EXPECTED_ARTIFACTS")
    print(json.dumps(mission_input["expectedArtifacts"], ensure_ascii=False))
    if any(
        sample["question"] not in mission_input[field]
        for field in ("taskGoal", "userIntent")
    ):
        raise SmokeFailure(
            "MISSION_INPUT",
            "question is not present in both Planner-facing semantic fields",
        )


def print_report(result: dict[str, Any], *, smoke_pass: bool) -> None:
    usage = result.get("model_usage") or {}
    communication = result.get("communication") or {}
    print("================================")
    print("AgentOS Benchmark Smoke")
    print("================================")
    print(f"Dataset: {result.get('dataset')}")
    print(f"Sample ID: {result.get('sample_id')}")
    print(f"Context length: {result.get('context_length')}")
    print()
    print(f"Mission ID: {result.get('mission_id')}")
    print(f"Run ID: {result.get('run_id')}")
    print(f"Run status: {result.get('run_status')}")
    print()
    print(f"Reference: {result.get('answers')}")
    print(f"Prediction: {result.get('prediction')}")
    print(f"HotpotQA F1: {result.get('quality_score')}")
    print(f"Output content type: {result.get('output_content_type')}")
    print(f"Output content keys: {result.get('output_content_keys')}")
    print()
    print(f"E2E wall latency: {result.get('wall_latency_ms')} ms")
    print(f"Model latency: {usage.get('latency_ms')} ms")
    print(f"Model calls: {usage.get('call_count')}")
    print(f"Retry count: {usage.get('retry_count')}")
    print(f"Provider input tokens: {usage.get('input_tokens')}")
    print(f"Provider output tokens: {usage.get('output_tokens')}")
    print(f"Provider total tokens: {usage.get('total_tokens')}")
    print(f"Usage complete: {usage.get('usage_complete')} (observed: {usage.get('usage_observed')})")
    print()
    print(f"Communication events: {communication.get('event_count')}")
    print(f"Communication available est: {communication.get('tokens_available_est')}")
    print(f"Communication delivered est: {communication.get('tokens_delivered_est')}")
    print(f"Communication payload reduction: {communication.get('payload_reduction')}")
    print(f"Provenance integrity: {result.get('provenance_integrity')}")
    print()
    print(f"QUESTION_INPUT_PIPELINE = {result.get('question_pipeline')}")
    print(f"SCORABLE_OUTPUT_PIPELINE = {result.get('scorable_output_pipeline')}")
    print(f"USAGE_PIPELINE = {result.get('usage_pipeline')}")
    print()
    print("================================")
    print("Smoke Result")
    print("================================")
    print("SMOKE_PASS" if smoke_pass else "SMOKE_FAIL")
    if not smoke_pass:
        print(f"error_stage: {result.get('error_stage')}")
        print(f"error: {result.get('error')}")
    print("================================")


def run(args: argparse.Namespace) -> int:
    result: dict[str, Any] = {
        "dataset": f"{DATASET}/{CONFIG}/{SPLIT}",
        "sample_id": None,
        "context_length": None,
        "context_hash": None,
        "mission_id": None,
        "run_id": None,
        "run_status": None,
        "prediction": None,
        "output_content_type": None,
        "output_content_keys": [],
        "answers": [],
        "quality_metric": "hotpotqa_f1",
        "quality_score": None,
        "wall_latency_ms": None,
        "model_usage": {},
        "communication": {},
        "provenance_integrity": None,
        "question_pipeline": None,
        "scorable_output_pipeline": None,
        "usage_pipeline": None,
        "error_stage": None,
        "error": None,
    }
    result_path = Path(args.result_path)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    submit_started_at: float | None = None

    try:
        sample = load_sample()
        result.update({
            "sample_id": sample["sample_id"],
            "context_length": sample["context_length"],
            "context_hash": sample["context_hash"],
            "answers": sample["answers"],
        })
        print(f"sample id: {sample['sample_id']}")
        print(f"context length: {sample['context_length']}")
        print(f"question/input: {sample['question']}")
        print(f"reference answers: {sample['answers']}")
        client_request_id = args.client_request_id or f"{CLIENT_REQUEST_ID}-{int(time.time())}"
        payload = build_payload(sample, client_request_id=client_request_id)
        _print_mission_preflight(sample, payload)

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
        with httpx.Client(base_url=args.base_url.rstrip("/"), headers=headers, timeout=timeout) as client:
            submit_started_at = time.monotonic()
            created = _request_json(client, "POST", "/ai/agentos/v2/missions", json_body=payload)
            result["mission_id"] = created.get("missionId")
            result["run_id"] = created.get("runId")
            if not result["mission_id"] or not result["run_id"]:
                raise SmokeFailure("MISSION_CREATE", "Mission response did not contain missionId and runId")

            deadline = time.monotonic() + args.timeout_seconds
            run_payload: dict[str, Any] = created
            while True:
                run_payload = _request_json(client, "GET", f"/ai/agentos/v2/runs/{result['run_id']}")
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
                if result["run_status"] == "waiting_review":
                    raise SmokeFailure("RUNTIME", "unable_to_complete_automatically: Run is waiting_review")
                raise SmokeFailure("RUNTIME", f"Run ended in {result['run_status']} state")

            output_ref = run_payload.get("outputRef")
            if not output_ref:
                raise SmokeFailure("OUTPUT", "completed Run did not contain outputRef")
            output_payload = _request_json(client, "GET", f"/ai/agentos/v2/runs/{result['run_id']}/outputs/{output_ref}")
            output_content = output_payload.get("content")
            result["output_content_type"] = type(output_content).__name__
            result["output_content_keys"] = (
                sorted(output_content.keys())
                if isinstance(output_content, dict)
                else []
            )
            prediction = extract_prediction(output_payload)
            result["prediction"] = prediction
            if prediction is not None:
                result["quality_score"] = max(token_f1(prediction, answer) for answer in sample["answers"])

            history_payload = _request_json(
                client,
                "GET",
                f"/ai/agentos/v2/runs/{result['run_id']}/history-config",
            )
            result["question_pipeline"] = _question_pipeline_status(
                question=sample["question"], history_payload=history_payload,
            )
            result["scorable_output_pipeline"] = _scorable_output_pipeline_status(prediction)

            try:
                usage_payload = _request_json(client, "GET", f"/ai/agentos/v2/runs/{result['run_id']}/resource-usage")
            except SmokeFailure as exc:
                raise SmokeFailure("RESOURCE_USAGE", exc.message) from exc
            result["model_usage"] = _model_usage(usage_payload)
            result["usage_pipeline"] = _usage_pipeline_status(result["model_usage"])

            try:
                provenance_payload = _request_json(client, "GET", f"/ai/agentos/v2/runs/{result['run_id']}/provenance")
            except SmokeFailure as exc:
                raise SmokeFailure("PROVENANCE", exc.message) from exc
            provenance = _provenance_metrics(provenance_payload)
            result["communication"] = {
                key: provenance[key]
                for key in ("event_count", "tokens_available_est", "tokens_delivered_est", "payload_reduction")
            }
            result["provenance_integrity"] = provenance["integrity"]
    except SmokeFailure as exc:
        result["error_stage"] = exc.stage
        result["error"] = exc.message
    except (OSError, ValueError) as exc:
        result["error_stage"] = "ENVIRONMENT"
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if submit_started_at is not None:
            result["wall_latency_ms"] = int((time.monotonic() - submit_started_at) * 1000)
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    reduction = result["communication"].get("payload_reduction")
    smoke_pass = (
        result["error"] is None
        and result["run_status"] == "completed"
        and result["scorable_output_pipeline"] == "PASS"
        and result["quality_score"] is not None
        and bool(result["model_usage"])
        and (reduction is None or isinstance(reduction, (float, int)))
    )
    print_report(result, smoke_pass=smoke_pass)
    return 0 if smoke_pass else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token-file", default="/run/kinlin-secrets/ai_internal_token")
    parser.add_argument("--result-path", default="tmp/benchmark_smoke_result.json")
    parser.add_argument("--client-request-id", default=None)
    parser.add_argument("--poll-interval-seconds", type=float, default=POLL_INTERVAL_SECONDS)
    parser.add_argument("--timeout-seconds", type=float, default=RUN_TIMEOUT_SECONDS)
    parser.add_argument("--user-id", default="00000000-0000-0000-0000-000000000001")
    parser.add_argument("--user-subject", default="benchmark-smoke")
    parser.add_argument("--user-role", default="system")
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(run(parse_args()))
