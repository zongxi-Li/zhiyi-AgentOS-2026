"""Offline Workbench urllib preparation profile. No model, DNS or network calls.

Measure the standard-library defaults used by HttpJsonTransport separately from
JSON/request preparation. This is not a TLS handshake or end-to-end TTFT test.
Only timings and boolean environment flags are emitted; never proxy/CA values.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
from pathlib import Path
import ssl
from statistics import median
import sys
from time import perf_counter
import urllib.request

root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(root / "apps/agentOS/src"), str(root / "apps/agentOS")]
from adapters.http_transport import HttpJsonTransport


def profile(samples=5):
    transport = HttpJsonTransport(base_url="https://127.0.0.1/v1")
    def prepare_request():
        return transport._request_for(path="chat/completions", payload={"model": "synthetic", "messages": [
            {"role": "user", "content": "synthetic material " * 1000}]}, idempotency_key=None, accept="text/event-stream")
    results = {}
    for label, create in (
        ("defaultHttpsConnection", lambda: http.client.HTTPSConnection("127.0.0.1")),
        ("defaultVerifiedContext", ssl.create_default_context),
        ("urllibOpener", urllib.request.build_opener),
        ("requestPreparation", prepare_request),
    ):
        values = []
        for _ in range(samples):
            at = perf_counter()
            resource = create()
            values.append(round((perf_counter() - at) * 1000, 3))
            close = getattr(resource, "close", None)
            if callable(close):
                close()
        results[label] = {"coldMs": values[0], "warmMedianMs": median(values[1:]), "samplesMs": values}
    return {"schemaVersion": 1, "networkUsed": False, "measurement": "urllib-offline-preparation",
            "customCaFile": bool(os.getenv("SSL_CERT_FILE")), "customCaDirectory": bool(os.getenv("SSL_CERT_DIR")),
            "proxyConfigured": any(os.getenv(k) for k in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")),
            "samples": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=5)
    arguments = parser.parse_args()
    if not 2 <= arguments.samples <= 100:
        parser.error("samples must be between 2 and 100")
    print(json.dumps(profile(arguments.samples), ensure_ascii=False, indent=2))
