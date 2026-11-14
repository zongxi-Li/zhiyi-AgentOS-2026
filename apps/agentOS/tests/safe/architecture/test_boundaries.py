"""分层与导入行为守卫：检查实际源文件，不通过假服务绕过边界。"""

import ast
from pathlib import Path
import subprocess
import sys

import safe

ROOT = Path(safe.__file__).parent
LAYERS = {"contracts", "domain", "ports", "application", "infrastructure", "interfaces", "bootstrap", "integration"}
ALLOWED = {
    "contracts": {"contracts"},
    "domain": {"contracts", "domain"},
    "ports": {"contracts", "domain", "ports"},
    "application": {"contracts", "domain", "ports", "application"},
    "infrastructure": {"contracts", "domain", "ports", "infrastructure"},
    "interfaces": {"contracts", "application", "interfaces"},
    "bootstrap": LAYERS,
    "integration": LAYERS | {"inference", "activation", "manifest", "privacy", "privacy_ledger", "session", "transport"},
    "facade": {"contracts", "application", "ports"},
}
PURE = {"contracts", "domain", "ports", "application", "facade"}


def test_dependency_directions_and_lightweight_inner_layers():
    for path in ROOT.rglob("*.py"):
        relative = path.relative_to(ROOT)
        if relative == Path("encryptionservice.py") or "legacy" in relative.parts:
            continue  # 旧实现的行为迁移独立验收，新链路不能依赖它。
        layer = relative.parts[0] if relative.parts[0] in LAYERS else "facade"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"请使用统一safe.*绝对导入：{path}"
                names = [node.module or ""]
            for name in names:
                parts = name.split(".")
                if parts[0] == "safe":
                    assert len(parts) >= 2 and parts[1] in ALLOWED[layer], (relative, name)
                    assert "legacy" not in parts and "encryptionservice" not in parts, (relative, name)
                elif layer in PURE:
                    assert parts[0] in sys.stdlib_module_names | {"pydantic", "__future__"}, (relative, name)
                if parts[0] in {"apps", "components", "adapters", "runtime"} or parts[0] == "contracts":
                    assert layer == "integration", (relative, name)


def test_public_imports_do_not_load_heavy_dependencies_or_create_resources(tmp_path):
    script = r'''
import builtins, importlib, pathlib, socket, sys, threading
sys.path.insert(0, sys.argv[1])
real_import = builtins.__import__
forbidden = {"torch", "transformers", "numpy", "fastapi", "httpx", "sqlite3", "cryptography", "diffprivlib"}
def guarded_import(name, *args, **kwargs):
    if name.split(".")[0] in forbidden:
        raise AssertionError("导入了重依赖：" + name)
    return real_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
def no_resource(*args, **kwargs):
    raise AssertionError("导入时创建外部资源")
socket.socket.connect = no_resource
threading.Thread.start = no_resource
pathlib.Path.mkdir = no_resource
def audit(event, args):
    if event == "open":
        mode = args[1]
        flags = args[2]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & 3):
            raise AssertionError("导入时写文件")
sys.addaudithook(audit)
for name in ("inference", "activation", "manifest", "privacy", "privacy_ledger", "session", "transport"):
    importlib.import_module("safe." + name)
from safe.inference import InferenceRequest
from safe.contracts.inference import InferenceRequest as Contract
assert InferenceRequest is Contract
from safe.manifest import SplitModelManifest
from safe.inference import SplitModelManifest as Reexport
assert SplitModelManifest is Reexport
assert not (forbidden & set(sys.modules))
'''
    result = subprocess.run([sys.executable, "-B", "-c", script, str(ROOT.parent)],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not list(tmp_path.iterdir())
