"""The hardened validity cut: >=8 INVALIDATED cases per validity family, each constructed so the
HEADLINE NUMBER REPRODUCES (a recompute / an LLM judge calls it honest) while calma INVALIDATES it via
its validity layer -- the cut that separates calma from every recompute-or-judge substitute.

This is a STANDALONE catalog, deliberately NOT spliced into benchmark/manifest.json: it strengthens the
validity-cut evidence (statistical N + citable third-party provenance) WITHOUT re-running or destabilizing
the committed agent-arm benchmark. Each case is verified against the LIVE calma engine (offline, $0).

It also carries an honest "calma's own misses" set -- results that ARE substantively flawed but that calma
CONFIRMS, to mark the ceiling: calma verifies the number + the DECLARED validity families; it does not
invent a flaw the producer never declared, nor judge the truth of the inputs themselves.

  python3 benchmark/validity_catalog.py            # (re)generate cases + verify + write the report
  python3 benchmark/validity_catalog.py --check     # regression gate: assert the invariant, no rewrite
"""
import argparse
import csv
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CALMA = os.path.join(HERE, "..", ".claude", "skills", "calma", "scripts", "calma.py")
CATALOG = os.path.join(HERE, "validity_catalog")
CASES = os.path.join(CATALOG, "cases")
N_PER_FAMILY = 8


def _lcg(seed):
    """The same pure-stdlib LCG the committed cases use -- deterministic, no numpy."""
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x / 0x7FFFFFFF


def _write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


def _emit(case_id, files, contract):
    """Write one case dir: its committed data CSV(s), a no-op entrypoint (data is committed; the run just
    has to exit 0), and verify.yaml. Returns the dir."""
    d = os.path.join(CASES, case_id)
    os.makedirs(os.path.join(d, "runs"), exist_ok=True)
    for name, (header, rows) in files.items():
        _write_csv(os.path.join(d, name), header, rows)
    with open(os.path.join(d, "gen.py"), "w") as f:
        f.write("pass\n")
    json.dump(contract, open(os.path.join(d, "verify.yaml"), "w"), indent=2)
    return d


def _metric_of(case_dir):
    try:
        c = json.load(open(os.path.join(case_dir, "verify.yaml")))
        return (c.get("metrics") or [{}])[0].get("metric_id")
    except (OSError, ValueError, IndexError):
        return None


def _verify(case_dir, claim_text=None):
    """Run the LIVE engine EXACTLY as benchmark/run_calma.py does: pin the metric with --metric (so a
    free-text claim can't mis-route, the bug that made sharpe claims INCONCLUSIVE) and --force. Returns
    (verdict, recomputed). claim_text=None reads back the recomputed value; a scope-asserting claim_text
    drives the INVALIDATED."""
    argv = [sys.executable, os.path.abspath(CALMA), "verify", case_dir]
    if claim_text is not None:
        argv.append(claim_text)
    metric = _metric_of(case_dir)
    if metric:
        argv += ["--metric", metric]
    argv += ["--json", "--force"]
    p = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    try:
        d = json.loads(p.stdout)
    except ValueError:
        return ("ERROR:%s" % (p.stderr or p.stdout)[-200:], None)
    return d.get("verdict"), d.get("recomputed")


def _base_contract(artifact, columns, metric_id, binding, extra):
    """A committed-contract skeleton matching the shape of the hand-built benchmark cases."""
    c = {"run": {"entrypoint": "gen.py", "network": "off", "cwd": "."},
         "env": {"ecosystem": "auto", "trust": "own-code"},
         "artifacts": [{"path": artifact, "columns": columns}],
         "metrics": [{"metric_id": metric_id, "artifact": artifact, "binding": binding,
                      "convention": None, "headline": True}],
         "baselines": []}
    c.update(extra)
    return c


def _col(tag, dtype="float"):
    return {"tag": tag, "dtype": dtype, "na_policy": "error"}


RET_ART = "runs/returns.csv"
RET_COLS = {"daily_return": _col("return")}
RET_BIND = {"return": "daily_return"}


# ============================ the 8 validity families ============================
# Each gen_<family>(i) writes a case dir and returns (case_id, scope_claim_template). The build loop
# reads back the recomputed value (so the claim REPRODUCES) and asserts the engine INVALIDATES it.

