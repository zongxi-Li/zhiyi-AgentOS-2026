"""Keep the SAFE-style dependency boundary enforceable after future changes."""
import ast
from pathlib import Path
import subprocess
import sys


ROOT = next(p for p in Path(__file__).resolve().parents if (p / "apps/agentOS/src").is_dir())
BASE = ROOT / "apps/agentOS/src/components/evolution"


def test_use_case_and_rule_layers_do_not_import_adapters_or_runtime():
    forbidden = {
        "application": ("runtime", "contracts.workflow", "sqlite3", "pathlib",
            "components.evolution.infrastructure", "components.evolution.integration",
            "components.evolution.bootstrap", "components.evolution.store"),
        "domain": ("runtime", "sqlite3", "components.evolution.ports",
            "components.evolution.application", "components.evolution.infrastructure"),
        "ports": ("runtime", "sqlite3", "components.evolution.application",
            "components.evolution.infrastructure", "components.evolution.integration"),
    }
    for layer, prefixes in forbidden.items():
        assert (BASE / layer).is_dir()
        for path in (BASE / layer).glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                modules = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                           [a.name for a in node.names] if isinstance(node, ast.Import) else [])
                assert not any(m == p or m.startswith(p + ".") for m in modules for p in prefixes), path


def test_public_policy_import_does_not_load_storage_or_runtime():
    script = """
import sys
sys.path.insert(0, 'apps/agentOS/src')
import components.evolution.policy
assert 'sqlite3' not in sys.modules
assert not any(n.startswith('components.evolution.infrastructure') for n in sys.modules)
assert not any(n.startswith('runtime') for n in sys.modules)
"""
    result = subprocess.run([sys.executable, "-B", "-c", script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
