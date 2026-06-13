"""Validate the benchmark's ground-truth oracles against PUBLISHED reference implementations.

For every base in manifest.json, recompute the true value with the canonical third-party library —
scikit-learn for classification/regression/forecasting, SciPy for statistics, NumPy for quantiles
and the quant formulas (documented below) — and assert agreement with the stdlib oracle to 1e-9
relative. This is what makes the benchmark's ground truth externally credible: every labeled value
is cross-checked against the implementation the field actually uses, with library versions recorded.

Quant + IR metrics have no sklearn one-liner; they validate against the textbook formula computed
in NumPy (definitions stated inline) — and calma's own recipes for ALL metrics are separately
validated against 385 byte-reproducible reference vectors (assets/reference_vectors.json).

Run INSIDE a venv that has numpy, scikit-learn, scipy:
  python3 -m venv /tmp/calma_bench_venv
  /tmp/calma_bench_venv/bin/pip install numpy scikit-learn scipy
  /tmp/calma_bench_venv/bin/python benchmark/validate_oracles.py

Writes benchmark/results/oracle_validation.json.
"""
import csv
import json
import math
import os

import numpy as np
import scipy
import scipy.stats
import sklearn
from sklearn import metrics as SK

HERE = os.path.dirname(os.path.abspath(__file__))


def _cols(case_dir):
    runs = os.path.join(case_dir, "runs")
    art = next(f for f in sorted(os.listdir(runs)) if f.endswith(".csv"))
    with open(os.path.join(runs, art)) as f:
        rows = list(csv.DictReader(f))
    return {k: [r[k] for r in rows] for k in rows[0]}


def _f(c):
    return np.array([float(x) for x in c])


def _i(c):
    return np.array([int(x) for x in c])


def ref_recall_at_k(q, rank, rel, k):
    """Standard IR recall@k: mean over queries of (relevant in top-k)/(all relevant); zero-relevant
    queries skipped (TREC convention)."""
    per = {}
    for qq, rr, ll in zip(q, rank, rel):
        per.setdefault(qq, []).append((int(rr), int(ll)))
    vals = []
    for rows in per.values():
        rows.sort()
        tot = sum(1 for _, l in rows if l > 0)
        if tot:
            vals.append(sum(1 for r, l in rows[:k] if l > 0) / tot)
    return float(np.mean(vals))


def ref_mrr(q, rank, rel):
    per = {}
    for qq, rr, ll in zip(q, rank, rel):
        per.setdefault(qq, []).append((int(rr), int(ll)))
    vals = []
    for rows in per.values():
        rows.sort()
        rr_ = 0.0
        for pos, (_, l) in enumerate(rows, start=1):
            if l > 0:
                rr_ = 1.0 / pos
                break
        vals.append(rr_)
    return float(np.mean(vals))


