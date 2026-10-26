#!/usr/bin/env python3
"""Run exactly the pytest node IDs listed in a manifest file.

The freeze gate transports its test selection as data because Windows caps
CreateProcess command lines at 32767 characters and a per-node argument
vector crashed startup with WinError 206 once the selection grew.  The
runner reads the manifest, invokes pytest in-process with the identical
flags, and exits with pytest's own exit status so the gate's status
mapping (PASSED / FAILED / timeout) stays meaningful.  No batching, no
dropped or duplicated nodes: the manifest is the selection.
"""
from __future__ import annotations

import sys
import hashlib
import json
import os
import tempfile
from pathlib import Path

import pytest


class RunObservation:
    """Structured execution evidence, not the rounded terminal duration table."""

    def __init__(self):
        self.collected = []
        self.reports = []
        self.session_exit_code = None

    def pytest_collection_finish(self, session):
        self.collected = [item.nodeid.replace('\\', '/') for item in session.items]

    def pytest_runtest_logreport(self, report):
        self.reports.append(dict(nodeId=report.nodeid.replace('\\', '/'), phase=report.when,
            outcome=report.outcome, durationSeconds=report.duration,
            expectedFailure=bool(getattr(report, 'wasxfail', False))))

    def pytest_sessionfinish(self, session, exitstatus):
        self.session_exit_code = int(exitstatus)


def load_node_ids(manifest_path: Path) -> list[str]:
    lines = manifest_path.read_text(encoding="utf-8").splitlines()
    node_ids = [line.strip().replace("\\", "/") for line in lines if line.strip()]
    if not node_ids:
        raise SystemExit(f"node manifest is empty: {manifest_path}")
    return node_ids


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: freeze_gate_pytest_runner.py NODE_MANIFEST [PYTEST_ARGS...]",
              file=sys.stderr)
        return 2
    manifest = Path(argv[1])
    manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    node_ids = load_node_ids(manifest)
    observation = RunObservation()
    result = int(pytest.main(["-q", *node_ids, *argv[2:]], plugins=[observation]))
    destination = os.environ.get('FREEZE_GATE_OBSERVATION_PATH')
    if destination:
        body = dict(version=1, invocationId=os.environ.get('FREEZE_GATE_INVOCATION_ID'),
            manifestSha256=manifest_sha, collectedNodeIds=observation.collected,
            reports=observation.reports, sessionExitCode=observation.session_exit_code,
            processExitCode=result)
        path = Path(destination)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                            delete=False, prefix='observation-', suffix='.tmp') as stream:
                temporary = Path(stream.name)
                json.dump(body, stream, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return result


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
