#!/usr/bin/env python3
"""Explicit C2 Schema maintenance; default is inspection without target writes."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "agentOS" / "src"))
from support.stores.c2_schema_upgrade import SchemaUpgradeError, inspect_databases, upgrade_databases


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-db", type=Path, required=True)
    parser.add_argument("--checkpoint-db", type=Path, required=True)
    parser.add_argument("--identity-db", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="write Schema using existing administrative upgrades")
    parser.add_argument("--initialize-empty", action="store_true", help="explicitly initialize absent/empty databases only")
    args = parser.parse_args(argv)
    paths = dict(workflow=args.workflow_db, checkpoint=args.checkpoint_db, identity=args.identity_db)
    try:
        if args.apply:
            result = upgrade_databases(**paths, initialize_empty=args.initialize_empty)
        else:
            result = {"status": "INSPECTED", "databases": inspect_databases(**paths, initialize_empty=args.initialize_empty)}
            if any(item["status"] != "READY" for item in result["databases"].values()):
                result["status"] = "NOT_READY"
        code = 0 if result["status"] in {"READY", "INSPECTED"} else 2
    except (SchemaUpgradeError, sqlite3.Error, OSError, RuntimeError, ValueError) as exc:
        result = {"status": "FAILED", "error": str(exc), "recovery": "Inspect these exact files, then reapply; never delete accepted data."}
        try:
            result["databases"] = inspect_databases(**paths, initialize_empty=args.initialize_empty)
        except (SchemaUpgradeError, sqlite3.Error, OSError, RuntimeError, ValueError) as inspect_error:
            result["inspection_error"] = str(inspect_error)
        code = 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
