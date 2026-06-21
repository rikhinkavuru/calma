"""T2 (real offline evidence): FRAMEWORK REFERENCE VECTORS.

The deferred "framework-generated reference vectors" arm needed backtrader/vectorbt/zipline/pytorch/
xgboost installed, so offline it was scaffolding. This turns it into a STANDING oracle that runs every
build with zero heavy deps, using the golden-vector pattern (cf. FIPS / codec test vectors):

  1. Each vector is a FIXED tiny artifact + the headline value the framework computes for it BY ITS
     DOCUMENTED FORMULA (e.g. sklearn.metrics.roc_auc_score). That value is frozen in reference_vectors/
     vectors.json with the exact framework function it mirrors.
  2. OFFLINE (default, every build): Calma's own recompute engine (recompute.recompute_contract - pure,
     no sandbox) reproduces each frozen value, asserted to <= 1e-9. The frozen value is ALSO re-derived
     by an INDEPENDENT pure-python reference (a DIFFERENT algorithm than Calma's recipe - e.g. AUC via
     the Mann-Whitney rank sum, not trapezoidal ROC) so the offline check is a genuine cross-engine
     agreement, not Calma grading its own homework.
  3. --check-live (the gated CI job, frameworks installed): each frozen value is recomputed with the REAL
     framework (import sklearn / xgboost / ...) and asserted == the frozen value to <= 1e-9. A framework
     that isn't importable is SKIPPED out loud, never a silent pass.

So offline gives:  Calma == frozen-golden == independent-reference.
And the gate adds: frozen-golden == live-framework.
Transitively, every build proves Calma reproduces the live framework's number to floating-point noise.

Run:
  python3 benchmark/gen_framework_vectors.py                 # offline: Calma == golden == independent ref
  python3 benchmark/gen_framework_vectors.py --check-live    # also: golden == the real installed framework
  python3 benchmark/gen_framework_vectors.py --freeze        # re-derive + rewrite reference_vectors/vectors.json
"""
import argparse
import json
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(HERE, "..", ".claude", "skills", "calma", "scripts")
sys.path.insert(0, SKILL)
import recompute as RC  # noqa: E402  Calma's own pure recompute (reads the artifact, runs the recipe)

TOL = 1e-9
VECTORS_JSON = os.path.join(HERE, "reference_vectors", "vectors.json")


# ---- independent pure-python references (a DIFFERENT implementation than Calma's recipe) -------------
# These are the framework's documented formulas, written from scratch here so "Calma == this" is a real
# second-engine agreement. Where Calma likely uses one algorithm we deliberately use another (AUC: rank
# sum, not ROC trapezoid).

def _ref_accuracy(c):
    yt, yp = c["y_true"], c["y_pred"]
    return sum(1 for a, b in zip(yt, yp) if a == b) / len(yt)


def _ref_f1(c):
    yt, yp = c["y_true"], c["y_pred"]
    tp = sum(1 for a, b in zip(yt, yp) if a == 1 and b == 1)
    fp = sum(1 for a, b in zip(yt, yp) if a == 0 and b == 1)
    fn = sum(1 for a, b in zip(yt, yp) if a == 1 and b == 0)
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    return 2 * p * r / (p + r) if (p + r) else 0.0


def _ref_mcc(c):
    yt, yp = c["y_true"], c["y_pred"]
    tp = sum(1 for a, b in zip(yt, yp) if a == 1 and b == 1)
    tn = sum(1 for a, b in zip(yt, yp) if a == 0 and b == 0)
    fp = sum(1 for a, b in zip(yt, yp) if a == 0 and b == 1)
    fn = sum(1 for a, b in zip(yt, yp) if a == 1 and b == 0)
    denom = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    return (tp * tn - fp * fn) / denom if denom else 0.0


def _ref_auc(c):
    # Mann-Whitney U / rank-sum (DIFFERENT algorithm than a trapezoidal ROC integral). Average ranks
    # handle ties; our vectors use distinct scores so all definitions coincide exactly.
    yt, sc = c["y_true"], c["score"]
    n = len(sc)
    order = sorted(range(n), key=lambda i: sc[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n and sc[order[j]] == sc[order[i]]:
            j += 1
        avg = (i + 1 + j) / 2.0  # mean of 1-based ranks i+1..j
        for k in range(i, j):
            ranks[order[k]] = avg
        i = j
    npos = sum(1 for y in yt if y == 1)
    nneg = n - npos
    sumr = sum(ranks[i] for i in range(n) if yt[i] == 1)
    return (sumr - npos * (npos + 1) / 2.0) / (npos * nneg)


def _ref_r2(c):
    t, p = c["target"], c["prediction"]
    tb = sum(t) / len(t)
    ssr = sum((a - b) ** 2 for a, b in zip(t, p))
    sst = sum((a - tb) ** 2 for a in t)
    return 1 - ssr / sst


def _ref_rmse(c):
    t, p = c["target"], c["prediction"]
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(t, p)) / len(t))


