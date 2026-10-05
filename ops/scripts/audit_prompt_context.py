"""Read-only comparison of persisted contexts with the current prompt projection.

This reports JSON character counts, not provider tokens, prices, or cache hits.
No model requests or database writes are performed. Run with AgentOS on PYTHONPATH.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

if Path(__file__).name != "<stdin>":
    agentos = Path(__file__).resolve().parents[2] / "apps" / "agentOS"
    sys.path[:0] = [str(agentos / "src"), str(agentos)]

from adapters.model.prompt_context import project_prompt_context
from adapters.prompt_runtime import TrustClass, trust_envelope


def audit(database: Path, run_id: str) -> dict:
    def encoded(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    uri = database.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            "SELECT step_id, payload_json FROM execution_values WHERE run_id = ? AND kind = 'context' ORDER BY step_id, reference",
            (run_id,),
        ).fetchall()
    if not rows:
        raise ValueError("No persisted contexts found for this run")
    items = []
    for step_id, raw in rows:
        context = json.loads(raw)
        data, sources = context.get("data", {}), context.get("sourceData", {})
        unique, projected, aliases = project_prompt_context(data, sources)
        before = {
            "upstreamOutputs": trust_envelope(TrustClass.AGENT_GENERATED, data),
            "sourceData": trust_envelope(TrustClass.EXTERNAL_UNTRUSTED, {"taskSources": {}, "contextSources": sources}),
        }
        after = {
            "upstreamOutputs": trust_envelope(TrustClass.AGENT_GENERATED, unique),
            "sourceData": trust_envelope(TrustClass.EXTERNAL_UNTRUSTED, {"taskSources": {}, "contextSources": projected}),
        }
        if aliases:
            after["upstreamOutputRefs"] = trust_envelope(TrustClass.AGENT_GENERATED, aliases)
        restored = dict(unique)
        for field, ref in aliases.items():
            restored[field] = projected[ref["sourceId"]][ref["field"]]
        lossless = encoded(restored) == encoded(data) and encoded(projected) == encoded(sources)
        if not lossless:
            raise ValueError("Projection failed lossless reconstruction")
        old_size, new_size = len(encoded(before)), len(encoded(after))
        items.append({"stepId": step_id, "beforeChars": old_size, "afterChars": new_size,
                      "savedChars": old_size - new_size, "aliasCount": len(aliases), "lossless": lossless})
    old_total, new_total = sum(item["beforeChars"] for item in items), sum(item["afterChars"] for item in items)
    return {"runId": run_id, "measurement": "context-json-characters", "readOnly": True,
            "beforeChars": old_total, "afterChars": new_total, "savedChars": old_total - new_total,
            "reductionPercent": round((1 - new_total / old_total) * 100, 2) if old_total else 0,
            "items": items}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.database, args.run_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
