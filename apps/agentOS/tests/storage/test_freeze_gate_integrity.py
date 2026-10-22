"""Mapping and fail-closed reporting, without a real 300-second timeout."""
import hashlib
from pathlib import Path
import runpy
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[4]


def load():
    return runpy.run_path(str(ROOT / "scripts/freeze_gate.py"))


@pytest.mark.parametrize("source,required", [
    ("src/components/resource/__init__.py", "tests/components/resource/test_resource_auth.py"),
    ("src/components/resource/errors.py", "tests/components/resource/test_remote_observation.py"),
    ("src/components/resource/health_store.py", "tests/components/resource/test_health_store.py"),
    ("src/components/resource/node_health.py", "tests/components/resource/test_node_store.py"),
    ("src/components/resource/node_store.py", "tests/components/resource/test_node_store.py"),
    ("src/components/resource/service.py", "tests/components/resource/test_resource_auth.py"),
    ("src/components/resource/sqlite_support.py", "tests/components/resource/test_store_contract.py"),
    ("src/components/resource/store.py", "tests/components/resource/test_store_contract.py"),
    ("src/contracts/resource.py", "tests/components/resource/test_edge_cloud_contracts.py"),
    ("src/components/scheduler/binder.py", "tests/components/scheduler/test_binder.py"),
    ("src/components/scheduler/leases.py", "tests/components/scheduler/test_redis_leases.py"),
    ("src/components/scheduler/models.py", "tests/components/scheduler/test_binder.py"),
    ("src/support/stores/c2_schema_upgrade.py", "tests/storage/test_c2_schema_integrity.py"),
    ("scripts/upgrade_agentos_c2_schema.py", "tests/storage/test_c2_schema_upgrade.py"),
])
def test_relevant_source_resolves_real_related_tests(source, required):
    gate = load()
    path = source if source.startswith("scripts/") else "apps/agentOS/" + source
    selected, uncovered = gate["resolve_tests"]([path])
    assert not uncovered
    assert required in selected
    assert all((gate["AGENTOS"] / item.split("::", 1)[0]).is_file() for item in selected)


def test_entire_original_baseline_delta_is_mapped_without_moving_baseline():
    gate = load()
    baseline = gate["DEFAULT_BASELINE"]
    assert hashlib.sha256(baseline.read_bytes()).hexdigest() == "54ccc02a3d0ba550fffff8dd23f259460977ae0a75f3d8eea4d7c1848ce1a591"
    changed, _ = gate["changed_python_paths"](gate["source_snapshot"](), baseline)
    selected, uncovered = gate["resolve_tests"](changed)
    assert not uncovered, uncovered
    assert selected and len(selected) == len(set(selected))
    assert all((gate["AGENTOS"] / item.split("::", 1)[0]).is_file() for item in selected)


@pytest.mark.parametrize("fault,status", [("sources", "INCOMPLETE_SOURCE_CHANGED"),
    ("schema_failure", "FAILED"), ("timeout", "INCOMPLETE_TIMEOUT")])
def test_gate_never_reports_success_for_changed_sources_failed_preflight_or_timeout(tmp_path, monkeypatch, fault, status):
    gate = load()
    ns = gate["main"].__globals__
    test_file = tmp_path / "agentOS/tests/test_target.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_target(): pass\n", encoding="utf8")
    snapshots = iter(("initial", "changed" if fault == "sources" else "initial"))
    # Control the child-process boundary only. Real SQLite failure/refusal is
    # exercised separately in test_c2_schema_integrity, not mocked here.
    class Child:
        def __init__(self, command, **kwargs):
            kwargs["stdout"].write(b"1 failed in 0.01s\n" if fault == "schema_failure" else b"1 passed in 0.01s\n")
            self.returncode = 1 if fault == "schema_failure" else 0
        def wait(self, timeout=None):
            if timeout is not None and fault == "timeout":
                raise subprocess.TimeoutExpired("pytest", timeout)
            return self.returncode
        def kill(self):
            pass
    for key, value in {
        "ROOT": tmp_path, "AGENTOS": test_file.parents[1],
        "source_snapshot": lambda: {"aggregate": next(snapshots), "files": {"source": "hash"}},
        "external_snapshot": lambda: {}, "check_diff_whitespace": lambda: (0, ""),
        "changed_python_paths": lambda *a: (["source"], "fixed original baseline"),
        "resolve_tests": lambda *a: (["tests/test_target.py"], []),
        "collect_node_ids": lambda *a: (["tests/test_target.py::test_target"], 0, ""),
        "load_duration_history": lambda: {}, "update_duration_history": lambda *a: None,
        "os": SimpleNamespace(environ={}, name="posix"),
        "subprocess": SimpleNamespace(check_output=lambda *a, **kw: "", Popen=Child,
                                      STDOUT=subprocess.STDOUT, TimeoutExpired=subprocess.TimeoutExpired),
    }.items():
        monkeypatch.setitem(ns, key, value)
    monkeypatch.setattr(sys, "argv", ["freeze_gate.py"])
    assert gate["main"]() != 0
    import json
    reports = list((tmp_path / "tmp/freeze_gate").glob("*.json"))
    assert len(reports) == 1
    result = json.loads(reports[0].read_text(encoding="utf8"))
    assert result["status"] == status
    assert result["status"] != "PASSED"


def test_wall_clock_over_budget_cannot_be_a_success(tmp_path, monkeypatch):
    gate = load()
    ns = gate["write_report"].__globals__
    monkeypatch.setitem(ns, "time", SimpleNamespace(perf_counter=lambda: 301))
    report = {"status": "PASSED", "budget_seconds": 300}
    assert gate["write_report"](report, 0, 0, tmp_path / "report.json") == 1
    assert report["status"] == "INCOMPLETE_GATE_BUDGET_EXCEEDED"