def _ref_mae(c):
    t, p = c["target"], c["prediction"]
    return sum(abs(a - b) for a, b in zip(t, p)) / len(t)


def _ref_log_loss(c, eps=1e-15):
    yt, pr = c["y_true"], c["prob"]
    s = 0.0
    for y, p in zip(yt, pr):
        p = min(max(p, eps), 1 - eps)
        s += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return s / len(yt)


def _ref_brier(c):
    yt, pr = c["y_true"], c["prob"]
    return sum((p - y) ** 2 for y, p in zip(yt, pr)) / len(yt)


def _ref_total_return(c):
    acc = 1.0
    for x in c["return"]:
        acc *= (1 + x)
    return acc - 1


# ---- live-framework references (only run under --check-live, when the framework imports) -------------

def _live_sklearn(metric):
    """Return a fn(cols)->value using the REAL installed framework, or None if it can't import."""
    try:
        import sklearn.metrics as M  # noqa: F401
    except Exception:
        return None
    fns = {
        "accuracy": lambda c: M.accuracy_score(c["y_true"], c["y_pred"]),
        "f1": lambda c: M.f1_score(c["y_true"], c["y_pred"]),
        "mcc": lambda c: M.matthews_corrcoef(c["y_true"], c["y_pred"]),
        "auc": lambda c: M.roc_auc_score(c["y_true"], c["score"]),
        "r2": lambda c: M.r2_score(c["target"], c["prediction"]),
        "rmse": lambda c: M.root_mean_squared_error(c["target"], c["prediction"]),
        "mae": lambda c: M.mean_absolute_error(c["target"], c["prediction"]),
        "log_loss": lambda c: M.log_loss(c["y_true"], c["prob"], labels=[0, 1]),
        "brier": lambda c: M.brier_score_loss(c["y_true"], c["prob"]),
    }
    return fns.get(metric)


def _live_quant(metric):
    """total_return is what backtrader/vectorbt/zipline report as the headline; the framework-agnostic
    closed form is prod(1+r)-1. (numpy gives an independent reduction order from the pure-python ref.)"""
    if metric != "total_return":
        return None
    try:
        import numpy as np
    except Exception:
        return None
    return lambda c: float(np.prod(1.0 + np.asarray(c["return"], dtype=float)) - 1.0)