def gen_omitted_costs(i):
    """A GROSS return reported as net: a cost model is declared but never deducted (Novy-Marx & Velikov
    2016 -- many anomalies die net of costs)."""
    fee = [5, 10, 15, 20, 30, 40, 50, 60][i]
    g = _lcg(2200 + i)
    rows = [[round(0.001 + (next(g) - 0.5) * 0.02, 6), round(0.3 + next(g) * 0.7, 4)] for _ in range(180)]
    cid = "omitted-costs_%d" % i
    contract = _base_contract(RET_ART, {"gross_return": _col("return"), "turnover": _col("ignore")},
                              "total_return", {"return": "gross_return"},
                              {"costs": {"fee_bps": float(fee), "turnover_col": "turnover"}})
    _emit(cid, {RET_ART: (["gross_return", "turnover"], rows)}, contract)
    return cid, "net-of-fees total return %s"


def gen_survivorship(i):
    """A survivors-only universe sold as point-in-time (Brown, Goetzmann, Ibbotson & Ross 1992 --
    truncating to survivors manufactures apparent performance)."""
    g = _lcg(3300 + i)
    n = [120, 150, 180, 210, 240, 130, 160, 200][i]
    rows = [[round(0.0008 + (next(g) - 0.5) * 0.018, 8)] for _ in range(n)]
    univ = {"universe": "survivors-only"} if i % 2 == 0 else {"universe": {"survivors_only": True}}
    cid = "survivorship_%d" % i
    _emit(cid, {RET_ART: (["daily_return"], rows)},
          _base_contract(RET_ART, RET_COLS, "total_return", RET_BIND, univ))
    return cid, "point-in-time survivorship-free total return %s"


def gen_window(i):
    """A short sample reported as a full-period track record: the claimed period exceeds the data the
    backtest actually covers (Bailey, Borwein, Lopez de Prado & Zhu 2014 -- misrepresented backtests)."""
    g = _lcg(4400 + i)
    n = [40, 55, 70, 60, 45, 80, 50, 65][i]
    claimed = [252, 252, 504, 252, 504, 252, 378, 252][i]
    rows = [[round(0.0009 + (next(g) - 0.5) * 0.02, 8)] for _ in range(n)]
    cid = "window_%d" % i
    _emit(cid, {RET_ART: (["daily_return"], rows)},
          _base_contract(RET_ART, RET_COLS, "total_return", RET_BIND, {"claimed_periods": claimed}))
    return cid, "representative total return %s over the full period"


def gen_data_snooping(i):
    """A best-of-N-trials Sharpe with no multiple-testing haircut: the t-stat is declared but Holm/HLZ
    deflation kills the significance (Harvey & Liu 2014; Bailey & Lopez de Prado 2014, deflated Sharpe)."""
    g = _lcg(5500 + i)
    rows = [[round(0.0006 + (next(g) - 0.5) * 0.012, 8)] for _ in range(252)]
    trials = [100, 150, 200, 250, 300, 120, 180, 240][i]
    tstat = [2.5, 2.6, 2.4, 2.7, 2.3, 2.8, 2.5, 2.6][i]
    cid = "data-snooping_%d" % i
    _emit(cid, {RET_ART: (["daily_return"], rows)},
          _base_contract(RET_ART, RET_COLS, "sharpe", RET_BIND,
                         {"study": {"trials": trials, "t_stat": tstat}}))
    return cid, "a statistically significant factor, Sharpe of %s"


def gen_model_leakage(i):
    """Preprocessing fit on train+test inflates a held-out metric (Kaufman, Rosset, Perlich &
    Stitelman 2012 -- the canonical leakage formalization)."""
    g = _lcg(6600 + i)
    gap = [0.10, 0.12, 0.08, 0.15, 0.05, 0.11, 0.09, 0.13][i]
    leaked = [0.88, 0.90, 0.92, 0.85, 0.95, 0.87, 0.91, 0.93][i]
    transform = ["StandardScaler", "MinMaxScaler", "PCA", "TargetEncoder", "QuantileTransformer",
                 "StandardScaler", "RobustScaler", "PCA"][i]
    n = 200
    correct = int(round(leaked * n))
    rows = [[1, 1] if k < correct else [1, 0] for k in range(n)]   # accuracy == leaked by construction
    for k in range(n):                                            # keep a balanced-ish label mix
        rows[k] = [k % 2, k % 2] if k < correct else [k % 2, 1 - (k % 2)]
    cid = "model-leakage_%d" % i
    contract = _base_contract("runs/preds.csv",
                              {"y_pred": _col("prediction", "int"), "y_true": _col("label", "int")},
                              "accuracy", {"prediction": "y_pred", "label": "y_true"},
                              {"pipeline": {"fit_on": "train+test", "transform": transform,
                                            "leaked_metric": leaked, "train_only_metric": round(leaked - gap, 4)}})
    _emit(cid, {"runs/preds.csv": (["y_pred", "y_true"], rows)}, contract)
    return cid, "no data leakage, properly held-out accuracy %s"


