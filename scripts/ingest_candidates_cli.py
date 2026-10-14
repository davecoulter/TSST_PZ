#!/usr/bin/env python3
"""CLI tool to load candidate JSON files into STZ-PZ through /add_candidate/.

Each file holds one candidate object, or an array of them (the pipeline writes one
array file per run). Candidates are posted in batches; the server matches each one
to existing objects, creates or appends, and reports per candidate which worked and
which failed, so one bad candidate never blocks the rest. The payload format is
agentic_planning/023-add-candidate-endpoint/contract.md.

Usage:
    export YSE_URL=http://localhost:8001 USER_YSE=<user>   # PW is prompted for if unset
    python scripts/ingest_candidates_cli.py candidates.json [more.json ...]
    python scripts/ingest_candidates_cli.py --dry-run candidates.json

--dry-run asks the server to run everything and roll it back: you see exactly what a
real run would do (created or appended, or the errors) and nothing is saved.

Re-running a file is safe: the server flags earlier points for the same band and
epoch "Superseded" rather than duplicating what is shown.

Exit code: 0 all candidates succeeded; 1 at least one candidate or file failed;
2 bad usage or a login failure.
"""
import argparse
import base64
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

# YSE_URL first: a bare "URL" is a very generic variable name that may already be set to
# something else in a shell, so it is only a fallback.
DEFAULT_URL = os.environ.get("YSE_URL") or os.environ.get("URL") or "http://localhost:8001"
ENDPOINT_MAX_BATCH = 500  # the server's cap per request
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def load_candidates(path):
    """The list of candidate objects in a file (a single object counts as a list of one)."""
    with open(path) as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        raise ValueError("expected a JSON object, or a non-empty array of objects")
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError("item %d is not a JSON object" % index)
    return data


def post_batch(url, token, batch, dry_run, timeout):
    """POST a list of candidates; returns (http_status, response_text)."""
    endpoint = url.rstrip("/") + "/add_candidate/" + ("?dry_run=1" if dry_run else "")
    request = urllib.request.Request(
        endpoint, data=json.dumps(batch).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Basic " + token})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode()


def format_errors(errors):
    if isinstance(errors, dict):
        return "; ".join("%s: %s" % (field or "request", message) for field, message in errors.items())
    return str(errors)


class Report:
    def __init__(self, dry_run):
        self.dry_run = dry_run
        self.created = self.appended = self.failed = 0
        self.files = 0

    def line(self, source, index, candidate_id, outcome, detail=""):
        print("%s [%d] %s  %s%s" % (source, index, candidate_id, outcome, "  " + detail if detail else ""))

    def result(self, source, index, result):
        candidate_id = result.get("candidate_id") or "?"
        status = result.get("status")
        if status in (200, 201):
            created = status == 201
            self.created += created
            self.appended += not created
            verb = ("would create" if created else "would append") if self.dry_run else (
                "created" if created else "appended")
            detail = "%s, %d points, %d superseded" % (
                result.get("transient", ""), result.get("photometry_added", 0),
                result.get("photometry_superseded", 0))
            if result.get("match_separation_arcsec") is not None:
                detail += ", matched at %.2f arcsec" % result["match_separation_arcsec"]
            self.line(source, index, candidate_id, verb, detail)
        else:
            self.fail(source, index, candidate_id, format_errors(result.get("errors", "HTTP %s" % status)))

    def fail(self, source, index, candidate_id, message):
        self.failed += 1
        self.line(source, index, candidate_id, "FAILED", message)

    def summary(self):
        total = self.created + self.appended + self.failed
        verbs = ("would create", "would append") if self.dry_run else ("created", "appended")
        text = "%d candidate%s in %d file%s: %d %s, %d %s, %d failed" % (
            total, "" if total == 1 else "s", self.files, "" if self.files == 1 else "s",
            self.created, verbs[0], self.appended, verbs[1], self.failed)
        if self.dry_run:
            text += " (dry run, nothing saved)"
        print(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="\n".join(__doc__.splitlines()[2:]))
    parser.add_argument("files", nargs="+", help="JSON file(s): one candidate object or an array")
    parser.add_argument("--url", default=DEFAULT_URL, help="base URL of the app (env YSE_URL, then URL; default %(default)s)")
    parser.add_argument("--user", default=os.environ.get("USER_YSE"), help="STZ-PZ username (env USER_YSE)")
    parser.add_argument("--pw", default=os.environ.get("PW"),
                        help="password (env PW; prefer the env var, or leave unset to be prompted)")
    parser.add_argument("--dry-run", action="store_true",
                        help="run everything on the server but save nothing")
    parser.add_argument("--batch-size", type=int, default=100,
                        help="candidates per request (default %(default)s, at most " + str(ENDPOINT_MAX_BATCH) + ")")
    parser.add_argument("--timeout", type=int, default=120, help="seconds to wait for each request")
    args = parser.parse_args()

    if not 1 <= args.batch_size <= ENDPOINT_MAX_BATCH:
        parser.error("--batch-size must be between 1 and %d" % ENDPOINT_MAX_BATCH)
    if not args.user:
        print("error: no username; set USER_YSE or pass --user", file=sys.stderr)
        return 2
    password = args.pw
    if not password:
        if not sys.stdin.isatty():
            print("error: no password; set PW or pass --pw (no terminal to prompt on)", file=sys.stderr)
            return 2
        password = getpass.getpass("Password for %s: " % args.user)
    token = base64.b64encode(("%s:%s" % (args.user, password)).encode()).decode()

    print("Target: %s as %s%s" % (args.url, args.user, " (dry run)" if args.dry_run else ""),
          file=sys.stderr)
    parsed = urllib.parse.urlparse(args.url)
    if parsed.scheme == "http" and parsed.hostname not in LOCAL_HOSTS:
        print("warning: %s is plain http, so your password and the data travel unencrypted"
              % args.url, file=sys.stderr)

    report = Report(args.dry_run)
    for path in args.files:
        name = os.path.basename(path)
        report.files += 1
        try:
            candidates = load_candidates(path)
        except (OSError, ValueError) as err:  # includes json.JSONDecodeError
            report.fail(name, 0, "(file)", "cannot read: %s" % err)
            continue

        for start in range(0, len(candidates), args.batch_size):
            batch = candidates[start:start + args.batch_size]
            ids = [c.get("candidate_id") or "?" for c in batch]
            try:
                status, text = post_batch(args.url, token, batch, args.dry_run, args.timeout)
            except (urllib.error.URLError, OSError) as err:
                for offset, candidate_id in enumerate(ids):
                    report.fail(name, start + offset, candidate_id, "could not reach the server: %s" % err)
                continue
            if status in (401, 403):
                print("error: the server rejected the login (HTTP %d); nothing was sent" % status,
                      file=sys.stderr)
                return 2
            try:
                body = json.loads(text)
            except ValueError:
                body = {}
            if status != 200 or "results" not in body:
                message = format_errors(body.get("errors", text[:200] or "HTTP %d" % status))
                for offset, candidate_id in enumerate(ids):
                    report.fail(name, start + offset, candidate_id, message)
                continue
            for result in body["results"]:
                report.result(name, start + result["index"], result)

    report.summary()
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
