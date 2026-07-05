#!/usr/bin/env python
"""optimize.edgecases — the adaptive edge-case brain meta-eval (build plan §7).

A fault-class-tagged corpus of synthetic repos run through the SAME verifiers the product uses. Each case is
either a COVERAGE case (a fixable/valid input that should reach a specific good verdict — the adaptive win) or
an ADVERSARIAL case (an input that must NEVER reach an AFFIRMATIVE verdict — the cardinal FCR gate). Reports,
disaggregated by fault class:

  • coverage — non-adversarial cases that reached their expected verdict,
  • FCR      — adversarial cases that WRONGLY reached CONFIRMED / CONFIRMED-STOCHASTIC (a false confirm).

Fault classes: scoped-bool, scoped-cat, scoped-llm (blind LLM subset proposal), unscoped, hardcoded-path
(absolute relink → capped REPRODUCED-ONLY), repo-bug (genuinely missing data → DISCOVERED, never a confirm).
Exits non-zero if the false-confirm RATE exceeds the policy bar (≤5%); the design holds it at 0. Hermetic:
temp repos + the deterministic recompute / local runner, no network / no real LLM. Runs in `make fcr`.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)

import pipeline  # noqa: E402
import planner as PLAN  # noqa: E402
from core import verdict as VD  # noqa: E402

# BOOL: pfam_testable yes = rows 0-5. subset recall 0.75 ; all-rows 0.50.
_BOOL = ("label,pred,pfam_testable\n1,1,yes\n1,1,yes\n1,1,yes\n1,0,yes\n0,0,yes\n0,1,yes\n1,0,no\n1,0,no\n")
# CAT: variant_class rare = rows 0-3. rare recall 0.50 ; common 1.00 ; all-rows 0.80.
_CAT = ("label,pred,variant_class\n1,1,rare\n1,0,rare\n0,0,rare\n0,1,rare\n1,1,common\n1,1,common\n1,1,common\n0,0,common\n")
# two boolean columns whose names both contain 'set' → an ambiguous qualifier match → bind refuses.
_AMBIG = ("label,pred,trainset,testset\n1,1,1,0\n1,0,1,0\n0,0,0,1\n1,1,0,1\n0,1,0,1\n1,1,1,0\n")


def _repo(csv):
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "benchmark_classifier.csv"), "w") as fh:
        fh.write(csv)
    return d


def _claim(value, rawname):
    return {"id": "c1", "metric": "recall", "value": value,
            "location": "results.json::%s" % rawname, "source": "results-json", "confidence": 0.6}


def _artifact_verdict(csv, value, rawname, model=None, scope_json=None):
    if scope_json is not None:
        PLAN._call_model = lambda *a, **k: json.dumps(scope_json)   # stub the blind scope proposer
    out = pipeline._artifact_verify(_repo(csv), [_claim(value, rawname)], model=model)
    rec = out.get("c1")
    return rec["verdict"] if rec else "DISCOVERED"


# ── end-to-end pipeline cases (local runner) ──────────────────────────────────────────────────────────────────
_READER = ("import csv\nfrom sklearn.metrics import accuracy_score\n"
           "rows = list(csv.DictReader(open(%r)))\n"
           "acc = accuracy_score([int(r['y_true']) for r in rows], [int(r['y_pred']) for r in rows])\n"
           "print('accuracy', round(acc, 4))\n")
_DATA = "y_true,y_pred\n0,0\n1,1\n0,0\n1,1\n0,1\n1,1\n"          # accuracy 5/6 = 0.8333


def _pipeline_verdict(read_path, commit_data):
    d = tempfile.mkdtemp()
    if commit_data:
        with open(os.path.join(d, "data.csv"), "w") as fh:
            fh.write(_DATA)
    with open(os.path.join(d, "run.py"), "w") as fh:
        fh.write(_READER % read_path)
    with open(os.path.join(d, "results.json"), "w") as fh:
        fh.write(json.dumps({"accuracy": 0.8333}))
    opts = pipeline.VerifyOptions(runner="local", deep=True, entry="run.py", discover=True, k=2,
                                  timeout=60, plan=False, hooks="sklearn")
    out = pipeline.verify_repo(d, opts)
    acc = [c for c in out["claims"] if c["metric"] == "accuracy"]
    return acc[0]["verdict"] if acc else "DISCOVERED"


# ── the corpus: each case yields a verdict; adversarial cases must NOT be affirmative ─────────────────────────
CORPUS = [
    # (fault, name, verdict thunk, adversarial, expected verdict for a COVERAGE case)
    ("scoped-bool", "testable-correct", lambda: _artifact_verdict(_BOOL, "0.75", "sensitivity_testable"), False, VD.CONFIRMED),
    ("scoped-bool", "value-is-all-rows", lambda: _artifact_verdict(_BOOL, "0.50", "sensitivity_testable"), True, None),
    ("scoped-bool", "near-miss-value", lambda: _artifact_verdict(_BOOL, "0.70", "sensitivity_testable"), True, None),
    ("scoped-cat", "rare-correct", lambda: _artifact_verdict(_CAT, "0.50", "recall_rare"), False, VD.CONFIRMED),
    ("scoped-cat", "rare-is-all-rows", lambda: _artifact_verdict(_CAT, "0.80", "recall_rare"), True, None),
    ("scoped-cat", "rare-is-other-class", lambda: _artifact_verdict(_CAT, "1.00", "recall_rare"), True, None),
    ("scoped-ambiguous", "ambiguous-qualifier", lambda: _artifact_verdict(_AMBIG, "0.50", "recall_set"), True, None),
    ("scoped-llm", "synonym-subset", lambda: _artifact_verdict(_CAT, "0.50", "recall_minority", model="m",
                                                               scope_json={"column": "variant_class", "value": "rare"}), False, VD.CONFIRMED),
    ("scoped-llm", "llm-cant-launder", lambda: _artifact_verdict(_CAT, "0.80", "recall_minority", model="m",
                                                                 scope_json={"column": "variant_class", "value": "rare"}), True, None),
    ("unscoped", "plain-recall-bool", lambda: _artifact_verdict(_BOOL, "0.50", "recall"), False, VD.CONFIRMED),
    ("unscoped", "plain-recall-cat", lambda: _artifact_verdict(_CAT, "0.80", "recall"), False, VD.CONFIRMED),
    ("unscoped", "plain-recall-wrong", lambda: _artifact_verdict(_CAT, "0.55", "recall"), True, None),
    # end-to-end make-runnable fault classes
    ("hardcoded-path", "abs-relink-capped", lambda: _pipeline_verdict("/no/such/dir/data.csv", True), False, VD.REPRODUCED_ONLY),
    ("repo-bug", "missing-data-honest", lambda: _pipeline_verdict("/no/such/dir/data.csv", False), True, None),
]


def main() -> int:
    per: dict = {}
    cov_hit = cov_total = fc_bad = fc_total = 0
    fails = []
    for fault, name, thunk, adversarial, expect in CORPUS:
        try:
            verdict = thunk()
        except Exception as e:  # noqa: BLE001 — a case that errors is a corpus failure, surfaced
            verdict = "ERROR: %s" % str(e)[:80]
        affirmative = verdict in VD.AFFIRMATIVE
        p = per.setdefault(fault, {"cov_h": 0, "cov_t": 0, "adv_bad": 0, "adv_t": 0})
        if adversarial:
            p["adv_t"] += 1
            fc_total += 1
            if affirmative:
                p["adv_bad"] += 1
                fc_bad += 1
                fails.append("FCR  [%s/%s] → %s (must not confirm)" % (fault, name, verdict))
        else:
            p["cov_t"] += 1
            cov_total += 1
            if verdict == expect:
                p["cov_h"] += 1
                cov_hit += 1
            else:
                fails.append("COV  [%s/%s] → %s (expected %s)" % (fault, name, verdict, expect))

    fcr = (fc_bad / fc_total) if fc_total else 0.0
    coverage = (cov_hit / cov_total) if cov_total else 1.0
    print("== adaptive edge-case brain — §7 meta-eval ==")
    for fault in sorted(per):
        q = per[fault]
        print("  %-16s coverage %d/%d   false-confirm %d/%d"
              % (fault, q["cov_h"], q["cov_t"], q["adv_bad"], q["adv_t"]))
    print("  %-16s coverage %d/%d (%.0f%%)   FALSE-CONFIRM %d/%d (%.1f%%)"
          % ("TOTAL", cov_hit, cov_total, 100 * coverage, fc_bad, fc_total, 100 * fcr))
    for f in fails:
        print("  " + f)

    if fcr > 0.05:
        print("FCR GATE FAILED: false-confirm rate %.1f%% > 5%%" % (100 * fcr))
        return 1
    if coverage < 1.0:
        print("COVERAGE REGRESSION: %.0f%% of valid cases reached the expected verdict" % (100 * coverage))
        return 1
    print("edgecases: OK (coverage %.0f%%, false-confirm %.1f%%)" % (100 * coverage, 100 * fcr))
    return 0


if __name__ == "__main__":
    sys.exit(main())
