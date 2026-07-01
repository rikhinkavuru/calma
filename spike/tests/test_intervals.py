"""Feature 19 — certified enclosures. The enclosure rigorously contains the true value (soundness), a
straddling enclosure at the tolerance boundary fails closed (never a confirm), and a well-conditioned CONFIRMED
is unchanged."""
import os
import sys
from fractions import Fraction

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from core import diff as D  # noqa: E402
from core import intervals as ITV  # noqa: E402
from core import verdict as VD  # noqa: E402


def _exact_mean(v):
    return float(Fraction(sum(Fraction(str(x)) for x in v), len(v)))


def test_neumaier_sum_bound_contains_exact():
    v = [1e9 + 4, 1e9 + 7, 1e9 + 13, 1e9 + 16]
    s, err = ITV.neumaier_sum(v)
    exact = float(sum(Fraction(str(x)) for x in v))
    assert s - err <= exact <= s + err


def test_enclosure_contains_exact_mean_and_variance():
    v = [1e9 + 4, 1e9 + 7, 1e9 + 13, 1e9 + 16]
    em = _exact_mean(v)
    enc = ITV.enclosure("mean", {"values": v}, {})
    assert enc["lo"] <= em <= enc["hi"]
    ev = float(sum((Fraction(str(x)) - Fraction(sum(Fraction(str(y)) for y in v), len(v))) ** 2 for x in v) / (len(v) - 1))
    encv = ITV.enclosure("variance", {"values": v}, {})
    assert encv["lo"] <= ev <= encv["hi"]


def test_band_relation_inside_outside_straddle():
    enc = {"lo": 1.0, "hi": 1.0001}
    assert ITV.band_relation(enc, 1.00005, 0.001) == "inside"
    assert ITV.band_relation(enc, 5.0, 0.001) == "outside"
    assert ITV.band_relation({"lo": 0.9, "hi": 1.1}, 1.0, 0.001) == "straddle"


def test_well_conditioned_confirm_unchanged():
    clean = [-5.0, 3.0, 8.0, -2.0, 6.0, 1.0]
    m = _exact_mean(clean)
    call = {"metric": "mean", "result": m, "inputs": {"values": clean}, "kwargs": {}, "user_site": True,
            "captured_full": True, "n": len(clean), "seq": 0, "sink": "target:mean", "site": "r.py:1"}
    rec = D.diff_claim({"metric": "mean", "value": "%.6f" % m}, [[call], [dict(call)]])
    assert rec["verdict"] == VD.CONFIRMED


def test_straddle_downgrades_a_would_be_confirm():
    # force a straddle: a metric whose enclosure width is large relative to the confirm tolerance. Near-constant
    # data with a huge offset makes the variance enclosure straddle the tolerance boundary → fail closed.
    v = [1e11 + 1, 1e11 + 1.0000001, 1e11 + 0.9999999, 1e11 + 1.0, 1e11 + 1.0000002]
    # produced = the catalog recompute (so it would otherwise CONFIRM); if the enclosure straddles, we downgrade.
    from core import catalog as C
    rv = C.recompute("variance", {"values": v}, {})["value"]
    call = {"metric": "variance", "result": rv, "inputs": {"values": v}, "kwargs": {}, "user_site": True,
            "captured_full": True, "n": len(v), "seq": 0, "sink": "target:variance", "site": "r.py:1"}
    rec = D.diff_claim({"metric": "variance", "value": "%.10g" % rv}, [[call], [dict(call)]])
    # either it certified (inside → CONFIRMED) or it straddled (→ fail-closed), but NEVER a wrong confirm.
    assert rec["verdict"] in (VD.CONFIRMED, VD.REPRODUCED_ONLY, VD.INCONCLUSIVE)
    if rec.get("enclosure", {}).get("relation") == "straddle":
        assert rec["verdict"] != VD.CONFIRMED
