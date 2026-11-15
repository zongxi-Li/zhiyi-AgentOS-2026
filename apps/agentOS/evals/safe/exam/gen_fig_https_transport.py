"""核验真实 HTTPS 回环实验原始数据后绘图；拒绝失败、缺项或哈希不符的报告。"""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics


def load_verified_data(directory):
    report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    if (report.get("schema_version") != "safe-https-loopback-v1" or report.get("status") != "passed"
            or report.get("network") != "real-tcp-tls-loopback" or not report.get("independent_suffix_process")):
        raise ValueError("只允许已通过的真实独立进程回环实验")
    tables = []
    for name in ("runs.csv", "http.csv"):
        raw = (directory / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != report["data_sha256"][name]:
            raise ValueError("原始数据哈希不一致")
        with (directory / name).open(encoding="utf-8", newline="") as stream:
            tables.append(list(csv.DictReader(stream)))
    runs, http = tables
    pairs = {}
    for run in runs:
        key = run["case_id"], int(run["repeat"])
        methods = pairs.setdefault(key, {})
        if run["method"] not in ("full", "https") or run["method"] in methods:
            raise ValueError("重复或未知方法")
        methods[run["method"]] = run
        for metric in ("ttft_ms", "e2e_ms"):
            if not math.isfinite(float(run[metric])) or float(run[metric]) <= 0:
                raise ValueError("非法延迟")
        if run["tpot_ms"] and (not math.isfinite(float(run["tpot_ms"])) or float(run["tpot_ms"]) <= 0):
            raise ValueError("非法 TPOT")
    expected = {(f"synthetic-{case:02d}", repeat) for case in range(report["samples"])
        for repeat in range(report["repeats"])}
    if set(pairs) != expected or any(set(pair) != {"full", "https"} for pair in pairs.values()):
        raise ValueError("配对或覆盖范围不完整")
    matched = 0
    for key, pair in pairs.items():
        for field in ("output_ids_sha256", "generated_tokens", "prompt_tokens", "finish_reason"):
            if pair["full"][field] != pair["https"][field]:
                raise ValueError("输出或停止规则不一致")
        count = int(pair["https"]["generated_tokens"])
        prompt = int(pair["https"]["prompt_tokens"])
        if not 1 <= count <= report["max_new_tokens"] or not 1 <= prompt <= 128:
            raise ValueError("长度超限")
        for run in pair.values():
            if run["finish_reason"] not in ("eos", "length") or (run["finish_reason"] == "length" and count != report["max_new_tokens"]):
                raise ValueError("停止原因和输出长度不一致")
            if (count == 1 and run["tpot_ms"]) or (count > 1 and not run["tpot_ms"]):
                raise ValueError("TPOT与输出数量不一致")
            minimum = float(run["ttft_ms"]) + (count - 1) * float(run["tpot_ms"] or 0)
            if float(run["e2e_ms"]) + 1e-5 < minimum:
                raise ValueError("端到端延迟小于token接收时间跨度")
        selected = [row for row in http if (row["case_id"], int(row["repeat"])) == key]
        if [row["operation"] for row in selected] != ["create"] + ["step"] * count + ["close_session"]:
            raise ValueError("HTTP控制流不完整或发生额外重发")
        for index, row in enumerate(selected[1:-1]):
            raw_bytes = (prompt if index == 0 else 1) * report["hidden_size"] * 4
            encoded_bytes = 4 * ((raw_bytes + 2) // 3)
            if (int(row["step"]) != index or row["phase"] != ("prefill" if index == 0 else "decode")
                    or int(row["position_offset"]) != (0 if index == 0 else prompt + index - 1)
                    or int(row["activation_raw_bytes"]) != raw_bytes):
                raise ValueError("实际步骤、阶段、位置或原始激活字节不一致")
            if not encoded_bytes < int(row["request_bytes"]) <= encoded_bytes + 16384:
                raise ValueError("请求体字节不符合激活格式")
        matched += count
    if len(http) != matched + 2 * len(expected):
        raise ValueError("存在未关联的HTTP记录")
    for row in http:
        if (int(row["status_code"]) != 200 or int(row["response_bytes"]) <= 0 or int(row["request_bytes"]) < 0
                or not math.isfinite(float(row["elapsed_ms"])) or float(row["elapsed_ms"]) <= 0):
            raise ValueError("HTTP请求失败或计量非法")
    worker = report["worker"]
    if (report["matched_tokens"] != matched or report["exact_sequence_matches"] != len(expected)
            or worker["status"] != "passed" or worker["active_kv"] != 0
            or worker["forwards"] != matched + report["warmup_tokens"]
            or worker["created_kv"] != worker["released_kv"] or worker["created_kv"] != len(expected) + 2
            or not report["prefix_kv_empty"]):
        raise ValueError("输出、幂等或KV清理计数不一致")
    return report, runs, http


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report, runs, http = load_verified_data(args.input)
    output = args.output or args.input / "figures"
    if output.exists():
        parser.error("图像目录已存在，请保留历史证据")

    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import font_manager
    import matplotlib.pyplot as plt
    import numpy as np

    font = None
    for candidate in ("Microsoft YaHei", "Noto Sans CJK SC", "SimHei"):
        try:
            font_manager.findfont(candidate, fallback_to_default=False)
            font = candidate
            break
        except ValueError:
            continue
    if font is None:
        raise ValueError("需要安装中文字体")
    plt.rcParams.update({"font.family": font, "font.size": 10, "axes.unicode_minus": False,
        "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
        "axes.grid": True, "axes.axisbelow": True, "grid.alpha": 0.18,
        "pdf.fonttype": 42, "savefig.dpi": 300})
    output.mkdir(parents=True)
    summary = dict(status="passed", font=font, matplotlib=matplotlib.__version__,
        aggregation="先按输入汇总重复测量中位数；点为输入，箱为输入间分布；非置信区间",
        input_report_sha256=hashlib.sha256((args.input / "report.json").read_bytes()).hexdigest(),
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), metrics={})
    fig, axes = plt.subplots(1, 3, figsize=(10.8, 3.5), constrained_layout=True)
    for ax, metric, title in zip(axes, ("ttft_ms", "tpot_ms", "e2e_ms"), ("首 token 延迟", "后续 token 平均耗时", "端到端延迟")):
        for position, method, color in ((1, "full", "#517A9E"), (2, "https", "#168E76")):
            values = [statistics.median(float(row[metric]) for row in runs if row["method"] == method
                and row["case_id"] == f"synthetic-{case:02d}" and row[metric]) for case in range(report["samples"])
                if any(row[metric] for row in runs if row["method"] == method and row["case_id"] == f"synthetic-{case:02d}")]
            box = ax.boxplot([values], positions=[position], widths=0.45, patch_artist=True, showfliers=False)
            box["boxes"][0].set(facecolor=color, alpha=0.25)
            for line in box["medians"]:
                line.set(color=color, linewidth=1.8)
            ax.scatter(np.full(len(values), position) + np.linspace(-0.09, 0.09, len(values)), values,
                s=22, color=color, zorder=3, alpha=0.8)
            summary["metrics"][method + "_" + metric] = statistics.median(values) if values else None
        ax.set(title=title, ylabel="毫秒", xticks=[1, 2], xticklabels=["完整模型", "HTTPS 拆分"])
        ax.set_ylim(bottom=0)
    fig.suptitle(f"独立进程 TLS 回环 · {report['samples']} 条输入 × {report['repeats']} 轮 · CPU FP32", fontsize=12)
    for extension in ("png", "pdf"):
        fig.savefig(output / ("latency." + extension))
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.6), constrained_layout=True)
    steps = [row for row in http if row["operation"] == "step"]
    for phase, color, marker, label in (("prefill", "#517A9E", "o", "Prefill"), ("decode", "#168E76", "s", "Decode")):
        selected = [row for row in steps if row["phase"] == phase]
        # 每个输入先合并重复轮次，再画请求体/回执和完整HTTP耗时分布。
        groups = []
        for case in range(report["samples"]):
            rows = [row for row in selected if row["case_id"] == f"synthetic-{case:02d}"]
            if rows:
                groups.append({key: statistics.median(float(row[key]) for row in rows)
                    for key in ("request_bytes", "response_bytes", "elapsed_ms")})
        axes[0].scatter([row["request_bytes"] / 1024 for row in groups], [row["response_bytes"] for row in groups],
            c=color, marker=marker, s=45, label=label, alpha=0.85)
        axes[1].scatter([row["request_bytes"] / 1024 for row in groups], [row["elapsed_ms"] for row in groups],
            c=color, marker=marker, s=45, label=label, alpha=0.85)
    axes[0].set(xlabel="实际请求正文（KiB）", ylabel="实际回执正文（B）", title="激活上传与单 token 回执")
    axes[1].set(xlabel="实际请求正文（KiB）", ylabel="完整 HTTP 调用耗时（ms）", title="含后段计算与协议处理")
    for ax in axes:
        ax.set_xscale("log")
        ax.legend()
    fig.suptitle("仅计请求/响应正文；不含 HTTP 头、TLS、TCP；回环不代表公网", fontsize=11)
    for extension in ("png", "pdf"):
        fig.savefig(output / ("payload_and_latency." + extension))
    plt.close(fig)
    (output / "analysis.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
