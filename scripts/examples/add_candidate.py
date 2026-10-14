#!/usr/bin/env python3
"""POST one candidate payload (contract v1.0) to STZ-PZ's /add_candidate/.

Payload format: agentic_planning/023-add-candidate-endpoint/contract.md.

Usage:
    export YSE_URL=http://localhost:8001 YSE_USER=<user> YSE_PW=<password>
    python scripts/examples/add_candidate.py \\
        --payload agentic_planning/023-add-candidate-endpoint/add_candidate_example.json

Prints the HTTP status and the JSON response (created/appended, transient name,
URL, photometry added/superseded). Uses only the standard library.
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--payload", required=True, help="path to a candidate JSON file")
    parser.add_argument("--url", default=os.environ.get("YSE_URL", "http://localhost:8001"))
    parser.add_argument("--user", default=os.environ.get("YSE_USER"))
    parser.add_argument("--pw", default=os.environ.get("YSE_PW"))
    args = parser.parse_args()
    if not args.user or not args.pw:
        sys.exit("set YSE_USER and YSE_PW (or pass --user/--pw)")

    with open(args.payload) as fh:
        body = json.dumps(json.load(fh)).encode()
    token = base64.b64encode(f"{args.user}:{args.pw}".encode()).decode()
    request = urllib.request.Request(
        args.url.rstrip("/") + "/add_candidate/", data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Basic " + token})
    try:
        with urllib.request.urlopen(request, timeout=60) as resp:
            status, text = resp.status, resp.read().decode()
    except urllib.error.HTTPError as err:
        status, text = err.code, err.read().decode()

    print(status)
    try:
        print(json.dumps(json.loads(text), indent=2))
    except ValueError:
        print(text[:2000])
    sys.exit(0 if status in (200, 201) else 1)


if __name__ == "__main__":
    main()