# ---- the vectors: fixed data + which Calma recipe + the framework function it mirrors -----------------
# convention=None for accuracy/f1/mcc: the columns are already class LABELS (not a logit matrix), so no
# argmax is needed - this is exactly how a framework user scores y_true vs y_pred labels.
VECTORS = [
    {"name": "sklearn_accuracy", "framework": "sklearn", "metric_id": "accuracy",
     "framework_fn": "sklearn.metrics.accuracy_score",
     "binding": {"label": "y_true", "prediction": "y_pred"},
     "cols": {"y_true": [1, 0, 1, 1, 0, 1, 0, 0, 1, 1, 0, 1],
              "y_pred": [1, 0, 0, 1, 0, 1, 1, 0, 1, 1, 0, 1]},
     "ref": _ref_accuracy, "live": lambda: _live_sklearn("accuracy")},
    {"name": "sklearn_f1", "framework": "sklearn", "metric_id": "f1",
     "framework_fn": "sklearn.metrics.f1_score (binary, pos_label=1)",
     "binding": {"prediction": "y_pred", "label": "y_true"},
     "cols": {"y_true": [1, 0, 1, 1, 0, 1, 0, 0, 1, 1, 0, 1],
              "y_pred": [1, 0, 0, 1, 0, 1, 1, 0, 1, 1, 0, 1]},
     "ref": _ref_f1, "live": lambda: _live_sklearn("f1")},
    {"name": "sklearn_mcc", "framework": "sklearn", "metric_id": "mcc",
     "framework_fn": "sklearn.metrics.matthews_corrcoef",
     "binding": {"prediction": "y_pred", "label": "y_true"},
     "cols": {"y_true": [1, 0, 1, 1, 0, 1, 0, 0, 1, 1, 0, 1],
              "y_pred": [1, 0, 0, 1, 0, 1, 1, 0, 1, 1, 0, 1]},
     "ref": _ref_mcc, "live": lambda: _live_sklearn("mcc")},
    {"name": "sklearn_roc_auc", "framework": "sklearn", "metric_id": "auc",
     "framework_fn": "sklearn.metrics.roc_auc_score",
     "binding": {"label": "y_true", "score": "score"},
     "cols": {"y_true": [0, 0, 0, 1, 0, 1, 1, 0, 1, 1],
              "score": [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.95]},
     "ref": _ref_auc, "live": lambda: _live_sklearn("auc")},
    {"name": "sklearn_r2", "framework": "sklearn", "metric_id": "r2",
     "framework_fn": "sklearn.metrics.r2_score",
     "binding": {"prediction": "prediction", "target": "target"},
     "cols": {"target": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
              "prediction": [1.2, 1.8, 3.5, 3.9, 5.5, 5.8, 7.2, 8.4]},
     "ref": _ref_r2, "live": lambda: _live_sklearn("r2")},
    {"name": "sklearn_rmse", "framework": "sklearn", "metric_id": "rmse",
     "framework_fn": "sklearn.metrics.root_mean_squared_error",
     "binding": {"prediction": "prediction", "target": "target"},
     "cols": {"target": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
              "prediction": [1.2, 1.8, 3.5, 3.9, 5.5, 5.8, 7.2, 8.4]},
     "ref": _ref_rmse, "live": lambda: _live_sklearn("rmse")},
    {"name": "sklearn_mae", "framework": "sklearn", "metric_id": "mae",
     "framework_fn": "sklearn.metrics.mean_absolute_error",
     "binding": {"prediction": "prediction", "target": "target"},
     "cols": {"target": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
              "prediction": [1.2, 1.8, 3.5, 3.9, 5.5, 5.8, 7.2, 8.4]},
     "ref": _ref_mae, "live": lambda: _live_sklearn("mae")},
    {"name": "sklearn_log_loss", "framework": "sklearn", "metric_id": "log_loss",
     "framework_fn": "sklearn.metrics.log_loss",
     "binding": {"prob": "prob", "label": "y_true"},
     "cols": {"y_true": [1, 0, 1, 0, 1, 0, 1, 0],
              "prob": [0.8, 0.3, 0.6, 0.2, 0.9, 0.4, 0.7, 0.1]},
     "ref": _ref_log_loss, "live": lambda: _live_sklearn("log_loss")},
    {"name": "sklearn_brier", "framework": "sklearn", "metric_id": "brier",
     "framework_fn": "sklearn.metrics.brier_score_loss",
     "binding": {"prob": "prob", "label": "y_true"},
     "cols": {"y_true": [1, 0, 1, 0, 1, 0, 1, 0],
              "prob": [0.8, 0.3, 0.6, 0.2, 0.9, 0.4, 0.7, 0.1]},
     "ref": _ref_brier, "live": lambda: _live_sklearn("brier")},
    {"name": "quant_total_return", "framework": "backtrader/vectorbt/zipline", "metric_id": "total_return",
     "framework_fn": "compounded simple return prod(1+r)-1 (the headline all three report)",
     "binding": {"return": "return"},
     "cols": {"return": [0.10, -0.05, 0.20, 0.00, 0.05]},
     "ref": _ref_total_return, "live": lambda: _live_quant("total_return")},
]


def _materialize(v, d):
    """Write the vector's artifact CSV + a minimal contract into dir `d`; return the contract path."""
    cols = v["cols"]
    names = list(cols)
    n = len(cols[names[0]])
    art = os.path.join(d, "data.csv")
    with open(art, "w", newline="") as f:
        f.write(",".join(names) + "\n")
        for i in range(n):
            f.write(",".join(repr(cols[c][i]) if isinstance(cols[c][i], float) else str(cols[c][i])
                              for c in names) + "\n")
    metric = {"metric_id": v["metric_id"], "artifact": "data.csv", "binding": v["binding"],
              "headline": True}
    if v.get("convention"):
        metric["convention"] = v["convention"]
    contract = {"run": {"entrypoint": "data.csv", "network": "off"}, "env": {"ecosystem": "python"},
                "artifacts": [{"path": "data.csv", "columns": {c: {} for c in names}}],
                "metrics": [metric]}
    cpath = os.path.join(d, "verify.json")
    json.dump(contract, open(cpath, "w"))
    return cpath


