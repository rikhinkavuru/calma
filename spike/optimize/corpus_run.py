#!/usr/bin/env python
"""optimize.corpus_run — low-friction live corpus: a BARE repo URL -> verdict, no hand-entry.

run_spike.py needs every repo hand-specified (pinned commit, entry, pip_install). This auto-resolves all of
it — clone HEAD, detect the entrypoint, infer deps (requirements.txt else imports), discover claims, verify —
so you can throw a plain list of repo URLs at it. This is what makes n=many measurable, and it's the harness
for the "test on tons of random repos" phase.

    ~/.calma/spike-venv/bin/python optimize/corpus_run.py --urls urls.txt [--e2b] [--out results/live-many]

urls.txt: one repo URL per line; blank lines and #-comments ignored. A line may carry a grade:
    https://github.com/owner/repo            CONFIRMED        # expected headline verdict (optional)
When a grade is present it's scored (match / FALSE-CONFIRM); ungraded repos still report coverage.

Local runner for curated repos (fast); pass --e2b to sandbox untrusted/random code (the safe path at scale).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)
sys.path.insert(0, os.path.join(SPIKE, "capture"))

from core import verdict as VD  # noqa: E402
from pipeline import VerifyOptions, verify_repo  # noqa: E402
from runner import build  # noqa: E402
from runner import data_resolver as DR  # noqa: E402

# verdicts that mean "the claim was bound to a runtime computation" (vs unbound/ambiguous/undiscovered)
_BOUND = (VD.CONFIRMED, VD.REFUTED, VD.INVALIDATED, VD.REPRODUCED_ONLY, VD.NON_DETERMINISTIC)


def _name(url):
    base = url.rstrip("/").split("/")[-1]
    if base.endswith(".git"):
        base = base[:-4]
    return re.sub(r"[^A-Za-z0-9_-]", "-", base)[:40] or "repo"


def materialize_notebooks(repo_dir):
    """Convert every .ipynb to a sibling .py (pure stdlib) so the existing entrypoint-detection + capture
    path handles notebooks. MOST real ML repos are notebooks, not scripts — this is the make-runnable step
    that unlocks them. An .ipynb is JSON: concatenate code cells; comment out line-magics / shell-escapes /
    get_ipython so the script imports cleanly. Doesn't clobber a real .py of the same stem. Returns count."""
    n = 0
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".ipynb_checkpoints")]
        for fn in files:
            if not fn.endswith(".ipynb"):
                continue
            dst = os.path.join(root, fn[:-6] + ".py")
            if os.path.exists(dst):
                continue
            try:
                nb = json.load(open(os.path.join(root, fn), errors="replace"))
            except (OSError, ValueError):
                continue
            lines = []
            for cell in nb.get("cells", []):
                if cell.get("cell_type") != "code":
                    continue
                src = cell.get("source", [])
                if isinstance(src, str):
                    src = src.splitlines(keepends=True)
                for ln in src:
                    s = ln.rstrip("\n")
                    if s.lstrip().startswith(("%", "!", "get_ipython(")):
                        s = "# " + s
                    lines.append(s)
                lines.append("")
            try:
                with open(dst, "w") as fh:
                    fh.write("\n".join(lines) + "\n")
                n += 1
            except OSError:
                pass
    return n


def parse_urls(path):
    out = []
    with open(path) as fh:
        for line in fh:
            line = line.split("#")[0].strip()
            if not line:
                continue
            parts = line.split()
            out.append((parts[0], parts[1] if len(parts) > 1 else None))
    return out


def run_one(url, expect, args):
    t0 = time.time()
    spec = {"name": _name(url), "source": {"kind": "git", "url": url}}
    try:
        repo_dir, _ = build.ensure_repo(spec, os.path.join(args.out, "repos"))
    except Exception as e:  # noqa: BLE001
        return {"url": url, "name": spec["name"], "ran": False, "error": "clone failed: %s" % str(e)[:160],
                "seconds": round(time.time() - t0, 1), "claims": [], "expect": expect}
    n_nb = materialize_notebooks(repo_dir)              # notebooks → .py so they become runnable
    deps, why = build.infer_requirements(repo_dir)
    era = None
    if why == "inferred from imports" and not args.no_era and args.e2b:
        # era packages need an era PYTHON (provisioned via uv in the E2B path) — old wheels don't exist for
        # the local runner's bleeding-edge Python, so era-pin only when sandboxed.
        deps, era = build.era_pin(deps, repo_dir)
    opts = VerifyOptions(runner=("e2b" if args.e2b else "local"), deep=True, discover=True,
                         pip_install=(None if args.e2b else deps), k=args.k, job_id=spec["name"],
                         venvs_dir=os.path.join(args.out, ".venvs"), timeout=args.timeout)
    try:
        res = verify_repo(repo_dir, opts)
    except Exception as e:  # noqa: BLE001
        return {"url": url, "name": spec["name"], "ran": False,
                "error": "%s: %s" % (type(e).__name__, str(e)[:160]), "seconds": round(time.time() - t0, 1),
                "claims": [], "expect": expect}
    run = res.get("run") or {}
    fetch_note = None
    if args.fetch_data and not run.get("ran"):          # opt-in: grab missing external data via Exa, then retry
        miss = DR.missing_data_path(run.get("error_full") or run.get("error"))
        if miss:
            ok, fetch_note = DR.resolve_missing_data(repo_dir, miss)
            if ok:
                res = verify_repo(repo_dir, opts)
                run = res.get("run") or {}
    claims = [{"id": c.get("id"), "metric": c.get("metric"), "claimed": c.get("claimed"),
               "verdict": c.get("verdict")} for c in res.get("claims", [])]
    headline = next((c["verdict"] for c in claims if c["verdict"] in (VD.CONFIRMED, VD.REFUTED,
                                                                       VD.INVALIDATED)), None)
    return {"url": url, "name": spec["name"], "ran": bool(run.get("ran")),
            "seconds": round(time.time() - t0, 1), "entry": run.get("entry"), "notebooks": n_nb,
            "error": (run.get("error") or "")[:160], "deps": deps[:8], "why_deps": why, "era": era,
            "data_fetch": fetch_note,
            "n_claims": res.get("n_claims"), "counts": res.get("counts", {}), "claims": claims,
            "expect": expect, "headline": headline,
            "graded_match": (None if expect is None else (headline == expect))}


