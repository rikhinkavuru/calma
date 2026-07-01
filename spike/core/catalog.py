"""calma.spike.core.catalog — the trusted metric catalog (the independent recompute oracle).

This is the correctness core (rebuild guide §4). Each entry is a *trusted deterministic implementation*
of a recognized metric, written PURE-STDLIB and from first principles — deliberately sharing **zero code**
with the repo under test (which uses sklearn/numpy/pandas). When the repo computes `roc_auc_score(y, p)`
and we recompute `roc_auc` here on the *same captured arrays*, agreement is genuine cross-implementation
evidence; disagreement is an INVALIDATED (a wrong/cheating formula that still ran).

Contract per metric fn:  fn(inputs: dict, kwargs: dict) -> Result
  inputs   canonical arrays the metric consumes (e.g. {"y_true": [...], "y_pred": [...]})
  kwargs   metric options that change the math (pos_label, average, ddof, periods_per_year, ...)
  Result   {"value": float, "degenerate": bool, "note": str, "terms": dict}

`degenerate=True` is the fail-closed signal: the inputs could not yield a finite, trustworthy number
(length mismatch, empty, single-class AUC, near-zero-vol Sharpe, non-coercible cells). The verdict layer
turns a degenerate recompute into INCONCLUSIVE — never a CONFIRMED.

The catalog is intentionally small here (the beachhead metrics). Breadth (the 600+ recipe corpus) is a
later port; the spike only needs enough to measure reproduction + binding + false-confirm on real repos.
"""
from __future__ import annotations

import math
from typing import Callable

_INF, _NINF = float("inf"), float("-inf")


def _finite(x: float) -> bool:
    return isinstance(x, float) and x == x and x not in (_INF, _NINF)


def result(value, degenerate=False, note="", **terms) -> dict:
    v = float(value) if value is not None else float("nan")
    if not _finite(v):
        degenerate = True
    return {"value": v, "degenerate": bool(degenerate), "note": note, "terms": terms}


def _degenerate(note: str) -> dict:
    return {"value": float("nan"), "degenerate": True, "note": note, "terms": {}}


# ---- coercion helpers ----------------------------------------------------------------------------
def _as_floats(seq):
    """Coerce a captured sequence to a list of floats. Raises ValueError on a non-coercible / non-finite
    cell (inf/NaN literal), because an order statistic over corrupt data must degenerate, not silently
    return a finite-but-wrong number (median([10,20,inf]) == 20). Booleans -> 0.0/1.0."""
    out = []
    for v in seq:
        if isinstance(v, bool):
            out.append(1.0 if v else 0.0)
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise ValueError("non-numeric cell %r" % (v,))
        if not _finite(f):
            raise ValueError("non-finite cell %r" % (v,))
        out.append(f)
    return out


def _as_labels(seq):
    """Labels kept as their raw value for equality (int/str/bool), only normalizing numpy-ish numbers
    to a hashable python scalar. A 1.0 and a 1 must compare equal (sklearn treats them as the same class),
    so an integral float collapses to int."""
    out = []
    for v in seq:
        if isinstance(v, bool):
            out.append(int(v))
        elif isinstance(v, float) and v.is_integer():
            out.append(int(v))
        else:
            out.append(v)
    return out


def _pair(inputs, a="y_true", b="y_pred"):
    ya, yb = inputs.get(a), inputs.get(b)
    if ya is None or yb is None:
        raise ValueError("missing input %r/%r" % (a, b))
    if len(ya) != len(yb):
        raise ValueError("length mismatch: %s=%d vs %s=%d" % (a, len(ya), b, len(yb)))
    if len(ya) == 0:
        raise ValueError("empty input")
    return ya, yb


# ---- classification -------------------------------------------------------------------------------
def accuracy(inputs, kwargs) -> dict:
    try:
        yt, yp = _pair(inputs)
        yt, yp = _as_labels(yt), _as_labels(yp)
    except ValueError as e:
        return _degenerate(str(e))
    n = len(yt)
    correct = sum(1 for a, b in zip(yt, yp) if a == b)
    normalize = kwargs.get("normalize", True)
    val = (correct / n) if normalize else float(correct)
    return result(val, n=n, correct=correct)


