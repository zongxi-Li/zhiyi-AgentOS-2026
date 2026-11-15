"""基于已测JSON步骤数据的网络敏感性模型。

这里计算的是**分析模型**，不是网络实测：把同机拆分的每步测量叠加指定
RTT和带宽下的串行请求/回执传输时间。请求体字节来自真实实验；回执大小是
显式固定的假设参数，不保证是实际大小的上界，不把模拟结果写成公网实测。
"""

from __future__ import annotations

import csv
import hashlib
from io import StringIO
import json
import math
from dataclasses import dataclass
from pathlib import Path
import statistics
from typing import Iterable


@dataclass(frozen=True)
class NetworkScenario:
    """RTT为一次请求—回执往返时间，bandwidth为单向链路额定吞吐。"""

    name: str
    bandwidth_mbps: float
    rtt_ms: float
    response_bytes: int = 256

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("网络场景名称不能为空")
        if type(self.bandwidth_mbps) not in (int, float) or isinstance(self.bandwidth_mbps, bool):
            raise ValueError("带宽必须是正数")
        if type(self.rtt_ms) not in (int, float) or isinstance(self.rtt_ms, bool):
            raise ValueError("RTT必须是非负数")
        if not math.isfinite(self.bandwidth_mbps) or not math.isfinite(self.rtt_ms):
            raise ValueError("带宽和RTT必须是有限数")
        if not self.bandwidth_mbps > 0 or not self.rtt_ms >= 0:
            raise ValueError("带宽必须为正，RTT不能为负")
        if type(self.response_bytes) is not int or self.response_bytes <= 0:
            raise ValueError("回执字节数必须是正整数")


def _number(row: dict[str, str], field: str) -> float:
    try:
        if isinstance(row[field], bool):
            raise ValueError
        value = float(row[field])
        if not math.isfinite(value) or value < 0:
            raise ValueError
        return value
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError(f"缺少指标或数值无效：{field}") from None


def _integer(row: dict, field: str, *, minimum: int = 0) -> int:
    """计数和字节只接受十进制整数；禁止通过float再int静默截断。"""
    value = row.get(field)
    if type(value) is int:
        result = value
    elif isinstance(value, str) and value.isascii() and value.isdecimal():
        result = int(value)
    else:
        raise ValueError(f"整数指标无效：{field}")
    if result < minimum:
        raise ValueError(f"整数指标超出范围：{field}")
    return result


def calculate_transfer_ms(steps: Iterable[dict[str, str]], scenario: NetworkScenario) -> float:
    rows = list(steps)
    if not rows:
        raise ValueError("网络模型需要至少一个步骤")
    request_bytes = sum(_integer(row, "request_json_bytes", minimum=1) for row in rows)
    payload_bytes = request_bytes + len(rows) * scenario.response_bytes
    result = len(rows) * scenario.rtt_ms + payload_bytes * 8 / (scenario.bandwidth_mbps * 1000)
    if not math.isfinite(result):
        raise ValueError("传输时间超出有限数范围")
    return result


def _one_step_transfer_ms(row: dict[str, str], scenario: NetworkScenario) -> float:
    return scenario.rtt_ms + (_integer(row, "request_json_bytes", minimum=1) + scenario.response_bytes) * 8 / (
        scenario.bandwidth_mbps * 1000
    )


