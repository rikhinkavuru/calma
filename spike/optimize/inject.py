"""optimize.inject — generate labeled synthetic claims against a captured true value.

Given a metric and the value the repo ACTUALLY produced (captured ground truth), emit claims that carry a
ground-truth `expect` plus injection metadata. Three families:

  honest     faithful reports of the true value (2/3/4 decimals + percent form) → expect CONFIRMED.
             These are the false-REFUTE controls (an honest number must never be REFUTED) and the
             CONFIRMED denominator.
  misreport  clear misreports: ≥1% perturbation, far beyond any rounding → expect REFUTED.
             These are the catch-rate numerator AND the false-CONFIRM test (a wrong number must never be
             CONFIRMED). Labeled REFUTED by construction.
  sweep      a fine geometric perturbation at a fixed reporting precision, for the catch-rate-vs-magnitude
             (MDE) curve. Each is labeled by an INDEPENDENT rounding check (does the perturbed value round
             to the same N-decimal string as the true value?) — never by tolerance.py, so the ground truth
             can't move in lockstep with the system under test.

Pure stdlib, no core import: `expect` is the bare verdict string, which equals core.verdict.CONFIRMED /
REFUTED. Keeping inject dependency-free lets it be reasoned about in isolation.
"""
from __future__ import annotations

CONFIRMED = "CONFIRMED"
REFUTED = "REFUTED"

# metrics whose value lives in [0, 1] — perturbations get clamped so we never propose an impossible claim
RATE = {"accuracy", "roc_auc", "f1", "precision", "recall", "balanced_accuracy"}


def _fmt(v, d):
    return "%.*f" % (d, v)


def _clamp(metric, v):
    return min(max(v, 0.0), 1.0) if metric in RATE else v


def honest(metric, true):
    out = []
    for d in (2, 3, 4):
        out.append({"value": _fmt(true, d), "expect": CONFIRMED, "inj": {"kind": "honest", "prec": d}})
    if metric in RATE and 0.0 <= true <= 1.0:
        out.append({"value": _fmt(true * 100, 2) + "%", "expect": CONFIRMED,
                    "inj": {"kind": "honest", "prec": "pct"}})
    return out


def misreport(metric, true, rels=(0.01, 0.02, 0.05, 0.10, 0.20)):
    out = []
    for r in rels:
        for s in (1, -1):
            v = _clamp(metric, true * (1 + s * r))
            if abs(v - true) < 5e-4:          # perturbation collapsed (e.g. clamped at a bound) — not clean
                continue
            out.append({"value": _fmt(v, 4), "expect": REFUTED,
                        "inj": {"kind": "misreport", "rel": s * r}})
    return out


# fine grid spanning below and above the 4-decimal rounding floor (~5e-5 for a value near 1)
SWEEP_RELS = (3e-5, 6e-5, 1e-4, 3e-4, 6e-4, 1e-3, 3e-3, 1e-2, 3e-2, 1e-1)


def sweep(metric, true, prec=4, rels=SWEEP_RELS):
    out = []
    true_str = _fmt(true, prec)
    for r in rels:
        for s in (1, -1):
            v = _clamp(metric, true * (1 + s * r))
            cs = _fmt(v, prec)
            faithful = (cs == true_str)       # independent ground truth: does it round to the true string?
            out.append({"value": cs, "expect": CONFIRMED if faithful else REFUTED,
                        "inj": {"kind": "sweep", "rel": s * r, "delta": abs(v - true), "faithful": faithful}})
    return out


def all_claims(metric, true):
    return honest(metric, true) + misreport(metric, true) + sweep(metric, true)