def _per_class(yt, yp):
    """Return {label: (tp, fp, fn, support)} over the label set of y_true ∪ y_pred."""
    labels = sorted(set(yt) | set(yp), key=lambda x: (str(type(x)), str(x)))
    stats = {}
    for lab in labels:
        tp = sum(1 for a, b in zip(yt, yp) if a == lab and b == lab)
        fp = sum(1 for a, b in zip(yt, yp) if a != lab and b == lab)
        fn = sum(1 for a, b in zip(yt, yp) if a == lab and b != lab)
        support = sum(1 for a in yt if a == lab)
        stats[lab] = (tp, fp, fn, support)
    return stats


def _prf(tp, fp, fn):
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
    return prec, rec, f1


def _prf_metric(which):
    def fn(inputs, kwargs) -> dict:
        try:
            yt, yp = _pair(inputs)
            yt, yp = _as_labels(yt), _as_labels(yp)
        except ValueError as e:
            return _degenerate(str(e))
        average = kwargs.get("average", "binary")
        stats = _per_class(yt, yp)
        idx = {"precision": 0, "recall": 1, "f1": 2}[which]
        if average == "binary":
            pos = kwargs.get("pos_label", 1)
            pos = int(pos) if isinstance(pos, float) and pos.is_integer() else pos
            if pos not in stats:
                # binary metric but the positive label never appears: sklearn warns + returns 0.0.
                # Fail-closed-friendly: report 0.0 but note it (the verdict layer can treat a 0.0 with
                # a 'positive label absent' note conservatively).
                return result(0.0, note="positive label %r absent" % (pos,))
            tp, fp, fn, _ = stats[pos]
            return result(_prf(tp, fp, fn)[idx], pos_label=pos)
        per = {lab: _prf(tp, fp, fn)[idx] for lab, (tp, fp, fn, _) in stats.items()}
        if average == "macro":
            return result(sum(per.values()) / len(per), per_class=per)
        if average == "micro":
            TP = sum(s[0] for s in stats.values())
            FP = sum(s[1] for s in stats.values())
            FN = sum(s[2] for s in stats.values())
            return result(_prf(TP, FP, FN)[idx])
        if average == "weighted":
            tot = sum(s[3] for s in stats.values()) or 1
            return result(sum(per[lab] * stats[lab][3] for lab in per) / tot)
        return _degenerate("unsupported average=%r" % (average,))
    return fn


def balanced_accuracy(inputs, kwargs) -> dict:
    try:
        yt, yp = _pair(inputs)
        yt, yp = _as_labels(yt), _as_labels(yp)
    except ValueError as e:
        return _degenerate(str(e))
    labels = sorted(set(yt), key=lambda x: (str(type(x)), str(x)))
    recalls = []
    for lab in labels:
        support = sum(1 for a in yt if a == lab)
        tp = sum(1 for a, b in zip(yt, yp) if a == lab and b == lab)
        if support:
            recalls.append(tp / support)
    if not recalls:
        return _degenerate("no classes in y_true")
    return result(sum(recalls) / len(recalls), n_classes=len(recalls))


