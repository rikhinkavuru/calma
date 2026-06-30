#!/usr/bin/env python
"""optimize.discovery_eval — claim-discovery recall + precision (#9; the front of the funnel).

Discovery is "free = auto-discover"; its recall caps how many claims ever reach the verifier, and a
hallucinated claim (precision miss) wastes a verification. The memo's SOTA weak spot is the VALUE / prose
parse. This measures recall + precision on a labeled text battery, split into STRUCTURED ("Metric: value",
tables) vs PROSE ("achieved 96.67% accuracy"), so the gap is visible.

Each case: (text, [(metric, value_substr)...]) — the claims a human would extract. recall = found/expected,
precision = legit/found (a found claim whose (metric,value) isn't expected is a hallucination). Pure stdlib.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)

from core import catalog as C  # noqa: E402
from discovery import extract as DISC  # noqa: E402

STRUCTURED = [
    ("Accuracy: 0.831", [("accuracy", "0.831")]),
    ("test AUC = 0.91", [("roc_auc", "0.91")]),
    ("| F1 | 0.72 |", [("f1", "0.72")]),
    ("MCC: 0.78", [("mcc", "0.78")]),
    ("Final Accuracy: 96.67%", [("accuracy", "96.67")]),
    ("RMSE = 12.3", [("rmse", "12.3")]),
    ("r2: 0.85", [("r2", "0.85")]),
    ("Cohen's kappa = 0.66", [("cohen_kappa", "0.66")]),
    ("Validation accuracy: 0.92\nTest accuracy: 0.89", [("accuracy", "0.92"), ("accuracy", "0.89")]),
]

PROSE = [
    ("The model achieved 96.67% accuracy on the held-out set.", [("accuracy", "96.67")]),
    ("We report an F1 score of 0.72.", [("f1", "0.72")]),
    ("Our classifier reached an accuracy of 0.83 on the test set.", [("accuracy", "0.83")]),
    ("AUC was 0.91 on the validation split.", [("roc_auc", "0.91")]),
    ("The system scored 0.88 AUROC overall.", [("roc_auc", "0.88")]),
    ("Test-set accuracy came out to 95%.", [("accuracy", "95")]),
    ("a Matthews correlation coefficient of 0.78", [("mcc", "0.78")]),
    ("RMSE of 12.3 on the test data", [("rmse", "12.3")]),
]


def _found_set(text):
    out = set()
    for c in DISC.from_text(text):
        out.add((C.canonical(c["metric"]) or c["metric"], c["value"].rstrip("%")))
    return out


def _score(cases):
    exp_total, found_total, hit, halluc = 0, 0, 0, 0
    misses = []
    for text, expected in cases:
        exp = {(m, v) for m, v in expected}
        found = _found_set(text)
        exp_total += len(exp)
        found_total += len(found)
        matched = {e for e in exp if any(e[0] == f[0] and e[1] in f[1] or f[1] in e[1] for f in found)}
        hit += len(matched)
        halluc += len([f for f in found if not any(f[0] == e[0] and (e[1] in f[1] or f[1] in e[1])
                                                   for e in exp)])
        if matched != exp:
            misses.append({"text": text[:60], "expected": sorted(exp), "found": sorted(found)})
    return {"recall": round(hit / exp_total, 3) if exp_total else None,
            "precision": round((found_total - halluc) / found_total, 3) if found_total else None,
            "expected": exp_total, "found": found_total, "hits": hit, "hallucinations": halluc,
            "misses": misses}


def main():
    s, p = _score(STRUCTURED), _score(PROSE)
    out = {"structured": s, "prose": p}
    with open(os.path.join(HERE, "discovery_metrics.json"), "w") as fh:
        json.dump(out, fh, indent=2)
    print("=== DISCOVERY recall / precision (#9 — front of the funnel) ===")
    for name, m in (("structured", s), ("prose", p)):
        print("%-11s recall=%s  precision=%s  (expected=%d found=%d hits=%d halluc=%d)"
              % (name, m["recall"], m["precision"], m["expected"], m["found"], m["hits"], m["hallucinations"]))
    print("\nPROSE misses (the SOTA weak spot — safe recall headroom):")
    for mm in p["misses"][:8]:
        print("  ·", mm["text"], "| expected", mm["expected"], "| found", mm["found"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
