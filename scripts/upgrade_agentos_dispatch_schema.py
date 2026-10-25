"""Explicit administrative installation of the Dispatch admission journal."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/agentOS/src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/agentOS"))
from support.stores.execution_dispatch_store import SQLiteExecutionDispatchStore


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-db", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Explicitly install version 1 into an existing C2 DB")
    args = parser.parse_args()
    if args.apply:
        SQLiteExecutionDispatchStore.upgrade_schema(args.workflow_db)
    SQLiteExecutionDispatchStore(args.workflow_db)
    print("Dispatch schema version 1 verified")
