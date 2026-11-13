"""Compare context projections offline; SQLite is opened read-only, no model calls.

Run from the repository root with --data-dir and --run-id. Prints sizes and
identifiers only. These characters are not model input tokens or cache usage.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys

AGENTOS_ROOT = Path(__file__).resolve().parents[1] / "apps" / "agentOS"
sys.path[:0] = [str(AGENTOS_ROOT / "src"), str(AGENTOS_ROOT)]

from adapters.model.prompt_context import project_inline_content, project_prompt_context
from adapters.prompt_runtime import TrustClass, trust_envelope


def compare_projection(data_dir: Path, run_id: str) -> dict:
    rows = []
    connection = sqlite3.connect((data_dir.resolve() / "values.sqlite3").as_uri() + "?mode=ro", uri=True)
    try:
        for step, raw in connection.execute(
            "SELECT step_id,payload_json FROM execution_values WHERE run_id=? AND kind=? ORDER BY step_id,reference",
            (run_id, "context"),
        ):
            pack = json.loads(raw)
            upstream, sources, aliases = project_prompt_context(pack["data"], pack["sourceData"])
            original = {
                "upstreamOutputs": trust_envelope(TrustClass.AGENT_GENERATED, upstream),
                "sourceData": trust_envelope(TrustClass.EXTERNAL_UNTRUSTED, {"contextSources": sources}),
            }
            if aliases:
                original["upstreamOutputRefs"] = trust_envelope(TrustClass.AGENT_GENERATED, aliases)
            projected = project_inline_content(original)
            restored = deepcopy(projected)
            references = restored.pop("inlineContentRefs", {}).get("content", {}).get("references", [])
            for ref in references:
                target = restored
                for key in ref["targetPath"]:
                    target = target[key]
                parent = restored
                for key in ref["path"][:-1]:
                    parent = parent[key]
                if not isinstance(target, (str, dict, list)) or parent[ref["path"][-1]] is not None:
                    raise ValueError(f"Invalid inline reference in step {step}")
                parent[ref["path"][-1]] = deepcopy(target)
            if restored != original:
                raise ValueError(f"Projection is not lossless in step {step}")
            def size(value):
                return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            before, after = size(original), size(projected)
            rows.append({"stepId": step, "beforeCharacters": before, "afterCharacters": after,
                         "savedCharacters": before - after, "referenceCount": len(references)})
    finally:
        connection.close()
    if not rows:
        raise ValueError("No persisted ContextPacks found for this Run")
    before = sum(row["beforeCharacters"] for row in rows)
    after = sum(row["afterCharacters"] for row in rows)
    return {"runId": run_id, "scope": "upstream-context-projection", "unit": "characters",
            "packs": len(rows), "allLossless": True, "beforeCharacters": before, "afterCharacters": after,
            "savedCharacters": before - after, "reductionPercent": round((before - after) / before * 100, 2) if before else 0,
            "steps": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(compare_projection(args.data_dir, args.run_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
