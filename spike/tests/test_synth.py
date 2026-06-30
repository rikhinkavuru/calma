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


def test_synth_machinery_synthesizes_validates_banks_reuses(tmp_path):
    # the synth machinery directly (recompute_any now routes mcc to the lifted recipe catalog first;
    # synth is the fallback for the long tail beyond catalog+recipes).
    store = LocalStore(path=str(tmp_path / "s.json"))
    rec = F._synthesize_and_validate("mcc", store)         # synthesize + validate vs sklearn + bank
    assert rec is not None and rec.metric == "mcc"
    rng = random.Random(1)
    yt = [rng.randint(0, 1) for _ in range(140)]
    yp = [rng.randint(0, 1) for _ in range(140)]
    hit = store.lookup("phi coefficient", text="matthews correlation coefficient")  # reuse by paraphrase
    assert hit is not None and hit[0].metric == "mcc"
    assert abs(F.exec_formula(hit[0].code, {"y_true": yt, "y_pred": yp}, {}) - matthews_corrcoef(yt, yp)) < 1e-9


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
    F._synthesize_and_validate("mcc", store)                      # bank via synth machinery
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
    # spearman is NOT in the core catalog (unlike mcc/cohen_kappa, now ported to it), so it is the metric
    # that genuinely exercises the flywheel-through-diff path: synthesize/recipe → validate → CONFIRMED.
    store = LocalStore(path=str(tmp_path / "s.json"))
    resolver = lambda m, i, k: F.recompute_any(m, i, k, store=store)  # noqa: E731
    rng = random.Random(7)
    x = [rng.random() for _ in range(160)]
    y = [xi * 2.0 + rng.random() * 0.3 for xi in x]      # strongly (monotonically) correlated
    val = float(spearmanr(x, y)[0])
    call = {"seq": 0, "sink": "scipy.stats.spearmanr", "metric": "spearmanr",
            "inputs": {"x": x, "y": y}, "kwargs": {}, "result": val, "captured_full": True}
    runs = [[dict(call)], [dict(call)]]
    rec = D.diff_claim({"id": "m", "metric": "spearmanr", "value": "%.4f" % val}, runs, resolver=resolver)
    assert rec["verdict"] == VD.CONFIRMED, rec
    # not in the core catalog → resolved through the flywheel (recipe / synth / banked store)
    assert rec["recompute_provenance"] in ("recipe", "synth", "store:local")

    # a misreported value -> REFUTED (the flywheel makes it checkable, so it can be broken too)
    rec2 = D.diff_claim({"id": "m", "metric": "spearmanr", "value": "%.4f" % (val - 0.3)}, runs, resolver=resolver)
    assert rec2["verdict"] == VD.REFUTED, rec2
