"""calma.spike.core.artifacts — recompute a claim directly from COMMITTED predictions, no re-run.

Many research repos ship the raw per-example outputs (a `predictions.csv` with y_true / y_pred / y_score
columns, or per-fold preds). When they do, Calma doesn't need to rebuild the environment, fetch the data,
or re-run the model — it recomputes the headline metric **straight from the committed arrays** and diffs
against the claim. This is the cheapest verification path (pure arithmetic, $0) and it makes data-heavy
repos verifiable without their data (rebuild guide §4: recompute from the raw outputs).

It's a two-way diff (claimed vs independent-recompute-from-committed-data) — there is no runtime "produced"
value because we didn't execute. Match → CONFIRMED (from committed predictions); mismatch → REFUTED.
"""
from __future__ import annotations

import csv
import os

# CSV column name → the canonical input role it fills (first match wins)
_COL_ROLES = {
    "y_true": ["y_true", "ytrue", "label", "labels", "target", "targets", "actual", "truth", "gold", "gt", "y"],
    "y_pred": ["y_pred", "ypred", "prediction", "predictions", "pred", "preds", "yhat", "predicted", "output"],
    "y_score": ["y_score", "yscore", "score", "scores", "prob", "proba", "probability", "y_prob", "confidence"],
}
_PRED_FILE_HINTS = ("pred", "result", "output", "score", "eval", "test")
_MAX_ROWS = 5_000_000


def _role_of(col: str):
    c = col.strip().lower().replace(" ", "_")
    for role, names in _COL_ROLES.items():
        if c in names:
            return role
    return None


def read_prediction_csv(path):
    """Return {role: [values]} for a CSV whose columns map to y_true/y_pred/y_score, else None."""
    try:
        with open(path, newline="", errors="replace") as fh:
            rd = csv.DictReader(fh)
            header = rd.fieldnames or []
            roles = {}
            for col in header:
                role = _role_of(col)
                if role and role not in roles:
                    roles[role] = col
            if "y_true" not in roles or not ({"y_pred", "y_score"} & set(roles)):
                return None                       # need labels + (predictions or scores)
            cols = {r: [] for r in roles}
            for i, row in enumerate(rd):
                if i >= _MAX_ROWS:
                    break
                for r, col in roles.items():
                    cols[r].append(row.get(col, ""))
        return {r: _numify(v) for r, v in cols.items()}
    except (OSError, csv.Error):
        return None


def _numify(vals):
    out = []
    for v in vals:
        v = (v or "").strip()
        try:
            f = float(v)
            out.append(int(f) if f.is_integer() else f)
        except ValueError:
            out.append(v)
    return out


def find_prediction_files(repo_dir, limit=12):
    """CSV files (top-level + one level under results/output dirs) that look like committed predictions."""
    found = []
    roots = [repo_dir] + [os.path.join(repo_dir, d) for d in ("results", "output", "outputs", "predictions",
                                                               "preds", "data")]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for fn in sorted(os.listdir(root)):
            if not fn.lower().endswith(".csv"):
                continue
            p = os.path.join(root, fn)
            if not os.path.isfile(p):
                continue
            cols = read_prediction_csv(p)
            if cols:
                found.append((p, cols))
                if len(found) >= limit:
                    return found
    return found


def recompute_from_cols(cols, metric, resolver):
    """Recompute `metric` from one prediction file's columns. `resolver` is recompute_any (catalog →
    recipes → store → synth). Returns a Result or None."""
    inputs = dict(cols)
    # map y_score↔y_pred for metrics that want the other (roc_auc wants y_score, accuracy y_pred)
    if "y_pred" not in inputs and "y_score" in inputs:
        inputs["y_pred"] = inputs["y_score"]
    if "y_score" not in inputs and "y_pred" in inputs:
        inputs["y_score"] = inputs["y_pred"]
    res = resolver(metric, inputs, {})
    return res if (res and not res.get("degenerate")) else None


def recompute_from_artifacts(repo_dir, metric, resolver):
    """Try to recompute `metric` from any committed prediction file. Returns (Result, filename) or None."""
    for path, cols in find_prediction_files(repo_dir):
        res = recompute_from_cols(cols, metric, resolver)
        if res:
            return res, os.path.basename(path)
    return None