def _calma_recompute(v):
    """Calma's own recompute of the vector's headline metric (pure, no sandbox)."""
    d = tempfile.mkdtemp(prefix="calma_fv_")
    cpath = _materialize(v, d)
    out = RC.recompute_contract(cpath, base=d)
    m = out["metrics"][0]
    return m


def run(check_live=False, freeze=False):
    frozen = {}
    if os.path.exists(VECTORS_JSON):
        frozen = {r["name"]: r for r in json.load(open(VECTORS_JSON)).get("vectors", [])}
    results, n_fail, n_skip_live = [], 0, 0
    print("%-22s %-12s %14s %14s  %s" % ("vector", "metric", "calma", "golden", "status"))
    print("-" * 92)
    for v in VECTORS:
        ref_val = float(v["ref"](v["cols"]))               # the independent pure-python reference
        m = _calma_recompute(v)
        calma_val = m.get("value")
        degen = m.get("degenerate")
        ok_calma = (not degen) and isinstance(calma_val, float) and abs(calma_val - ref_val) <= TOL
        status = "ok" if ok_calma else ("DEGENERATE: %s" % m.get("error", "?") if degen else "MISMATCH")

        # the frozen golden (committed) must equal the independent reference, unless we're (re)freezing
        if not freeze and v["name"] in frozen:
            gv = frozen[v["name"]]["value"]
            if abs(gv - ref_val) > TOL:
                status += " | FROZEN-GOLDEN-DRIFT (vectors.json=%s ref=%s)" % (gv, ref_val)
                ok_calma = False

        live_val = None
        if check_live:
            live_fn = v["live"]()
            if live_fn is None:
                n_skip_live += 1
                status += " | live SKIP (%s not importable)" % v["framework"].split("/")[0]
            else:
                live_val = float(live_fn(v["cols"]))
                if abs(live_val - ref_val) > TOL:
                    status += " | LIVE MISMATCH (framework=%s golden=%s)" % (live_val, ref_val)
                    ok_calma = False
                else:
                    status += " | live==golden (%s)" % v["framework_fn"].split("(")[0].strip()

        if not ok_calma:
            n_fail += 1
        print("%-22s %-12s %14.10g %14.10g  %s" % (v["name"], v["metric_id"],
              calma_val if isinstance(calma_val, float) else float("nan"), ref_val, status))
        results.append({"name": v["name"], "framework": v["framework"], "metric_id": v["metric_id"],
                        "framework_fn": v["framework_fn"], "binding": v["binding"], "cols": v["cols"],
                        "value": ref_val, "calma": calma_val, "live": live_val})

    if freeze:
        os.makedirs(os.path.dirname(VECTORS_JSON), exist_ok=True)
        json.dump({"_note": "Frozen framework reference vectors. value = the framework's documented number "
                            "for this fixed artifact; every build asserts Calma's recompute reproduces it "
                            "to <=1e-9 (see gen_framework_vectors.py). Regenerate with --freeze.",
                   "tolerance": TOL,
                   "vectors": [{k: r[k] for k in ("name", "framework", "metric_id", "framework_fn",
                                                  "binding", "cols", "value")} for r in results]},
                  open(VECTORS_JSON, "w"), indent=2)
        print("\nfroze %d vectors -> %s" % (len(results), os.path.relpath(VECTORS_JSON, HERE)))

    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    json.dump(results, open(os.path.join(HERE, "results", "framework_vectors.json"), "w"), indent=2)
    print("-" * 92)
    tail = (" | %d live checks skipped (no framework installed - run in the gated CI job)" % n_skip_live
            if check_live and n_skip_live else "")
    print("%d/%d vectors: Calma reproduces the framework golden to <=%g%s"
          % (len(VECTORS) - n_fail, len(VECTORS), TOL, tail))
    return n_fail


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check-live", action="store_true",
                    help="also recompute each golden with the REAL framework (sklearn/numpy/...) and "
                         "assert golden==framework; SKIPs frameworks that aren't installed")
    ap.add_argument("--freeze", action="store_true", help="re-derive + rewrite reference_vectors/vectors.json")
    a = ap.parse_args()
    return 1 if run(check_live=a.check_live, freeze=a.freeze) else 0


if __name__ == "__main__":
    sys.exit(main())
