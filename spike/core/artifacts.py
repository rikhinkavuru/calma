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


# ── S4: subset-scoped binding — recompute a claim on the SUBSET of rows it's about ────────────────────────────
# A claim is often about a SUBSET ("sensitivity on the pfam-testable subset", "recall on rare variants"), not
# all rows. The unchanged recompute is the Judge; S4 only changes WHICH rows feed it, by deterministically
# binding a qualifier token in the claim's name to a real boolean column in the predictions file. A wrong bind
# → a wrong subset → a wrong number → REFUTED (never a silent all-rows CONFIRM of a scoped claim). The bind is
# grounded (a real column + a claim-named qualifier), so the false-confirm rate stays far under the 5% bar.
_BOOL_TRUE = {"1", "true", "t", "yes", "y", "pos", "positive"}
_BOOL_FALSE = {"0", "false", "f", "no", "n", "neg", "negative", ""}
# metric / split words are NOT subset qualifiers — strip them so only a genuine subset token ('testable') remains
_NON_QUALIFIER = {
    "sensitivity", "specificity", "recall", "precision", "accuracy", "acc", "auc", "auroc", "roc", "pr", "auprc",
    "ap", "f1", "fscore", "score", "tpr", "tnr", "fpr", "fnr", "mcc", "matthews", "brier", "kappa", "cohen",
    "rmse", "mae", "mse", "r2", "rsquared", "sharpe", "ndcg", "map", "mrr", "spearman", "pearson", "balanced",
    "macro", "micro", "weighted", "mean", "average", "avg", "median", "std", "overall", "total",
    "test", "testing", "val", "valid", "validation", "holdout", "heldout", "train", "training", "final", "the",
}


def _truthy(v) -> bool | None:
    """Whether a boolean-column cell is TRUE (in the subset), FALSE (out), or None (not boolean → not a scope)."""
    s = str(v).strip().lower()
    if s in _BOOL_TRUE:
        return True
    if s in _BOOL_FALSE:
        return False
    try:
        return float(s) != 0.0
    except ValueError:
        return None


def read_scoped(path):
    """Read a predictions CSV → (roles, scope_cols), row-aligned: ``roles`` = the y_true/y_pred/y_score arrays
    (as ``read_prediction_csv``), ``scope_cols`` = every BOOLEAN non-role column (name → per-row raw values) that
    could scope a subset. Boolean-only (clear truthy semantics → FCR-safe); returns None if not a predictions
    CSV. Reads roles + scope columns in ONE pass so the two are guaranteed aligned for the masked recompute."""
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
                return None
            role_cols = set(roles.values())
            cand = [c for c in header if c and c not in role_cols]         # non-role columns → possible scopes
            rcols = {r: [] for r in roles}
            scols = {c: [] for c in cand}
            n = 0
            for i, row in enumerate(rd):
                if i >= _MAX_ROWS:
                    break
                for r, col in roles.items():
                    rcols[r].append(row.get(col, ""))
                for c in cand:
                    scols[c].append(row.get(c, ""))
                n += 1
        # keep only columns that are genuinely boolean (every non-empty cell is truthy/falsy) and a PROPER,
        # non-trivial subset (not all-true, not all-false) — a boolean split, not an id/score column.
        scope_cols = {}
        for c, vals in scols.items():
            flags = [_truthy(v) for v in vals]
            if any(f is None for f in flags):
                continue
            trues = sum(1 for f in flags if f)
            if 0 < trues < n:                                              # a real split (some in, some out)
                scope_cols[c] = vals
        return {r: _numify(v) for r, v in rcols.items()}, scope_cols
    except (OSError, csv.Error):
        return None


def scope_qualifiers(text):
    """The candidate SUBSET-qualifier tokens of a claim's raw name/context — the tokens left after removing
    metric + split words ('homology_sensitivity_testable' → ['homology', 'testable'])."""
    import re  # noqa: PLC0415
    toks = re.split(r"[^a-z0-9]+", (text or "").lower())
    return [t for t in toks if len(t) >= 3 and t not in _NON_QUALIFIER and not t.isdigit()]


def bind_scope(qualifiers, scope_col_names):
    """Deterministically bind a claim qualifier to ONE boolean scope column (token ⊆ column name or vice versa).
    Returns the column name, or None if nothing matches OR the match is AMBIGUOUS (>1 distinct column) — we
    never guess between subsets, since a coincidental match on the wrong one is the only false-confirm path."""
    matched = set()
    for q in qualifiers:
        for col in scope_col_names:
            cl = col.lower()
            clc = cl.replace("_", "").replace("-", "")
            if q == cl or q in cl or cl in q or q in clc:
                matched.add(col)
    return next(iter(matched)) if len(matched) == 1 else None


def recompute_scoped(roles, scope_values, metric, resolver):
    """Recompute ``metric`` over the SUBSET of rows where ``scope_values[i]`` is truthy (row-aligned with the
    role arrays). Guards: a real, proper subset of ≥3 rows (never all rows → that's the unscoped recompute, and
    never a near-empty slice → unreliable). Returns a Result or None. The resolver is the UNCHANGED Judge."""
    mask = [i for i, v in enumerate(scope_values) if _truthy(v) is True]
    total = len(scope_values)
    if len(mask) < 3 or len(mask) >= total:
        return None
    scoped = {r: [vals[i] for i in mask if i < len(vals)] for r, vals in roles.items()}
    return recompute_from_cols(scoped, metric, resolver)


def bind_and_recompute_scoped(qualifier_text, roles, scope_cols, metric, resolver):
    """Tie the subset binding together: extract qualifiers from the claim's raw name/context, bind ONE boolean
    column, and recompute ``metric`` on that subset. Returns (Result, scope_column) or (None, None) — the caller
    uses the scoped result for a subset claim, falling back to the unscoped recompute otherwise."""
    quals = scope_qualifiers(qualifier_text)
    if not quals or not scope_cols:
        return None, None
    col = bind_scope(quals, list(scope_cols))
    if not col:
        return None, None
    res = recompute_scoped(roles, scope_cols[col], metric, resolver)
    return (res, col) if res else (None, None)
