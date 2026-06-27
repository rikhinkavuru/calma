"""The catalog flywheel: synthesize a formula for an unknown metric, VALIDATE it against sklearn/scipy,
bank it, and reuse it — and prove an unknown metric now reaches CONFIRMED through the diff. Also that the
restricted executor blocks anything but safe math."""
import random

import pytest
from scipy.stats import spearmanr
from sklearn.metrics import cohen_kappa_score, matthews_corrcoef

from core import diff as D
from core import verdict as VD
from synth import formula as F
from synth.store import LocalStore


def test_synthesized_formulas_validate_vs_reference():
    for m in ("mcc", "cohen_kappa", "spearman"):
        ok, ev = F._validate_synth(m, F.SYNTH_REGISTRY[m]["code"])
        assert ok, (m, ev)
        assert ev["max_err"] < 1e-9, (m, ev)


def test_unknown_metric_synthesizes_then_reuses(tmp_path):
    store = LocalStore(path=str(tmp_path / "s.json"))
    rng = random.Random(1)
    yt = [rng.randint(0, 1) for _ in range(140)]
    yp = [rng.randint(0, 1) for _ in range(140)]
    # first encounter -> synthesize + validate + bank
    r = F.recompute_any("matthews_corrcoef", {"y_true": yt, "y_pred": yp}, {}, store=store)
    assert r["provenance"] == "synth" and not r["degenerate"]
    assert abs(r["value"] - matthews_corrcoef(yt, yp)) < 1e-9
    # second encounter (even a paraphrase) -> fast store reuse, no re-synthesis
    r2 = F.recompute_any("phi coefficient", {"y_true": yt, "y_pred": yp}, {}, store=store)
    assert r2["provenance"].startswith("store")
    assert abs(r2["value"] - matthews_corrcoef(yt, yp)) < 1e-9


def test_kappa_and_spearman_resolve(tmp_path):
    store = LocalStore(path=str(tmp_path / "s.json"))
    rng = random.Random(3)
    yt = [rng.randint(0, 2) for _ in range(120)]
    yp = [rng.randint(0, 2) for _ in range(120)]
    rk = F.recompute_any("cohen_kappa_score", {"y_true": yt, "y_pred": yp}, {}, store=store)
    assert abs(rk["value"] - cohen_kappa_score(yt, yp)) < 1e-9
    x = [rng.gauss(0, 1) for _ in range(120)]
    y = [rng.gauss(0, 1) for _ in range(120)]
    rs = F.recompute_any("spearmanr", {"x": x, "y": y}, {}, store=store)
    ref = spearmanr(x, y)
    assert abs(rs["value"] - float(getattr(ref, "correlation", getattr(ref, "statistic", 0.0)))) < 1e-9


def test_store_vector_match_for_paraphrase(tmp_path):
    store = LocalStore(path=str(tmp_path / "s.json"))
    F.recompute_any("mcc", {"y_true": [0, 1, 1, 0], "y_pred": [0, 1, 0, 0]}, {}, store=store)
    assert store.lookup("matthews_corrcoef") is not None          # exact alias
    hit = store.lookup("matthews correlation", text="matthews correlation coefficient")  # semantic
    assert hit is not None and hit[0].metric == "mcc"


def test_restricted_exec_blocks_imports_and_io():
    with pytest.raises(Exception):
        F.exec_formula("def recompute(I, K):\n import os\n return 1.0", {}, {})
    with pytest.raises(Exception):
        F.exec_formula("def recompute(I, K):\n return open('/etc/passwd').read()", {}, {})
    # a legitimate pure-math formula still runs
    assert F.exec_formula("def recompute(I, K):\n return math.sqrt(sum(I['v']))", {"v": [1, 3]}, {}) == 2.0


def test_diff_resolves_unknown_metric_to_confirmed(tmp_path):
    store = LocalStore(path=str(tmp_path / "s.json"))
    resolver = lambda m, i, k: F.recompute_any(m, i, k, store=store)  # noqa: E731
    rng = random.Random(7)
    yt = [rng.randint(0, 1) for _ in range(160)]
    yp = [rng.randint(0, 1) for _ in range(160)]
    val = float(matthews_corrcoef(yt, yp))
    call = {"seq": 0, "sink": "sklearn.metrics.matthews_corrcoef", "metric": "mcc",
            "inputs": {"y_true": yt, "y_pred": yp}, "kwargs": {}, "result": val, "captured_full": True}
    runs = [[dict(call)], [dict(call)]]
    rec = D.diff_claim({"id": "m", "metric": "mcc", "value": "%.4f" % val}, runs, resolver=resolver)
    assert rec["verdict"] == VD.CONFIRMED, rec
    assert rec["recompute_provenance"] in ("synth", "store:local")

    # a misreported MCC -> REFUTED (the flywheel makes it checkable, so it can be broken too)
    rec2 = D.diff_claim({"id": "m", "metric": "mcc", "value": "%.4f" % (val + 0.2)}, runs, resolver=resolver)
    assert rec2["verdict"] == VD.REFUTED, rec2