def model_run(run: dict[str, str], steps: Iterable[dict[str, str]], scenario: NetworkScenario) -> dict[str, float | int | str | None]:
    rows = sorted(list(steps), key=lambda row: _integer(row, "step"))
    if not rows:
        raise ValueError("网络模型需要至少一个步骤")
    expected = _integer(run, "generated_tokens", minimum=1)
    if len(rows) != expected:
        raise ValueError("运行与步骤数不匹配")
    for index, row in enumerate(rows):
        if _integer(row, "step") != index:
            raise ValueError("步骤不连续")
    repeat = _integer(run, "repeat")
    measured_e2e = _number(run, "e2e_ms")
    measured_ttft = _number(run, "ttft_ms")
    measured_tpot = _number(run, "tpot_ms") if expected > 1 else None
    if expected == 1 and run.get("tpot_ms") not in (None, ""):
        raise ValueError("单token输出不能定义TPOT")
    transfer_ms = calculate_transfer_ms(rows, scenario)
    first_transfer = _one_step_transfer_ms(rows[0], scenario)
    per_token = statistics.mean(_one_step_transfer_ms(row, scenario) for row in rows[1:]) if len(rows) > 1 else first_transfer
    return {
        "case_id": run["case_id"],
        "repeat": repeat,
        "network_scenario": scenario.name,
        "bandwidth_mbps": scenario.bandwidth_mbps,
        "rtt_ms": scenario.rtt_ms,
        "response_bytes": scenario.response_bytes,
        "network_bytes": sum(_integer(row, "request_json_bytes", minimum=1) for row in rows) + len(rows) * scenario.response_bytes,
        "network_requests": len(rows),
        "first_request_json_bytes": _integer(rows[0], "request_json_bytes", minimum=1),
        "network_transfer_ms": transfer_ms,
        "measured_e2e_ms": measured_e2e,
        "measured_ttft_ms": measured_ttft,
        "measured_tpot_ms": measured_tpot,
        "modeled_e2e_ms": measured_e2e + transfer_ms,
        "modeled_ttft_ms": measured_ttft + first_transfer,
        "modeled_tpot_ms": measured_tpot + per_token if measured_tpot is not None else None,
    }


def _quantiles(values: list[float]) -> dict[str, float]:
    if not values:
        raise ValueError("缺少指标，不能统计")
    values = sorted(values)
    # 与绘图脚本的numpy.percentile(linear)保持一致，避免报告口径漂移。
    def percentile(percent: float) -> float:
        position = (len(values) - 1) * percent / 100
        lower, upper = int(position), min(int(position) + 1, len(values) - 1)
        return values[lower] + (values[upper] - values[lower]) * (position - lower)
    return {"q25": percentile(25), "median": percentile(50), "q75": percentile(75), "mean": statistics.mean(values)}


def summarize_scenario(rows: Iterable[dict[str, float | int | str]], scenario: NetworkScenario) -> dict[str, object]:
    rows = list(rows)
    metrics = ("network_bytes", "network_transfer_ms", "measured_e2e_ms", "modeled_e2e_ms",
               "measured_ttft_ms", "modeled_ttft_ms", "measured_tpot_ms", "modeled_tpot_ms")
    summary: dict[str, object] = {"scenario": scenario.name, "bandwidth_mbps": scenario.bandwidth_mbps,
        "rtt_ms": scenario.rtt_ms, "response_bytes": scenario.response_bytes, "n": len(rows)}
    for metric in metrics:
        values = [_number(row, metric) for row in rows if row.get(metric) is not None]
        if not values:
            raise ValueError(f"缺少指标：{metric}")
        summary[metric] = _quantiles(values)
    return summary


def _read_csv(path: Path, digest: str) -> list[dict[str, str]]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError(f"{path.name}哈希不匹配")
    reader = csv.DictReader(StringIO(raw.decode("utf-8"), newline=""))
    fields = reader.fieldnames
    if not fields or len(fields) != len(set(fields)):
        raise ValueError("CSV缺少表头或存在重复列")
    rows = list(reader)
    if not rows or any(None in row or None in row.values() for row in rows):
        raise ValueError("CSV为空或列数不一致")
    return rows


def _identity(row: dict) -> tuple[str, int, str]:
    if not isinstance(row.get("case_id"), str) or not row["case_id"].strip():
        raise ValueError("输入标识不能为空")
    if row.get("method") not in ("full", "split"):
        raise ValueError("未知实验方法")
    return row["case_id"], _integer(row, "repeat"), row["method"]