def gen_regime(i):
    """An in-sample edge that vanishes out-of-sample (McLean & Pontiff 2016 -- predictor returns decay
    ~26% OOS / ~58% post-publication)."""
    g = _lcg(7700 + i)
    k = [2, 2, 3, 2, 4, 2, 3, 2][i]
    strong = [0.008, 0.010, 0.007, 0.012, 0.009, 0.006, 0.011, 0.008][i]
    half = [40, 50, 45, 60, 40, 55, 48, 52][i]
    rows = [[round(strong + (next(g) - 0.5) * 0.01, 8)] for _ in range(half)]            # regime 1: edge
    rows += [[round(-0.001 + (next(g) - 0.5) * 0.01, 8)] for _ in range(half)]           # regime 2: gone
    cid = "regime_%d" % i
    _emit(cid, {RET_ART: (["daily_return"], rows)},
          _base_contract(RET_ART, RET_COLS, "total_return", RET_BIND, {"windows": {"k": k}}))
    return cid, "a robust edge across every regime, walk-forward validated total return %s"


def gen_distribution_shift(i):
    """Test features drawn from a different distribution than train (Quinonero-Candela et al. 2009 --
    dataset/covariate shift); the test accuracy reproduces but does not generalize in-distribution."""
    g = _lcg(8800 + i)
    shift = [3, 4, 2, 5, 3, 4, 2, 5][i]
    acc = [0.88, 0.90, 0.86, 0.92, 0.89, 0.91, 0.87, 0.93][i]
    train = [[round(next(g), 4), j % 2, j % 2] for j in range(80)]
    test = []
    for j in range(80):
        y = j % 2
        p = y if next(g) < acc else 1 - y
        test.append([round(shift + next(g), 4), p, y])
    cid = "distribution-shift_%d" % i
    cols = {"feat": _col("feature"), "y_pred": _col("prediction", "int"), "y_true": _col("label", "int")}
    contract = _base_contract("runs/test.csv", cols, "accuracy",
                              {"prediction": "y_pred", "label": "y_true"},
                              {"split": {"train": "runs/train.csv", "test": "runs/test.csv"},
                               "keys": {"target": "y_true"}})
    _emit(cid, {"runs/train.csv": (["feat", "y_pred", "y_true"], train),
                "runs/test.csv": (["feat", "y_pred", "y_true"], test)}, contract)
    return cid, "the model generalizes in-distribution, accuracy %s"


def gen_look_ahead(i):
    """The signal is the same-bar sign of the return it trades, so the backtest 'knows' each bar's
    outcome before trading it (Luo et al. 2014, 'Seven Sins of Quantitative Investing', look-ahead)."""
    g = _lcg(9900 + i)
    n = [60, 90, 120, 75, 100, 80, 110, 70][i]
    drift = [0.001, 0.0008, 0.0012, 0.0009, 0.0011, 0.0007, 0.001, 0.0013][i]
    rows = []
    for _ in range(n):
        a = round(drift + (next(g) - 0.5) * 0.02, 6)
        s = 1.0 if a >= 0 else -1.0
        rows.append([s, a, round(s * a, 6)])
    cid = "look-ahead_%d" % i
    cols = {"signal": _col("ignore"), "asset_ret": _col("ignore"), "strat_ret": _col("return")}
    contract = _base_contract("runs/bt.csv", cols, "total_return", {"return": "strat_ret"},
                              {"availability": {"signal": "signal", "return": "asset_ret",
                                                "artifact": "runs/bt.csv"}})
    _emit(cid, {"runs/bt.csv": (["signal", "asset_ret", "strat_ret"], rows)}, contract)
    return cid, "out-of-sample tradeable total return %s"


