"""Fail when active setup files refer to removed repository paths."""
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[3]
SCANNED_FILES = [
    ROOT / ".gitignore",
    ROOT / "README.md",
    ROOT / ".env.example",
    ROOT / ".github/workflows/backend-ci.yml",
    ROOT / "apps/backend/package.json",
    ROOT / "apps/agent/README.md",
    ROOT / "apps/agentOS/README.md",
    ROOT / "ops/scripts/release/assemble_portable.py",
    ROOT / "ops/scripts/release/product_runtime.py",
    ROOT / "ops/scripts/runtime_streaming_combined_acceptance.py",
]
REQUIRED_TEXT = {
    ROOT / "README.md": (
        "python -m pytest -c apps/agentOS/pytest.ini TEST/tests -q",
        "apps/backend/test",
    ),
    ROOT / "apps/agent/README.md": (
        "python -m pytest tests -q",
        "requirements.in",
        "requirements.lock",
    ),
}
STALE_PATHS = ("apps/backend-ts", "KINLIN_HTTP_PORT=8080")
REQUIRED_PATHS = (
    ROOT / "apps/backend",
    ROOT / "TEST/tests",
    ROOT / "apps/agent/requirements.in",
    ROOT / "apps/agent/requirements.lock",
    ROOT / ".env.example",
)


def main() -> int:
    failures = [f"missing required path: {path.relative_to(ROOT)}"
                for path in REQUIRED_PATHS if not path.exists()]
    for path in SCANNED_FILES:
        if not path.is_file():
            failures.append(f"missing hygiene input: {path.relative_to(ROOT)}")
            continue
        contents = path.read_text(encoding="utf-8")
        for stale_path in STALE_PATHS:
            if stale_path in contents:
                failures.append(f"stale path {stale_path!r} in {path.relative_to(ROOT)}")
    for path, snippets in REQUIRED_TEXT.items():
        contents = path.read_text(encoding="utf-8")
        for snippet in snippets:
            if snippet not in contents:
                failures.append(f"missing current setup text {snippet!r} in {path.relative_to(ROOT)}")
    if failures:
        print("Repository hygiene failed:")
        print("\n".join(f"- {failure}" for failure in failures))
        return 1
    print("Repository paths are current.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
