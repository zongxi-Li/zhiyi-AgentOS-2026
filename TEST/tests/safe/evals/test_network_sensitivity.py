"""网络敏感性分析的纯规则测试；不启动模型、不访问网络。"""

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from components.safe.infrastructure.experiments.network_sensitivity import (
    NetworkScenario,
    calculate_transfer_ms,
    model_run,
    summarize_scenario,
)


def row(*, step=0, request=1000):
    return {"step": str(step), "request_json_bytes": str(request)}


def run(*, e2e=100.0, ttft=20.0, tpot=10.0, tokens=2):
    return {"case_id": "synthetic-00", "repeat": "0", "method": "split",
        "e2e_ms": str(e2e), "ttft_ms": str(ttft), "tpot_ms": str(tpot),
        "generated_tokens": str(tokens)}


def test_transfer_uses_round_trip_latency_and_both_payload_directions():
    scenario = NetworkScenario("测试", bandwidth_mbps=10.0, rtt_ms=20.0, response_bytes=200)
    # 两次请求各计一次20ms RTT，另加两个方向的有效载荷串行传输时间。
    assert calculate_transfer_ms([row(request=1000), row(step=1, request=2000)], scenario) == pytest.approx(
        40.0 + (1000 + 2000 + 400) * 8 / (10.0 * 1000), rel=1e-9)


def test_model_run_preserves_measured_values_and_adds_network_cost():
    scenario = NetworkScenario("测试", bandwidth_mbps=100.0, rtt_ms=5.0, response_bytes=100)
    modeled = model_run(run(), [row(request=1000), row(step=1, request=2000)], scenario)
    assert modeled["modeled_e2e_ms"] == pytest.approx(100.0 + 10.0 + 3200 * 8 / 100000, rel=1e-9)
    assert modeled["modeled_ttft_ms"] == pytest.approx(20.0 + 5.0 + 1100 * 8 / 100000, rel=1e-9)
    assert modeled["modeled_tpot_ms"] == pytest.approx(10.0 + 5.0 + 2100 * 8 / 100000, rel=1e-9)
    assert modeled["network_bytes"] == 3200
    assert modeled["network_requests"] == 2
    assert modeled["bandwidth_mbps"] == 100.0
    assert modeled["rtt_ms"] == 5.0


def test_summary_has_quantiles_and_rejects_missing_metric():
    scenario = NetworkScenario("测试", bandwidth_mbps=100.0, rtt_ms=5.0, response_bytes=100)
    values = [model_run(run(e2e=value), [row(request=1000), row(step=1, request=1000)], scenario)
              for value in (100, 200, 300)]
    summary = summarize_scenario(values, scenario)
    assert summary["n"] == 3
    assert summary["modeled_e2e_ms"]["median"] == 200.0 + 10.0 + 2200 * 8 / 100000
    assert summary["network_bytes"]["median"] == 2200
    with pytest.raises(ValueError, match="缺少指标"):
        summarize_scenario([{"modeled_e2e_ms": 1.0}], scenario)


@pytest.mark.parametrize("bandwidth,rtt,response", [(0, 1, 1), (-1, 1, 1), (1, -1, 1), (1, 1, -1),
                                                     (True, 1, 1), (1, 1, True)])
def test_scenario_rejects_invalid_network_assumptions(bandwidth, rtt, response):
    with pytest.raises(ValueError):
        NetworkScenario("坏", bandwidth_mbps=bandwidth, rtt_ms=rtt, response_bytes=response)


def test_report_directory_rejects_tampered_csv(tmp_path):
    from components.safe.infrastructure.experiments.network_sensitivity import load_verified_benchmark

    source = Path(__file__).resolve().parents[4] / "docs/superpowers/reports/safe/experiments/2026-11-15-local-generation"
    if not (source / "report.json").exists():
        pytest.skip("仓库未带实验原始证据")
    for name in ("report.json", "runs.csv", "steps.csv"):
        (tmp_path / name).write_bytes((source / name).read_bytes())
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    (tmp_path / "steps.csv").write_bytes((tmp_path / "steps.csv").read_bytes() + b"x")
    with pytest.raises(ValueError, match="哈希"):
        load_verified_benchmark(tmp_path)


@pytest.mark.parametrize("bandwidth,rtt", [(float("inf"), 1), (1, float("inf")),
                                          (float("nan"), 1), (1, float("nan"))])
def test_scenario_rejects_nonfinite_parameters(bandwidth, rtt):
    with pytest.raises(ValueError):
        NetworkScenario("非有限参数", bandwidth, rtt)


@pytest.mark.parametrize("byte_count", [-1, 0, 1.5, "nan", "inf"])
def test_transfer_rejects_invalid_request_bytes(byte_count):
    with pytest.raises(ValueError):
        calculate_transfer_ms([row(request=byte_count)], NetworkScenario("测试", 10, 1))


@pytest.mark.parametrize("field,value", [("e2e_ms", "nan"), ("ttft_ms", "-1"),
                                        ("tpot_ms", "inf"), ("generated_tokens", "2.5"),
                                        ("repeat", "-1")])
