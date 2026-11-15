"""图像入口必须拒绝缺步、额外重试和与清理计数矛盾的实验数据。"""

import csv
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


def load_module():
    path = Path(__file__).resolve().parents[3] / "evals/safe/exam/gen_fig_https_transport.py"
    spec = importlib.util.spec_from_file_location("safe_https_figures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evidence(directory, mutate=None):
    runs = [dict(case_id="synthetic-00", repeat=0, method=method, generated_tokens=2,
        prompt_tokens=3, finish_reason="length", output_ids_sha256="a" * 64,
        ttft_ms=10.0, tpot_ms=3.0, e2e_ms=14.0) for method in ("full", "https")]
    http = [dict(case_id="synthetic-00", repeat=0, operation=operation, request_bytes=size,
        response_bytes=140, status_code=200, elapsed_ms=3.0, step="", phase="", position_offset="", activation_raw_bytes="")
        for operation, size in (("create", 86), ("step", 576), ("step", 536), ("close_session", 0))]
    http[1].update(step=0, phase="prefill", position_offset=0, activation_raw_bytes=48)
    http[2].update(step=1, phase="decode", position_offset=3, activation_raw_bytes=16)
    report = dict(schema_version="safe-https-loopback-v1", status="passed", network="real-tcp-tls-loopback",
        independent_suffix_process=True, samples=1, repeats=1, hidden_size=4, max_new_tokens=2,
        matched_tokens=2, exact_sequence_matches=1, warmup_tokens=4, prefix_kv_empty=True,
        worker=dict(status="passed", active_kv=0, forwards=6, created_kv=3, released_kv=3))
    if mutate:
        mutate(report, runs, http)
    for name, rows in (("runs.csv", runs), ("http.csv", http)):
        with (directory / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    report["data_sha256"] = {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in ("runs.csv", "http.csv")}
    (directory / "report.json").write_text(json.dumps(report), encoding="utf-8")


def test_complete_evidence_is_accepted(tmp_path):
    evidence(tmp_path)
    report, runs, http = load_module().load_verified_data(tmp_path)
    assert len(runs) == 2 and len(http) == 4
    assert [row.get("phase") for row in http] == ["", "prefill", "decode", ""]


@pytest.mark.parametrize("mutate", [
    lambda report, runs, http: http.pop(1),
    lambda report, runs, http: http.insert(2, dict(http[1])),
    lambda report, runs, http: runs[1].update(output_ids_sha256="b" * 64),
    lambda report, runs, http: report["worker"].update(forwards=7),
    lambda report, runs, http: report["worker"].update(active_kv=1),
    lambda report, runs, http: http[1].update(request_bytes=20),
    lambda report, runs, http: http[1].update(elapsed_ms=float("nan")),
    lambda report, runs, http: http[2].update(step=0),
    lambda report, runs, http: http[2].update(phase="prefill"),
    lambda report, runs, http: http[2].update(position_offset=0),
    lambda report, runs, http: runs[1].update(tpot_ms=1000),
    lambda report, runs, http: runs[1].update(tpot_ms=""),
    lambda report, runs, http: report.update(max_new_tokens=3),
    lambda report, runs, http: report.update(status="failed"),
])
def test_inconsistent_evidence_is_rejected_even_with_updated_hashes(tmp_path, mutate):
    evidence(tmp_path, mutate)
    with pytest.raises(ValueError):
        load_module().load_verified_data(tmp_path)


def test_modified_raw_data_is_rejected(tmp_path):
    evidence(tmp_path)
    with (tmp_path / "http.csv").open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(ValueError, match="哈希"):
        load_module().load_verified_data(tmp_path)
