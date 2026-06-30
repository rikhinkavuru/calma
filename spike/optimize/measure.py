#!/usr/bin/env python
"""optimize.measure — the meta-eval: replay injected claims against captured truth, score the confusion.

Computes what the go/no-go harness (run_spike.py) does not:
  false_confirm_rate    fraction of MISREPORTS wrongly CONFIRMED — the cardinal sin, target 0
  catch_rate            fraction of misreports correctly REFUTED — the value metric, target → 1
  false_refute_rate     fraction of HONEST claims wrongly REFUTED — trust, target 0
  confirm_rate_honest   fraction of honest claims CONFIRMED — coverage of the happy path
  mde_curve             catch-rate vs perturbation magnitude — the sensitivity / min-detectable-error curve

Pure stdlib: it replays the persisted captures (no re-execution), so it runs fast and anywhere.

    python optimize/measure.py            # any python; reads optimize/captures/*.json
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)
sys.path.insert(0, HERE)

from core import catalog as C  # noqa: E402
from core import diff as D  # noqa: E402
from core import verdict as VD  # noqa: E402
import inject as INJ  # noqa: E402

CAP_DIR = os.path.join(HERE, "captures")


def _headlines(cap):
    """[(metric, true_value)] for each uniquely-bindable catalog metric the repo computed at a user site.

    A metric computed once → its result is the ground-truth produced value. A metric computed several times
    (train+test) is ambiguous at the headline level and skipped this cycle (it needs an occurrence hint;
    that path is exercised by the binding-rate work, not the catch-rate confusion)."""
    runs = cap.get("runs") or []
    base = runs[0] if runs else []
    by = {}
    for c in base:
        cid = C.canonical(c.get("metric") or "")
        if cid is None:
            continue
        try:
            f = float(c.get("result"))
        except (TypeError, ValueError):
            continue
        if f != f:
            continue
        by.setdefault(cid, []).append(c)
    out = []
    for cid, calls in by.items():
        user = [c for c in calls if c.get("user_site")]
        pick = user if user else calls
        if len(pick) == 1:
            out.append((cid, float(pick[0]["result"])))
    return out


def evaluate(caps):
    rows = []
    for cap in caps:
        runs = cap.get("runs") or []
        heads = _headlines(cap)
        for metric, true in heads:
            for cl in INJ.all_claims(metric, true):
                rec = D.diff_claim({"metric": metric, "value": cl["value"]}, runs)
                rows.append({"cap": cap["name"], "metric": metric, "true": true,
                             "claimed": cl["value"], "expect": cl["expect"], "verdict": rec["verdict"],
                             "inj": cl["inj"], "match": rec["verdict"] == cl["expect"]})
    return rows


def _rate(sub, pred):
    return round(sum(1 for r in sub if pred(r)) / len(sub), 4) if sub else None


def score(rows):
    honest = [r for r in rows if r["inj"]["kind"] == "honest"]
    mis = [r for r in rows if r["inj"]["kind"] == "misreport"]
    swp = [r for r in rows if r["inj"]["kind"] == "sweep"]
    m = {
        "n_rows": len(rows), "n_honest": len(honest), "n_misreport": len(mis), "n_sweep": len(swp),
        "false_confirm_rate": _rate(mis, lambda r: r["verdict"] == VD.CONFIRMED),
        "catch_rate": _rate(mis, lambda r: r["verdict"] == VD.REFUTED),
        "false_refute_rate": _rate(honest, lambda r: r["verdict"] == VD.REFUTED),
        "confirm_rate_honest": _rate(honest, lambda r: r["verdict"] == VD.CONFIRMED),
        "false_confirms": [(r["cap"], r["metric"], r["claimed"], round(r["true"], 6)) for r in mis
                           if r["verdict"] == VD.CONFIRMED],
        "false_refutes": [(r["cap"], r["metric"], r["claimed"], round(r["true"], 6)) for r in honest
                          if r["verdict"] == VD.REFUTED],
        "honest_nonconfirm": [(r["cap"], r["metric"], r["claimed"], r["verdict"]) for r in honest
                              if r["verdict"] != VD.CONFIRMED],
    }
    # MDE curve: catch fraction among genuinely-perturbed (non-faithful) sweep claims, by |rel| bucket
    buckets = {}
    for r in swp:
        if r["inj"]["faithful"]:
            continue
        buckets.setdefault(abs(r["inj"]["rel"]), []).append(r["verdict"] == VD.REFUTED)
    m["mde_curve"] = {("%.0e" % b): round(sum(v) / len(v), 3) for b, v in sorted(buckets.items())}
    full = [b for b, v in sorted(buckets.items()) if all(v)]
    m["mde_rel_full_catch"] = ("%.0e" % min(full)) if full else None
    # confusion over the cleanly-labeled sets (honest + misreport)
    clean = honest + mis
    m["verdict_accuracy_clean"] = _rate(clean, lambda r: r["match"])
    return m


def write_metrics(m, caps, out_dir):
    payload = {"captures": [{"name": c["name"], "k": c.get("k"), "n_calls": c.get("n_calls")} for c in caps],
               "metrics": m}
    path = os.path.join(out_dir, "metrics.json")
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2)
    return path


def main():
    if not os.path.isdir(CAP_DIR):
        print("no captures/ — run capture_fixtures.py first", file=sys.stderr)
        return 1
    caps = [json.load(open(os.path.join(CAP_DIR, f))) for f in sorted(os.listdir(CAP_DIR))
            if f.endswith(".json")]
    caps = [c for c in caps if c.get("ran_ok")]
    if not caps:
        print("no usable captures in %s" % CAP_DIR, file=sys.stderr)
        return 1
    rows = evaluate(caps)
    m = score(rows)
    path = write_metrics(m, caps, HERE)
    print("=== META-EVAL (injection corpus) ===")
    print("captures: %s" % ", ".join("%s(k=%s,calls=%s)" % (c["name"], c.get("k"), c.get("n_calls"))
                                      for c in caps))
    print("rows=%d  honest=%d  misreport=%d  sweep=%d" %
          (m["n_rows"], m["n_honest"], m["n_misreport"], m["n_sweep"]))
    print("FALSE-CONFIRM rate (misreport→CONFIRMED): %s   [target 0]" % m["false_confirm_rate"])
    print("CATCH rate        (misreport→REFUTED):    %s   [target →1]" % m["catch_rate"])
    print("FALSE-REFUTE rate (honest→REFUTED):       %s   [target 0]" % m["false_refute_rate"])
    print("CONFIRM rate      (honest→CONFIRMED):     %s" % m["confirm_rate_honest"])
    print("MDE (smallest |rel| with full catch):     %s" % m["mde_rel_full_catch"])
    print("MDE curve (|rel|→catch):                  %s" % m["mde_curve"])
    if m["false_confirms"]:
        print("!! FALSE CONFIRMS:", m["false_confirms"])
    if m["false_refutes"]:
        print("!! FALSE REFUTES:", m["false_refutes"][:12])
    if m["honest_nonconfirm"]:
        print(".. honest non-CONFIRMED:", m["honest_nonconfirm"][:12])
    print("→ %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
