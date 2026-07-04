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
import subprocess
import sys
import time

_COMPAT_KERNEL: dict = {}


def _ensure_compat_kernel(venvs_dir, repo_dir=None):
    """Build (once per era) an ERA-APPROPRIATE science venv with ipykernel and register its kernelspec, so a
    version-drift NOTEBOOK can be re-run in a kernel matching its era (an old notebook needs py3.8 + sklearn
    0.x, not the latest kernel) — the notebook analog of era-python. Returns the kernel name, or None.
    era comes from the repo's git commit date; falls back to a moderate downgrade (sklearn 1.3.2)."""
    from orchestrator import tools_exec as _XT
    era = build.repo_commit_date(repo_dir) if repo_dir else None
    tag = (era or "moderate")[:7]
    if tag in _COMPAT_KERNEL:
        return _COMPAT_KERNEL[tag]
    _COMPAT_KERNEL[tag] = None
    try:
        base = ["scikit-learn", "pandas", "numpy", "scipy", "matplotlib", "seaborn", "ipykernel", "nbformat"]
        base_py = build.compat_python(era)
        pyver = build.python_version(base_py) or "3.12"
        if era:                                            # pin the science libs to the notebook's era
            deps, _e, _n = _XT.era_pin_compat(base, repo_dir, py_version=pyver)
        else:
            deps = ["scikit-learn==1.3.2", "pandas==2.2.3", "numpy==1.26.4", "scipy==1.11.4",
                    "matplotlib", "seaborn", "ipykernel", "nbformat"]
        py, _ = build.ensure_venv("_kernel_" + tag, deps, venvs_dir, base_python=base_py)
        name = "calma-" + tag
        subprocess.run([py, "-m", "ipykernel", "install", "--user", "--name", name],
                       check=True, timeout=120, capture_output=True)
        _COMPAT_KERNEL[tag] = name
    except Exception:  # noqa: BLE001 — best-effort
        pass
    return _COMPAT_KERNEL[tag]

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
    entry = spec.get("entry")                      # None -> auto-detect below (exercises the reverse map)
    hooks = spec.get("hooks", "sklearn")
    targets = spec.get("targets")
    pip_install = spec.get("pip_install")
    t0 = time.time()
    repo_dir, src_note = build.ensure_repo(spec, os.path.join(args.out, "repos"))
    build_note, env_note = src_note, ""
    if not entry:
        # no hand-specified entry: use the same detection the product does — README run-command, then the
        # artifact->producer reverse map (run the script that WROTE the committed table, not a quickstart),
        # then name heuristics. Lets a real corpus repo carry only its URL+SHA and still run the right script.
        entry = build.detect_entrypoint(repo_dir) or ["eval.py"]
    try:
        if runner == "e2b":
            from runner.e2b_runner import run_e2b
            r = run_e2b(repo_dir, entry, k=args.k, hooks=hooks, targets=targets,
                        timeout=spec.get("timeout", 600), pip_install=pip_install)
            env_note = "e2b" + ("+pip" if pip_install else "")
        else:
            # era-appropriate reproduction: pin unpinned deps to the repo's commit-era versions (a 2023 repo
            # gets sklearn ~1.3, not today's 1.9 that rejects its label types) and build the venv with a
            # compatible interpreter (py3.14 lacks wheels for an era-old stack). The E2B product already does
            # this; the local corpus measurement must too, else version drift reads as a false non-repro.
            # era-appropriate reproduction with a latest-FALLBACK. Pin to the commit era (fixes version drift,
            # e.g. sklearn 1.9 rejecting a 2023 repo's label types), but an ANCIENT era can pin a version with
            # no wheel for the build python (sklearn 0.23 on py3.12) — requires-python metadata says it's fine,
            # yet it won't build. So if the era-pinned install fails, fall back to unpinned/latest (which
            # installs and often still runs the old code). Best of both, no regression.
            # era FIRST → an era-appropriate PYTHON (a 2019 stack needs py3.9, not py3.12) → pin deps to the
            # era, relaxing only pins incompatible with THAT python. Matches the E2B product (any python).
            era0 = build.repo_commit_date(repo_dir)
            base_py = build.compat_python(era0)
            pyver = build.python_version(base_py) or "3.12"
            era = None
            try:
                if pip_install:
                    from orchestrator import tools_exec as _XT
                    pinned, era, _notes = _XT.era_pin_compat(pip_install, repo_dir, py_version=pyver)
                else:
                    pinned = pip_install
                python, env_note = build.ensure_venv(name, pinned, venvs_dir, base_python=base_py)
            except Exception:  # noqa: BLE001 — era-pinned install failed → try latest (a fresh venv name)
                python, env_note = build.ensure_venv(name + "-latest", pip_install, venvs_dir, base_python=base_py)
                env_note += " (era-pin install failed → latest)"
                era = None
            if era:
                env_note += " era=%s py=%s" % (era, pyver)
            # dispatch (notebook vs script) behind one _do_run so the data-resolution retries apply to BOTH.
            from runner import data_resolver as _DR
            is_nb = bool(entry and str(entry[0]).startswith("nb:"))

            def _do_run():
                if is_nb:
                    from orchestrator import tools_exec as XT
                    return XT.run_notebook(repo_dir, entry[0], k=args.k, hooks=hooks, targets=targets,
                                           timeout=spec.get("timeout", 600), python=python)
                return run_local(repo_dir, entry, k=args.k, python=python, hooks=hooks, targets=targets,
                                 timeout=spec.get("timeout", 600))

            env_note += "+nb" if is_nb else ""
            r = _do_run()
            _stderr = lambda: " ".join(m.get("stderr_tail", "") for m in r.get("meta", []))  # noqa: E731
            # chained committed-data relink (multi-artifact repos miss >1 file; also a sole differently-named
            # committed dataset) — place where the code reads + re-run. Make-runnable, FCR-safe.
            for _ in range(3):
                if r.get("ran_ok"):
                    break
                miss = _DR.missing_data_path(_stderr())
                if not miss or not _DR.make_data_available(repo_dir, miss)[0]:
                    break
                r = _do_run()
                env_note += " +data"
            # not committed, but a recognised public dataset (UCI magic04/adult/wine/…) → fetch to the read
            # path (deterministic catalog, no key) + rewrite a hardcoded abs path literal.
            if not r.get("ran_ok"):
                miss = _DR.missing_data_path(_stderr())
                if miss:
                    from runner import data_catalog as _DC
                    url = _DC.resolve_path(miss)
                    if url:
                        b = os.path.basename(str(miss).replace("\\", "/"))
                        if _DR.fetch_to(url, os.path.join(repo_dir, b)):
                            _DR.rewrite_data_path(repo_dir, miss, b)
                            r = _do_run()
                            env_note += " +fetch"
            # a nested SCRIPT that assumes CWD = its own dir (reads ../data/x.csv) → re-run from there
            if not r.get("ran_ok") and not is_nb and entry and os.path.dirname(str(entry[0])):
                if _DR.missing_data_path(_stderr()) or "No such file" in _stderr():
                    edir = os.path.join(repo_dir, os.path.dirname(str(entry[0])))
                    r2 = run_local(repo_dir, [os.path.basename(str(entry[0]))], k=args.k, python=python,
                                   hooks=hooks, targets=targets, timeout=spec.get("timeout", 600), cwd=edir)
                    if r2.get("ran_ok"):
                        r, entry = r2, [os.path.basename(str(entry[0]))]
                        env_note += " +cwd"
            # version-incompat ENV-repair (scripts): the run can fail purely because the latest science stack
            # tightened behavior the repo relied on (sklearn rejecting a label type / NaN it once tolerated, a
            # removed API) — an ENVIRONMENT problem, not the repo's compute. Retry once in a proven-compatible
            # older stack. FCR-safe (env-only, no source touched); recovers version-drift latest can't run.
            if not r.get("ran_ok") and not is_nb and pip_install:
                _e = _stderr().lower()
                if any(s in _e for s in ("unknown label type", "estimators that handle nan", "input contains nan",
                                         "cannot import name", "no attribute 'plot_", "not a valid feature")):
                    try:
                        _dg = build.downgrade_science(pip_install)
                        _pyc, _ = build.ensure_venv(name + "-compat", _dg, venvs_dir,
                                                    base_python=build.compat_python(None))
                        _r2 = run_local(repo_dir, entry, k=args.k, python=_pyc, hooks=hooks, targets=targets,
                                        timeout=spec.get("timeout", 600))
                        if _r2.get("ran_ok"):
                            r = _r2
                            env_note += " +downgrade"
                    except Exception:  # noqa: BLE001 — repair is best-effort
                        pass
            # notebook version-drift: the kernel ran the LATEST stack (removed sklearn.cross_validation,
            # changed pandas API) → retry in a downgraded kernel — the notebook analog of the script downgrade.
            if not r.get("ran_ok") and is_nb:
                _e = _stderr().lower()
                if any(s in _e for s in ("cross_validation", "cannot specify both", "cannot import name",
                                         "has no attribute", "unknown label type", "deprecated", "removed in")):
                    kname = _ensure_compat_kernel(venvs_dir, repo_dir)
                    if kname:
                        from orchestrator import tools_exec as _XT
                        _r2 = _XT.run_notebook(repo_dir, entry[0], k=args.k, hooks=hooks, targets=targets,
                                               timeout=spec.get("timeout", 600), kernel_name=kname)
                        if _r2.get("ran_ok"):
                            r = _r2
                            env_note += " +nbcompat"
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
            "meta": spec.get("meta", {}),   # domain/tier/split — makes results self-describing for the scorecard
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
    # a repo tagged with a repro_class (broken-code / no-eval / pathological / ancient-py) is objectively NOT
    # reproducible by any tool — an author compute bug, no runnable code, or a py3.6-era stack. Report
    # reproduction over the REPRODUCIBLE denominator (the honest question: of repos that CAN be reproduced,
    # do we?) alongside the raw aggregate. A tagged repo that ran anyway still counts as a repro.
    non_repro = sum(1 for r in results if (r.get("meta") or {}).get("repro_class"))
    repro_denom = repos_total - non_repro
    return {
        "repos_total": repos_total, "repos_ran": repos_ran, "discovered_claims": discovered,
        "reproduction_rate": round(repos_ran / repos_total, 3) if repos_total else 0.0,
        "reproducible_total": repro_denom, "non_reproducible": non_repro,
        "reproduction_of_reproducible": round(min(repos_ran, repro_denom) / repro_denom, 3) if repro_denom else None,
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
    ap = argparse.ArgumentParser(
        description="Run the Calma verification loop over a corpus: discover claims, re-run each repo, "
                    "independently recompute, three-way diff, and score vs hand-graded truth (FALSE_CONFIRMS=0 "
                    "is the franchise gate). Writes results/SPIKE-REPORT.md.")
    ap.add_argument("--repos", default=os.path.join(HERE, "repos.yaml"),
                    help="corpus file (default: repos.yaml)")
    ap.add_argument("--only", default="", help="comma-separated repo names to run (default: the whole corpus)")
    ap.add_argument("--k", type=int, default=2, help="runs per repo (determinism gate needs >=2)")
    ap.add_argument("--out", default=os.path.join(HERE, "results"),
                    help="output dir for the report + scored results (default: results/)")
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
    ror = agg.get("reproduction_of_reproducible")
    if ror is not None:
        print("reproduction of REPRODUCIBLE repos=%.0f%% (%d/%d; %d excluded as broken-code/no-eval/"
              "pathological/ancient-py — objectively unreproducible by any tool)"
              % (100 * ror, min(agg["repos_ran"], agg["reproducible_total"]),
                 agg["reproducible_total"], agg["non_reproducible"]))
    print("report:", report)
    return 0 if agg["false_confirm_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
