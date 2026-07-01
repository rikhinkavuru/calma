"""Feature 11 — cross-run anomaly detection. Advisory/downgrade-only: a value unusual vs the verified-run
history is FLAGGED, never auto-REFUTED (a genuine SOTA is also an outlier) and never auto-CONFIRMED. These pin
the robust detector's guards (min_n, MAD=0), the no-poison store update, and the advisory-only overlay."""
import os
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from core import anomaly as ANOM  # noqa: E402
from core import refstore as RS  # noqa: E402
from core import verdict as VD  # noqa: E402
import pipeline as P  # noqa: E402

_HIST = [0.79, 0.81, 0.80, 0.82, 0.78, 0.80, 0.81, 0.79, 0.80, 0.82, 0.78, 0.81, 0.80, 0.79, 0.81, 0.80]


def test_robust_z_flags_an_outlier():
    z = ANOM.robust_z(0.99, _HIST)
    assert z["is_outlier"] and not z["degenerate"]


def test_robust_z_inlier_not_flagged():
    z = ANOM.robust_z(0.805, _HIST)
    assert not z["is_outlier"]


def test_robust_z_min_n_gate():
    z = ANOM.robust_z(0.99, [0.80, 0.81, 0.79])   # n=3 < min_n
    assert not z["is_outlier"] and z["degenerate"]


def test_robust_z_mad_zero_no_crash_no_flag():
    z = ANOM.robust_z(0.99, [0.80] * 20)          # zero-spread reference
    assert not z["is_outlier"] and z["degenerate"]


def test_refstore_append_and_values(tmp_path):
    s = RS.RefStore(str(tmp_path / "ref.json"))
    s.append("human_promoters", "accuracy", 0.8)
    s.append("Human Promoters", "accuracy", 0.82)   # normalized to the same key
    assert sorted(s.values("human-promoters", "accuracy")) == [0.8, 0.82]


def _rec(verdict, produced, dataset):
    return {"id": "c", "metric": "accuracy", "verdict": verdict,
            "diff": {"produced": produced, "recomputed": produced},
            "context": "dataset=%s" % dataset, "location": "", "validity": {"invalidating": [], "advisory": []}}


def test_overlay_flags_outlier_but_does_not_change_verdict(tmp_path):
    store = RS.RefStore(str(tmp_path / "r.json"))
    for v in _HIST:
        store.append("ds1", "accuracy", v)
    rec = _rec(VD.CONFIRMED, 0.99, "ds1")
    P._apply_anomaly_overlay([rec], store)
    assert rec["verdict"] == VD.CONFIRMED                       # never auto-refuted / changed
    assert any("cross-run outlier" in a for a in rec["validity"]["advisory"])
    assert rec.get("anomaly", {}).get("is_outlier")


def test_overlay_ignores_unverified_for_store_update(tmp_path):
    store = RS.RefStore(str(tmp_path / "r.json"))
    P._apply_anomaly_overlay([_rec(VD.REFUTED, 0.99, "ds2"), _rec(VD.INCONCLUSIVE, 0.5, "ds2")], store)
    assert store.values("ds2", "accuracy") == []               # unverified verdicts never poison the baseline
    P._apply_anomaly_overlay([_rec(VD.CONFIRMED, 0.8, "ds2")], store)
    assert store.values("ds2", "accuracy") == [0.8]            # a verified record does update it
