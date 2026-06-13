"""External-benchmark track: real models on RECOGNIZED benchmark datasets, plus real-world repos.

Track "external": classic UCI-provenance benchmark datasets that ship with scikit-learn —
Breast Cancer Wisconsin (Diagnostic), Optical Recognition of Handwritten Digits, Wine, and the
Diabetes regression benchmark (Efron et al. 2004) — with REAL scikit-learn models producing
out-of-fold predictions (5-fold cross_val_predict, fixed seeds). Ground truth = scikit-learn's own
metric on those predictions (the canonical implementation, version recorded). Predictions are frozen
to CSV with a pure-stdlib re-emitting entrypoint (the vendored-snapshot pattern), so verification is
hermetic and needs no sklearn at verify time. Each base gets honest / obvious / subtle claims.

Track "realworld": the repo's real cases, with citable provenance —
  * the civil-war RF leakage replication (a PUBLISHED academic-correction case: reported AUC ~0.97,
    leakage-corrected ~0.91), claim = the published inflated number;
  * the real BTC overfit backtest (claimed +14,698%, recomputes to -32.4%);
  * two vendored real GitHub repos (sh-mukherjee/momentum-strategy, HilmiSamdya/btc-sma-backtest)
    with their honest committed numbers.

Models are deliberately feature-restricted / regularized so metrics land mid-range (0.6-0.93) -
realistic model-card numbers where a subtle inflation is plausible (and statistically refutable
at these n). Run INSIDE the bench venv (numpy + scikit-learn):
  /tmp/calma_bench_venv/bin/python benchmark/external_track.py
Appends to benchmark/manifest.json (idempotent: drops prior external/realworld entries first).
"""
import json
import math
import os
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import sklearn
from sklearn import metrics as SK
from sklearn.datasets import load_breast_cancer, load_diabetes, load_digits, load_wine
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.model_selection import cross_val_predict
from sklearn.naive_bayes import GaussianNB
from sklearn.tree import DecisionTreeClassifier

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = os.path.join(HERE, "cases_external")
REPO = os.path.realpath(os.path.join(HERE, ".."))

# the same shading directions as the synthetic track (gen_corpus.py)
LOWER_IS_BETTER = {"rmse", "mae"}
UNIT_RANGE = {"accuracy", "auc", "f1", "balanced_accuracy", "macro_f1", "r2"}


def _flawed(metric, v):
    if metric in LOWER_IS_BETTER:
        return round(v * 0.55, 4)
    if metric in UNIT_RANGE:
        return round(min(0.999, v + 0.12), 4)
    return round(v * 1.4, 4)


def _subtle(metric, v):
    if metric in LOWER_IS_BETTER:
        return round(v * 0.90, 4)
    if metric in UNIT_RANGE:
        return round(min(0.999, v + 0.05), 4)
    return round(v * 1.04, 4)


_REEMIT = '''import os, shutil
os.makedirs("runs", exist_ok=True)
shutil.copy(os.path.join("data", "%s"), os.path.join("runs", "%s"))
'''


def _freeze(cid, fname, header, rows):
    d = os.path.join(CASES, cid)
    os.makedirs(os.path.join(d, "data"), exist_ok=True)
    os.makedirs(os.path.join(d, "runs"), exist_ok=True)
    body = ",".join(header) + "\n" + "\n".join(",".join(str(x) for x in r) for r in rows) + "\n"
    for sub in ("data", "runs"):
        with open(os.path.join(d, sub, fname), "w") as f:
            f.write(body)
    with open(os.path.join(d, "gen.py"), "w") as f:
        f.write(_REEMIT % (fname, fname))
    return d


def _band_ok(p, n, gap):
    """For proportion-like metrics: the subtle gap must clear the 95% sampling band, or the case
    would be statistically indistinguishable (calma would CORRECTLY decline to refute it)."""
    se = math.sqrt(max(p * (1 - p), 1e-9) / n)
    return gap > 1.96 * se * 1.15        # 15% headroom


