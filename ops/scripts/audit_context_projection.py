"""Compare lossless request projections against stored contexts, without model calls.

This reads a SQLite snapshot through a read-only connection. It reports canonical
JSON character counts, not provider tokens or complete model request sizes.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sqlite3


def restore(pack: dict) -> dict:
    """Resolve runtime-authored references in dependency order for offline QA."""
    result = deepcopy(pack)
    sidecar = result.pop("inlineContentRefs", {}).get("content", {})
    for reference in sidecar.get("references", []):
        target = result
        for key in reference["targetPath"]:
            target = target[key]
        if not isinstance(target, (str, dict, list)):
            raise ValueError("alias target is not an inline JSON value")
        parent = result
        for key in reference["path"][:-1]:
            parent = parent[key]
        if parent[reference["path"][-1]] is not None:
            raise ValueError("alias path is not a null placeholder")
        parent[reference["path"][-1]] = deepcopy(target)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--value-db", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[2] / "apps/agentOS/src/adapters/model/prompt_context.py"
    spec = importlib.util.spec_from_file_location("context_projection_audit", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    results = []
    with sqlite3.connect(args.value_db.resolve(strict=True).as_uri() + "?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT step_id,payload_json FROM execution_values WHERE run_id=? AND kind='context' ORDER BY step_id,reference",
            (args.run_id,),
        ).fetchall()
    if not rows:
        raise ValueError("run has no stored contexts")
    for step_id, payload in rows:
        context = json.loads(payload)
        upstream, sources, aliases = module.project_prompt_context(context["data"], context["sourceData"])
        pack = {
            "sourceData": {"trustClass": "external_untrusted", "content": {"taskSources": {}, "contextSources": sources}},
            "upstreamOutputs": {"trustClass": "agent_generated", "content": upstream},
        }
        if aliases:
            pack["upstreamOutputRefs"] = {"trustClass": "agent_generated", "content": aliases}
        baseline = module._project_inline_content(pack, containers=False)
        projected = module.project_inline_content(pack)
        if module._wire(restore(projected)) != module._wire(pack):
            raise ValueError(f"projection does not round-trip: {step_id}")
        before, after = len(module._wire(baseline)), len(module._wire(projected))
        if after > before:
            raise ValueError(f"projection expands input: {step_id}")
        results.append({"stepId": step_id, "beforeChars": before, "afterChars": after,
                        "savedChars": before - after, "roundtrip": "passed"})
    before = sum(item["beforeChars"] for item in results)
    after = sum(item["afterChars"] for item in results)
    print(json.dumps({"runId": args.run_id, "scope": "stored_context_projection_only",
                      "unit": "canonical_json_characters", "contexts": results,
                      "beforeChars": before, "afterChars": after,
                      "reductionRatio": (before - after) / before if before else 0}, indent=2))


if __name__ == "__main__":
    main()