def _validate_benchmark(report: dict, runs: list[dict], steps: list[dict]) -> None:
    samples = _integer(report, "samples", minimum=1)
    repeats = _integer(report, "repeats", minimum=1)
    hidden_size = _integer(report, "hidden_size", minimum=1)
    indexed = {}
    for run in runs:
        key = _identity(run)
        if key in indexed:
            raise ValueError("重复运行记录")
        indexed[key] = run
        _integer(run, "generated_tokens", minimum=1)
        _integer(run, "prompt_tokens", minimum=1)
        _number(run, "e2e_ms")
        _number(run, "ttft_ms")
        if _integer(run, "generated_tokens") > 1:
            _number(run, "tpot_ms")
    cases = {key[0] for key in indexed}
    expected = {(case, repeat, method) for case in cases for repeat in range(repeats) for method in ("full", "split")}
    if len(cases) != samples or set(indexed) != expected:
        raise ValueError("输入/轮次/方法未形成完整配对")
    matched = 0
    for case in cases:
        for repeat in range(repeats):
            left, right = indexed[(case, repeat, "full")], indexed[(case, repeat, "split")]
            for field in ("output_ids_sha256", "generated_tokens", "prompt_tokens", "finish_reason"):
                if not left.get(field) or left[field] != right.get(field):
                    raise ValueError("配对输出或停止规则不一致")
            matched += _integer(right, "generated_tokens")
    if (_integer(report, "paired_runs") != samples * repeats
            or _integer(report, "exact_sequence_matches") != samples * repeats
            or _integer(report, "matched_tokens") != matched):
        raise ValueError("输出一致性计数与报告不符")
    grouped = {key: [] for key in indexed}
    for step in steps:
        key = _identity(step)
        if key not in grouped:
            raise ValueError("存在孤立步骤")
        index = _integer(step, "step")
        if step.get("phase") != ("prefill" if index == 0 else "decode"):
            raise ValueError("阶段与步骤不匹配")
        if key[2] == "split":
            length = _integer(indexed[key], "prompt_tokens") if index == 0 else 1
            if _integer(step, "activation_raw_bytes", minimum=1) != length * hidden_size * 4:
                raise ValueError("激活字节数与FP32形状不符")
            _integer(step, "request_json_bytes", minimum=1)
        grouped[key].append(index)
    for key, indices in grouped.items():
        if sorted(indices) != list(range(_integer(indexed[key], "generated_tokens"))):
            raise ValueError("步骤重复、不连续或数量不匹配")


def load_verified_benchmark(directory: Path) -> tuple[dict, list[dict[str, str]], list[dict[str, str]]]:
    """验证SHA256、配对输出、轮次和步骤结构；哈希只能证明一致性，不能认证来源。"""
    directory = Path(directory)
    try:
        report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("实验报告必须是JSON对象")
        if report.get("status") != "passed" or report.get("schema_version") != "safe-local-benchmark-v1":
            raise ValueError("实验报告不是已通过的safe-local-benchmark-v1")
        runs, steps = [_read_csv(directory / name, report["data_sha256"][name]) for name in ("runs.csv", "steps.csv")]
        _validate_benchmark(report, runs, steps)
        return report, runs, steps
    except (KeyError, OSError, TypeError, json.JSONDecodeError):
        raise ValueError("实验报告或原始数据无效") from None


