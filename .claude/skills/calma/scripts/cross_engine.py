"""calma.cross_engine - B2: cross-engine correctness. Recompute the headline metric a SECOND time
through an INDEPENDENT implementation and diff the two under the calibrated tolerance.

Why this is a differentiator: a 2026 study found no backtest engine publishes cross-engine correctness
comparisons - every single-engine result carries *unquantified implementation uncertainty* (a Sharpe
from engine A and engine B can differ from accumulation order, annualization, or an off-by-one, and
nobody checks). Calma already recomputes the metric from raw outputs on its primary kernels
(numeric.py); this adds a second, independently-written kernel and QUANTIFIES the agreement. Two
independent implementations agreeing to 1e-9 on the same raw data is strong evidence the number is
implementation-robust; a divergence is a real, named finding (implementation-dependent metric).

The second engine is deliberately DIFFERENT in algorithm / reduction order from numeric.py, so a bug in
EITHER surfaces as disagreement (a redundant copy of the same code would catch nothing):
  - sum/mean    : naive left-fold accumulation        (numeric.py uses math.fsum, correctly-rounded)
  - total_return: sequential left-fold product         (numeric.py uses a pairwise product tree)
  - sharpe      : Welford's online mean+variance        (numeric.py uses a two-pass fsum variance)
  - rmse/mae/accuracy: independent straight loops
Pure stdlib, deterministic, bit-stable. ADDITIVE: it never changes the primary verdict - it attaches a
cross-engine block (and, on divergence, a soft CAVEAT-class finding). The primary numeric.py recompute
stays authoritative.

It also reports which EXTERNAL language stacks (R / Julia / Node) the host could use as an even stronger
second engine - transparency about the strongest available cross-check, without requiring them.

Library: cross_check_metric(metric_id, cols, binding, convention, primary_value) -> dict | None;
cross_check_contract(contract, base, rec) -> {engine, tolerance, metrics:[...], any_divergence};
available_external_engines() -> [names]; finding(divergences, claim_id) -> finding | None.
"""
import csv
import math
import shutil

import pathsafe as PS

# the calibrated agreement budget: two correct implementations of the same metric on the same raw data
# should agree to floating-point reduction-order noise. Mirrors compare.py's ABS/REL floors.
ABS_FLOOR = 1e-9
REL_FLOOR = 1e-9
SECOND_ENGINE = "python-independent-kernel"


# ---- the INDEPENDENT second-engine kernels (different algorithm than numeric.py) -------------------
def _naive_sum(xs):
    """Left-fold accumulation - a DIFFERENT reduction order than numeric.py's math.fsum (which is
    correctly-rounded). If the two agree to 1e-9 the sum is reduction-order robust."""
    acc = 0.0
    for x in xs:
        acc += x
    return acc


def _naive_mean(xs):
    return _naive_sum(xs) / len(xs) if xs else float("nan")


def _seq_total_return(rets):
    """Sequential product (1+r0)(1+r1)... - 1 by a left fold, vs numeric.py's pairwise product tree."""
    acc = 1.0
    for r in rets:
        acc *= (1.0 + r)
    return acc - 1.0


def _welford(xs):
    """Welford's online mean + sample variance (one pass) - independent of numeric.py's two-pass
    fsum((x-m)^2). Returns (mean, var_ddof1) or (nan, nan) for < 2 points."""
    n = 0
    mean = m2 = 0.0
    for x in xs:
        n += 1
        d = x - mean
        mean += d / n
        m2 += d * (x - mean)
    if n < 2:
        return (mean if n else float("nan")), float("nan")
    return mean, m2 / (n - 1)


def _sharpe(rets, periods=1):
    mean, var = _welford(rets)
    sd = math.sqrt(var) if var == var and var > 0 else float("nan")
    if not (sd == sd) or sd == 0:
        return float("nan")
    return (mean / sd) * math.sqrt(periods)


def _rmse(pred, actual):
    n = len(pred)
    if n == 0 or n != len(actual):
        return float("nan")
    s = 0.0
    for p, a in zip(pred, actual):
        s += (p - a) * (p - a)
    return math.sqrt(s / n)


