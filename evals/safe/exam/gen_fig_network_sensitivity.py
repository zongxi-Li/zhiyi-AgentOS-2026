"""生成网络敏感性分析图；绘制前校验分析报告和CSV哈希。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "apps/agentOS/src"))

from components.safe.infrastructure.experiments.network_sensitivity import load_verified_analysis


def _load(path: Path):
    return load_verified_analysis(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report, rows = _load(args.input)
    output = args.output or args.input / "figures"
    if output.exists():
        parser.error("图像目录已存在，请使用新目录保留历史证据")

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
        raise ValueError("未找到中文字体")
    plt.rcParams.update({"font.family": font, "font.size": 10, "axes.titlesize": 12,
        "axes.titleweight": "bold", "axes.labelsize": 10, "axes.unicode_minus": False,
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
        "grid.alpha": 0.18, "savefig.dpi": 300, "pdf.fonttype": 42, "ps.fonttype": 42})
    output.mkdir(parents=True)
    scenarios = [item["name"] for item in report["scenarios"]]
    summary = {item["scenario"]: item for item in report["summaries"]}
    config = report["source_configuration"]

    def save(fig, name):
        fig.savefig(output / f"{name}.png", dpi=300, bbox_inches="tight", facecolor="white")
        fig.savefig(output / f"{name}.pdf", bbox_inches="tight", facecolor="white",
                    metadata={"Creator": "Safe reproducible experiments", "CreationDate": None, "ModDate": None})
        plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(11.8, 4.5))
    metrics = (("modeled_ttft_ms", "首 token 延迟", "毫秒"),
               ("modeled_tpot_ms", "逐 token 延迟", "毫秒 / token"),
               ("modeled_e2e_ms", "端到端完成时间", "秒"))
    for ax, (metric, title, ylabel) in zip(axes, metrics):
        divisor = 1000 if metric == "modeled_e2e_ms" else 1
        medians = [summary[name][metric]["median"] / divisor for name in scenarios]
        q25 = [summary[name][metric]["q25"] / divisor for name in scenarios]
        q75 = [summary[name][metric]["q75"] / divisor for name in scenarios]
        x = np.arange(len(scenarios))
        # 情景是离散类别，使用点和IQR须线，避免连续曲线暗示等距网络变化。
        ax.errorbar(x, medians, yerr=[np.subtract(medians, q25), np.subtract(q75, medians)],
                    fmt="o", color="#009E73", markersize=6, capsize=4, elinewidth=1.4)
        for index, value in enumerate(medians):
            label = f"{value:.2f}" if metric == "modeled_e2e_ms" else f"{value:.1f}"
            ax.annotate(label, (index, value), xytext=(0, 8), textcoords="offset points",
                        ha="center", fontsize=8.3,
                        bbox=dict(facecolor="white", edgecolor="none", pad=1.0, alpha=0.85))
        ax.set_xticks(x, scenarios, rotation=28, ha="right")
        ax.margins(x=0.08)
        ax.set_ylabel(ylabel)
        ax.set_title(title, loc="left", pad=12)
        ax.set_ylim(bottom=0)
        ax.set_ylim(top=max(q75) * 1.15)
        ax.grid(axis="x", visible=False)
    fig.suptitle("网络条件对拆分生成延迟的敏感性（分析模型）", x=0.52, y=1.01, fontsize=14, fontweight="bold")
    fig.text(0.52, 0.94, f"{config['model_id']} · K={config['cut_layer']}/{config['total_layers']} · 回执假设{report['response_bytes_assumption']} B",
             ha="center", fontsize=9.2, color="#59656D")
    fig.subplots_adjust(left=0.065, right=0.99, top=0.8, bottom=0.28, wspace=0.35)
    fig.text(0.5, 0.018, f"{config['samples']}条输入 × {config['repeats']}轮（{report['n_runs']}组）；点为中位数，须线为IQR而非置信区间；所有网络时间均为情景估算",
             ha="center", fontsize=8.2, color="#59656D")
    save(fig, "fig_network_latency")

    # 带宽×RTT网格：对每个输入运行计算中位端到端时间，展示通信条件的交互效应。
    bandwidths = [5, 20, 50, 100, 1000]
    rtts = [0.2, 1, 10, 35, 80]
    split_rows = [row for row in rows if row["network_scenario"] == scenarios[0]]
    matrix = np.empty((len(rtts), len(bandwidths)))
    for ri, rtt in enumerate(rtts):
        for bi, bandwidth in enumerate(bandwidths):
            # 直接从相同计算路径、总字节和请求次数重建网格，不依赖某个硬编码基准场景。
            matrix[ri, bi] = np.median([float(row["measured_e2e_ms"]) + int(row["network_requests"]) * rtt
                + int(row["network_bytes"]) * 8 / (bandwidth * 1000) for row in split_rows]) / 1000
    fig, ax = plt.subplots(figsize=(7.7, 5.1))
    image = ax.imshow(matrix, cmap="YlGnBu", aspect="auto")
    ax.grid(False)
    ax.set_xticks(np.arange(len(bandwidths)), [f"{value:g}" for value in bandwidths])
    ax.set_yticks(np.arange(len(rtts)), [f"{value:g}" for value in rtts])
    ax.set_xlabel("共享链路带宽（Mbps）")
    ax.set_ylabel("请求—回执 RTT（毫秒）")
    ax.set_title("带宽与 RTT 的联合影响", loc="left", pad=12)
    for ri in range(len(rtts)):
        for bi in range(len(bandwidths)):
            red, green, blue, _ = image.cmap(image.norm(matrix[ri, bi]))
            luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
            ax.text(bi, ri, f"{matrix[ri, bi]:.2f}s", ha="center", va="center",
                    color="white" if luminance < 0.48 else "#183B4D", fontsize=8.5)
    cbar = fig.colorbar(image, ax=ax, pad=0.025)
    cbar.set_label("模型端到端时间（秒）")
    fig.suptitle("拆分生成的通信条件热力图（分析模型）", x=0.52, y=0.99, fontsize=14, fontweight="bold")
    fig.text(0.52, 0.925, f"{report['n_runs']}组已测计算路径；回执假设{report['response_bytes_assumption']} B；串行叠加，不含HTTP/TLS头",
             ha="center", fontsize=9.2, color="#59656D")
    fig.subplots_adjust(left=0.13, right=0.9, top=0.82, bottom=0.14)
    fig.text(0.5, 0.025, "颜色越深表示模型端到端时间越长；这是带宽/RTT情景估算，不能替代真实网络实验",
             ha="center", fontsize=8.2, color="#59656D")
    save(fig, "fig_network_heatmap")

    analysis = {"status": "passed", "font": font, "matplotlib": matplotlib.__version__,
        "source_report_sha256": report["source_report_sha256"],
        "analysis_report_sha256": hashlib.sha256((args.input / "report.json").read_bytes()).hexdigest(),
        "plotting_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "heatmap": {"bandwidths_mbps": bandwidths, "rtts_ms": rtts, "modeled_e2e_seconds": matrix.tolist()},
        "figures": ["fig_network_latency", "fig_network_heatmap"],
        "model_type": report["analysis_type"], "response_bytes_assumption": report["response_bytes_assumption"]}
    analysis["file_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.iterdir()) if path.suffix in (".png", ".pdf")}
    (output / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已生成网络敏感性图：{output}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as exc:
        print("绘图拒绝：" + str(exc), file=sys.stderr)
        raise SystemExit(1)
