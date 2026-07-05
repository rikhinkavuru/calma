#!/usr/bin/env python
"""optimize.edgecases — the adaptive edge-case brain meta-eval (build plan §7).

A tagged corpus of synthetic repos, one row per (fault class × positive/adversarial), each run through the
SAME artifact-recompute verifier the product uses (``pipeline._artifact_verify`` → the unchanged pure-stdlib
recompute Judge). Reports, disaggregated by fault class:

  • coverage  — the fixable / valid cases that reach CONFIRMED (the adaptive win: a subset claim recomputed on
                the right rows), and
  • FCR       — the ADVERSARIAL cases that WRONGLY reach CONFIRMED (the cardinal gate): a subset claim whose
                value is really the all-rows number, or names a different subset, must be REFUTED — a wrong
                adaptive bind/scope must NEVER launder into a CONFIRM.

Exits non-zero if the false-confirm RATE exceeds the policy bar (≤5%). The deterministic scoped-binding paths
hold it at 0. Hermetic: temp repos + the deterministic recompute, no sandbox / network / LLM. Runs in `make fcr`.
"""
from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)

import pipeline  # noqa: E402
from core import verdict as VD  # noqa: E402

# ── fixtures (exact recall values worked out in the header of each) ───────────────────────────────────────────
# BOOL: pfam_testable yes = rows 0-5. subset recall = TP3/(TP3+FN1) = 0.75 ; all-rows recall = 3/6 = 0.50.
_BOOL = ("label,pred,pfam_testable\n"
         "1,1,yes\n1,1,yes\n1,1,yes\n1,0,yes\n0,0,yes\n0,1,yes\n1,0,no\n1,0,no\n")
# CAT: variant_class rare = rows 0-3. rare recall = 1/2 = 0.50 ; common = 3/3 = 1.00 ; all-rows = 4/5 = 0.80.
_CAT = ("label,pred,variant_class\n"
        "1,1,rare\n1,0,rare\n0,0,rare\n0,1,rare\n1,1,common\n1,1,common\n1,1,common\n0,0,common\n")


def _repo(csv):
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "benchmark_classifier.csv"), "w") as fh:
        fh.write(csv)
    return d


def _claim(value, rawname):
    return {"id": "c1", "metric": "recall", "value": value,
            "location": "results.json::%s" % rawname, "source": "results-json", "confidence": 0.6}


def _verdict(csv, value, rawname):
    out = pipeline._artifact_verify(_repo(csv), [_claim(value, rawname)])
    rec = out.get("c1")
    return rec["verdict"] if rec else "DISCOVERED"


# ── the corpus: (fault_class, name, csv, claim_value, claim_label, adversarial, expect_confirm) ────────────────
CORPUS = [
    # scoped boolean subset — the ebv-ms shape
    ("scoped-bool", "testable-subset-correct", _BOOL, "0.75", "homology_sensitivity_testable", False, True),
    ("scoped-bool", "testable-value-is-all-rows", _BOOL, "0.50", "homology_sensitivity_testable", True, False),
    # scoped categorical subset — class-conditional metric
    ("scoped-cat", "rare-class-correct", _CAT, "0.50", "recall_rare", False, True),
    ("scoped-cat", "rare-value-is-all-rows", _CAT, "0.80", "recall_rare", True, False),
    ("scoped-cat", "rare-value-is-other-class", _CAT, "1.00", "recall_rare", True, False),  # the COMMON value
    # unscoped baseline — a plain claim must still verify on all rows (no over-scoping)
    ("unscoped", "plain-recall-bool", _BOOL, "0.50", "recall", False, True),
    ("unscoped", "plain-recall-cat", _CAT, "0.80", "recall", False, True),
    ("unscoped", "plain-recall-wrong", _CAT, "0.55", "recall", True, False),
]


def main() -> int:
    per_class: dict = {}
    fc_total = fc_bad = cov_total = cov_hit = 0
    rows = []
    for fault, name, csv, value, label, adversarial, expect_confirm in CORPUS:
        verdict = _verdict(csv, value, label)
        confirmed = verdict == VD.CONFIRMED
        pc = per_class.setdefault(fault, {"cov_total": 0, "cov_hit": 0, "adv_total": 0, "adv_bad": 0})
        if adversarial:
            pc["adv_total"] += 1
            fc_total += 1
            bad = confirmed                                   # an adversarial that CONFIRMED = a false confirm
            pc["adv_bad"] += int(bad)
            fc_bad += int(bad)
            ok = not confirmed
        else:
            pc["cov_total"] += 1
            cov_total += 1
            hit = confirmed == expect_confirm
            pc["cov_hit"] += int(hit)
            cov_hit += int(hit)
            ok = hit
        rows.append((fault, name, verdict, "adv" if adversarial else "cov", "OK" if ok else "FAIL"))

    fcr_rate = (fc_bad / fc_total) if fc_total else 0.0
    coverage = (cov_hit / cov_total) if cov_total else 1.0

    print("== adaptive edge-case brain — §7 meta-eval ==")
    for fault in sorted(per_class):
        p = per_class[fault]
        print("  %-14s coverage %d/%d   false-confirm %d/%d"
              % (fault, p["cov_hit"], p["cov_total"], p["adv_bad"], p["adv_total"]))
    print("  %-14s coverage %d/%d (%.0f%%)   FALSE-CONFIRM %d/%d (%.1f%%)"
          % ("TOTAL", cov_hit, cov_total, 100 * coverage, fc_bad, fc_total, 100 * fcr_rate))
    for fault, name, verdict, kind, status in rows:
        if status == "FAIL":
            print("  FAIL [%s] %s/%s → %s" % (kind, fault, name, verdict))

    # cardinal gate: the false-confirm RATE must stay within the policy bar (≤5%); the deterministic paths = 0.
    if fcr_rate > 0.05:
        print("FCR GATE FAILED: false-confirm rate %.1f%% > 5%%" % (100 * fcr_rate))
        return 1
    if coverage < 1.0:
        print("COVERAGE REGRESSION: %.0f%% of valid cases did not reach the expected verdict" % (100 * coverage))
        return 1
    print("edgecases: OK (coverage %.0f%%, false-confirm %.1f%%)" % (100 * coverage, 100 * fcr_rate))
    return 0


if __name__ == "__main__":
    sys.exit(main())