# family -> (generator, citable third-party provenance)
FAMILIES = {
    "omitted-costs": (gen_omitted_costs,
                      "Novy-Marx & Velikov (2016), 'A Taxonomy of Anomalies and Their Trading Costs,' "
                      "Review of Financial Studies 29(1):104-147."),
    "survivorship": (gen_survivorship,
                     "Brown, Goetzmann, Ibbotson & Ross (1992), 'Survivorship Bias in Performance "
                     "Studies,' Review of Financial Studies 5(4):553-580."),
    "window": (gen_window,
               "Bailey, Borwein, Lopez de Prado & Zhu (2014), 'Pseudo-Mathematics and Financial "
               "Charlatanism,' Notices of the AMS 61(5):458-471."),
    "data-snooping": (gen_data_snooping,
                      "Harvey & Liu (2014), 'Backtesting' (SSRN 2345489); Bailey & Lopez de Prado "
                      "(2014), 'The Deflated Sharpe Ratio,' Journal of Portfolio Management 40(5):94-107."),
    "model-leakage": (gen_model_leakage,
                      "Kaufman, Rosset, Perlich & Stitelman (2012), 'Leakage in Data Mining: "
                      "Formulation, Detection, and Avoidance,' ACM TKDD 6(4), Article 15."),
    "regime": (gen_regime,
               "McLean & Pontiff (2016), 'Does Academic Research Destroy Stock Return "
               "Predictability?,' Journal of Finance 71(1):5-32."),
    "distribution-shift": (gen_distribution_shift,
                           "Quinonero-Candela, Sugiyama, Schwaighofer & Lawrence, eds. (2009), "
                           "'Dataset Shift in Machine Learning,' MIT Press."),
    "look-ahead": (gen_look_ahead,
                   "Luo, Alvarez, Wang, Jussa, Wang & Rohal (2014), 'Seven Sins of Quantitative "
                   "Investing,' Deutsche Bank Markets Research."),
}


# ===================== calma's own misses (the honest ceiling) =====================
# Substantively flawed results that calma CONFIRMS -- not to hide them, but to mark exactly what
# verification can and cannot do, by design.

def _miss_undeclared_haircut():
    g = _lcg(111000)
    rows = [[round(0.0006 + (next(g) - 0.5) * 0.012, 8)] for _ in range(252)]
    cid = "miss_undeclared-haircut"
    _emit(cid, {RET_ART: (["daily_return"], rows)},      # SAME best-of-many-trials flaw, but NO study block
          _base_contract(RET_ART, RET_COLS, "sharpe", RET_BIND, {}))
    return cid, "Sharpe of %s"


def _miss_corrupted_labels():
    n, correct = 200, 190
    rows = [[k % 2, k % 2] if k < correct else [k % 2, 1 - (k % 2)] for k in range(n)]
    cid = "miss_corrupted-labels"
    _emit(cid, {"runs/preds.csv": (["y_pred", "y_true"], rows)},
          _base_contract("runs/preds.csv",
                         {"y_pred": _col("prediction", "int"), "y_true": _col("label", "int")},
                         "accuracy", {"prediction": "y_pred", "label": "y_true"}, {}))
    return cid, "accuracy %s"


MISSES = [
    (_miss_undeclared_haircut,
     "The multiple-testing haircut only runs when a `study` block is declared. A producer who omits it -- "
     "or never knew to -- escapes the check. calma verifies what the contract declares; it does not infer "
     "an undeclared flaw. (Mitigation: calma draft/onboard proposes the blocks; the producer must adopt them.)"),
    (_miss_corrupted_labels,
     "calma recomputes the metric from the produced outputs; it cannot know the ground-truth labels are "
     "themselves wrong. Verifying that a number is correctly computed is not validating the truth of its "
     "inputs -- a different problem (data provenance), out of scope by design."),
]


def _fmt(val):
    return "%.4f" % float(val)


