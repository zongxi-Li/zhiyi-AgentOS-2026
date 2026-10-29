"""Preserve tool pins and Linux hashes; add published Windows wheel hashes.

Maintenance only. Installation still verifies downloaded bytes with pip
--require-hashes. Does not resolve or upgrade versions.
"""
import json
from pathlib import Path
import re
import time
from urllib.request import urlopen


def main():
    root = Path(__file__).resolve().parents[5]
    source = root / "apps/agent/requirements.tools.lock"
    text = source.read_text(encoding="utf-8")
    blocks = re.split(r"(?=^[a-zA-Z0-9_-]+==)", text, flags=re.M)[1:]
    output = ["# Windows CPython 3.14 x64 tool lock; exact pins from requirements.tools.lock.",
              "# Original hashes retained; additional wheel hashes from PyPI release JSON.",
              "# Regenerate: python ops/scripts/infra/windows/native/refresh_tool_lock.py", ""]
    # Click's Windows dependency is absent from the Linux tool lock.
    blocks.append("colorama==0.4.6\n")
    # MCP's Windows-only dependency; pip's cp314 Windows resolution selected 312.
    blocks.append("pywin32==312\n")
    for block in blocks:
        name, version = re.match(r"([^=]+)==([^\s\\]+)", block).groups()
        for attempt in range(4):
            try:
                with urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as response:
                    release = json.load(response)
                break
            except OSError:
                if attempt == 3:
                    raise
                time.sleep(1)
        hashes = set(re.findall(r"--hash=sha256:([0-9a-f]{64})", block))
        for artifact in release["urls"]:
            filename = artifact["filename"]
            if filename.endswith(".whl") and ("win_amd64" in filename or "none-any" in filename):
                hashes.add(artifact["digests"]["sha256"])
        if not hashes:
            raise RuntimeError(f"No wheel hashes: {name}=={version}")
        output.append(f"{name}=={version} \\")
        ordered = sorted(hashes)
        output.extend("    --hash=sha256:" + digest + (" \\" if i < len(ordered)-1 else "")
                      for i, digest in enumerate(ordered))
    source.with_name("requirements.native-tools.lock").write_text("\n".join(output) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