def _externals():
    out = []
    # --- Breast Cancer Wisconsin (Diagnostic), UCI via sklearn ---
    X, y = load_breast_cancer(return_X_y=True)
    # feature-restricted weak learners -> mid-range, realistic model-card numbers
    yp = cross_val_predict(DecisionTreeClassifier(max_depth=2, random_state=0), X[:, :2], y, cv=5)
    out.append(("ext_bc_acc", "accuracy", "classification", "Breast Cancer Wisconsin (UCI)",
                "DecisionTree(depth=2, 2 features)", "accuracy %s",
                _freeze("ext_bc_acc", "preds.csv", ["y_true", "y_pred"], list(zip(y, yp))),
                "runs/preds.csv", float(SK.accuracy_score(y, yp)), len(y)))
    out.append(("ext_bc_f1", "f1", "classification", "Breast Cancer Wisconsin (UCI)",
                "DecisionTree(depth=2, 2 features)", "f1 %s",
                _freeze("ext_bc_f1", "preds.csv", ["y_true", "y_pred"], list(zip(y, yp))),
                "runs/preds.csv", float(SK.f1_score(y, yp)), len(y)))
    prob = cross_val_predict(GaussianNB(), X[:, :2], y, cv=5, method="predict_proba")[:, 1]
    out.append(("ext_bc_auc", "auc", "classification", "Breast Cancer Wisconsin (UCI)",
                "GaussianNB(2 features)", "auc %s",
                _freeze("ext_bc_auc", "preds.csv", ["y_true", "score"],
                        [(int(a), round(float(b), 9)) for a, b in zip(y, prob)]),
                "runs/preds.csv", float(SK.roc_auc_score(y, prob)), len(y)))

    # --- Optical digits (UCI), multiclass ---
    Xd, yd = load_digits(return_X_y=True)
    ypd = cross_val_predict(LogisticRegression(max_iter=2000, C=0.05, random_state=0),
                            Xd[:, :32], yd, cv=5)
    out.append(("ext_dg_acc", "accuracy", "classification",
                "Optical Handwritten Digits (UCI)", "LogisticRegression(C=0.05, 32 of 64 px)",
                "accuracy %s",
                _freeze("ext_dg_acc", "preds.csv", ["y_true", "y_pred"], list(zip(yd, ypd))),
                "runs/preds.csv", float(SK.accuracy_score(yd, ypd)), len(yd)))
    out.append(("ext_dg_bacc", "balanced_accuracy", "classification",
                "Optical Handwritten Digits (UCI)", "LogisticRegression(C=0.05, 32 of 64 px)",
                "balanced accuracy %s",
                _freeze("ext_dg_bacc", "preds.csv", ["y_true", "y_pred"], list(zip(yd, ypd))),
                "runs/preds.csv", float(SK.balanced_accuracy_score(yd, ypd)), len(yd)))
    out.append(("ext_dg_mf1", "macro_f1", "classification",
                "Optical Handwritten Digits (UCI)", "LogisticRegression(C=0.05, 32 of 64 px)",
                "macro f1 %s",
                _freeze("ext_dg_mf1", "preds.csv", ["y_true", "y_pred"], list(zip(yd, ypd))),
                "runs/preds.csv", float(SK.f1_score(yd, ypd, average="macro")), len(yd)))

    # --- Wine (UCI), multiclass ---
    Xw, yw = load_wine(return_X_y=True)
    ypw = cross_val_predict(DecisionTreeClassifier(max_depth=2, random_state=0), Xw[:, :4], yw, cv=5)
    out.append(("ext_wn_acc", "accuracy", "classification", "Wine (UCI)",
                "DecisionTree(depth=2, 4 features)", "accuracy %s",
                _freeze("ext_wn_acc", "preds.csv", ["y_true", "y_pred"], list(zip(yw, ypw))),
                "runs/preds.csv", float(SK.accuracy_score(yw, ypw)), len(yw)))

    # --- Diabetes regression (Efron et al. 2004) ---
    Xb, yb = load_diabetes(return_X_y=True)
    ypb = cross_val_predict(Ridge(alpha=1.0, random_state=0), Xb, yb, cv=5)
    rows = [(round(float(a), 6), round(float(b), 6)) for a, b in zip(yb, ypb)]
    for cid, metric, true_v, fmt in (
            ("ext_db_rmse", "rmse", math.sqrt(SK.mean_squared_error(yb, ypb)), "rmse %s"),
            ("ext_db_mae", "mae", SK.mean_absolute_error(yb, ypb), "mae %s"),
            ("ext_db_r2", "r2", SK.r2_score(yb, ypb), "r2 %s")):
        out.append((cid, metric, "regression", "Diabetes (Efron et al. 2004)", "Ridge(alpha=1)",
                    fmt, _freeze(cid, "reg.csv", ["target", "prediction"], rows),
                    "runs/reg.csv", float(true_v), len(yb)))
    return out