def aggregate(results):
    total = len(results)
    ran = sum(1 for r in results if r["ran"])
    claims = [c for r in results for c in r["claims"]]
    bound = sum(1 for c in claims if c["verdict"] in _BOUND)
    dist = {}
    for c in claims:
        dist[c["verdict"]] = dist.get(c["verdict"], 0) + 1
    graded = [r for r in results if r["expect"] is not None]
    matches = sum(1 for r in graded if r["graded_match"])
    # a FALSE CONFIRM = a graded repo whose expected verdict is NOT confirmed but we CONFIRMED it
    false_confirms = [r["name"] for r in graded if r["headline"] == VD.CONFIRMED and r["expect"] != VD.CONFIRMED]
    return {"repos_total": total, "repos_ran": ran,
            "reproduction_rate": round(ran / total, 3) if total else 0.0,
            "claims_total": len(claims), "claims_bound": bound,
            "binding_rate": round(bound / len(claims), 3) if claims else 0.0,
            "verdict_distribution": dist,
            "graded": len(graded), "graded_matches": matches,
            "verdict_accuracy": (round(matches / len(graded), 3) if graded else None),
            "false_confirm_count": len(false_confirms), "false_confirms": false_confirms}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", required=True)
    ap.add_argument("--out", default=os.path.join(SPIKE, "results", "live-many"))
    ap.add_argument("--e2b", action="store_true")
    ap.add_argument("--no-era", action="store_true", help="disable era-based package pinning of inferred deps")
    ap.add_argument("--fetch-data", action="store_true", help="opt-in: fetch missing external data via Exa, then retry")
    ap.add_argument("--k", type=int, default=2)
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--only", default="", help="comma-substring filter on repo name")
    args = ap.parse_args()
    args.out = os.path.abspath(args.out)
    os.makedirs(args.out, exist_ok=True)
    urls = parse_urls(args.urls)
    if args.only:
        subs = args.only.split(",")
        urls = [(u, e) for (u, e) in urls if any(s in _name(u) for s in subs)]
    results = []
    for url, expect in urls:
        print("→ %s ..." % _name(url), flush=True)
        r = run_one(url, expect, args)
        v = ",".join("%s=%s" % (c["metric"], c["verdict"]) for c in r["claims"]) or "(no claims)"
        print("   ran=%s %ss  %s%s" % (r["ran"], r["seconds"], v[:90],
                                       "" if r["expect"] is None else "  [expect %s -> %s]" % (
                                           r["expect"], "✓" if r["graded_match"] else "✗")), flush=True)
        results.append(r)
    agg = aggregate(results)
    with open(os.path.join(args.out, "corpus_run.json"), "w") as fh:
        json.dump({"aggregate": agg, "repos": results}, fh, indent=2)
    print("\n=== LIVE CORPUS (auto, n=%d) ===" % agg["repos_total"])
    print("reproduction=%.0f%% (%d/%d)  binding=%.0f%% (%d/%d)  FALSE_CONFIRMS=%d  verdict_acc=%s" % (
        100 * agg["reproduction_rate"], agg["repos_ran"], agg["repos_total"],
        100 * agg["binding_rate"], agg["claims_bound"], agg["claims_total"],
        agg["false_confirm_count"], agg["verdict_accuracy"]))
    print("verdict distribution:", agg["verdict_distribution"])
    if agg["false_confirms"]:
        print("!! FALSE CONFIRMS:", agg["false_confirms"])
    print("→ %s" % os.path.join(args.out, "corpus_run.json"))
    return 1 if agg["false_confirm_count"] else 0


if __name__ == "__main__":
    sys.exit(main())
