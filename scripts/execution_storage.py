"""Inspect or maintain an owned Run through the existing local API boundary.

Default action is read-only. No direct database connection or credential access.
"""
import argparse
import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urlparse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--origin", default="http://127.0.0.1:18080")
    parser.add_argument("--action", choices=["report", "migrate", "archive", "eligible"], default="report")
    parser.add_argument("--older-than", help="UTC ISO timestamp; required for archive/eligible")
    parser.add_argument("--since", help="UTC ISO timestamp for growth statistics")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if "/" in args.run_id or "?" in args.run_id or not args.run_id:
        parser.error("invalid Run ID")
    origin = urlparse(args.origin)
    if (origin.scheme != "http" or origin.hostname != "127.0.0.1" or origin.path not in {"", "/"}
            or origin.username or origin.query or origin.fragment):
        parser.error("origin must be the local loopback backend")
    path = "/api/agentos/v2/runs/" + args.run_id + "/storage"
    payload = None
    if args.action != "report":
        if args.action != "migrate" and not args.older_than:
            parser.error("retention requires an explicit --older-than timestamp")
        cutoff = args.older_than or datetime.now(timezone.utc).isoformat()
        payload = json.dumps({"action": args.action, "olderThan": cutoff, "limit": args.limit}).encode()
        path += "/maintenance"
    elif args.since:
        path += "?" + urlencode({"since": args.since})
    request = Request(args.origin.rstrip("/") + path, data=payload,
        headers={"X-Zhiyi-Local-Request": "1", "Content-Type": "application/json"})
    with urlopen(request, timeout=120) as response:
        print(json.dumps(json.load(response), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