def _mae(pred, actual):
    n = len(pred)
    if n == 0 or n != len(actual):
        return float("nan")
    s = 0.0
    for p, a in zip(pred, actual):
        s += abs(p - a)
    return s / n


def _accuracy(pred, label):
    n = len(pred)
    if n == 0 or n != len(label):
        return float("nan")
    hits = 0
    for p, a in zip(pred, label):
        if p == a:
            hits += 1
    return hits / n


# metric_id -> (kernel(cols-via-binding) -> float). Only the headline metrics with a genuinely
# independent second kernel are covered; anything else reports "no second-engine kernel" (honest -
# never a silent pass). Each pulls its inputs from the bound columns by tag.
def _by_tag(cols, binding, tag):
    col = binding.get(tag)
    return cols.get(col) if col is not None else None


_KERNELS = {
    "total_return": lambda c, b: _seq_total_return(_by_tag(c, b, "return")),
    "column_sum":   lambda c, b: _naive_sum(_by_tag(c, b, "value")),
    "column_mean":  lambda c, b: _naive_mean(_by_tag(c, b, "value")),
    "mean":         lambda c, b: _naive_mean(_by_tag(c, b, "value")),
    "sum":          lambda c, b: _naive_sum(_by_tag(c, b, "value")),
    "sharpe":       lambda c, b: _sharpe(_by_tag(c, b, "return"), 1),
    "rmse":         lambda c, b: _rmse(_by_tag(c, b, "prediction") or _by_tag(c, b, "pred"),
                                       _by_tag(c, b, "actual") or _by_tag(c, b, "label")),
    "mae":          lambda c, b: _mae(_by_tag(c, b, "prediction") or _by_tag(c, b, "pred"),
                                      _by_tag(c, b, "actual") or _by_tag(c, b, "label")),
    "accuracy":     lambda c, b: _accuracy(_by_tag(c, b, "prediction") or _by_tag(c, b, "pred"),
                                           _by_tag(c, b, "label")),
}

# the DISTINCT metric families a second independent kernel covers (column_sum/sum and
# column_mean/mean are the same kernel) - shown to the user when a metric has NO kernel, so an
# empty cross-engine pass is never silently misread as agreement (M3).
COVERED = ["total_return", "sum", "mean", "sharpe", "rmse", "mae", "accuracy"]

# convention multipliers the second engine understands; an UNKNOWN convention -> skip (don't pretend to
# match a transformed value). Keeps the cross-check honest: it only diffs where it computes the SAME
# quantity numeric.py did.
_PLAIN_CONVENTIONS = (None, "", "compounded", "argmax", "raw")


def _agree(a, b):
    """True iff |a-b| within the calibrated budget. Two NaNs agree (both degenerate); one NaN does not."""
    an, bn = (a != a), (b != b)
    if an or bn:
        return an and bn
    return abs(a - b) <= max(ABS_FLOOR, REL_FLOOR * max(abs(a), abs(b)))


def _safe_join(base, rel):
    """Resolve rel under base; refuse escapes (abs path / .. traversal / symlink-out). Delegates to the
    shared guard (pathsafe) so there is ONE audited containment implementation (L1)."""
    return PS.safe_join(base, rel)


def _read_floats(path, colnames):
    """Independent CSV reader (not recompute's) so the second engine is a genuinely separate path.
    Returns {col: [floats]} for the requested columns; non-parseable cells are dropped per column."""
    out = {c: [] for c in colnames}
    with open(path, newline="") as fh:
        rd = csv.reader(fh)
        header = next(rd, [])
        idx = {c: header.index(c) for c in colnames if c in header}
        for row in rd:
            for c, j in idx.items():
                if j < len(row):
                    try:
                        out[c].append(float(row[j]))
                    except (TypeError, ValueError):
                        pass
    return out


