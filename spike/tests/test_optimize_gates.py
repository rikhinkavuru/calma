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

import anomaly_eval  # noqa: E402
import binding  # noqa: E402
import bounty  # noqa: E402
import convention_fuzz  # noqa: E402
import corpus_synth  # noqa: E402
import discovery_eval  # noqa: E402
import edge_stress  # noqa: E402
import fabrication  # noqa: E402
import repair as repair_eval  # noqa: E402
import formula_fuzz_eval  # noqa: E402
import interval_eval  # noqa: E402
import leakage_stress  # noqa: E402
import metamorphic_eval  # noqa: E402
import recompute_stress  # noqa: E402
import stochastic  # noqa: E402
import redteam  # noqa: E402
import xcheck_eval  # noqa: E402


def test_adversarial_false_confirm_is_zero():
    """#13 — the franchise. NO engineered attack may yield an AFFIRMATIVE verdict (CONFIRMED or the weaker
    CONFIRMED-STOCHASTIC)."""
    breaches = [name for name, claim, runs in redteam.attacks()
                if D.diff_claim(claim, runs)["verdict"] in VD.AFFIRMATIVE]
    assert breaches == [], "adversarial false-confirm breach: %s" % breaches


def test_inline_redteam_gate_holds_and_is_precise():
    """Feature 8 — the inline red-team gate. After the gate, adversarial-FCR is still 0 (downgrade-only can
    never add a confirm), AND no legitimately-CONFIRMED claim is downgraded (the precision guard)."""
    assert redteam.main() == 0


def test_formula_fuzz_catches_cheats_without_false_invalidating():
    """Feature 2 — fuzz-the-formula. Honest + convention-legit formulas survive (false-INVALIDATED 0), every
    cheating formula is caught, and a coincidentally-right cheat never reaches CONFIRMED with fuzz on."""
    m = formula_fuzz_eval.measure()
    assert m["false_confirm_rate"] == 0.0, m
    assert m["false_invalidated_rate"] == 0.0, m["false_invalidated"]
    assert m["catch_rate"] == 1.0, m["missed"]


def test_metamorphic_relations_sound_and_catch_impostors():
    """Feature 7 — exact MRs hold on honest metrics (no false-INVALIDATED), catch an order-sensitive impostor,
    and a satisfied MR never confirms."""
    m = metamorphic_eval.measure()
    assert not m["false_invalidated"], m["false_invalidated"]
    assert m["catch_rate"] == 1.0 and m["mr_confirms"] == 0, m


def test_fabrication_detector_catches_constants_no_false_flags():
    """Feature 10 — hard-coded literals caught, genuine metrics never flagged, coincident constant never
    CONFIRMED with fuzz on."""
    m = fabrication.measure()
    assert m["false_confirm_rate"] == 0.0, m
    assert m["false_fabrication_flag_rate"] == 0.0, m["false_fabrication_flag"]
    assert m["catch_rate"] == 1.0, m["missed"]


def test_repair_loop_is_structurally_fcr_safe():
    """Feature 1 — the repair loop's action space is env-only, injected out-of-enum actions are refused, and
    the source-modified cap is downgrade-only → the loop can never manufacture a confirm."""
    m = repair_eval.measure()
    assert m["fcr_safe"] and m["false_confirm_rate"] == 0.0, m


def test_anomaly_overlay_is_advisory_and_never_confirms_or_refutes():
    """Feature 11 — the cross-run anomaly overlay flags outliers as ADVISORY only: it never sets CONFIRMED and
    never auto-REFUTES, with good flag precision."""
    m = anomaly_eval.measure()
    assert m["false_confirm_rate"] == 0.0 and m["auto_refute_rate"] == 0.0, m
    assert m["flag_precision"] >= 0.8 and m["outlier_flagged_advisory"], m


def test_stochastic_verification_holds_fcr_and_power_gate():
    """Feature 6 — a claim clearly outside the run-to-run distribution never reaches CONFIRMED-STOCHASTIC
    (FCR=0), the power gate blocks it below k_min, and in-distribution claims do confirm."""
    m = stochastic.measure()
    assert m["false_confirm_rate"] == 0.0 and m["low_k_confirms"] == 0, m
    assert m["honest_confirm_rate"] >= 0.8 and m["catch_rate"] == 1.0, m


def test_differential_recompute_downgrades_on_oracle_disagreement():
    """Feature 17 — two independent recompute paths must agree: a buggy shadow oracle downgrades the verdict
    (never confirms through it), and agreement preserves the CONFIRM."""
    m = xcheck_eval.measure()
    assert m["disagreement_downgrades"] and m["false_confirm_rate"] == 0.0, m
    assert m["agreement_preserves_confirm"], m


def test_certified_enclosures_are_sound_and_fail_closed():
    """Feature 19 — the certified enclosure always contains the exact value (soundness) and a well-conditioned
    CONFIRMED is preserved; straddling enclosures fail closed (proven in test_intervals)."""
    m = interval_eval.measure()
    assert m["sound"], m["soundness_failures"][:3]
    assert m["well_conditioned_confirm_preserved"], m


def test_bounty_wild_fcr_is_zero():
    """Feature 9 — the standing attack corpus yields ZERO valid bounties (the engine holds FCR=0); a
    false-CONFIRM is the only Critical, and triage flags exactly that."""
    valid = [nm for nm, claim, runs in redteam.attacks()
             if bounty.triage({"claim": claim, "runs": runs, "metric": claim.get("metric"),
                               "capability": nm})["is_false_confirm"]]
    assert valid == [], valid


def test_convention_search_never_confirms_a_fabricated_value():
    """§B.2 rule 8 — the coincidental-value fuzz. As the convention grid grows, a FABRICATED value must never
    coincidentally match a standard convention and reach CONFIRMED. The standing FCR proof for the registry."""
    m = convention_fuzz.measure(n_per_metric=300)
    assert m["false_confirms"] == 0, m["breaches"][:10]


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
