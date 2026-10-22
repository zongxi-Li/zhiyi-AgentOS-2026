#!/usr/bin/env python3
"""Run the AgentOS five-minute stage-freeze gate.

The gate compares the current src/tests tree with a source snapshot, maps
changed modules to focused contract tests, and never turns a timeout into a
pass. It intentionally does not enable pytest-xdist.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
AGENTOS = ROOT / "apps" / "agentOS"
# Exact src/tests manifest at INT-1 entry Commit 09860f8c (C2A-3 frozen).
DEFAULT_BASELINE = ROOT / "scripts" / "freeze_gate_baselines" / "c2b-int1-entry.json"
BASELINE_SHA256 = "54ccc02a3d0ba550fffff8dd23f259460977ae0a75f3d8eea4d7c1848ce1a591"
BASELINE_AGGREGATE = "cb5809b8a2e29278d39d6ab70c6bd1567da7073148195201d013f1105f9a2c47"
BASELINE_COMMIT = "09860f8c88c4b8d40cac2c80ca836f0bfa5a2c35"
DEFAULT_BUDGET_SECONDS = 300
SLOW_EXCLUSION = "not slow_benchmark and not slow_multiprocess and not slow_fault_injection"
FAST_OR_CRITICAL = (
    "freeze_gate or (not slow_benchmark and not slow_multiprocess "
    "and not slow_fault_injection)"
)

# Each changed source area must have a focused test module. Freeze-critical
# counterexamples in those modules carry @pytest.mark.freeze_gate. New rules
# should be added alongside the implementation that introduces the module.
SOURCE_TEST_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("scripts/freeze_gate.py", ("tests/storage/test_freeze_gate_integrity.py",)),
    ("src/support/stores/c2_schema_upgrade.py", ("tests/storage/test_c2_schema_upgrade.py", "tests/storage/test_c2_schema_integrity.py", "tests/storage/v2/test_schema.py")),
    ("scripts/upgrade_agentos_c2_schema.py", ("tests/storage/test_c2_schema_upgrade.py",)),
    ("src/components/resource/__init__.py", ("tests/components/resource/test_node_store.py", "tests/components/resource/test_resource_auth.py")),
    ("src/components/resource/errors.py", ("tests/components/resource/test_remote_observation.py", "tests/components/resource/test_node_store.py")),
    ("src/components/resource/health_store.py", ("tests/components/resource/test_health_store.py",)),
    ("src/components/resource/node_health.py", ("tests/components/resource/test_node_store.py",)),
    ("src/components/resource/node_store.py", ("tests/components/resource/test_node_store.py",)),
    ("src/components/resource/service.py", ("tests/components/resource/test_remote_observation.py", "tests/components/resource/test_resource_auth.py", "tests/components/resource/test_node_store.py")),
    ("src/components/resource/sqlite_support.py", ("tests/components/resource/test_store_contract.py", "tests/components/resource/test_health_store.py", "tests/components/resource/test_node_store.py")),
    ("src/components/resource/store.py", ("tests/components/resource/test_store_contract.py", "tests/components/resource/test_remote_observation.py", "tests/components/resource/test_resource_auth.py")),
    ("src/contracts/resource.py", ("tests/components/resource/test_edge_cloud_contracts.py", "tests/components/scheduler/test_binder.py")),
    ("src/components/scheduler/binder.py", ("tests/components/scheduler/test_binder.py",)),
    ("src/components/scheduler/leases.py", ("tests/components/scheduler/test_redis_leases.py",)),
    ("src/components/scheduler/models.py", ("tests/components/scheduler/test_binder.py",)),
    ("src/runtime/initial_execution.py", ("tests/components/planner/test_initial_execution_permit.py",
        "tests/architecture/test_capability_upgrade_gates.py")),
    ("src/runtime/graph_handoff.py", ("tests/components/planner/test_initial_execution_permit.py",
        "tests/components/planner/test_graph_handoff.py::test_real_prefix_handoff_preserves_all_existing_facts",
        "tests/components/planner/test_graph_handoff.py::test_restart_reconstructs_same_preparation_but_cannot_execute")),
    ("src/runtime/execution_permit.py", ("tests/components/planner/test_initial_execution_permit.py",
        "tests/components/planner/test_execution_permit_audit.py")),
    ("src/contracts/graph_handoff.py", ("tests/components/planner/test_initial_execution_permit.py",)),
    ("src/contracts/execution_permit.py", ("tests/components/planner/test_initial_execution_permit.py",)),
    ("src/runtime/initial_graph_compilation.py", ("tests/components/planner/test_initial_graph_materialization.py",
        "tests/contracts/test_compiled_acg.py", "tests/contracts/test_binding_authority.py",
        "tests/architecture/test_capability_upgrade_gates.py")),
    ("src/runtime/graph_materialization.py", ("tests/components/planner/test_initial_graph_materialization.py",
        "tests/components/planner/test_graph_revision_commit.py::test_completed_prefix_pending_suffix_replacement",
        "tests/components/planner/test_graph_revision_commit.py::test_checkpoint_identity_and_control_evidence_are_required",
        "tests/components/planner/test_graph_materialization.py::test_inactive_package_is_complete_read_only_and_restartable",
        "tests/components/planner/test_graph_materialization.py::test_compile_window_changes_cannot_publish",
        "tests/components/planner/test_graph_materialization.py::test_atomic_faults_reconcile_original_key")),
    ("src/contracts/graph_materialization.py", ("tests/components/planner/test_initial_graph_materialization.py",
        "tests/components/planner/test_graph_materialization.py::test_corrupted_content_is_rejected")),
    ("src/runtime/graph_activation.py", ("tests/components/planner/test_initial_graph_materialization.py",
        "tests/components/planner/test_graph_activation.py::test_commit_switches_head_and_projection_atomically",
        "tests/components/planner/test_graph_activation.py::test_stale_sources_are_rejected_before_and_after_preparation",
        "tests/components/planner/test_graph_activation.py::test_activation_transaction_failure_rolls_back_completely",
        "tests/components/planner/test_graph_activation.py::test_scheduler_entries_refuse_the_paused_graph")),
    ("src/support/stores/graph_activation_store.py", (
        "tests/components/planner/test_initial_execution_permit.py",
        "tests/components/planner/test_initial_graph_materialization.py::test_initial_v1_paused_and_real_claim_denied",
        "tests/components/planner/test_initial_graph_materialization.py::test_real_process_exit_recovers_same_initial_fact",
        "tests/components/planner/test_initial_graph_materialization.py::test_initial_concurrent_activation_cannot_replace_head",
        "tests/components/planner/test_graph_activation.py::test_old_thread_snapshot_cannot_regress_the_graph_version")),
    ("src/contracts/graph_activation.py", ("tests/components/planner/test_initial_graph_materialization.py",)),
    ("src/runtime/workflow_runtime.py", ("tests/runtime/test_kernel_vertical_slice.py",)),
    ("src/contracts/initial_planning.py", ("tests/components/planner/test_initial_planning_sources.py", "tests/components/planner/test_planning_commit_runtime.py")),
    ("src/contracts/planning_commit.py", ("tests/components/planner/test_initial_planning_sources.py", "tests/components/planner/test_planning_commit.py", "tests/components/planner/test_planning_commit_runtime.py")),
    ("src/components/planner/planning_commit.py", ("tests/components/planner/test_initial_planning_sources.py", "tests/components/planner/test_planning_commit.py", "tests/components/planner/test_planning_commit_runtime.py")),
    ("src/runtime/planning_commit.py", ("tests/components/planner/test_initial_planning_sources.py", "tests/components/planner/test_planning_commit_runtime.py", "tests/components/planner/test_graph_revision_commit.py")),
    ("src/runtime/initial_planning_sources.py", ("tests/components/planner/test_initial_planning_sources.py", "tests/components/planner/test_planning_commit_runtime.py")),
    ("apps/agent/app/api/agentos_v2.py", ("tests/runtime/test_kernel_vertical_slice.py", "tests/runtime/test_contract_review_delivery.py")),
    ("src/examples/", ("tests/runtime/test_kernel_vertical_slice.py", "tests/runtime/test_contract_review_delivery.py", "tests/runtime/v2/test_workspace_projection.py")),
    ("src/runtime/planning_loop.py", ("tests/runtime/test_kernel_vertical_slice.py",)),
    ("src/adapters/agent_invocation.py", ("tests/components/planner/test_permit_recovery.py",)),
    ("src/runtime/permit_recovery.py", ("tests/components/planner/test_permit_recovery.py",)),
    ("src/runtime/graph_handoff.py", ("tests/components/planner/test_execution_permit.py",)),
    ("src/runtime/graph_activation.py", ("tests/components/planner/test_execution_permit.py",)),
    ("src/runtime/binding.py", ("tests/components/planner/test_execution_permit.py",)),
    ("src/contracts/acg_lifecycle.py", ("tests/components/planner/test_execution_permit.py",)),
    ("src/runtime/ports.py", ("tests/components/planner/test_execution_permit.py",)),
    ("src/support/stores/graph_handoff_store.py", ("tests/components/planner/test_execution_permit.py",)),
    ("src/support/stores/graph_activation_store.py", ("tests/components/planner/test_execution_permit.py",)),
    ("src/runtime/workflow_runtime.py", ("tests/components/planner/test_execution_permit.py",)),
    ("src/runtime/acg_execution.py", ("tests/components/planner/test_execution_permit.py",)),
    ("src/runtime/runtime_recovery.py", ("tests/components/planner/test_permit_recovery.py",)),
    ("src/runtime/state_persistence.py", ("tests/runtime/test_checkpoint_promotion.py",)),
    ("src/components/recovery/checkpoint.py", ("tests/components/planner/test_execution_permit.py",)),
    ("src/components/executor/graph.py", ("tests/components/planner/test_execution_permit.py",)),
    ("src/components/executor/node_runner.py", ("tests/components/planner/test_execution_permit.py",)),
    ("src/components/executor/value_store.py", ("tests/components/planner/test_execution_permit.py",)),
    ("src/support/run_execution_fence.py", ("tests/components/planner/test_execution_permit.py",)),
    ("src/runtime/v2/identity_projection.py", ("tests/components/planner/test_execution_permit.py",)),
    ("src/components/scheduler/", ("tests/components/scheduler/test_binder.py", "tests/components/scheduler/test_redis_leases.py")),
    ("src/runtime/execution_permit.py", ("tests/components/planner/test_execution_permit.py",)),
    ("src/support/stores/execution_permit_store.py", ("tests/components/planner/test_execution_permit.py",)),
    ("src/contracts/execution_permit.py", ("tests/components/planner/test_execution_permit.py",)),
    ("src/contracts/graph_handoff.py", ("tests/components/planner/test_execution_permit.py",)),
    ("src/contracts/graph_activation.py", ("tests/components/planner/test_execution_permit.py",)),
)

# Accepted INT-1 entry content, never HEAD. API uses that Windows checkout's
# raw CRLF digest; the gate used LF. CLI did not exist at the accepted entry.
EXTERNAL_BASELINE = {
    "apps/agent/app/api/agentos_v2.py": "b78ffdd8d0b1c004f9befdd63c7372070cf9a733c244f86591328897791ccc21",
    "scripts/freeze_gate.py": "06816f400a6d5a6143ead0f9d32af1d70a2715202cbbcd7223e05df1469d0637",
    "scripts/upgrade_agentos_c2_schema.py": None,
}
EXTERNAL_SOURCES = tuple(EXTERNAL_BASELINE)


def external_snapshot() -> dict[str, str | None]:
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            if (ROOT / path).is_file() else None for path in EXTERNAL_SOURCES}


def changed_external_paths(snapshot: dict[str, str | None]) -> list[str]:
    return sorted(path for path in EXTERNAL_SOURCES if snapshot.get(path) != EXTERNAL_BASELINE[path])


class BaselineIntegrityError(ValueError):
    pass


def load_baseline(path: Path) -> dict:
    """Authenticate the accepted manifest before selecting any tests.

    --baseline may locate a byte-identical copy, never silently establish a
    different acceptance baseline. Missing/corrupt files cannot fall back to
    HEAD, even in a clean checkout.
    """
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != BASELINE_SHA256:
            raise ValueError("content SHA-256 differs from accepted INT-1 entry")
        baseline = json.loads(raw)
        files = baseline["files"]
        if not isinstance(files, dict) or len(files) != 445:
            raise ValueError("invalid file manifest")
        manifest = "\n".join(f"{p} {d}" for p, d in sorted(files.items()))
        aggregate = hashlib.sha256(manifest.encode("utf8")).hexdigest()
        if baseline["aggregate"] != aggregate or aggregate != BASELINE_AGGREGATE:
            raise ValueError("manifest aggregate differs from accepted INT-1 entry")
        return baseline
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BaselineIntegrityError(f"baseline integrity failure: {path}: {exc}") from exc


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def source_snapshot() -> dict[str, object]:
    files: dict[str, str] = {}
    for folder in ("src", "tests"):
        for path in sorted((AGENTOS / folder).rglob("*.py")):
            relative = path.relative_to(ROOT).as_posix()
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = "\n".join(f"{path} {digest}" for path, digest in sorted(files.items()))
    return {
        "aggregate": hashlib.sha256(manifest.encode("utf-8")).hexdigest(),
        "files": files,
    }


def changed_python_paths(current: dict[str, object], baseline_path: Path) -> tuple[list[str], str]:
    old_files = load_baseline(baseline_path)["files"]
    now_files = current["files"]
    assert isinstance(now_files, dict)
    changed = sorted(path for path in set(old_files) | set(now_files)
                     if old_files.get(path) != now_files.get(path))
    return changed, str(baseline_path)


def resolve_tests(changed_paths: list[str]) -> tuple[list[str], list[str]]:
    changed_sources = [
        path.removeprefix("apps/agentOS/")
        for path in changed_paths
        if (path.startswith("apps/agentOS/src/") or path in EXTERNAL_SOURCES) and path.endswith(".py")
    ]
    changed_tests = [
        path.removeprefix("apps/agentOS/")
        for path in changed_paths
        if path.startswith("apps/agentOS/tests/") and path.endswith(".py")
    ]
    selected: set[str] = set(changed_tests)
    uncovered: list[str] = []
    for source in changed_sources:
        rules = [tests for prefix, tests in SOURCE_TEST_RULES if source == prefix or source.startswith(prefix)]
        mapped = {test for group in rules for test in group}
        if not mapped:
            uncovered.append(source)
            continue
        selected.update(mapped)
    return sorted(selected), uncovered


def parse_pytest_counts(output: str) -> dict[str, int | None]:
    # Read pytest's final summary only. A timed-out partial run is explicitly
    # marked incomplete by the caller even if some tests already passed.
    summary = next((line for line in reversed(output.splitlines()) if re.search(r"\b(in|no tests ran)\b", line)), "")
    counts: dict[str, int | None] = {}
    for name in ("passed", "failed", "error", "errors", "skipped", "xfailed", "xpassed", "deselected"):
        found = re.search(rf"\b(\d+)\s+{name}\b", summary)
        counts[name] = int(found.group(1)) if found else (0 if summary else None)
    collected = re.search(r"\bcollected\s+(\d+)\s+items?\b", output)
    counts["collected"] = int(collected.group(1)) if collected else None
    counted = sum(counts[name] or 0 for name in ("passed", "failed", "error", "errors", "skipped", "xfailed", "xpassed", "deselected"))
    counts["not_completed"] = max(0, counts["collected"] - counted) if counts["collected"] is not None else None
    return counts


def measured_test_durations(output: str) -> dict[str, float]:
    durations: dict[str, float] = {}
    pattern = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)s\s+(?:setup|call|teardown)\s+(.+)$")
    for line in output.splitlines():
        match = pattern.match(line)
        if match:
            seconds, node_id = float(match.group(1)), match.group(2).strip()
            durations[node_id] = durations.get(node_id, 0.0) + seconds
    return durations


def update_duration_history(durations: dict[str, float]) -> dict[str, float]:
    path = ROOT / "tmp" / "freeze_gate" / "test_durations.json"
    history: dict[str, float] = {}
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                history = {str(key): float(value) for key, value in payload.items()}
        except (ValueError, TypeError):
            history = {}
    # Keep the maximum measured duration per test. It is an observation, not a
    # worst-case guarantee; missing entries stay unknown instead of guessed.
    for node_id, seconds in durations.items():
        history[node_id] = max(history.get(node_id, 0.0), seconds)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return history


def load_duration_history() -> dict[str, float]:
    path = ROOT / "tmp" / "freeze_gate" / "test_durations.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {str(key): float(value) for key, value in payload.items()} if isinstance(payload, dict) else {}
    except (ValueError, TypeError):
        return {}


def collect_node_ids(paths: list[str], timeout: float) -> tuple[list[str], int, str]:
    command = [
        sys.executable, "-m", "pytest", "--collect-only", "-q", *paths,
        "-m", FAST_OR_CRITICAL,
    ]
    completed = subprocess.run(
        command, cwd=AGENTOS, text=True, encoding="utf-8", errors="replace",
        capture_output=True, timeout=timeout,
    )
    node_ids = sorted({
        line.strip().replace("\\", "/")
        for line in completed.stdout.splitlines()
        if line.strip().startswith("tests/") and "::" in line
    })
    return node_ids, completed.returncode, completed.stdout + completed.stderr


def check_diff_whitespace() -> tuple[int, str]:
    completed = subprocess.run(
        ["git", "diff", "--check", "HEAD"], cwd=ROOT,
        text=True, encoding="utf-8", errors="replace", capture_output=True,
    )
    return completed.returncode, (completed.stdout + completed.stderr).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE,
                        help="prior src/tests snapshot manifest (default: frozen C2A-3 at INT-1 entry)")
    parser.add_argument("--budget-seconds", type=int, default=DEFAULT_BUDGET_SECONDS,
                        help="hard stage-freeze budget; values above 300 are rejected")
    parser.add_argument("--dry-run", action="store_true", help="show selected tests without executing pytest")
    args = parser.parse_args()
    if not 1 <= args.budget_seconds <= DEFAULT_BUDGET_SECONDS:
        parser.error("--budget-seconds must be between 1 and 300")

    baseline_path = args.baseline if args.baseline.is_absolute() else ROOT / args.baseline
    started = utc_now()
    wall_start = time.perf_counter()
    before = source_snapshot()
    external_before = external_snapshot()
    try:
        changed, baseline_name = changed_python_paths(before, baseline_path)
    except BaselineIntegrityError as exc:
        return write_report({"started_utc": started, "budget_seconds": args.budget_seconds,
            "status": "BLOCKED_BASELINE_INTEGRITY", "baseline": str(baseline_path),
            "error": str(exc), "pytest_counts": None, "pytest_command": None,
            "source_aggregate_sha256": before["aggregate"]}, wall_start, 2)
    external_changed = changed_external_paths(external_before)
    changed = sorted(set(changed + external_changed))
    selected, uncovered = resolve_tests(changed)
    missing = [path for path in selected if not (AGENTOS / path.split("::", 1)[0]).is_file()]
    check_code, check_output = check_diff_whitespace()

    report: dict[str, object] = {
        "started_utc": started,
        "finished_utc": None,
        "budget_seconds": args.budget_seconds,
        "baseline": baseline_name,
        "baseline_commit": BASELINE_COMMIT,
        "baseline_sha256": BASELINE_SHA256,
        "external_baseline_sha256": EXTERNAL_BASELINE,
        "source_aggregate_sha256": before["aggregate"],
        "source_file_count": len(before["files"]),  # type: ignore[arg-type]
        "external_source_sha256": external_before,
        "changed_agentos_python_files": changed,
        "selected_test_paths": selected,
        "uncovered_source_paths": uncovered,
        "missing_test_paths": missing,
        "missing_external_source_paths": [p for p, digest in external_before.items() if digest is None],
        "git_diff_check_exit_code": check_code,
        "git_diff_check_output": check_output,
        "status": "NOT_STARTED",
        "pytest_command": None,
        "pytest_counts": None,
        "elapsed_seconds": 0.0,
        "log_path": None,
    }
    if args.dry_run:
        report["status"] = "DRY_RUN"
        report["finished_utc"] = utc_now()
        report["elapsed_seconds"] = round(time.perf_counter() - wall_start, 3)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if not uncovered and not missing and not report["missing_external_source_paths"] and check_code == 0 else 2
    if uncovered or missing or report["missing_external_source_paths"] or check_code != 0:
        report["status"] = "BLOCKED_BEFORE_TESTS"
        return write_report(report, wall_start, 2)
    if not changed:
        report["status"] = "NO_AGENTOS_PYTHON_CHANGES"
        return write_report(report, wall_start, 0)
    if not selected:
        report["status"] = "NO_TESTS_SELECTED"
        return write_report(report, wall_start, 2)

    remaining = max(0.0, args.budget_seconds - (time.perf_counter() - wall_start))
    if remaining <= 0:
        report["status"] = "INCOMPLETE_TIMEOUT_DURING_DISCOVERY"
        return write_report(report, wall_start, 1)
    try:
        node_ids, collect_exit, collect_output = collect_node_ids(selected, remaining)
    except subprocess.TimeoutExpired:
        report["status"] = "INCOMPLETE_TIMEOUT_DURING_DISCOVERY"
        return write_report(report, wall_start, 1)
    report["collected_test_node_ids"] = node_ids
    report["collection_exit_code"] = collect_exit
    report["collection_output_tail"] = collect_output.splitlines()[-8:]
    if collect_exit != 0 or not node_ids:
        report["status"] = "BLOCKED_TEST_DISCOVERY" if collect_exit != 0 else "NO_TESTS_SELECTED"
        return write_report(report, wall_start, 2)

    duration_history = load_duration_history()
    known = {node_id: duration_history[node_id] for node_id in node_ids if node_id in duration_history}
    unknown = [node_id for node_id in node_ids if node_id not in duration_history]
    measured_sum = sum(known.values())
    remaining = max(0.0, args.budget_seconds - (time.perf_counter() - wall_start))
    report["historical_duration_seconds"] = known
    report["historical_duration_sum_seconds"] = round(measured_sum, 3)
    report["duration_unknown_test_node_ids"] = unknown
    if measured_sum > remaining:
        report["status"] = "BLOCKED_KNOWN_DURATION_OVER_BUDGET"
        report["remaining_budget_before_tests_seconds"] = round(remaining, 3)
        return write_report(report, wall_start, 1)
    if remaining <= 0:
        report["status"] = "INCOMPLETE_TIMEOUT_DURING_DISCOVERY"
        return write_report(report, wall_start, 1)

    command = [
        sys.executable, "-m", "pytest", "-q", *node_ids,
        "--tb=short", "--durations=0",
    ]
    report["pytest_command"] = command
    output_dir = ROOT / "tmp" / "freeze_gate"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = output_dir / f"{stamp}.log"
    report_path = output_dir / f"{stamp}.json"
    report["log_path"] = str(log_path.relative_to(ROOT))
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    timed_out = False
    remaining = max(0.0, args.budget_seconds - (time.perf_counter() - wall_start))
    with log_path.open("wb") as log:
        if remaining <= 0:
            process = None
            timed_out = True
        else:
            process = subprocess.Popen(command, cwd=AGENTOS, stdout=log, stderr=subprocess.STDOUT, env=env)
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                timed_out = True
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   cwd=ROOT, capture_output=True, check=False)
                else:
                    process.kill()
                process.wait()
    output = log_path.read_text(encoding="utf-8", errors="replace")
    report["pytest_counts"] = parse_pytest_counts(output)
    observed_durations = measured_test_durations(output)
    report["measured_test_durations_seconds"] = observed_durations
    report["duration_history_file"] = "tmp/freeze_gate/test_durations.json"
    update_duration_history(observed_durations)
    report["status"] = "INCOMPLETE_TIMEOUT" if timed_out else ("PASSED" if process and process.returncode == 0 else "FAILED")
    report["pytest_exit_code"] = process.returncode if process else None
    report["timed_out"] = timed_out
    try:
        load_baseline(baseline_path)
    except BaselineIntegrityError as exc:
        report["status"] = "INCOMPLETE_BASELINE_CHANGED"
        report["error"] = str(exc)
        return write_report(report, wall_start, 1, report_path)
    if source_snapshot()["aggregate"] != before["aggregate"] or external_snapshot() != external_before:
        report["status"] = "INCOMPLETE_SOURCE_CHANGED"
        return write_report(report, wall_start, 1, report_path)
    return write_report(report, wall_start, 0 if process and process.returncode == 0 and not timed_out else 1, report_path)


def write_report(report: dict[str, object], wall_start: float, exit_code: int, report_path: Path | None = None) -> int:
    report["finished_utc"] = utc_now()
    report["elapsed_seconds"] = round(time.perf_counter() - wall_start, 3)
    if (report.get("status") in {"PASSED", "FAILED"}
            and report["elapsed_seconds"] > report.get("budget_seconds", DEFAULT_BUDGET_SECONDS)):
        report["status"] = "INCOMPLETE_GATE_BUDGET_EXCEEDED"
        exit_code = 1
    if report_path is None:
        output_dir = ROOT / "tmp" / "freeze_gate"
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        report_path = output_dir / f"{stamp}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