def cross_check_metric(metric_id, cols, binding, convention, primary_value):
    """Run the second-engine kernel for one metric and diff vs the primary value. Returns a dict
    {metric, engine, primary, second, agree, abs_diff, ...} or None when there is no independent kernel
    for this metric or the convention is one the second engine doesn't replicate (honest skip)."""
    kern = _KERNELS.get(metric_id)
    if kern is None or convention not in _PLAIN_CONVENTIONS:
        return None
    try:
        second = float(kern(cols, binding))
    except (TypeError, ValueError, ZeroDivisionError, KeyError, IndexError):
        return None
    try:
        primary = float(primary_value)
    except (TypeError, ValueError):
        return None
    agree = _agree(primary, second)
    diff = (abs(primary - second) if (primary == primary and second == second) else float("nan"))
    return {"metric": metric_id, "engine": SECOND_ENGINE, "primary": primary, "second": second,
            "agree": agree, "abs_diff": diff}


def cross_check_contract(contract, base, rec):
    """Cross-check every metric in the recompute `rec` against the second engine. `rec` is the
    recompute.recompute_contract result ({metrics:[{metric_id, value, ...}]}). Returns
    {engine, tolerance, external_available, metrics:[...], any_divergence, n_checked}."""
    by_id = {m.get("metric_id"): m for m in (contract.get("metrics") or [])}
    results = []
    for rm in (rec.get("metrics") or []):
        mid = rm.get("metric_id")
        cm = by_id.get(mid) or {}
        binding = cm.get("binding") or {}
        art = cm.get("artifact")
        if not binding or not art or rm.get("value") is None:
            continue
        # load just the bound columns via the independent reader
        cols = {}
        try:
            wanted = [str(v) for v in binding.values() if "::" not in str(v)]
            if wanted:
                cols = _read_floats(_safe_join(base, art), wanted)
        except (OSError, ValueError, csv.Error, StopIteration):
            cols = {}
        if not cols:
            continue
        r = cross_check_metric(mid, cols, binding, cm.get("convention"), rm.get("value"))
        if r:
            results.append(r)
    requested = [rm.get("metric_id") for rm in (rec.get("metrics") or []) if rm.get("metric_id")]
    checked_ids = {r["metric"] for r in results}
    # metrics that were recomputed but have no independent second kernel - named in the empty case
    uncovered = [m for m in dict.fromkeys(requested) if m not in checked_ids and m not in _KERNELS]
    return {
        "engine": SECOND_ENGINE, "tolerance": {"abs": ABS_FLOOR, "rel": REL_FLOOR},
        "external_available": available_external_engines(),
        "metrics": results, "n_checked": len(results),
        "any_divergence": any(not r["agree"] for r in results),
        "covered": COVERED, "requested": requested, "uncovered": uncovered,
    }


def finding(cross, claim_id="c1"):
    """A soft, CAVEAT-class finding when the two engines DISAGREE on a metric - the metric value is
    implementation-dependent (unquantified implementation uncertainty, now quantified). Additive: it
    never drives an authoritative verdict (a divergence between two correct kernels is a heads-up to
    investigate, surfaced like the plausibility smells). None when every checked metric agrees."""
    div = [r for r in (cross.get("metrics") or []) if not r["agree"]]
    if not div:
        return None
    d = div[0]
    return {
        "id": "f-%s-cross-engine" % claim_id, "claim_id": claim_id, "dimension": "cross-engine",
        "severity": "minor", "status": "open", "confidence": "deterministic", "fixable_by": "author",
        "locator": ("cross-engine: %s recomputes to %.10g on the primary kernel but %.10g on an "
                    "independent second kernel (abs diff %.3g > the %g budget) - the value is "
                    "implementation-dependent, not reduction-order noise"
                    % (d["metric"], d["primary"], d["second"], d["abs_diff"], ABS_FLOOR)),
        "unblock": ("reconcile the two implementations (accumulation order, annualization convention, an "
                    "off-by-one) and pin the definition; a metric that changes with the engine isn't a "
                    "stable number"),
        "reverify": {"kind": "artifact-recheck", "source": "cross-engine",
                     "expected": "the two independent kernels agree to the calibrated tolerance"},
        "validity_class": "heuristic", "cross_engine_kind": "implementation-divergence",
    }


_EXTERNAL_ENGINES = (("R", "Rscript"), ("Julia", "julia"), ("Node", "node"))


def available_external_engines():
    """Which external language stacks are on PATH (a stronger cross-engine tier than the in-process
    second kernel when present). Reported for transparency; never required."""
    return [name for name, exe in _EXTERNAL_ENGINES if shutil.which(exe)]
