"""对已完成的本机生成实验进行带宽/RTT敏感性分析。

该命令只读取已校验的CSV，不运行模型、不连接网络。输出是串行网络叠加模型：
每次激活请求到token回执合计经历一个RTT，传输时间按请求体真实字节与显式回执
字节参数计算。结果必须标记为modeled，不能当成公网实测。
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from safe.infrastructure.experiments.network_sensitivity import (
    NetworkScenario,
    load_verified_benchmark,
    model_run,
    summarize_scenario,
)
from safe.infrastructure.experiments import network_sensitivity


SCENARIOS = (
    NetworkScenario("同机基线", bandwidth_mbps=1_000.0, rtt_ms=0.2),
    NetworkScenario("局域网", bandwidth_mbps=1_000.0, rtt_ms=1.0),
    NetworkScenario("云区互联", bandwidth_mbps=100.0, rtt_ms=10.0),
    NetworkScenario("家庭宽带", bandwidth_mbps=20.0, rtt_ms=20.0),
    NetworkScenario("4G移动网", bandwidth_mbps=50.0, rtt_ms=35.0),
    NetworkScenario("受限移动网", bandwidth_mbps=5.0, rtt_ms=80.0),
)


def _write_csv(path: Path, rows: list[dict]) -> None:
    fields = list(dict.fromkeys(field for row in rows for field in row))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="已通过的local-generation证据目录")
    parser.add_argument("--output", type=Path, required=True, help="新的分析输出目录")
    parser.add_argument("--response-bytes", type=int, default=256,
                        help="模型回执JSON假设字节数，默认256；不是实测或大小上界")
    args = parser.parse_args()
    if args.response_bytes <= 0 or args.response_bytes > 16 * 1024:
        parser.error("response-bytes须位于1至16384")
    if args.output.exists():
        parser.error("输出目录已存在，请新建目录保留历史证据")
    report, runs, steps = load_verified_benchmark(args.input)
    groups: dict[tuple[str, int], dict[str, object]] = {}
    for run in runs:
        if run.get("method") != "split":
            continue
        key = (run["case_id"], int(run["repeat"]))
        groups.setdefault(key, {})["run"] = run
    for row in steps:
        if row.get("method") != "split":
            continue
        key = (row["case_id"], int(row["repeat"]))
        groups.setdefault(key, {}).setdefault("steps", []).append(row)
    if len(groups) != int(report["samples"]) * int(report["repeats"]):
        raise ValueError("split运行数量与原始报告不一致")

    scenarios = tuple(NetworkScenario(item.name, item.bandwidth_mbps, item.rtt_ms, args.response_bytes)
                      for item in SCENARIOS)
    all_rows: list[dict] = []
    summaries: list[dict] = []
    for scenario in scenarios:
        scenario_rows = []
        for group in groups.values():
            row = model_run(group["run"], group.get("steps", []), scenario)
            scenario_rows.append(row)
            all_rows.append(row)
        summaries.append(summarize_scenario(scenario_rows, scenario))

    output_report = {
        "status": "passed",
        "schema_version": "safe-network-sensitivity-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "analysis_type": "serial_network_overlay_model",
        "measured_source": str(args.input).replace("\\", "/"),
        "source_report_sha256": hashlib.sha256((args.input / "report.json").read_bytes()).hexdigest(),
        "source_manifest_digest": report["manifest_digest"],
        "source_runtime_commit": report.get("runtime_commit"),
        "analysis_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "network_model_sha256": hashlib.sha256(Path(network_sensitivity.__file__).read_bytes()).hexdigest(),
        "source_configuration": {key: report[key] for key in
            ("model_id", "cut_layer", "total_layers", "samples", "repeats")},
        "n_runs": len(groups),
        "n_scenarios": len(scenarios),
        "response_bytes_assumption": args.response_bytes,
        "response_bytes_measured": False,
        "rtt_definition": "一次激活请求到token回执的往返时间；每个step串行叠加一次",
        "bandwidth_definition": "请求方向和回执方向共享的额定吞吐；不含TLS/HTTP头和重传",
        "overlap_assumption": "无网络与计算重叠；网络时间直接叠加已测step/e2e时间",
        "scenarios": [scenario.__dict__ for scenario in scenarios],
        "summaries": summaries,
    }
    # 先完成证据验证和全部计算，再创建新目录；无效输入不会留下空结果目录。
    args.output.mkdir(parents=True)
    _write_csv(args.output / "network_runs.csv", all_rows)
    output_report["network_runs_sha256"] = hashlib.sha256((args.output / "network_runs.csv").read_bytes()).hexdigest()
    (args.output / "report.json").write_text(json.dumps(output_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已完成{len(groups)}组×{len(scenarios)}个网络场景的分析模型：{args.output}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as exc:
        print("分析拒绝：" + str(exc), file=sys.stderr)
        raise SystemExit(1)
