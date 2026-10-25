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
from pathlib import Path

import pytest


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
    node_ids = load_node_ids(Path(argv[1]))
    return pytest.main(["-q", *node_ids, *argv[2:]])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
