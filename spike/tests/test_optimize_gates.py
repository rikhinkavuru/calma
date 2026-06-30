"""Franchise invariants as permanent CI gates.

The optimize/ meta-eval found/holds these; pinning them here means a future change can't silently regress
them. Only the pure-synthetic instruments (no fixture captures needed) are gated — they construct their
captures in-process. Run in the spike venv (needs numpy/sklearn for the recompute stress).
"""
import os
import sys

_OPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "optimize")
sys.path.insert(0, _OPT)

from core import diff as D  # noqa: E402
from core import verdict as VD  # noqa: E402

import binding  # noqa: E402
import corpus_synth  # noqa: E402
import discovery_eval  # noqa: E402
import edge_stress  # noqa: E402
import leakage_stress  # noqa: E402
import recompute_stress  # noqa: E402
import redteam  # noqa: E402


def test_adversarial_false_confirm_is_zero():
    """#13 — the franchise. NO engineered attack may yield CONFIRMED."""
    breaches = [name for name, claim, runs in redteam.attacks()
                if D.diff_claim(claim, runs)["verdict"] in VD.POSITIVE]
    assert breaches == [], "adversarial false-confirm breach: %s" % breaches


def test_binding_never_overbinds_and_is_correct():
    """#4/#5 — bind only when there's a unique answer, always to the right call, never an ambiguous one."""
    m = binding.measure(binding.scenarios())
    assert m["over_bind_rate"] == 0.0, m["dangers"]
    assert m["bind_correctness"] == 1.0, m["bugs"]
    assert m["bind_rate"] == 1.0, m["bugs"]


def test_leakage_detector_no_false_positive_and_full_catch():
    """#8b — clean disjoint splits never flagged; contamination at/above threshold always caught."""
    ex = leakage_stress.run_axis(leakage_stress.contaminate_exact, sequences=False, threshold=0.01)
    ho = leakage_stress.run_axis(leakage_stress.contaminate_homology, sequences=True, threshold=0.05)
    for m in (ex, ho):
        assert m["false_positive"] == 0 and m["sub_threshold_flagged"] == 0
        assert m["catch_rate"] == 1.0


def test_recompute_matches_sklearn_on_subtle_inputs():
    """#8/#1-dual — the oracle agrees with sklearn (no false-INVALIDATE) on averaging/ties/coercion."""
    bugs = [r for r in (recompute_stress._check(*c) for c in recompute_stress.cases()) if r["recompute_bug"]]
    assert bugs == [], bugs


def test_discovery_prose_recall_and_precision():
    """#9 — prose claims are extracted (recall) without hallucinating (precision)."""
    s, p = discovery_eval._score(discovery_eval.STRUCTURED), discovery_eval._score(discovery_eval.PROSE)
    assert s["recall"] == 1.0 and s["precision"] == 1.0
    assert p["recall"] >= 0.9 and (p["precision"] or 1.0) >= 0.9


def test_harder_corpus_full_confusion_clean():
    """The harder corpus: EVERY catalog metric (binary/multiclass/averaging/regression/reductions/finance)
    passes the full confusion — honest→CONFIRMED, misreport→REFUTED, wrong-formula→INVALIDATED — with no
    false-confirm / false-refute / false-invalidate. The strongest cross-metric franchise gate."""
    m = corpus_synth.score(corpus_synth.measure())
    assert m["false_confirm_rate"] == 0.0, m["gaps"]
    assert m["false_refute_rate"] == 0.0 and m["false_invalidate_rate"] == 0.0, m["gaps"]
    assert m["misreport_catch_rate"] == 1.0 and m["wrong_formula_catch_rate"] == 1.0, m["gaps"]
    assert m["honest_confirm_rate"] == 1.0, m["gaps"]


def test_edge_numerics_fail_closed_and_valid_extremes_confirm():
    """Degenerate/invalid inputs (zero-variance Sharpe, constant-target R², all-equal AUC, single-class,
    NaN) must NEVER confirm; valid extremes (1e9 scale, 1e-8 magnitude, huge outliers) must still confirm."""
    rows = edge_stress.cases()
    false_confirms = [lbl for lbl, exp, v in rows if not exp and v == VD.CONFIRMED]
    valid_misses = [lbl for lbl, exp, v in rows if exp and v != VD.CONFIRMED]
    assert false_confirms == [], false_confirms
    assert valid_misses == [], valid_misses
