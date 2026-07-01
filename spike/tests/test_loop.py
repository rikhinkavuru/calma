"""End-to-end proof of the spike loop: run a fixture repo -> capture the metric inputs at runtime ->
recompute independently -> three-way diff -> verdict. One fixture per verdict. This is the de-risking
evidence that the whole pipeline routes correctly, and (critically) that a wrong number never earns a
false CONFIRMED.
"""
import os

from core import catalog as C
from core import diff as D
from core import verdict as VD
from runner.local_runner import run_local

FIX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")


def _run(name, k=2, **kw):
    r = run_local(os.path.join(FIX, name), ["eval.py"], k=k, **kw)
    assert r["ran_ok"], "fixture %s failed: %s" % (name, r["meta"])
    return r


def _produced(runs, metric, occ=0):
    cid = C.canonical(metric)
    cands = sorted([c for c in runs[0] if C.canonical(c.get("metric") or "") == cid],
                   key=lambda c: c["seq"])
    return cands[occ]["result"]


def test_confirmed():
    r = _run("clean_eval")
    for metric in ("accuracy", "roc_auc"):
        p = _produced(r["runs"], metric)
        # claims arrive as text (a README/table string), e.g. "0.8237" — the rounding-aware path
        rec = D.diff_claim({"id": metric, "metric": metric, "value": f"{p:.4f}"}, r["runs"])
        assert rec["verdict"] == VD.CONFIRMED, (metric, rec)


def test_refuted():
    r = _run("clean_eval")
    p = _produced(r["runs"], "accuracy")
    # README overstates the number by 0.1
    rec = D.diff_claim({"id": "acc", "metric": "accuracy", "value": f"{p + 0.1:.4f}"}, r["runs"])
    assert rec["verdict"] == VD.REFUTED, rec


def test_invalidated_by_formula():
    targets = [{"target": "metrics.my_accuracy", "metric": "accuracy",
                "inputs": {"y_true": "arg0", "y_pred": "arg1"}}]
    r = _run("custom_metric", targets=targets)
    p = _produced(r["runs"], "accuracy")
    assert abs(p - 1.0) < 1e-9, "repo should report a perfect 1.0, got %r" % p
    # they report the (wrong) 1.0 honestly, so it is NOT refuted — it is invalid (formula disagrees)
    rec = D.diff_claim({"id": "acc", "metric": "accuracy", "value": 1.0}, r["runs"])
    assert rec["verdict"] == VD.INVALIDATED, rec
    assert rec["diff"]["recomputed"] < 0.6  # independent recompute ≈ chance


def test_invalidated_by_validity():
    r = _run("trivial_baseline")
    p = _produced(r["runs"], "accuracy")
    rec = D.diff_claim({"id": "acc", "metric": "accuracy", "value": f"{p:.4f}"}, r["runs"])
    assert rec["verdict"] == VD.INVALIDATED, rec
    assert any("majority-class" in s for s in rec["validity"]["invalidating"]), rec["validity"]


def test_non_deterministic():
    r = _run("nondeterministic")
    p = _produced(r["runs"], "accuracy")          # run-0 value (4 decimals -> well inside claim tolerance)
    rec = D.diff_claim({"id": "acc", "metric": "accuracy", "value": f"{p:.4f}"}, r["runs"])
    assert rec["verdict"] == VD.NON_DETERMINISTIC, rec
    assert rec["determinism"]["tested"] and not rec["determinism"]["stable"]


def test_inconclusive_ambiguous_then_scoped():
    r = _run("two_splits")
    # bare claim -> ambiguous (two accuracy computations) -> INCONCLUSIVE
    rec = D.diff_claim({"id": "acc", "metric": "accuracy", "value": 0.55}, r["runs"])
    assert rec["verdict"] == VD.INCONCLUSIVE and rec["binding"]["ambiguous"], rec
    # scoped to the test computation (occurrence 1) -> resolves
    p_test = _produced(r["runs"], "accuracy", occ=1)
    rec2 = D.diff_claim({"id": "acc", "metric": "accuracy", "value": round(p_test, 3),
                         "bind": {"occurrence": 1}}, r["runs"])
    assert rec2["verdict"] == VD.CONFIRMED, rec2


def test_reproduced_only_learned_metric():
    """A LEARNED/embedding metric (BERTScore) reproduces but cannot be independently recomputed → the honest
    fail-closed REPRODUCED-ONLY, never CONFIRMED (guide §B.3 (c))."""
    r = _run("unknown_metric")
    p = _produced_explicit(r["runs"], "bertscore")
    rec = D.diff_claim({"id": "b", "metric": "bertscore", "value": "%.4f" % p}, r["runs"],
                       resolver=__import__("synth.formula", fromlist=["recompute_any"]).recompute_any)
    assert rec["verdict"] == VD.REPRODUCED_ONLY, rec
    assert "learned" in rec.get("reason", "").lower(), rec


def _produced_explicit(runs, metric):
    cands = [c for c in runs[0] if (c.get("metric") or "").lower() == metric.lower()]
    return cands[0]["result"]


def test_no_false_confirm_across_fixtures():
    """The franchise rule: the only fixture that may be CONFIRMED is the clean one. Every wrong/invalid/
    unstable/ambiguous fixture must land on a non-positive verdict."""
    bad = {
        "custom_metric": (VD.INVALIDATED, [{"target": "metrics.my_accuracy", "metric": "accuracy",
                                            "inputs": {"y_true": "arg0", "y_pred": "arg1"}}]),
        "trivial_baseline": (VD.INVALIDATED, None),
        "nondeterministic": (VD.NON_DETERMINISTIC, None),
    }
    for name, (expected, targets) in bad.items():
        r = _run(name, targets=targets)
        p = _produced(r["runs"], "accuracy")
        rec = D.diff_claim({"id": "acc", "metric": "accuracy", "value": f"{p:.4f}"}, r["runs"])
        assert rec["verdict"] != VD.CONFIRMED, "FALSE CONFIRM on %s: %s" % (name, rec)
        assert rec["verdict"] == expected, (name, rec["verdict"])