def _realworld():
    """The repo's real cases (citable provenance). dir/claim/metric reference the committed fixtures."""
    A = os.path.join(REPO, ".claude", "skills", "calma", "assets")
    return [
        {"id": "rw_leakage", "dir": os.path.join(A, "leakage"), "metric": "auc",
         "family": "classification", "display": "auc (published leakage case)",
         "artifact": "runs/preds_holdout.csv", "n_rows": 4000,
         "claim": 0.97, "claim_text": "auc 0.97", "label": "flawed", "tier": "realworld",
         "provenance": "civil-war RF leakage replication - published correction: AUC ~0.97 -> ~0.91"},
        {"id": "rw_btc", "dir": os.path.join(A, "btc"), "metric": "total_return",
         "family": "quant", "display": "total return (real overfit backtest)",
         "artifact": "runs/oos/returns.csv", "n_rows": 1250,
         "claim": 146.98, "claim_text": "+14,698%", "label": "flawed", "tier": "realworld",
         "provenance": "real BTC backtest that claimed +14,698%; recomputes to -32.4% out-of-sample"},
        {"id": "rw_momentum", "dir": os.path.join(A, "corpus", "momentum-strategy"),
         "metric": "total_return", "family": "quant",
         "display": "total return (real GitHub repo)", "artifact": "runs/returns.csv",
         "n_rows": 2607, "claim": -0.0276, "claim_text": "total return -2.76%",
         "label": "honest", "tier": "realworld",
         "provenance": "sh-mukherjee/momentum-strategy (MIT), 2015-2024, vendored snapshot"},
        {"id": "rw_btcsma", "dir": os.path.join(A, "corpus", "btc-sma-crossover"),
         "metric": "column_sum", "family": "quant",
         "display": "total profit (real GitHub repo)", "artifact": "runs/trades.csv",
         "n_rows": 42, "claim": 19024.77, "claim_text": "total profit 19024.77",
         "label": "honest", "tier": "realworld",
         "provenance": "HilmiSamdya/btc-sma-backtest (MIT) on Coinbase BTC-USD via record/replay"},
    ]


def main():
    import shutil
    shutil.rmtree(CASES, ignore_errors=True)
    manifest = [m for m in json.load(open(os.path.join(HERE, "manifest.json")))
                if m.get("track") == "synthetic"]
    for cid, metric, family, dataset, model, fmt, d, artifact, true_v, n in _externals():
        tiers = [("honest", "honest", round(true_v, 4)),
                 ("flawed", "obvious", _flawed(metric, true_v)),
                 ("flawed", "subtle", _subtle(metric, true_v))]
        if metric in UNIT_RANGE:
            # proportion-like metrics want mid-range values; r2 is not a proportion (the canonical
            # Diabetes linear-model r2 is ~0.42-0.5 - a citable, realistic value)
            lo = 0.2 if metric == "r2" else 0.55
            assert lo <= true_v <= 0.95, "%s landed %.3f - retune the model" % (cid, true_v)
            if metric != "r2" and not _band_ok(true_v, n, 0.05):
                # small-n dataset: a +0.05 lie sits INSIDE the 95% sampling band - statistically
                # unverifiable, so a refusal to refute would be CORRECT. Keep honest+obvious only
                # (documented in the README as the honest small-sample limit).
                tiers = tiers[:2]
                print("  %-12s subtle tier dropped (n=%d: +0.05 inside sampling band)" % (cid, n))
        for label, tier, claim in tiers:
            manifest.append({"id": "%s_%s" % (cid, tier), "dir": d, "metric": metric,
                             "family": family, "display": metric, "n_rows": n,
                             "artifact": artifact, "track": "external",
                             "dataset": dataset, "model": model,
                             "sklearn_version": sklearn.__version__,
                             "true_value": true_v, "claim": claim, "claim_text": fmt % claim,
                             "label": label, "tier": tier})
        print("  %-12s %-18s %-38s true=%.6g (n=%d)" % (cid, metric, dataset, true_v, n))
    for m in _realworld():
        m["track"] = "realworld"
        m.setdefault("true_value", None)
        manifest.append(m)
        print("  %-12s %-18s %s" % (m["id"], m["metric"], m["provenance"][:58]))
    json.dump(manifest, open(os.path.join(HERE, "manifest.json"), "w"), indent=2)
    tr = {}
    for m in manifest:
        tr[m["track"]] = tr.get(m["track"], 0) + 1
    print("manifest: %d cases %s (numpy %s, scikit-learn %s)"
          % (len(manifest), tr, np.__version__, sklearn.__version__))


if __name__ == "__main__":
    main()
