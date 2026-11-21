"""Run selected S00 Python tests without opening business stores or sweeping old temp dirs.

python scripts/verify_mission_semantics.py api
python scripts/verify_mission_semantics.py core
python scripts/verify_mission_semantics.py audit
"""
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
for path in [ROOT, ROOT / "apps/agent", ROOT / "apps/agentOS", ROOT / "apps/agentOS/src",
             ROOT / "apps/agent/tests", ROOT / "TEST/tests/runtime"]:
    sys.path.insert(0, str(path))

API = ["apps/agent/tests/test_mission_semantic_commands.py",
       "apps/agent/tests/test_mission_revision_decisions.py",
       "apps/agent/tests/test_mission_semantic_audit.py",
       "apps/agent/tests/test_mission_semantic_convergence_boundary.py",
       "apps/agent/tests/test_workspace_semantic_boundary.py"]
CORE = ["TEST/tests/support", "TEST/tests/runtime/test_mission_semantic_convergence.py",
        "TEST/tests/runtime/test_identity_projection_lifecycle.py",
        "TEST/tests/runtime/test_acg_run.py", "TEST/tests/runtime/test_planning_loop.py",
        "TEST/tests/runtime/test_semantic_patch.py", "TEST/tests/runtime/test_graph_patch.py",
        "TEST/tests/runtime/test_runtime_guards.py", "TEST/tests/runtime/v2"]
AUDIT = list(dict.fromkeys([*CORE, *API,
    "TEST/tests/runtime/test_cancellation_and_execution_exclusivity.py",
    "TEST/tests/runtime/test_review_recovery_extraction.py",
    "TEST/tests/runtime/test_fault_recovery.py",
    "apps/agent/tests/test_agentos_v2_api.py", "apps/agent/tests/test_agentos_v2_workspace_api.py",
    "apps/agent/tests/test_agentos_v2_artifact_api.py", "apps/agent/tests/test_execution_coordinator.py",
    "apps/agent/tests/test_execution_runtime_application_wiring.py", "apps/agent/tests/test_internal_service_auth.py",
]))

if __name__ == "__main__":
    suite = sys.argv[1] if len(sys.argv) > 1 else "api"
    paths = API if suite == "api" else CORE if suite == "core" else AUDIT if suite == "audit" else sys.argv[1:]
    if suite in {"api", "core", "audit"}:
        paths = list(dict.fromkeys([*paths, *sys.argv[2:]]))
    with tempfile.TemporaryDirectory(prefix="kinlin-s00-", ignore_cleanup_errors=True) as directory:
        isolated = Path(directory)
        os.chdir(isolated)
        (isolated / ".env").write_text("", encoding="utf-8")
        for key in ["WORKFLOW_DB_PATH", "LANGGRAPH_CHECKPOINT_DB", "EXECUTION_VALUE_DB", "CONTENT_MANIFEST_DB",
                    "EXECUTION_MEMORY_DB", "PROVENANCE_DB", "AUDIT_DB", "RESOURCE_DB", "NODE_DB", "AGENT_DB",
                    "RESOURCE_HEALTH_DB", "EVOLUTION_DB", "IDENTITY_DB"]:
            os.environ["AGENTOS_" + key] = str(isolated / (key.lower() + ".sqlite3"))
        os.environ["AGENT_CHROMA_PATH"] = str(isolated / "chroma")
        os.environ["AGENTOS_ATTACHMENT_STORAGE_DIR"] = str(isolated / "attachments")
        import pytest
        result = pytest.main(["--noconftest", "--rootdir", str(ROOT), "-c", str(ROOT / "apps/agentOS/pytest.ini"),
            *[str(ROOT / p) for p in paths], "--basetemp", str(isolated / "pytest"),
            "-o", "asyncio_mode=auto", "-q", "-p", "no:cacheprovider"])
        os.chdir(ROOT)
        # Some provider libraries retain open handles until process exit on Windows.
        # The test stores themselves are always scoped to this owned temp directory.
    sys.exit(result)