def build_and_check(check_only=False):
    os.makedirs(CASES, exist_ok=True)
    report = {"families": {}, "misses": [], "n_caught": 0, "n_total": 0}
    failures = []
    for fam, (gen, cite) in FAMILIES.items():
        cases = []
        for i in range(N_PER_FAMILY):
            cid, scope = gen(i)
            d = os.path.join(CASES, cid)
            _, val = _verify(d)                                  # pass 1: read the recomputed value
            if val is None:
                failures.append((cid, "no recomputed value"))
                continue
            claim = scope % _fmt(val)
            verdict, _ = _verify(d, claim)                       # pass 2: the scope-asserting claim
            ok = verdict == "INVALIDATED"
            cases.append({"case": cid, "verdict": verdict, "claim": claim, "value": round(val, 6),
                          "invalidated": ok})
            report["n_total"] += 1
            report["n_caught"] += int(ok)
            if not ok:
                failures.append((cid, "expected INVALIDATED, got %s" % verdict))
        report["families"][fam] = {"citation": cite, "n": len(cases),
                                   "invalidated": sum(c["invalidated"] for c in cases), "cases": cases}
    for gen_fn, why in MISSES:
        cid, tmpl = gen_fn()
        d = os.path.join(CASES, cid)
        _, val = _verify(d)
        claim = tmpl % _fmt(val) if val is not None else tmpl % "0"
        verdict, _ = _verify(d, claim)
        missed = verdict != "INVALIDATED"                        # a 'miss' = calma did NOT invalidate it
        report["misses"].append({"case": cid, "verdict": verdict, "claim": claim,
                                 "value": round(val, 6) if val is not None else None,
                                 "missed": missed, "why": why})
        if not missed:
            failures.append((cid, "expected a documented MISS (not INVALIDATED), got %s" % verdict))
    if not check_only:
        _write_report(report)
    return report, failures


def _write_report(report):
    json.dump(report, open(os.path.join(CATALOG, "report.json"), "w"), indent=2)
    L = []
    L.append("# calma validity catalog -- the hardened validity cut\n")
    L.append("Every case below reproduces its headline number (a recompute / an LLM judge calls it "
             "honest) yet calma **INVALIDATES** it via the validity layer. Each is verified against the "
             "live engine, offline. This catalog is standalone -- it strengthens the validity-cut evidence "
             "(statistical N + citable provenance) without destabilizing the committed agent-arm benchmark.\n")
    L.append("**calma INVALIDATES %d / %d** designed-to-catch cases across %d families "
             "(>=%d per family).\n" % (report["n_caught"], report["n_total"], len(report["families"]),
                                       N_PER_FAMILY))
    L.append("| validity family | cases | calma INVALIDATES | citable provenance |")
    L.append("|---|---|---|---|")
    for fam, d in report["families"].items():
        L.append("| %s | %d | **%d/%d** | %s |" % (fam, d["n"], d["invalidated"], d["n"], d["citation"]))
    L.append("\n## calma's own misses (the honest ceiling)\n")
    L.append("Verification is not omniscience. These results are substantively flawed, yet calma CONFIRMS "
             "them -- disclosed so the boundary is explicit, not hidden.\n")
    L.append("| case | calma verdict | why calma misses it |")
    L.append("|---|---|---|")
    for m in report["misses"]:
        L.append("| %s | %s | %s |" % (m["case"], m["verdict"], m["why"]))
    L.append("\n_Regenerate / re-verify: `python3 benchmark/validity_catalog.py` "
             "(`--check` asserts the invariant as a regression gate)._\n")
    open(os.path.join(CATALOG, "REPORT.md"), "w").write("\n".join(L))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="regression gate: regenerate + re-verify, assert the invariant, exit nonzero on drift")
    a = ap.parse_args()
    report, failures = build_and_check(check_only=a.check)
    print("validity catalog: calma INVALIDATES %d/%d catch cases across %d families; %d documented misses"
          % (report["n_caught"], report["n_total"], len(report["families"]), len(report["misses"])))
    for fam, d in report["families"].items():
        flag = "" if d["invalidated"] == d["n"] else "  <-- INCOMPLETE"
        print("  %-20s %d/%d invalidated%s" % (fam, d["invalidated"], d["n"], flag))
    for m in report["misses"]:
        print("  miss %-26s %s%s" % (m["case"], m["verdict"],
                                     "" if m["missed"] else "  <-- UNEXPECTEDLY CAUGHT"))
    if failures:
        print("\nFAILURES (%d):" % len(failures))
        for cid, msg in failures:
            print("  %s: %s" % (cid, msg))
        return 1
    print("\nOK: every family >=%d INVALIDATED, every documented miss reproduced." % N_PER_FAMILY)
    return 0


if __name__ == "__main__":
    sys.exit(main())
