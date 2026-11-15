"""从已通过且哈希匹配的实验CSV生成中文实验图；不产生或补造测量数据。"""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys


def load_verified_data(directory):
    report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    if report.get("status") != "passed" or report.get("schema_version") != "safe-local-benchmark-v1":
        raise ValueError("只允许绘制本实验协议下已通过的完整报告")
    datasets = {}
    for name in ("runs.csv", "steps.csv"):
        raw = (directory / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != report["data_sha256"][name]:
            raise ValueError("原始数据哈希不匹配：" + name)
        with (directory / name).open(encoding="utf-8", newline="") as stream:
            datasets[name] = list(csv.DictReader(stream))
    runs, steps = datasets["runs.csv"], datasets["steps.csv"]
    groups = {}
    for run in runs:
        key = (run["case_id"], int(run["repeat"]))
        methods = groups.setdefault(key, {})
        if run["method"] not in ("full", "split") or run["method"] in methods:
            raise ValueError("重复或未知实验方法")
        methods[run["method"]] = run
    if len(groups) != report["samples"] * report["repeats"]:
        raise ValueError("配对数与预注册配置不一致")
    if any(set(methods) != {"full", "split"} for methods in groups.values()):
        raise ValueError("存在未配对的测量，不能绘制比较图")
    matched = 0
    for methods in groups.values():
        left, right = methods["full"], methods["split"]
        for key in ("output_ids_sha256", "generated_tokens", "prompt_tokens", "finish_reason"):
            if left[key] != right[key]:
                raise ValueError("配对输出或停止规则不一致")
        matched += int(left["generated_tokens"])
    if matched != report["matched_tokens"] or report["exact_sequence_matches"] != len(groups):
        raise ValueError("输出一致性计数不匹配")
    for run in runs:
        events = sorted((row for row in steps if row["case_id"] == run["case_id"]
            and row["repeat"] == run["repeat"] and row["method"] == run["method"]), key=lambda row: int(row["step"]))
        if [int(event["step"]) for event in events] != list(range(int(run["generated_tokens"]))):
            raise ValueError("步骤不连续或计数不匹配")
        for event in events:
            if event["phase"] != ("prefill" if int(event["step"]) == 0 else "decode"):
                raise ValueError("阶段与步骤不匹配")
            if run["method"] == "split":
                length = int(run["prompt_tokens"]) if event["phase"] == "prefill" else 1
                if int(event["activation_raw_bytes"]) != length * report["hidden_size"] * 4:
                    raise ValueError("激活字节数与FP32形状不符")
    if len(steps) != sum(int(run["generated_tokens"]) for run in runs):
        raise ValueError("存在额外步骤记录")
    return report, runs, steps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="默认input/figures，必须为新目录")
    args = parser.parse_args()
    report, runs, steps = load_verified_data(args.input)
    output = args.output or args.input / "figures"
    if output.exists():
        parser.error("图像目录已存在，请保留旧证据并使用新目录")

    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import font_manager
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
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
        raise ValueError("未找到中文字体，请安装微软雅黑或Noto Sans CJK SC后再绘图")
    plt.rcParams.update({"font.family": font, "font.size": 10, "axes.titlesize": 11,
        "axes.labelsize": 10, "axes.titleweight": "bold", "axes.unicode_minus": False,
        "legend.fontsize": 9, "legend.frameon": False, "axes.spines.top": False,
        "axes.spines.right": False, "axes.edgecolor": "#73818A", "axes.linewidth": 0.7,
        "axes.grid": True, "axes.axisbelow": True, "grid.alpha": 0.16,
        "grid.linewidth": 0.6, "savefig.dpi": 300, "figure.dpi": 140,
        "pdf.fonttype": 42, "ps.fonttype": 42})
    output.mkdir(parents=True)
    colors = {"full": "#517A9E", "split": "#168E76"}
    names = {"full": "完整模型", "split": "拆分推理"}
    context = (f"Qwen2.5-0.5B-Instruct  |  K={report['cut_layer']}/{report['total_layers']}  |  "
               f"CPU · FP32 · {report['threads']}线程")
    analysis = dict(status="passed", font=font, matplotlib=matplotlib.__version__,
        report_sha256=hashlib.sha256((args.input / "report.json").read_bytes()).hexdigest(),
        plotting_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        n_prompts=report["samples"], repeats=report["repeats"], matched_tokens=report["matched_tokens"],
        latency_unit="one point = one prompt averaged over repeats", descriptive_intervals="IQR; no confidence interval",
        component_scope="forward start to token receipt; excludes tokenizer/session-create/final cleanup",
        traffic_scope=report["wire_scope"], case_aggregated_latency={}, figures=[])

    def save(fig, name, caption):
        fig.savefig(output / (name + ".png"), dpi=300, bbox_inches="tight", facecolor="white")
        fig.savefig(output / (name + ".pdf"), bbox_inches="tight", facecolor="white",
                    metadata={"Creator": "Safe reproducible experiments", "CreationDate": None, "ModDate": None})
        analysis["figures"].append(dict(name=name, caption_zh=caption))
        plt.close(fig)

    def footer(fig, text):
        fig.text(0.5, 0.012, text, ha="center", va="bottom", fontsize=8.2, color="#59656D")

    cases = sorted({run["case_id"] for run in runs})
    fig, axes = plt.subplots(1, 3, figsize=(11.4, 4.4))
    rng = np.random.default_rng(20261115)
    for ax, metric, title, unit in zip(axes, ("ttft_ms", "tpot_ms", "e2e_ms"),
            ("a  首 token 延迟", "b  逐 token 延迟", "c  端到端完成时间"), ("毫秒", "毫秒 / token", "秒")):
        values = {}
        divisor = 1000 if metric == "e2e_ms" else 1
        for method in ("full", "split"):
            values[method] = np.array([np.mean([float(run[metric]) / divisor for run in runs
                if run["case_id"] == case and run["method"] == method and run[metric] != ""]) for case in cases])
            if not np.isfinite(values[method]).all():
                raise ValueError("没有可计算的逐token测量，不能补零绘图")
            q25, median, q75 = np.percentile(values[method], [25, 50, 75])
            analysis["case_aggregated_latency"].setdefault(method, {})[metric] = dict(
                q25=float(q25 * divisor), median=float(median * divisor), q75=float(q75 * divisor))
        jitter = rng.uniform(-0.045, 0.045, len(cases))
        for index in range(len(cases)):
            ax.plot([1 + jitter[index], 2 + jitter[index]], [values["full"][index], values["split"][index]],
                color="#C2CCD0", alpha=0.45, linewidth=0.65, zorder=1)
        box = ax.boxplot([values["full"], values["split"]], positions=[1, 2], widths=0.4,
            patch_artist=True, showfliers=False, medianprops=dict(color="#23343D", linewidth=1.6),
            whiskerprops=dict(color="#84939B", linewidth=0.8), capprops=dict(color="#84939B", linewidth=0.8))
        for index, method in enumerate(("full", "split")):
            box["boxes"][index].set(facecolor=colors[method], alpha=0.22, edgecolor=colors[method])
            ax.scatter(index + 1 + jitter, values[method], s=18, color=colors[method],
                edgecolors="white", linewidths=0.35, alpha=0.9, zorder=3)
        ax.set_xticks([1, 2], [names["full"], names["split"]])
        ax.set_ylabel(unit)
        ax.set_title(title, loc="left", pad=13)
        ax.set_ylim(bottom=0)
        ax.grid(axis="x", visible=False)
        ratio = float(np.median(values["split"] / values["full"]))
        ax.text(0.04, 0.96, f"配对耗时比中位数 {ratio:.2f}×", transform=ax.transAxes, va="top", fontsize=8.5,
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="none", alpha=0.9))
        analysis.setdefault("paired_latency_ratio_median", {})[metric] = ratio
    fig.suptitle("完整模型与本机拆分生成的配对延迟", x=0.52, y=1.01, fontsize=14, fontweight="bold")
    fig.text(0.52, 0.94, context, ha="center", fontsize=9.2, color="#59656D")
    fig.subplots_adjust(left=0.065, right=0.99, top=0.81, bottom=0.18, wspace=0.36)
    footer(fig, f"{report['samples']}条输入 × {report['repeats']}轮；每点为单条输入跨轮均值；箱体为IQR，须线为1.5 IQR；同机JSON循环，无网络")
    save(fig, "fig_latency", "配对延迟。先对每条输入的重复测量取均值，再绘制跨输入分布；灰线连接同一输入。")

    components = [("prefix_ms", "前段执行", "#56B4E9"), ("client_codec_ms", "本机激活编码", "#E69F00"),
        ("suffix_ms", "后段执行", "#009E73"), ("sampling_ms", "词表校验与采样", "#CC79A7"),
        ("protocol_other_ms", "协议与其他步骤开销", "#8C969C")]
    fig, axes = plt.subplots(1, 2, figsize=(9.8, 4.9))
    analysis["component_means_ms"] = {}
    for ax, phase, title in zip(axes, ("prefill", "decode"), ("a  首步前向（prefill）", "b  单步续算（decode）")):
        records = {method: [row for row in steps if row["phase"] == phase and row["method"] == method]
                   for method in ("full", "split")}
        if not all(records.values()):
            raise ValueError("缺少首步/续算数据，不能绘制组件图")
        full_ms = float(np.mean([float(row["full_model_ms"]) for row in records["full"]]))
        ax.bar(0, full_ms, width=0.5, color=colors["full"], edgecolor="white", linewidth=0.5)
        bottom = 0.0
        means = {}
        for field, label, color in components:
            value = float(np.mean([float(row[field]) for row in records["split"]]))
            ax.bar(1, value, bottom=bottom, width=0.5, color=color, edgecolor="white", linewidth=0.5)
            bottom += value
            means[field] = value
        for x, value in enumerate((full_ms, bottom)):
            ax.text(x, value, f"{value:.1f} ms", ha="center", va="bottom", fontsize=9.3,
                    bbox=dict(fc="white", ec="none", pad=0.3, alpha=0.8))
        ax.set_xticks([0, 1], [names["full"], names["split"]])
        ax.set_xlim(-0.6, 1.6)
        ax.set_ylim(0, max(full_ms, bottom) * 1.19)
        ax.set_ylabel("平均步骤耗时（毫秒）")
        ax.set_title(title, loc="left", pad=12)
        ax.grid(axis="x", visible=False)
        ax.text(0.98, 0.95, f"每种方法 n={len(records['split'])} 步", ha="right", va="top", transform=ax.transAxes,
                fontsize=8.5, color="#59656D")
        analysis["component_means_ms"][phase] = dict(full_model_ms=full_ms, **means)
    handles = [Patch(facecolor=colors["full"], label="完整模型前向与argmax")]
    handles += [Patch(facecolor=color, label=label) for _, label, color in components]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.52, 0.065), ncol=3, columnspacing=1.7,
               handlelength=1.25)
    fig.suptitle("拆分生成的步骤耗时构成", x=0.52, y=0.99, fontsize=14, fontweight="bold")
    fig.text(0.52, 0.93, context, ha="center", fontsize=9.2, color="#59656D")
    fig.subplots_adjust(left=0.08, right=0.98, top=0.81, bottom=0.27, wspace=0.3)
    footer(fig, "按实际步骤加权的均值；不含分词、会话创建及终态清理；协议项含JSON循环和字节计量开销，无网络")
    save(fig, "fig_time_breakdown", "组件平均时间。从前段执行开始到token回执返回；完整模型基线只含前向与argmax。")

    first = [row for row in steps if row["method"] == "split" and int(row["repeat"]) == 0]
    fig, axes = plt.subplots(1, 2, figsize=(10.0, 4.6))
    ax = axes[0]
    analysis["upload_bytes_median"] = {}
    for index, (field, label, color) in enumerate((("activation_raw_bytes", "原始FP32激活", "#87B5C4"),
                                                ("request_json_bytes", "JSON请求体", colors["split"]))):
        medians, lows, highs = [], [], []
        for step, phase in ((0, "prefill"), (1, "decode")):
            values = np.array([int(row[field]) / 1024 for row in first if int(row["step"]) == step])
            q25, median, q75 = np.percentile(values, [25, 50, 75])
            medians.append(median)
            lows.append(median - q25)
            highs.append(q75 - median)
            analysis["upload_bytes_median"].setdefault(phase, {})[field] = float(median * 1024)
        x = np.arange(2) + (index - 0.5) * 0.28
        bars = ax.bar(x, medians, width=0.27, label=label, color=color,
                      yerr=[lows, highs], capsize=3, error_kw=dict(ecolor="#59656D", linewidth=0.8))
        for bar, median in zip(bars, medians):
            ax.annotate(f"{median:.1f}", (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        xytext=(0, 6), textcoords="offset points", ha="center", fontsize=8.6)
    ax.set_xticks([0, 1], ["首步上传", "每次续算上传"])
    ax.set_ylabel("请求体大小（KiB）")
    ax.set_title("a  激活编码的上传量", loc="left", pad=12)
    ax.legend(loc="upper right")
    ax.set_ylim(0, ax.get_ylim()[1] * 1.2)
    ax.grid(axis="x", visible=False)
    ax = axes[1]
    count = {"eos": 0, "length": 0}
    for case in cases:
        records = sorted((row for row in first if row["case_id"] == case), key=lambda row: int(row["step"]))
        run = next(run for run in runs if run["case_id"] == case and run["repeat"] == "0" and run["method"] == "split")
        reason = run["finish_reason"]
        count[reason] += 1
        color = "#168E76" if reason == "eos" else "#D98D28"
        y = np.cumsum([int(row["request_json_bytes"]) for row in records]) / 1024
        x = np.arange(1, len(y) + 1)
        ax.plot(x, y, color=color, alpha=0.65, linewidth=1.15)
        ax.scatter(x[-1], y[-1], color=color, s=16, edgecolor="white", linewidth=0.3, zorder=3)
    ax.set_xlabel("已生成 token 数")
    ax.set_ylabel("累计上传（KiB）")
    ax.set_title("b  单条输入的累计激活上传量", loc="left", pad=12)
    ax.set_xlim(0, report["max_new_tokens"] + 1)
    ax.set_ylim(bottom=0)
    ax.legend(handles=[Line2D([], [], color="#168E76", label=f"EOS停止（{count['eos']}条）"),
        Line2D([], [], color="#D98D28", label=f"长度上限（{count['length']}条）")], loc="lower right")
    fig.suptitle("FP32激活传输的通信负担", x=0.52, y=1.0, fontsize=14, fontweight="bold")
    fig.text(0.52, 0.93, context + "  |  H=" + str(report["hidden_size"]), ha="center", fontsize=9.2, color="#59656D")
    fig.subplots_adjust(left=0.075, right=0.98, top=0.8, bottom=0.2, wspace=0.34)
    footer(fig, f"首轮{report['samples']}条输入；左图中位数与IQR，续算取各输入第1次decode；右图每线1条输入；仅step请求体，无HTTP/TLS头")
    save(fig, "fig_activation_traffic", "激活上传量。原始张量与真实JSON字节数分别计量；累计曲线到EOS或输出上限结束。")

    analysis["file_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.iterdir()) if path.suffix in (".png", ".pdf")}
    (output / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已生成3组中文实验图（300 DPI PNG + 矢量PDF）：{output}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError) as exc:
        print("绘图拒绝：" + str(exc), file=sys.stderr)
        raise SystemExit(1)
