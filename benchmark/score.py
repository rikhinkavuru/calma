"""Score the benchmark: Calma vs LLM-as-judge vs trust-the-number, against ground truth.

A verifier has two ways to be WRONG, both serious:
  - false-confirm: a flawed claim is called honest  (the dangerous one - it launders a wrong number)
  - false-alarm:   an honest claim is called flawed  (cries wolf - erodes trust)
Calma may also ABSTAIN (CAN'T-CONFIRM) - a safe non-answer, never a wrong answer.

Run: python3 benchmark/score.py   (after run_calma.py + the LLM-judge batches)
Writes results/summary.json (per-method) and results/site_data.json (chart-ready, per-tier/family/track).
"""
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def _passk(reruns, label, k):
    """pass^k for ONE case = C(c,k)/C(n,k), the probability that k i.i.d. runs (drawn without
    replacement) are ALL correct (tau-bench, Yao 2024). A verifier 'succeeds' on a run when its verdict
    is the correct prediction for the case label. NOT pass@k (which rewards 1-of-k). None if n<k."""
    n = len(reruns)
    if n < k or n == 0:
        return None
    want = "flawed" if label == "flawed" else "honest"
    c = sum(1 for v in reruns if v == want)
    return math.comb(c, k) / math.comb(n, k)


def _passk_curve(rows, K):
    """Arm-level pass^k curve over k=1..K = mean over cases of the per-case pass^k. pass^1 == pass@1 ==
    the headline accuracy; the curve's drop by pass^8 is the 'consistency cliff' of a stochastic agent."""
    curve = []
    for k in range(1, K + 1):
        vals = [p for r in rows if (p := _passk(r.get("reruns") or [], r["label"], k)) is not None]
        curve.append(round(sum(vals) / len(vals), 4) if vals else None)
    return curve


def _load_judge():
    mapping = json.load(open(os.path.join(HERE, "judge_map.json")))
    pred = {}
    for f in sorted(os.listdir(os.path.join(HERE, "results"))):
        if f.startswith("judge_batch_"):
            for r in json.load(open(os.path.join(HERE, "results", f))):
                pred[mapping[r["id"]]] = r["judgment"]
    return pred


def _confusion(rows):
    flawed = [r for r in rows if r["label"] == "flawed"]
    honest = [r for r in rows if r["label"] == "honest"]
    caught = sum(1 for r in flawed if r["pred"] == "flawed")
    fconf = sum(1 for r in flawed if r["pred"] == "honest")
    abf = sum(1 for r in flawed if r["pred"] == "abstain")
    passed = sum(1 for r in honest if r["pred"] == "honest")
    falarm = sum(1 for r in honest if r["pred"] == "flawed")
    abh = sum(1 for r in honest if r["pred"] == "abstain")
    return {"flawed": len(flawed), "honest": len(honest), "caught": caught,
            "false_confirm": fconf, "abstain_flawed": abf, "passed": passed,
            "false_alarm": falarm, "abstain_honest": abh,
            "catch_rate": caught / len(flawed) if flawed else None,
            "wrong": fconf + falarm}


