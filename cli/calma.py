#!/usr/bin/env python3
"""calma — command-line client for the Calma verification engine.

Connect a repo, re-run it, recompute every number it reports, and get a per-claim verdict — from your
terminal or CI, authenticated with an API key (create one at https://calma1.vercel.app/dashboard/keys).

Zero dependencies (stdlib only), so `pip install calma` stays true to the "nothing heavy to install" promise.

    export CALMA_API_KEY=calma_sk_...
    calma verify owner/repo --deep
    calma scans
    calma logs <scan-id>

Config (env):
    CALMA_API_KEY   your API key (required for the hosted engine)
    CALMA_API_URL   engine base URL (default https://calma-engine.fly.dev)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_API = "https://calma-engine.fly.dev"
__version__ = "0.1.0"


def _api() -> str:
    return (os.environ.get("CALMA_API_URL") or DEFAULT_API).rstrip("/")


def _key() -> str:
    return (os.environ.get("CALMA_API_KEY") or "").strip()


def _request(method: str, path: str, body: dict | None = None, *, want_text: bool = False):
    url = _api() + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    key = _key()
    if key:
        req.add_header("Authorization", "Bearer " + key)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("detail") or json.loads(detail).get("error") or detail
        except Exception:  # noqa: BLE001
            pass
        raise SystemExit("error %s: %s" % (e.code, str(detail)[:400]))
    except urllib.error.URLError as e:
        raise SystemExit("could not reach the engine at %s (%s)" % (_api(), e.reason))
    if want_text:
        return raw
    return json.loads(raw) if raw.strip() else {}


# ── verdict rendering ────────────────────────────────────────────────────────────────────────────────────
_ORDER = ["REFUTED", "INVALIDATED", "CONFIRMED", "CONFIRMED_STOCHASTIC", "REPRODUCED_ONLY",
          "INCONCLUSIVE", "DISCOVERED"]


def _fmt_counts(counts: dict) -> str:
    if not counts:
        return "—"
    parts = [(k, counts[k]) for k in _ORDER if counts.get(k)]
    parts += [(k, v) for k, v in counts.items() if k not in _ORDER and v]
    return "  ".join("%s:%d" % (k.lower(), v) for k, v in parts)


def _print_summary(job: dict) -> None:
    print("\n%s  [%s]" % (job.get("repo", "?"), job.get("status", "?")))
    if job.get("error"):
        print("  error: %s" % job["error"])
    counts = job.get("counts") or {}
    if counts:
        print("  verdicts: %s" % _fmt_counts(counts))
    n = job.get("n_claims") or 0
    print("  %d number(s) found" % n)
    run = job.get("run") or {}
    if run.get("entry"):
        print("  ran: %s (%s computation(s))" % (run.get("entry"), run.get("calls", 0)))
    ar = job.get("artifact_repro")
    if ar and ar.get("status") and ar["status"] != "incomplete":
        print("  artifact reproduction: %s — %d/%d committed result cells regenerated identically"
              % (ar["status"], ar.get("n_match", 0), ar.get("n_compared", 0)))
        for c in (ar.get("changed") or [])[:5]:
            print("    ✗ %s [%s]: committed %s, regenerated %s"
                  % (c.get("file"), c.get("cell"), c.get("committed"), c.get("regenerated")))


# ── commands ─────────────────────────────────────────────────────────────────────────────────────────────
def cmd_verify(args) -> int:
    body = {"repo": args.repo, "deep": bool(args.deep), "discover": True}
    if args.entry:
        body["entry"] = args.entry
    if args.pip:
        body["pip_install"] = args.pip
    if getattr(args, "artifact_repro", False):
        body["artifact_repro"] = True
    started = _request("POST", "/api/verify", body)
    jid = started.get("id")
    if not jid:
        raise SystemExit("no job id returned: %s" % started)
    print("scan %s submitted (%s)%s" % (
        jid, started.get("tier", "?"),
        " — deep" if started.get("deep") else " — validity check"))
    for note in started.get("limit_notes") or []:
        print("  note: %s" % note)
    if args.no_wait:
        print("running in the background — `calma get %s` to check" % jid)
        return 0
    # poll to completion, showing the live stage/progress
    last = ""
    while True:
        job = _request("GET", "/api/jobs/%s" % jid)
        status = job.get("status")
        line = job.get("progress") or job.get("stage") or status
        if line and line != last:
            print("  … %s" % line)
            last = line
        if status in ("done", "error", "stopped"):
            if args.json:
                print(json.dumps(job, indent=2, default=str))
            else:
                _print_summary(job)
            return _exit_code(job)
        time.sleep(2.5)


def _exit_code(job: dict) -> int:
    """CI-gate semantics: non-zero if the scan didn't finish, or if any reported number failed to reproduce
    (REFUTED) or was computed with the wrong formula (INVALIDATED). A clean 'done' with no such failures → 0."""
    if job.get("status") != "done":
        return 1
    counts = job.get("counts") or {}
    return 1 if (counts.get("REFUTED", 0) or counts.get("INVALIDATED", 0)) else 0


def cmd_scans(args) -> int:
    jobs = _request("GET", "/api/jobs")
    if not isinstance(jobs, list) or not jobs:
        print("no scans yet")
        return 0
    if args.json:
        print(json.dumps(jobs, indent=2, default=str))
        return 0
    print("%-14s %-34s %-9s %s" % ("ID", "REPO", "STATUS", "VERDICTS"))
    for j in jobs:
        print("%-14s %-34s %-9s %s" % (
            j.get("id", "")[:14], (j.get("repo") or "")[:34], j.get("status", ""),
            _fmt_counts(j.get("counts") or {})))
    return 0


def cmd_get(args) -> int:
    job = _request("GET", "/api/jobs/%s" % args.id)
    if args.json:
        print(json.dumps(job, indent=2, default=str))
    else:
        _print_summary(job)
    return 0


def cmd_logs(args) -> int:
    print(_request("GET", "/api/jobs/%s/logs" % args.id, want_text=True), end="")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="calma", description="Verify the numbers a repo reports.")
    p.add_argument("--version", action="version", version="calma " + __version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("verify", help="verify a repo (recompute its reported numbers)")
    v.add_argument("repo", help="owner/name or a github URL")
    v.add_argument("--deep", action="store_true", help="re-run the repo and recompute (default: validity check only)")
    v.add_argument("--entry", help="entrypoint override, e.g. 'run.py' (auto-detected otherwise)")
    v.add_argument("--pip", action="append", help="extra pip dependency (repeatable)")
    v.add_argument("--artifact-repro", dest="artifact_repro", action="store_true",
                   help="also verify committed result files regenerate identically (re-run-the-paper mode)")
    v.add_argument("--json", action="store_true", help="print the raw job JSON")
    v.add_argument("--no-wait", action="store_true", help="submit and return immediately")
    v.set_defaults(func=cmd_verify)

    s = sub.add_parser("scans", help="list your recent scans")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_scans)

    g = sub.add_parser("get", help="show one scan")
    g.add_argument("id")
    g.add_argument("--json", action="store_true")
    g.set_defaults(func=cmd_get)

    lg = sub.add_parser("logs", help="print the full run log for a scan")
    lg.add_argument("id")
    lg.set_defaults(func=cmd_logs)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not _key() and _api() == DEFAULT_API:
        sys.stderr.write("warning: CALMA_API_KEY is not set — create one at "
                         "https://calma1.vercel.app/dashboard/keys\n")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