def roc_auc(inputs, kwargs) -> dict:
    """Binary ROC-AUC via the Mann–Whitney U statistic with average ranks for ties — exact and equal to
    sklearn.metrics.roc_auc_score on binary inputs. Degenerate when only one class is present (AUC undefined)."""
    yt = inputs.get("y_true")
    ys = inputs.get("y_score", inputs.get("y_pred"))
    if yt is None or ys is None:
        return _degenerate("missing y_true/y_score")
    if len(yt) != len(ys):
        return _degenerate("length mismatch")
    if len(yt) == 0:
        return _degenerate("empty input")
    labs = _as_labels(yt)
    classes = sorted(set(labs), key=lambda x: (str(type(x)), str(x)))
    if len(classes) != 2:
        return _degenerate("ROC-AUC needs exactly 2 classes in y_true, saw %d" % len(classes))
    pos = classes[1]  # sklearn: the greater label is positive (for {0,1} -> 1)
    try:
        scores = _as_floats(ys)
    except ValueError as e:
        return _degenerate("y_score: %s" % e)
    y = [1 if lab == pos else 0 for lab in labs]
    # average ranks (1-based) over ascending scores
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # mean of the 1-based ranks i+1..j+1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    n_pos = sum(y)
    n_neg = len(y) - n_pos
    if n_pos == 0 or n_neg == 0:
        return _degenerate("one class only")
    sum_ranks_pos = sum(ranks[i] for i in range(len(y)) if y[i] == 1)
    auc = (sum_ranks_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
    return result(auc, pos_label=pos, n_pos=n_pos, n_neg=n_neg)


def _confusion(yt, yp):
    """(K labels, K×K matrix C[true][pred], n). Labels = sorted union of y_true ∪ y_pred."""
    labels = sorted(set(yt) | set(yp), key=lambda x: (str(type(x)), str(x)))
    idx = {lab: i for i, lab in enumerate(labels)}
    K = len(labels)
    C = [[0] * K for _ in range(K)]
    for a, b in zip(yt, yp):
        C[idx[a]][idx[b]] += 1
    return labels, C, len(yt)


def mcc(inputs, kwargs) -> dict:
    """Matthews correlation coefficient (binary + multiclass), == sklearn.metrics.matthews_corrcoef.
    Multiclass via the Gorodkin confusion-matrix identity. Degenerate when a marginal is zero (a class
    absent from y_true or y_pred → the denominator vanishes; MCC undefined)."""
    try:
        yt, yp = _pair(inputs)
        yt, yp = _as_labels(yt), _as_labels(yp)
    except ValueError as e:
        return _degenerate(str(e))
    _labels, C, n = _confusion(yt, yp)
    K = len(_labels)
    correct = sum(C[k][k] for k in range(K))
    t = [sum(C[k]) for k in range(K)]                       # row sums  (true totals)
    p = [sum(C[r][k] for r in range(K)) for k in range(K)]  # col sums  (pred totals)
    num = correct * n - sum(p[k] * t[k] for k in range(K))
    den = math.sqrt((n * n - sum(x * x for x in p)) * (n * n - sum(x * x for x in t)))
    if den == 0.0:
        return _degenerate("MCC denominator is zero (a class is absent in y_true or y_pred)")
    return result(num / den, n=n)


def cohen_kappa(inputs, kwargs) -> dict:
    """Cohen's kappa (unweighted) = (po - pe)/(1 - pe), == sklearn.metrics.cohen_kappa_score."""
    try:
        yt, yp = _pair(inputs)
        yt, yp = _as_labels(yt), _as_labels(yp)
    except ValueError as e:
        return _degenerate(str(e))
    _labels, C, n = _confusion(yt, yp)
    K = len(_labels)
    po = sum(C[k][k] for k in range(K)) / n
    t = [sum(C[k]) / n for k in range(K)]
    p = [sum(C[r][k] for r in range(K)) / n for k in range(K)]
    pe = sum(t[k] * p[k] for k in range(K))
    if abs(1.0 - pe) < 1e-15:
        return _degenerate("Cohen's kappa undefined (expected agreement == 1)")
    return result((po - pe) / (1.0 - pe), n=n)


def brier(inputs, kwargs) -> dict:
    """Brier score (binary) = mean((p - y)^2) with y = 1[label == positive], == sklearn.brier_score_loss.
    The shim already captures it (brier_score_loss); this makes it first-class instead of reproduced-only."""
    yt = inputs.get("y_true")
    yp = inputs.get("y_score", inputs.get("y_pred"))
    if yt is None or yp is None:
        return _degenerate("missing y_true/y_score")
    if len(yt) != len(yp):
        return _degenerate("length mismatch")
    if len(yt) == 0:
        return _degenerate("empty input")
    labs = _as_labels(yt)
    classes = sorted(set(labs), key=lambda x: (str(type(x)), str(x)))
    if len(classes) > 2:
        return _degenerate("Brier score is binary")
    try:
        p = _as_floats(yp)
    except ValueError as e:
        return _degenerate(str(e))
    pos = classes[-1]                                   # sklearn pos_label default = the greater label
    y = [1.0 if lab == pos else 0.0 for lab in labs]
    return result(math.fsum((pi - yi) ** 2 for pi, yi in zip(p, y)) / len(y), n=len(y))


# ---- regression -----------------------------------------------------------------------------------
def _reg(inputs):
    yt, yp = _pair(inputs)
    return _as_floats(yt), _as_floats(yp)


def mse(inputs, kwargs) -> dict:
    try:
        yt, yp = _reg(inputs)
    except ValueError as e:
        return _degenerate(str(e))
    v = sum((a - b) ** 2 for a, b in zip(yt, yp)) / len(yt)
    return result(v, n=len(yt))


def rmse(inputs, kwargs) -> dict:
    r = mse(inputs, kwargs)
    if r["degenerate"]:
        return r
    return result(math.sqrt(r["value"]), n=r["terms"].get("n"))


def mae(inputs, kwargs) -> dict:
    try:
        yt, yp = _reg(inputs)
    except ValueError as e:
        return _degenerate(str(e))
    v = sum(abs(a - b) for a, b in zip(yt, yp)) / len(yt)
    return result(v, n=len(yt))


def r2(inputs, kwargs) -> dict:
    try:
        yt, yp = _reg(inputs)
    except ValueError as e:
        return _degenerate(str(e))
    n = len(yt)
    mean = sum(yt) / n
    ss_tot = sum((a - mean) ** 2 for a in yt)
    ss_res = sum((a - b) ** 2 for a, b in zip(yt, yp))
    if ss_tot == 0.0:
        # constant y_true: R² undefined (sklearn returns 0.0 if also ss_res==0 else -inf). Degenerate.
        return _degenerate("y_true is constant (R² undefined)")
    return result(1.0 - ss_res / ss_tot, n=n)


# ---- reductions / analytics -----------------------------------------------------------------------
def _values(inputs):
    vals = inputs.get("values", inputs.get("x"))
    if vals is None:
        raise ValueError("missing 'values'")
    if len(vals) == 0:
        raise ValueError("empty input")
    return _as_floats(vals)


def mean(inputs, kwargs) -> dict:
    try:
        v = _values(inputs)
    except ValueError as e:
        return _degenerate(str(e))
    return result(math.fsum(v) / len(v), n=len(v))


def total_sum(inputs, kwargs) -> dict:
    try:
        v = _values(inputs)
    except ValueError as e:
        return _degenerate(str(e))
    return result(math.fsum(v), n=len(v))


# ---- finance --------------------------------------------------------------------------------------
def sharpe(inputs, kwargs) -> dict:
    """Sharpe ratio = mean(excess) / stdev(excess, ddof) * sqrt(periods_per_year). Defaults: ddof=1
    (sample std), periods_per_year=1 (no annualization unless declared), risk_free=0. Near-zero vol ->
    degenerate (the ratio explodes; not a trustworthy number)."""
    rets = inputs.get("returns", inputs.get("values"))
    if rets is None:
        return _degenerate("missing 'returns'")
    try:
        r = _as_floats(rets)
    except ValueError as e:
        return _degenerate(str(e))
    n = len(r)
    if n < 2:
        return _degenerate("need >=2 returns for a sample stdev")
    rf = float(kwargs.get("risk_free", 0.0) or 0.0)
    ddof = int(kwargs.get("ddof", 1))
    ppy = float(kwargs.get("periods_per_year", 1) or 1)
    excess = [x - rf for x in r]
    m = math.fsum(excess) / n
    denom = n - ddof
    if denom <= 0:
        return _degenerate("ddof too large")
    var = math.fsum((x - m) ** 2 for x in excess) / denom
    sd = math.sqrt(var)
    if sd < 1e-12 or sd == 0.0:
        return {"value": float("nan"), "degenerate": True, "note": "near-zero volatility (Sharpe undefined)",
                "terms": {"mean": m, "stdev": sd, "near_zero_vol": True}}
    val = (m / sd) * math.sqrt(ppy)
    return result(val, mean=m, stdev=sd, n=n, periods_per_year=ppy, ddof=ddof)


# Convention-sensitive metrics recompute to DIFFERENT values under different STANDARD conventions — Sharpe
# especially (annualization factor √periods_per_year, sample-vs-population stdev via ddof). The repo's
# convention is buried in its own code (e.g. `* np.sqrt(252)`, `np.std` default ddof=0) and isn't captured,
# so a single-convention recompute will falsely disagree with a correct number. `CONVENTIONS` gives diff.py a
# bounded grid of RECOGNIZED conventions to try against the REAL captured inputs: if one reproduces the
# produced value, the number is a valid metric (not cheating). FCR-safe — a fabricated value matches none of a
# small set of standard conventions; keep these grids to genuinely-standard settings only.
CONVENTIONS: dict[str, list[dict]] = {
    # daily/weekly/monthly/quarterly/annual annualization × sample/population stdev
    "sharpe": [{"periods_per_year": p, "ddof": d}
               for p in (1.0, 252.0, 52.0, 12.0, 4.0, 365.0) for d in (1, 0)],
}


# ---- registry -------------------------------------------------------------------------------------
CATALOG: dict[str, Callable[[dict, dict], dict]] = {
    "accuracy": accuracy,
    "balanced_accuracy": balanced_accuracy,
    "precision": _prf_metric("precision"),
    "recall": _prf_metric("recall"),
    "f1": _prf_metric("f1"),
    "roc_auc": roc_auc,
    "mcc": mcc,
    "cohen_kappa": cohen_kappa,
    "brier": brier,
    "mse": mse,
    "rmse": rmse,
    "mae": mae,
    "r2": r2,
    "mean": mean,
    "sum": total_sum,
    "sharpe": sharpe,
}

# canonical aliases a discovered/claimed metric name may arrive under
ALIASES = {
    "acc": "accuracy", "accuracy_score": "accuracy", "top1": "accuracy", "top-1": "accuracy",
    "balanced_accuracy_score": "balanced_accuracy", "bacc": "balanced_accuracy",
    "auc": "roc_auc", "auroc": "roc_auc", "roc_auc_score": "roc_auc", "auc_roc": "roc_auc",
    "f1_score": "f1", "f1-score": "f1", "f_score": "f1", "fscore": "f1",
    "precision_score": "precision", "recall_score": "recall",
    "mean_squared_error": "mse", "root_mean_squared_error": "rmse",
    "mean_absolute_error": "mae", "r2_score": "r2", "r^2": "r2", "rsquared": "r2", "r_squared": "r2",
    "average": "mean", "avg": "mean", "sharpe_ratio": "sharpe", "sr": "sharpe",
    "matthews_corrcoef": "mcc", "matthews": "mcc", "mcc_score": "mcc",
    "cohen_kappa_score": "cohen_kappa", "kappa": "cohen_kappa", "cohens_kappa": "cohen_kappa",
    "brier_score": "brier", "brier_score_loss": "brier",
}


def canonical(metric: str) -> str | None:
    if not metric:
        return None
    m = metric.strip().lower().replace(" ", "_")
    m = ALIASES.get(m, m)
    return m if m in CATALOG else None


def known(metric: str) -> bool:
    return canonical(metric) is not None


def recompute(metric: str, inputs: dict, kwargs: dict | None = None) -> dict:
    """Independently recompute `metric` from `inputs` using the trusted catalog implementation.
    Unknown metric -> a degenerate result (fail-closed: we recompute only what we recognize)."""
    cid = canonical(metric)
    if cid is None:
        return _degenerate("metric %r not in the trusted catalog" % (metric,))
    try:
        return CATALOG[cid](inputs or {}, kwargs or {})
    except Exception as e:  # noqa: BLE001 — any kernel failure is a degenerate recompute, never a crash
        return _degenerate("recompute raised %s: %s" % (type(e).__name__, str(e)[:160]))
