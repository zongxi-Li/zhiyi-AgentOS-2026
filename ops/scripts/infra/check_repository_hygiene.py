"""Validate active paths, lock contracts and the tracked artifact boundary."""
from pathlib import Path
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
PACKAGES = (
    "apps/backend", "apps/frontend", "apps/desktop/electron", "apps/terminal",
    "apps/agentOS/src/components/environment/hands",
    "apps/agentOS/src/components/environment/compact",
)
STALE_PATHS = ("apps/backend-ts", "apps/agentOS/tests")
RESEARCH_SOURCES = {".md", ".py", ".cjs", ".js", ".drawio", ".svg"}
TEXT_SUFFIXES = {".md", ".py", ".ts", ".vue", ".mjs", ".json", ".ps1", ".bat", ".yml", ".yaml", ".ini"}


def check_paths(root, paths):
    failures = []
    for relative in paths:
        name = relative.as_posix()
        # Audit evidence retains its original paths. Tests intentionally exercise
        # rejected paths; this checker is itself their definition.
        if name.startswith(("docs/", "papers/", "apps/agentOS/docs/", "scripts/freeze_gate_baselines/")):
            continue
        if name.endswith("check_repository_hygiene.py") or "/tests/" in name or name.endswith(".spec.ts"):
            continue
        if "/vendor/" in name or relative.suffix not in TEXT_SUFFIXES:
            continue
        path = root / relative
        if not path.is_file():
            failures.append(f"missing tracked input: {name}")
            continue
        source = path.read_text(encoding="utf-8")
        for stale in STALE_PATHS:
            if stale in source.replace("\\\\", "/"):
                failures.append(f"stale path {stale!r}: {name}")
    return failures


def check_package(root, relative):
    failures = []
    try:
        manifest = json.loads((root / relative / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((root / relative / "package-lock.json").read_text(encoding="utf-8"))
        locked = lock["packages"][""]
    except (OSError, ValueError, KeyError) as error:
        return [f"invalid package/lock: {relative}: {error}"]
    for key in ("name", "version", "dependencies", "devDependencies", "optionalDependencies", "engines"):
        if manifest.get(key) != locked.get(key):
            failures.append(f"{relative}: manifest/lock {key} mismatch")
    if manifest.get("engines", {}).get("node") != ">=24.9.0 <25":
        failures.append(f"{relative}: expected Node >=24.9.0 <25")
    typescript = manifest.get("devDependencies", {}).get("typescript")
    if typescript and typescript != "5.9.3":
        failures.append(f"{relative}: expected TypeScript 5.9.3")
    if typescript and lock["packages"].get("node_modules/typescript", {}).get("version") != typescript:
        failures.append(f"{relative}: resolved TypeScript differs from manifest")
    return failures


def check_artifacts(paths):
    failures = []
    for path in paths:
        if path.parts[0] == "papers" and (".build" in path.parts or
                path.suffix.lower() not in RESEARCH_SOURCES and path.name != "ARTIFACTS.csv"):
            failures.append(f"research artifact must stay untracked: {path}")
    return failures


def check_python_lock(root):
    failures = []
    for stem in ("requirements", "requirements.dev"):
        source = root / "apps/agent" / (stem + ".in")
        lock = root / "apps/agent" / (stem + ".lock")
        text = lock.read_text(encoding="utf-8")
        pins = {name.lower().replace("_", "-"): version for name, version in
                re.findall(r"^([\w.-]+)==([^\s\\;]+)", text, re.M)}
        for name, version in re.findall(r"^([\w.-]+)(?:\[[^]]+\])?==([^\s;]+)", source.read_text(encoding="utf-8"), re.M):
            if pins.get(name.lower().replace("_", "-")) != version:
                failures.append(f"{stem}: input pin not represented in lock: {name}=={version}")
        if "--hash=sha256:" not in text:
            failures.append(f"{stem}: missing dependency hashes")
    return failures


def main():
    result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    paths = [Path(name) for name in result.stdout.decode("utf-8").split("\0") if name]
    failures = check_paths(ROOT, paths) + check_artifacts(paths) + check_python_lock(ROOT)
    for package in PACKAGES:
        failures.extend(check_package(ROOT, Path(package)))
    for path in ("TEST/tests", "apps/agent/tests", "apps/backend/src/shared/runtime-defaults.json"):
        if not (ROOT / path).exists():
            failures.append(f"required path missing: {path}")
    if (ROOT / ".python-version").read_text().strip() != "3.14":
        failures.append("expected Python 3.14 development baseline")
    if not (ROOT / ".node-version").read_text().strip().startswith("24."):
        failures.append("expected Node 24 development baseline")
    if "python -m pytest --rootdir=. -c apps/agentOS/pytest.ini TEST/tests -n 4 --dist loadscope -q" not in (ROOT / "README.md").read_text(encoding="utf-8"):
        failures.append("README kernel test command is stale")
    if (ROOT / "apps/desktop/package-lock.json").exists():
        failures.append("orphan desktop lock must be removed")
    if failures:
        print("Repository hygiene failed:\n" + "\n".join(f"- {failure}" for failure in failures))
        return 1
    print("Repository paths, dependency locks and artifact boundaries are current.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