def test_model_rejects_invalid_source_numbers(field, value):
    record = run()
    record[field] = value
    with pytest.raises(ValueError):
        model_run(record, [row(), row(step=1)], NetworkScenario("测试", 10, 1))


def test_model_rejects_fractional_step_without_truncating():
    with pytest.raises(ValueError):
        model_run(run(), [row(), row(step=1.5)], NetworkScenario("测试", 10, 1))


def _write_csv(path, records):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def _source(directory, *, mutation=None):
    """独立的最小配对证据，不依赖仓库中大实验产物。"""
    directory.mkdir()
    runs = []
    steps = []
    for method in ("full", "split"):
        record = run()
        record.update(method=method, prompt_tokens="3", finish_reason="eos", output_ids_sha256="a" * 64)
        runs.append(record)
        for index in range(2):
            event = row(step=index)
            event.update(case_id="synthetic-00", repeat="0", method=method,
                         phase="prefill" if index == 0 else "decode",
                         activation_raw_bytes=str((3 if index == 0 else 1) * 4))
            steps.append(event)
    if mutation:
        mutation(runs, steps)
    for name, records in (("runs.csv", runs), ("steps.csv", steps)):
        _write_csv(directory / name, records)
    report = dict(status="passed", schema_version="safe-local-benchmark-v1", samples=1, repeats=1,
                  paired_runs=1, matched_tokens=2, exact_sequence_matches=1, hidden_size=1,
                  manifest_digest="b" * 64, model_id="测试模型", cut_layer=1, total_layers=2,
                  data_sha256={name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                               for name in ("runs.csv", "steps.csv")})
    (directory / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return directory


@pytest.mark.parametrize("mutation", [
    lambda runs, steps: runs.append(dict(runs[-1])),
    lambda runs, steps: runs.pop(0),
    lambda runs, steps: runs[0].update(output_ids_sha256="c" * 64),
    lambda runs, steps: runs[-1].update(e2e_ms="nan"),
    lambda runs, steps: steps.append(dict(steps[-1])),
    lambda runs, steps: steps[-1].update(case_id="孤立步骤"),
    lambda runs, steps: steps[-1].update(step="1.5"),
    lambda runs, steps: steps[-1].update(phase="prefill"),
    lambda runs, steps: steps[-1].update(activation_raw_bytes="5"),
])
def test_source_rejects_semantic_corruption_even_with_matching_hashes(tmp_path, mutation):
    from components.safe.infrastructure.experiments.network_sensitivity import load_verified_benchmark

    with pytest.raises(ValueError):
        load_verified_benchmark(_source(tmp_path / "source", mutation=mutation))


def _script(name):
    return Path(__file__).resolve().parents[4] / "evals/safe/exam" / name


def _analyze(source, output):
    return subprocess.run([sys.executable, "-B", str(_script("analyze_network_sensitivity.py")),
                           "--input", str(source), "--output", str(output)],
                          capture_output=True, text=True, encoding="utf-8")


def test_invalid_source_does_not_leave_output_directory(tmp_path):
    output = tmp_path / "output"
    result = _analyze(tmp_path / "missing-source", output)
    assert result.returncode != 0
    assert not output.exists()


def test_cli_emits_complete_grid_with_script_fingerprint_and_refuses_overwrite(tmp_path):
    source = _source(tmp_path / "source")
    output = tmp_path / "output"
    result = _analyze(source, output)
    assert result.returncode == 0, result.stderr
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["analysis_script_sha256"] == hashlib.sha256(_script("analyze_network_sensitivity.py").read_bytes()).hexdigest()
    assert report["n_runs"] == 1
    assert report["n_scenarios"] == 6
    assert report["response_bytes_measured"] is False
    from components.safe.infrastructure.experiments.network_sensitivity import load_verified_analysis
    verified, records = load_verified_analysis(output)
    assert verified["status"] == "passed"
    assert len(records) == 6
    before = (output / "report.json").read_bytes()
    assert _analyze(source, output).returncode != 0
    assert (output / "report.json").read_bytes() == before


@pytest.mark.parametrize("corruption", ["duplicate", "summary", "formula", "assumption", "analysis_type"])
def test_plot_loader_rejects_rehashed_but_inconsistent_analysis(tmp_path, corruption):
    source = _source(tmp_path / "source")
    output = tmp_path / "output"
    result = _analyze(source, output)
    assert result.returncode == 0, result.stderr
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    with (output / "network_runs.csv").open(encoding="utf-8", newline="") as stream:
        records = list(csv.DictReader(stream))
    if corruption == "duplicate":
        records[-1] = records[0]
    elif corruption == "formula":
        records[0]["modeled_e2e_ms"] = "9999999"
    elif corruption == "assumption":
        report["response_bytes_assumption"] = 512
    elif corruption == "analysis_type":
        report["analysis_type"] = "actual_network_measurement"
    else:
        report["summaries"][0]["modeled_e2e_ms"]["median"] = 9999999
    _write_csv(output / "network_runs.csv", records)
    report["network_runs_sha256"] = hashlib.sha256((output / "network_runs.csv").read_bytes()).hexdigest()
    (output / "report.json").write_text(json.dumps(report), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("safe_network_figure_test", _script("gen_fig_network_sensitivity.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(ValueError):
        module._load(output)
