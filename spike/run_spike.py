#!/usr/bin/env python
"""run_spike — the Phase-0 de-risking loop (rebuild guide §9).

For each curated repo: make-runnable -> run k× (capture) -> independently recompute each claimed number ->
three-way diff -> verdict; then SCORE against the hand-graded truth and emit a go/no-go memo. The numbers
this produces — reproduction rate, input-binding accuracy, FALSE-CONFIRM COUNT (must be 0), cost/latency —
are the evidence that decides whether to commit to the full build.

    python run_spike.py [--repos repos.yaml] [--only name1,name2] [--k 2] [--out results]

Every claim carries an `expect` (the hand-graded verdict). The gate: false-confirm == 0, a usable
reproduction floor, and binding accuracy. This script is the spike's product.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "capture"))

from core import diff as D  # noqa: E402
from core import verdict as VD  # noqa: E402
from discovery import extract as DISC  # noqa: E402
from runner import build  # noqa: E402
from runner.local_runner import run_local  # noqa: E402

# stderr signature -> (reason, the user action / upsell it routes to) — the "couldn't-reproduce" taxonomy
_FAIL_TAXONOMY = [
    ("ModuleNotFoundError", ("a dependency is missing", "declare/scan requirements -> agentic env build")),
    ("No such file or directory", ("an input file/dataset is missing", "connect your data")),
    ("CUDA", ("needs a GPU", "GPU tier")),
    ("out of memory", ("ran out of memory", "larger sandbox tier")),
    ("timeout", ("exceeded the time budget", "raise the timeout / scope the run")),
    ("FileNotFoundError", ("an input file/dataset is missing", "connect your data")),
]


def classify_failure(stderr_tail):
    for sig, (reason, action) in _FAIL_TAXONOMY:
        if sig.lower() in (stderr_tail or "").lower():
            return {"reason": reason, "action": action}
    return {"reason": "the entrypoint errored", "action": "inspect logs / agentic retry"}


def run_one(spec, args, venvs_dir):
    name = spec["name"]
    runner = spec.get("runner", "local")
    entry = spec.get("entry", ["eval.py"])
    hooks = spec.get("hooks", "sklearn")
    targets = spec.get("targets")
    pip_install = spec.get("pip_install")
    t0 = time.time()
    repo_dir, src_note = build.ensure_repo(spec, os.path.join(args.out, "repos"))
    build_note, env_note = src_note, ""
    try:
        if runner == "e2b":
            from runner.e2b_runner import run_e2b
            r = run_e2b(repo_dir, entry, k=args.k, hooks=hooks, targets=targets,
                        timeout=spec.get("timeout", 600), pip_install=pip_install)
            env_note = "e2b" + ("+pip" if pip_install else "")
        else:
            python, env_note = build.ensure_venv(name, pip_install, venvs_dir)
            r = run_local(repo_dir, entry, k=args.k, python=python, hooks=hooks, targets=targets,
                          timeout=spec.get("timeout", 600))
    except Exception as e:  # noqa: BLE001 — a build failure is a non-running repo, scored as such
        return {"name": name, "ran": False, "build_error": "%s: %s" % (type(e).__name__, str(e)[:200]),
                "seconds": round(time.time() - t0, 1), "claims": [], "runner": runner}

    elapsed = round(time.time() - t0, 1)
    # claims to verify = hand-specified + (optionally) auto-discovered (the free path, guide §3)
    claims = list(spec.get("claims", []))
    n_discovered = 0
    if spec.get("discover"):
        stdout0 = r["meta"][0].get("stdout_tail", "") if r.get("meta") else ""
        discovered = DISC.discover(repo_dir, stdout_text=stdout0)
        for c in discovered:
            c.setdefault("expect", None)  # discovered claims are reported, not hand-graded
        n_discovered = len(discovered)
        claims = discovered + claims
    claim_records = []
    for claim in claims:
        rec = D.diff_claim(claim, r["runs"]) if r["runs"] else {
            "verdict": VD.INCONCLUSIVE, "reason": "repo did not run", "binding": {"bound": False},
            "diff": {}, "caveats": []}
        expect = claim.get("expect")
        verdict = rec["verdict"]
        bound = bool(rec.get("binding", {}).get("bound"))
        claim_records.append({
            "id": claim.get("id"), "metric": claim.get("metric"), "claimed": claim.get("value"),
            "verdict": verdict, "expect": expect, "match": (expect is None or verdict == expect),
            "bound": bound, "reason": rec.get("reason", ""), "diff": rec.get("diff", {}),
            "discovered": bool(claim.get("source")), "discovery_source": claim.get("source"),
            "confidence": claim.get("confidence"),
            "false_confirm": (verdict in VD.POSITIVE and expect is not None and expect != verdict),
        })
    fail = None
    if not r["ran_ok"]:
        tail = " ".join(m.get("stderr_tail", "") for m in r.get("meta", []))
        fail = classify_failure(tail)
    return {"name": name, "ran": r["ran_ok"], "runner": runner, "seconds": elapsed,
            "n_calls": r.get("n_calls"), "hooks_armed": r.get("hooks_armed"), "n_discovered": n_discovered,
            "build": "%s/%s" % (build_note, env_note), "claims": claim_records, "failure": fail,
            "stderr_tail": ("" if r["ran_ok"] else (r.get("meta", [{}])[-1].get("stderr_tail", "")[-400:]))}


def aggregate(results):
    repos_total = len(results)
    repos_ran = sum(1 for r in results if r["ran"])
    claims = [c for r in results for c in r["claims"]]
    graded = [c for c in claims if c["expect"] is not None]
    bound = sum(1 for c in claims if c["bound"])
    matches = sum(1 for c in graded if c["match"])
    false_confirms = [c for c in claims if c["false_confirm"]]
    discovered = sum(1 for c in claims if c.get("discovered"))
    secs = [r["seconds"] for r in results]
    return {
        "repos_total": repos_total, "repos_ran": repos_ran, "discovered_claims": discovered,
        "reproduction_rate": round(repos_ran / repos_total, 3) if repos_total else 0.0,
        "claims_total": len(claims), "claims_bound": bound,
        "binding_rate": round(bound / len(claims), 3) if claims else 0.0,
        "claims_graded": len(graded), "verdict_matches": matches,
        "verdict_accuracy": (round(matches / len(graded), 3) if graded else None),
        "false_confirm_count": len(false_confirms),
        "false_confirms": [(c["id"], c["verdict"], c["expect"]) for c in false_confirms],
        "wall_seconds_total": round(sum(secs), 1),
        "wall_seconds_per_repo": round(sum(secs) / repos_total, 1) if repos_total else 0.0,
    }


def write_report(agg, results, out_dir):
    lines = []
    A = lines.append
    A("# Calma rebuild — Phase 0 spike report\n")
    A("_The de-risking loop (guide §9): clone → discover claim → make-runnable → sandbox run → "
      "instrument-capture raw inputs → independent recompute → three-way diff → verdict._\n")
    gate_fc = "✅ PASS" if agg["false_confirm_count"] == 0 else "❌ FAIL"
    A("## Go / no-go gates\n")
    A("| Gate | Target | Measured | |")
    A("|---|---|---|---|")
    A("| **False-confirm count** | **0** (the franchise) | **%d** | %s |"
      % (agg["false_confirm_count"], gate_fc))
    A("| Reproduction rate | ≥ 0.60 floor | %.0f%% (%d/%d) | %s |"
      % (100 * agg["reproduction_rate"], agg["repos_ran"], agg["repos_total"],
         "✅" if agg["reproduction_rate"] >= 0.60 else "⚠️"))
    A("| Input-binding rate | high | %.0f%% (%d/%d claims)|  |"
      % (100 * agg["binding_rate"], agg["claims_bound"], agg["claims_total"]))
    va = agg["verdict_accuracy"]
    A("| Verdict accuracy (graded) | high | %s (%d/%d) | %s |"
      % ("n/a" if va is None else "%.0f%%" % (100 * va), agg["verdict_matches"], agg["claims_graded"],
         "—" if va is None else ("✅" if va >= 0.9 else "⚠️")))
    A("| Auto-discovered claims | (free path) | %d verified |  |" % agg.get("discovered_claims", 0))
    A("| Wall-clock / repo | low | %.1fs |  |" % agg["wall_seconds_per_repo"])
    if agg["false_confirms"]:
        A("\n**FALSE CONFIRMS (must be empty):** %s" % agg["false_confirms"])
    A("\n## Per-repo\n")
    A("| Repo | Runner | Ran | s | Claims (verdict vs expect) |")
    A("|---|---|---|---|---|")
    for r in results:
        cl = ", ".join("%s:%s%s" % (c["id"], c["verdict"],
                       "" if c["match"] else "≠%s" % c["expect"]) for c in r["claims"]) or "—"
        ran = "✅" if r["ran"] else "❌ %s" % (r.get("failure", {}) or {}).get("reason", r.get("build_error", ""))
        A("| %s | %s | %s | %s | %s |" % (r["name"], r["runner"], ran, r["seconds"], cl))
    A("\n## Verdict distribution\n")
    dist = {}
    for r in results:
        for c in r["claims"]:
            dist[c["verdict"]] = dist.get(c["verdict"], 0) + 1
    for v in VD.ALL:
        if dist.get(v):
            A("- **%s**: %d" % (v, dist[v]))
    path = os.path.join(out_dir, "SPIKE-REPORT.md")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repos", default=os.path.join(HERE, "repos.yaml"))
    ap.add_argument("--only", default="", help="comma-separated repo names to run")
    ap.add_argument("--k", type=int, default=2, help="runs per repo (determinism gate needs >=2)")
    ap.add_argument("--out", default=os.path.join(HERE, "results"))
    args = ap.parse_args()

    import yaml
    with open(args.repos) as fh:
        specs = yaml.safe_load(fh)["repos"]
    only = set(s for s in args.only.split(",") if s)
    if only:
        specs = [s for s in specs if s["name"] in only]
    os.makedirs(args.out, exist_ok=True)
    venvs_dir = os.path.join(args.out, ".venvs")

    results = []
    for spec in specs:
        print("→ %s ..." % spec["name"], flush=True)
        r = run_one(spec, args, venvs_dir)
        verdicts = ",".join("%s=%s" % (c["id"], c["verdict"]) for c in r["claims"]) or "(no claims)"
        print("   ran=%s %ss  %s" % (r["ran"], r["seconds"], verdicts), flush=True)
        results.append(r)

    agg = aggregate(results)
    with open(os.path.join(args.out, "results.json"), "w") as fh:
        json.dump({"aggregate": agg, "repos": results}, fh, indent=2)
    report = write_report(agg, results, args.out)
    print("\n=== GO/NO-GO ===")
    va = agg["verdict_accuracy"]
    print("reproduction=%.0f%%  binding=%.0f%%  verdict_acc=%s  discovered=%d  FALSE_CONFIRMS=%d"
          % (100 * agg["reproduction_rate"], 100 * agg["binding_rate"],
             "n/a" if va is None else "%.0f%%" % (100 * va), agg["discovered_claims"],
             agg["false_confirm_count"]))
    print("report:", report)
    return 0 if agg["false_confirm_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