def load_verified_analysis(directory: Path) -> tuple[dict, list[dict]]:
    """绘图前复核情景笛卡尔积、网络公式和全部汇总，拒绝只更新哈希的错误产物。"""
    directory = Path(directory)
    try:
        report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        if not isinstance(report, dict) or report.get("status") != "passed" or report.get("schema_version") != "safe-network-sensitivity-v1":
            raise ValueError("分析报告不是已通过的safe-network-sensitivity-v1")
        if report.get("analysis_type") != "serial_network_overlay_model" or report.get("response_bytes_measured") is not False:
            raise ValueError("分析类型或回执测量声明不一致")
        rows = _read_csv(directory / "network_runs.csv", report["network_runs_sha256"])
        scenarios = [NetworkScenario(**item) for item in report["scenarios"]]
        response_bytes = _integer(report, "response_bytes_assumption", minimum=1)
        if any(item.response_bytes != response_bytes for item in scenarios):
            raise ValueError("回执假设与情景定义不符")
        names = [item.name for item in scenarios]
        if not names or len(set(names)) != len(names) or len(names) != _integer(report, "n_scenarios", minimum=1):
            raise ValueError("情景定义重复或数量不匹配")
        grouped = {name: [] for name in names}
        identities = {name: set() for name in names}
        baselines = {}
        numeric_metrics = ("network_transfer_ms", "measured_e2e_ms", "measured_ttft_ms", "modeled_e2e_ms", "modeled_ttft_ms")
        scenario_map = {item.name: item for item in scenarios}
        for row in rows:
            name = row["network_scenario"]
            if name not in grouped:
                raise ValueError("未知网络情景")
            scenario = scenario_map[name]
            key = (row["case_id"], _integer(row, "repeat"))
            if not key[0] or key in identities[name]:
                raise ValueError("情景内运行重复或输入标识为空")
            identities[name].add(key)
            for field in numeric_metrics:
                row[field] = _number(row, field)
            for field in ("bandwidth_mbps", "rtt_ms"):
                if _number(row, field) != getattr(scenario, field):
                    raise ValueError("网络参数与情景定义不符")
            count = _integer(row, "network_requests", minimum=1)
            size = _integer(row, "network_bytes", minimum=1)
            first = _integer(row, "first_request_json_bytes", minimum=1)
            if _integer(row, "response_bytes", minimum=1) != scenario.response_bytes:
                raise ValueError("回执假设与情景定义不符")
            remaining = size - count * scenario.response_bytes - first
            if remaining < count - 1 or (count == 1 and remaining != 0):
                raise ValueError("字节数与步骤不符")
            transfer = count * scenario.rtt_ms + size * 8 / (scenario.bandwidth_mbps * 1000)
            first_transfer = scenario.rtt_ms + (first + scenario.response_bytes) * 8 / (scenario.bandwidth_mbps * 1000)
            calculations = {"network_transfer_ms": transfer, "modeled_e2e_ms": row["measured_e2e_ms"] + transfer,
                            "modeled_ttft_ms": row["measured_ttft_ms"] + first_transfer}
            for field in ("measured_tpot_ms", "modeled_tpot_ms"):
                if count == 1:
                    if row.get(field) not in (None, ""):
                        raise ValueError("单token输出不能定义TPOT")
                    row[field] = None
                else:
                    row[field] = _number(row, field)
            if count > 1:
                calculations["modeled_tpot_ms"] = row["measured_tpot_ms"] + (transfer - first_transfer) / (count - 1)
            if any(not math.isclose(row[field], value, rel_tol=1e-10, abs_tol=1e-8) for field, value in calculations.items()):
                raise ValueError("网络公式与分析数值不一致")
            baseline = (row["measured_e2e_ms"], row["measured_ttft_ms"], row["measured_tpot_ms"], count, first,
                        size - count * scenario.response_bytes)
            if key in baselines and baselines[key] != baseline:
                raise ValueError("不同情景引用的计算路径不一致")
            baselines[key] = baseline
            grouped[name].append(row)
        reference = identities[names[0]]
        if len(reference) != _integer(report, "n_runs", minimum=1) or any(value != reference for value in identities.values()):
            raise ValueError("网络情景未覆盖相同的完整运行集合")
        expected = [summarize_scenario(grouped[item.name], item) for item in scenarios]
        if expected != report["summaries"]:
            raise ValueError("分析汇总与CSV不一致")
        return report, rows
    except (KeyError, OSError, TypeError, json.JSONDecodeError):
        raise ValueError("分析报告或CSV无效") from None


__all__ = ["NetworkScenario", "calculate_transfer_ms", "load_verified_benchmark", "load_verified_analysis", "model_run", "summarize_scenario"]
