#!/usr/bin/env python
"""optimize.leakage_stress — the soundness axis of two-axis catch (#8b: the validity moat).

Recompute catches a wrong FORMULA; it CANNOT catch a number that reproduces and recomputes perfectly yet is
INVALID because the held-out split leaked. That's `core.leakage`. This measures it on controlled-overlap
synthetic splits:
  catch_rate    contaminated splits (overlap ≥ threshold) → a leakage finding         (→1)
  false_pos     CLEAN, disjoint splits → NO finding                                   (→0, a false alarm)
  detection MDE smallest overlap fraction flagged (should track the 1% exact threshold)
Both detectors: exact duplicate-row overlap, and k-mer homology (near-duplicate sequences). Pure stdlib.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)

import random  # noqa: E402

from core import leakage as L  # noqa: E402


def rows(n, start=0):
    return ["id%05d,val_%d" % (i, (i * 31) % 997) for i in range(start, start + n)]


def contaminate_exact(train, clean_test, frac):
    """Replace `frac` of the clean test rows with verbatim train rows (duplicate-row leakage)."""
    k = int(round(frac * len(clean_test)))
    return list(train[:k]) + clean_test[k:]


_BASES = "ACGT"


def seqs(n, start=0, L_=80):
    """Independent pseudo-random DNA sequences (a per-sequence LCG stream) so DISTINCT sequences share few
    k-mers (low mutual Jaccard) — the precondition for a meaningful homology test. A cyclic generator makes
    every sequence a near-duplicate of every other and the clean split self-flags (the bug this replaces)."""
    out = []
    for i in range(start, start + n):
        rnd = random.Random(start * 100003 + i)   # independent, high-entropy, deterministic per sequence
        out.append("".join(rnd.choice(_BASES) for _ in range(L_)))
    return out


def near_dup(s, nmut=1):
    """A near-duplicate: nmut point mutation(s) (≈98.7% identity at L=80) — a homolog the detector should
    catch at sim=0.8. (2 mutations drop k-mer Jaccard to ~0.72, below threshold — a real sensitivity edge.)"""
    cs = list(s)
    for j in range(nmut):
        pos = (j * 17 + 3) % len(cs)
        cs[pos] = _BASES[(_BASES.index(cs[pos]) + 1) % 4]
    return "".join(cs)


def contaminate_homology(train, clean_test, frac):
    k = int(round(frac * len(clean_test)))
    return [near_dup(t) for t in train[:k]] + clean_test[k:]


FRACS = (0.0, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0)


def run_axis(contaminate, sequences, threshold):
    """Score one leakage axis against ITS OWN operating threshold (exact 1%, homology 5%): catch over
    contamination at/above threshold, false-positive on the clean split, and sub-threshold (must stay
    un-flagged — the detector is deliberately conservative below its threshold)."""
    train = (seqs(200) if sequences else rows(200))
    clean_test = (seqs(200, start=10000) if sequences else rows(200, start=10000))  # disjoint
    detail = []
    for frac in FRACS:
        test = clean_test if frac == 0.0 else contaminate(train, clean_test, frac)
        findings = L.check_leakage(train, test, sequences=sequences)
        detail.append({"frac": frac, "detected": bool(findings),
                       "mag": round(findings[0]["magnitude"], 3) if findings else 0.0})
    clean = [d for d in detail if d["frac"] == 0.0]
    above = [d for d in detail if d["frac"] >= threshold]
    sub = [d for d in detail if 0.0 < d["frac"] < threshold]
    return {"detail": detail, "threshold": threshold,
            "catch_rate": round(sum(d["detected"] for d in above) / len(above), 3) if above else None,
            "false_positive": sum(d["detected"] for d in clean),
            "sub_threshold_flagged": sum(d["detected"] for d in sub),
            "detection_mde": next((d["frac"] for d in detail if d["frac"] > 0 and d["detected"]), None)}


def main():
    exact = run_axis(contaminate_exact, sequences=False, threshold=0.01)
    homology = run_axis(contaminate_homology, sequences=True, threshold=0.05)
    out = {"exact": exact, "homology": homology}
    with open(os.path.join(HERE, "leakage_metrics.json"), "w") as fh:
        json.dump(out, fh, indent=2)
    print("=== LEAKAGE catch (the validity moat — soundness axis #8b) ===")
    for name, m in (("exact-row", exact), ("homology", homology)):
        print("%-10s thr=%.0f%%  catch(≥thr)=%s  false-positive(clean)=%d  sub-thr-flagged=%d  MDE=%s"
              % (name, 100 * m["threshold"], m["catch_rate"], m["false_positive"],
                 m["sub_threshold_flagged"], m["detection_mde"]))
        print("           by overlap-frac:",
              {("%.3f" % d["frac"]): ("Y" if d["detected"] else "·") for d in m["detail"]})
    ok = all(m["false_positive"] == 0 and m["sub_threshold_flagged"] == 0 and m["catch_rate"] == 1.0
             for m in (exact, homology))
    print("CLEAN pass + sub-threshold quiet + ALL at/above-threshold caught:", ok)
    return 0


if __name__ == "__main__":
    sys.exit(main())