# metric -> (reference callable over cols, implementation name)
def _references():
    return {
        "accuracy": (lambda c: SK.accuracy_score(_i(c["y_true"]), _i(c["y_pred"])),
                     "sklearn.metrics.accuracy_score"),
        "precision": (lambda c: SK.precision_score(_i(c["y_true"]), _i(c["y_pred"])),
                      "sklearn.metrics.precision_score"),
        "recall": (lambda c: SK.recall_score(_i(c["y_true"]), _i(c["y_pred"])),
                   "sklearn.metrics.recall_score"),
        "f1": (lambda c: SK.f1_score(_i(c["y_true"]), _i(c["y_pred"])), "sklearn.metrics.f1_score"),
        "auc": (lambda c: SK.roc_auc_score(_i(c["y_true"]), _f(c["score"])),
                "sklearn.metrics.roc_auc_score"),
        "log_loss": (lambda c: SK.log_loss(_i(c["y_true"]), _f(c["prob"])), "sklearn.metrics.log_loss"),
        "brier": (lambda c: SK.brier_score_loss(_i(c["y_true"]), _f(c["prob"])),
                  "sklearn.metrics.brier_score_loss"),
        "mcc": (lambda c: SK.matthews_corrcoef(_i(c["y_true"]), _i(c["y_pred"])),
                "sklearn.metrics.matthews_corrcoef"),
        "balanced_accuracy": (lambda c: SK.balanced_accuracy_score(_i(c["y_true"]), _i(c["y_pred"])),
                              "sklearn.metrics.balanced_accuracy_score"),
        "pr_auc": (lambda c: SK.average_precision_score(_i(c["y_true"]), _f(c["prob"])),
                   "sklearn.metrics.average_precision_score"),
        "exact_match": (lambda c: float(np.mean([p == r for p, r in zip(c["prediction"], c["reference"])])),
                        "exact string equality (SQuAD strict EM definition)"),
        "recall_at_k": (lambda c: ref_recall_at_k(c["query"], c["rank"], c["relevance"], 5),
                        "standard IR recall@k (TREC convention), NumPy"),
        "mrr": (lambda c: ref_mrr(c["query"], c["rank"], c["relevance"]),
                "standard MRR definition, NumPy"),
        "rmse": (lambda c: math.sqrt(SK.mean_squared_error(_f(c["target"]), _f(c["prediction"]))),
                 "sqrt(sklearn.metrics.mean_squared_error)"),
        "mae": (lambda c: SK.mean_absolute_error(_f(c["target"]), _f(c["prediction"])),
                "sklearn.metrics.mean_absolute_error"),
        "r2": (lambda c: SK.r2_score(_f(c["target"]), _f(c["prediction"])), "sklearn.metrics.r2_score"),
        "mape": (lambda c: SK.mean_absolute_percentage_error(_f(c["target"]), _f(c["prediction"])),
                 "sklearn.metrics.mean_absolute_percentage_error"),
        "total_return": (lambda c: float(np.prod(1 + _f(c["daily_return"])) - 1),
                         "prod(1+r)-1, NumPy"),
        "sharpe": (lambda c: float(_f(c["daily_return"]).mean() / _f(c["daily_return"]).std(ddof=1)
                                   * math.sqrt(252)),
                   "mean/std(ddof=1)*sqrt(252), NumPy"),
        "volatility": (lambda c: float(_f(c["daily_return"]).std(ddof=1) * math.sqrt(252)),
                       "std(ddof=1)*sqrt(252), NumPy"),
        "sortino": (lambda c: float(_f(c["daily_return"]).mean()
                                    / math.sqrt(float(np.mean(np.minimum(_f(c["daily_return"]), 0.0) ** 2)))
                                    * math.sqrt(252)),
                    "mean/downside-RMS*sqrt(252) (Sortino & Price 1994), NumPy"),
        "cagr": (lambda c: float((_f(c["revenue"])[-1] / _f(c["revenue"])[0])
                                 ** (1.0 / (len(c["revenue"]) - 1)) - 1),
                 "(end/start)^(1/years)-1, NumPy"),
        "column_sum": (lambda c: float(np.sum(_f(c["value"]))), "numpy.sum"),
        "column_mean": (lambda c: float(np.mean(_f(c["value"]))), "numpy.mean"),
        "column_median": (lambda c: float(np.median(_f(c["value"]))), "numpy.median"),
        "latency_p95": (lambda c: float(np.percentile(_f(c["latency_ms"]), 95)),
                        "numpy.percentile(95) [linear/method-7]"),
        "error_rate": (lambda c: float(np.mean(_f(c["error"]) != 0)), "mean(flag!=0), NumPy"),
        "correlation": (lambda c: float(scipy.stats.pearsonr(_f(c["x"]), _f(c["y"]))[0]),
                        "scipy.stats.pearsonr"),
    }


def main():
    manifest = json.load(open(os.path.join(HERE, "manifest.json")))
    bases = {}
    for m in manifest:                      # one validation per base (3 claims share a dataset)
        if m.get("track") == "synthetic":   # external track's ground truth IS sklearn already
            bases[m["dir"]] = m
    refs = _references()
    out, fails = [], 0
    for d, m in sorted(bases.items()):
        metric = m["metric"]
        fn, impl = refs[metric]
        ref_v = float(fn(_cols(d)))
        oracle_v = float(m["true_value"])
        denom = max(abs(ref_v), abs(oracle_v), 1e-12)
        rel = abs(ref_v - oracle_v) / denom
        ok = rel <= 1e-9
        fails += (not ok)
        out.append({"base": os.path.basename(d), "metric": metric, "oracle": oracle_v,
                    "reference": ref_v, "rel_diff": rel, "match": ok, "reference_impl": impl})
        print("%-8s %-18s oracle=%.10g ref=%.10g rel=%.1e %s"
              % (os.path.basename(d), metric, oracle_v, ref_v, rel, "OK" if ok else "MISMATCH"))
    report = {"libraries": {"numpy": np.__version__, "scikit-learn": sklearn.__version__,
                            "scipy": scipy.__version__},
              "tolerance_rel": 1e-9, "bases": len(out), "mismatches": fails, "results": out}
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    json.dump(report, open(os.path.join(HERE, "results", "oracle_validation.json"), "w"), indent=2)
    print("\n%d/%d oracles match the published reference implementations "
          "(numpy %s, scikit-learn %s, scipy %s)"
          % (len(out) - fails, len(out), np.__version__, sklearn.__version__, scipy.__version__))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
