#!/usr/bin/env python
"""optimize.scorecard — the metric × domain × difficulty-tier scorecard (guide §A.4).

The corpus is a measurement instrument, so its results must be reported as a MATRIX (not a single pass/fail):
for each (domain, tier) cell — reproduction / capture / binding / verdict-accuracy / verdict-distribution,
each with an n-count, and the one line that can never move: **false-confirm count == 0** (a hard gate,
per-cell and global). MLRC's discipline — never collapse to one number; small-n cells get flagged.

Two halves:
  * the INTAKE distribution (`corpus_matrix`) — always available offline, describes the corpus as
    'n per domain × tier' so the iris-trap is visible.
  * the OUTCOME metrics (`score_results`) — join a run_spike results.json's per-claim verdicts to each
    repo's meta and aggregate per cell. `fcr_breaches` is the release gate.

Pure-stdlib. Run `scorecard.py --results results/results.json` after a corpus run, or with no args to render
just the intake distribution.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
if SPIKE not in sys.path:
    sys.path.insert(0, SPIKE)

import corpus as CORP  # noqa: E402

# the seven-way taxonomy, for the per-cell verdict distribution
VERDICTS = ("CONFIRMED", "REFUTED", "INVALIDATED", "REPRODUCED-ONLY", "NON-DETERMINISTIC",
           "INCONCLUSIVE", "DISCOVERED")
POSITIVE = ("CONFIRMED",)


def corpus_matrix(specs=None) -> dict:
    """Intake distribution: domain × tier n-counts + split, from the corpus meta."""
    return CORP.distribution(specs)


def _meta_for(repo, name_to_meta):
    m = repo.get("meta") or name_to_meta.get(repo.get("name")) or {}
    return (m.get("domain", "unknown"), m.get("tier", "unknown"))


def score_results(results: dict) -> dict:
    """Per-(domain,tier) outcome cell aggregation from a run_spike results dict.

    Each cell: repos_total/ran, claims_total/bound, graded/matches, capture_calls, false_confirms, and the
    verdict histogram — all with n-counts. capture_rate = fraction of RAN repos that captured >=1 computation
    (a repo-level proxy; per-claim capture needs binding, tracked separately).
    """
    try:
        name_to_meta = {s["name"]: CORP.meta_of(s) for s in CORP.load()}
    except Exception:  # noqa: BLE001 — corpus unreadable → rely on embedded meta only
        name_to_meta = {}
    cells: dict[tuple, dict] = {}
    for repo in results.get("repos", []):
        dom, tier = _meta_for(repo, name_to_meta)
        c = cells.setdefault((dom, tier), {
            "repos": 0, "ran": 0, "captured": 0, "claims": 0, "bound": 0,
            "graded": 0, "matches": 0, "false_confirms": 0,
            "verdicts": dict.fromkeys(VERDICTS, 0)})
        c["repos"] += 1
        ran = bool(repo.get("ran"))
        c["ran"] += int(ran)
        n_calls = repo.get("n_calls") or []
        if ran and isinstance(n_calls, list) and sum(n_calls) > 0:
            c["captured"] += 1
        for cl in repo.get("claims", []):
            c["claims"] += 1
            c["bound"] += int(bool(cl.get("bound")))
            v = cl.get("verdict")
            if v in c["verdicts"]:
                c["verdicts"][v] += 1
            if cl.get("expect") is not None:
                c["graded"] += 1
                c["matches"] += int(bool(cl.get("match")))
                if cl.get("false_confirm"):
                    c["false_confirms"] += 1
    return cells


def fcr_breaches(cells: dict) -> list:
    """The hard gate: any (domain,tier) cell with a nonzero false-confirm count. Empty == FCR holds."""
    return [{"cell": "%s/%s" % k, "false_confirms": c["false_confirms"]}
            for k, c in cells.items() if c["false_confirms"]]


def _rate(num, den):
    return "—" if not den else "%.0f%% (%d/%d)" % (100 * num / den, num, den)


def render(matrix: dict, cells: dict | None) -> str:
    L: list = []
    A = L.append
    A("# Calma — metric × domain × tier scorecard (guide §A.4)\n")
    A("## Corpus as a distribution (intake)\n")
    A("n=%d repos · splits=%s\n" % (matrix["n"], matrix["by_split"]))
    A("| domain \\ tier | T1 | T2 | T3 | T4 | total |")
    A("|---|---|---|---|---|---|")
    doms = sorted({k.split("/")[0] for k in matrix["matrix"]})
    for dom in doms:
        row = [matrix["matrix"].get("%s/%s" % (dom, t), 0) for t in ("T1", "T2", "T3", "T4")]
        A("| %s | %d | %d | %d | %d | %d |" % (dom, *row, sum(row)))
    A("| **total** | %d | %d | %d | %d | **%d** |"
      % (*[matrix["by_tier"].get(t, 0) for t in ("T1", "T2", "T3", "T4")], matrix["n"]))
    for t in ("T1", "T2", "T3", "T4"):
        A("- **%s** — %s" % (t, CORP.TIER_MEANING[t]))

    if cells:
        A("\n## Outcomes per cell (from the last corpus run)\n")
        A("| cell | repos | reproduction | capture | binding | verdict-acc (graded) | **FCR** |")
        A("|---|---|---|---|---|---|---|")
        gate_ok = True
        for (dom, tier) in sorted(cells):
            c = cells[(dom, tier)]
            fcr = c["false_confirms"]
            gate_ok = gate_ok and fcr == 0
            small = " ⚠️" if c["graded"] and c["graded"] < 2 else ""
            A("| %s/%s | %d | %s | %s | %s | %s%s | %s |" % (
                dom, tier, c["repos"], _rate(c["ran"], c["repos"]), _rate(c["captured"], c["ran"]),
                _rate(c["bound"], c["claims"]), _rate(c["matches"], c["graded"]), small,
                "**%d** ✅" % fcr if fcr == 0 else "**%d** ❌" % fcr))
        A("\n**FCR gate (per-cell + global): %s** — a single false-confirm anywhere is a P0."
          % ("✅ PASS (0 everywhere)" if gate_ok else "❌ FAIL"))
        # verdict distribution per cell (a domain that's 100%% REPRODUCED-ONLY signals a coverage gap)
        A("\n## Verdict distribution per cell\n")
        for (dom, tier) in sorted(cells):
            dist = {v: n for v, n in cells[(dom, tier)]["verdicts"].items() if n}
            if dist:
                A("- **%s/%s**: %s" % (dom, tier, ", ".join("%s=%d" % (v, n) for v, n in dist.items())))
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="", help="a run_spike results.json to overlay outcome metrics")
    ap.add_argument("--out", default=os.path.join(SPIKE, "results", "SCORECARD.md"))
    args = ap.parse_args()
    matrix = corpus_matrix()
    cells = None
    if args.results and os.path.isfile(args.results):
        with open(args.results) as fh:
            cells = score_results(json.load(fh))
    md = render(matrix, cells)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        fh.write(md)
    print(md)
    if cells:
        breaches = fcr_breaches(cells)
        print("FCR breaches:", breaches or "none")
        return 1 if breaches else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