def main():
    manifest = {m["id"]: m for m in json.load(open(os.path.join(HERE, "manifest.json")))}
    calma = {r["id"]: r["prediction"] for r in json.load(open(os.path.join(HERE, "results", "calma.json")))}
    judge = _load_judge()
    _agent_path = os.path.join(HERE, "results", "agent.json")
    agent_rows = json.load(open(_agent_path)) if os.path.exists(_agent_path) else []
    agent = {r["id"]: r["prediction"] for r in agent_rows}
    methods = {
        "trust-the-number": lambda mid: "honest",
        "LLM-as-judge (no exec)": lambda mid: judge.get(mid, "abstain"),
        "Calma": lambda mid: calma.get(mid, "abstain"),
    }
    if agent:  # code-running-agent arm (benchmark/run_agent.py); only present once that's been run
        methods["agent-with-exec"] = lambda mid: agent.get(mid, "abstain")

    def rows_for(fn, where=None):
        out = []
        for mid, m in manifest.items():
            if where and not where(m):
                continue
            out.append({"label": m["label"], "tier": m.get("tier"), "family": m.get("family"),
                        "track": m.get("track"), "validity_family": m.get("validity_family"),
                        "pred": fn(mid)})
        return out

    n_h = sum(1 for m in manifest.values() if m["label"] == "honest")
    n_f = len(manifest) - n_h
    print("\n" + "=" * 86)
    print("CALMA BENCHMARK - catch a wrong number (%d cases: %d honest, %d flawed; "
          "3 tracks: synthetic / external [UCI+sklearn] / real-world)" % (len(manifest), n_h, n_f))
    print("=" * 86)
    print("%-24s %7s %8s %8s %9s %8s" % ("method", "catch%", "caught", "MISSED", "FALSE-AL", "abstain"))
    print("-" * 86)
    summary = {}
    for name, fn in methods.items():
        c = _confusion(rows_for(fn))
        summary[name] = c
        print("%-24s %6.0f%% %5d/%-2d %8d %9d %8d"
              % (name, (c["catch_rate"] or 0) * 100, c["caught"], c["flawed"],
                 c["false_confirm"], c["false_alarm"], c["abstain_flawed"] + c["abstain_honest"]))
    print("-" * 86)
    print("MISSED = flawed called honest (false-confirm) | FALSE-AL = honest called flawed (false-alarm)")

    # tier table
    print("\nBy flaw tier (catch%% on flawed; false-alarms on honest):")
    print("%-24s %9s %9s %10s %12s" % ("method", "obvious", "subtle", "realworld", "false-alarm"))
    tiers = {}
    for name, fn in methods.items():
        row = {}
        for tier in ("obvious", "subtle"):
            rr = rows_for(fn, lambda m, t=tier: m.get("tier") == t)
            row[tier] = sum(1 for r in rr if r["pred"] == "flawed") / len(rr) if rr else 0
        rw = rows_for(fn, lambda m: m.get("track") == "realworld" and m["label"] == "flawed")
        row["realworld"] = sum(1 for r in rw if r["pred"] == "flawed") / len(rw) if rw else 0
        ho = rows_for(fn, lambda m: m["label"] == "honest")
        row["false_alarm"] = sum(1 for r in ho if r["pred"] == "flawed")
        tiers[name] = row
        print("%-24s %8.0f%% %8.0f%% %9.0f%% %12d"
              % (name, row["obvious"] * 100, row["subtle"] * 100, row["realworld"] * 100,
                 row["false_alarm"]))

    # track table
    print("\nBy track:")
    print("%-24s %12s %18s %12s" % ("method", "synthetic", "external(UCI)", "real-world"))
    tracks = {}
    for name, fn in methods.items():
        row = {}
        line = "%-24s" % name
        for tk in ("synthetic", "external", "realworld"):
            c = _confusion(rows_for(fn, lambda m, t=tk: m.get("track") == t))
            row[tk] = c
            line += " %6.0f%%/%dw " % ((c["catch_rate"] or 0) * 100, c["wrong"])
        tracks[name] = row
        print(line + "   (catch%/wrong-verdicts)")

    # Two axes (NASEM 2019): REPRODUCIBILITY (recompute the headline number) vs VALIDITY (the result is
    # SOUND - no leakage/overfitting/survivorship/shift). reproducibility cut = flawed cases that are NOT
    # validity-tagged (a recompute catches these); validity cut = the validity_family cases (the number
    # REPRODUCES, so a recompute-only method false-confirms; the deterministic engine INVALIDATES them).
    def _catch(fn, where):
        rr = rows_for(fn, where)
        return (sum(1 for r in rr if r["pred"] == "flawed") / len(rr) if rr else None), len(rr)

    def _pct(x):
        return ("%3.0f%%" % (x * 100)) if x is not None else " n/a"

    print("\nTwo axes - reproducibility vs validity (catch%% on each cut):")
    print("%-24s %18s %18s" % ("method", "reproducibility", "validity"))
    axes = {}
    for name, fn in methods.items():
        rc, rn = _catch(fn, lambda m: m["label"] == "flawed" and not m.get("validity_family"))
        vc, vn = _catch(fn, lambda m: bool(m.get("validity_family")))
        axes[name] = {"reproducibility_catch": rc, "reproducibility_n": rn,
                      "validity_catch": vc, "validity_n": vn}
        print("%-24s %12s (n=%d) %12s (n=%d)" % (name, _pct(rc), rn, _pct(vc), vn))
    vfam_names = sorted({m["validity_family"] for m in manifest.values() if m.get("validity_family")})
    n_vcut = sum(1 for m in manifest.values() if m.get("validity_family"))
    print("  validity cut = %d cases the engine INVALIDATES across %d families %s" % (n_vcut, len(vfam_names), vfam_names))
    print("  (small per-family N -- indicative, not statistically tight; expanding to N>=8/family is future work)")

    # validity catch-rate BY family (the cell where a recompute-only method false-confirms but the
    # deterministic engine INVALIDATES). Calma ~1.0 by construction; the agent is predicted to miss a chunk.
    vfam_table = {}
    for name, fn in methods.items():
        vfam_table[name] = {vf: dict(zip(("catch", "n"), _catch(fn, lambda m, v=vf: m.get("validity_family") == v)))
                            for vf in vfam_names}

    # per-family for the site charts
    fams = {}
    for fam in sorted({m["family"] for m in manifest.values()}):
        fams[fam] = {}
        for name, fn in methods.items():
            c = _confusion(rows_for(fn, lambda m, f=fam: m.get("family") == f))
            fams[fam][name] = {"catch_rate": c["catch_rate"], "wrong": c["wrong"],
                               "flawed": c["flawed"], "honest": c["honest"]}

    if agent_rows:
        inst = sum(1 for r in agent_rows if r.get("unstable")) / len(agent_rows)
        usd = sum(r.get("usd", 0) for r in agent_rows)
        ams = sorted(r["ms"] for r in agent_rows)
        # validity-cut catch for the agent reads the engine-derived validity_family tag (NOT the metric
        # family) - this was previously dead (it filtered on `family`, which is never a validity family).
        av = axes.get("agent-with-exec", {})
        # variance metrics that distinguish a stochastic agent from a deterministic checker:
        K = max((len(r.get("reruns") or []) for r in agent_rows), default=1)
        passk = _passk_curve(agent_rows, K)
        agree = sum(1 for r in agent_rows if r["prediction"] == calma.get(r["id"], "abstain")) / len(agent_rows)
        flip = sum(1 for r in agent_rows if r.get("unstable")) / len(agent_rows)  # = instability (verdict flips across reruns)
        line = ("\nagent-with-exec extras: verdict-instability %.0f%% (Calma 0%%) | cost $%.2f | p50 %dms"
                % (inst * 100, usd, ams[len(ams) // 2]))
        if av.get("validity_n"):
            line += " | validity-cut catch %.0f%% (vs Calma 100%% by construction)" % ((av["validity_catch"] or 0) * 100)
        print(line)
        print("  pass^k curve (k=1..%d): %s   |   agreement-with-Calma %.0f%%   |   flip-rate %.0f%%"
              % (K, [("%.2f" % p) if p is not None else "n/a" for p in passk], agree * 100, flip * 100))
        print("  (Calma: instability 0, pass^k = 1.0 flat, agreement-with-itself 1.0 - all BY CONSTRUCTION)")
        summary["agent-with-exec_extras"] = {"instability": inst, "usd": usd, "p50_ms": ams[len(ams) // 2],
                                             "passk_curve": passk, "K": K,
                                             "agreement_with_calma": round(agree, 4), "flip_rate": round(flip, 4)}
    # cross-model arm (G3): a second model from a DIFFERENT family kills the single-model artifact + the
    # self-recognition self-preference bias (Panickssery 2024). Same metrics, side by side.
    cross_model = []
    cross_path = os.path.join(HERE, "results", "agent_cross.json")
    if os.path.exists(cross_path):
        print("\nCross-model (>=2 families - kills single-model artifact + self-preference bias):")
        print("%-26s %8s %9s %8s %8s %8s %8s" % ("model", "catch", "validity", "instab", "pass^1", "agree", "$"))
        for arm in json.load(open(cross_path)):
            rows, mdl = arm.get("rows", []), arm.get("model", "?")
            if not rows:
                continue
            cc = _confusion([{"label": r["label"], "pred": r["prediction"]} for r in rows])
            vrows = [r for r in rows if r.get("validity_family")]
            vcatch = (sum(1 for r in vrows if r["prediction"] == "flawed") / len(vrows)) if vrows else None
            ki = max((len(r.get("reruns") or []) for r in rows), default=1)
            pk = _passk_curve(rows, ki)
            inst2 = sum(1 for r in rows if r.get("unstable")) / len(rows)
            agr = sum(1 for r in rows if r["prediction"] == calma.get(r["id"], "abstain")) / len(rows)
            usd2 = sum(r.get("usd", 0) for r in rows)
            cross_model.append({"model": mdl, "catch_rate": cc["catch_rate"], "validity_catch": vcatch,
                                "instability": inst2, "passk_curve": pk, "agreement_with_calma": round(agr, 4),
                                "usd": round(usd2, 4)})
            print("%-26s %6.0f%% %8s %7.0f%% %7s %7.0f%% %7.2f" % (
                mdl, (cc["catch_rate"] or 0) * 100, ("%.0f%%" % (vcatch * 100)) if vcatch is not None else "n/a",
                inst2 * 100, ("%.2f" % pk[0]) if pk and pk[0] is not None else "n/a", agr * 100, usd2))

    lat = sorted(r["ms"] for r in json.load(open(os.path.join(HERE, "results", "calma.json"))))
    site = {"n_cases": len(manifest), "n_honest": n_h, "n_flawed": n_f,
            "overall": summary, "tiers": tiers, "tracks": {
                name: {tk: {"catch_rate": v[tk]["catch_rate"], "wrong": v[tk]["wrong"]}
                       for tk in v} for name, v in tracks.items()},
            "families": fams, "axes": axes, "validity_by_family": vfam_table,
            "validity_cut_n": n_vcut, "validity_families": vfam_names, "cross_model": cross_model,
            "calma_p50_ms": lat[len(lat) // 2]}
    json.dump(summary, open(os.path.join(HERE, "results", "summary.json"), "w"), indent=2)
    json.dump(site, open(os.path.join(HERE, "results", "site_data.json"), "w"), indent=2)
    print("\nwrote results/summary.json + results/site_data.json (calma p50 %dms)" % site["calma_p50_ms"])


if __name__ == "__main__":
    main()
