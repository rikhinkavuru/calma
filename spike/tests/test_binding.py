"""Multi-candidate binding — the franchise-critical path. When a metric is computed many times (GridSearchCV
folds, multi-model scripts), bind to the repo's OWN computation, never by value-proximity (which would hide a
REFUTED). Adversarial: a wrong claim that happens to equal an internal fold's value must still REFUTE."""
import os
import sys

from core import diff as D
from core import verdict as VD

FIX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")


def acc_call(value, n, user_site, seq=0, sink="sklearn.metrics.accuracy_score"):
    """A captured accuracy call whose y_true/y_pred actually recompute to result=round(value*n)/n. Uses two
    balanced classes so the validity layer doesn't (correctly) flag a single-class/degenerate eval."""
    ones = round(value * n)
    yt = [i % 2 for i in range(n)]                     # two classes, ~balanced
    yp = list(yt)
    for j in range(n - ones):                          # introduce exactly (n-ones) errors
        yp[j] = 1 - yp[j]
    return {"metric": "accuracy", "result": ones / n, "inputs": {"y_true": yt, "y_pred": yp},
            "captured_full": True, "user_site": user_site, "n": n, "seq": seq, "sink": sink}


def claim_for(call, **extra):
    return {"metric": "accuracy", "value": "%.6f" % call["result"], **extra}


def test_gridsearch_collapse_confirms_headline():
    # 31 library-internal CV-fold accuracies (user_site=False) + the repo's own final accuracy (user_site=True)
    internal = [acc_call(0.90 + 0.001 * i, 24, False, seq=i) for i in range(31)]
    headline = acc_call(29 / 30, 30, True, seq=31)
    calls = internal + [headline]
    rec = D.diff_claim(claim_for(headline), [calls, calls])   # k=2 identical runs
    assert rec["verdict"] == VD.CONFIRMED
    assert "repo's own computation" in rec["binding"]["reason"]


def test_no_false_confirm_via_internal_fold_value():
    """The cardinal sin: a claim equal to an INTERNAL fold value (not the headline) must NOT confirm."""
    internal = [acc_call(0.80, 24, False, seq=0), acc_call(0.92, 24, False, seq=1)]
    headline = acc_call(29 / 30, 30, True, seq=2)               # 0.9667 is the real repo number
    calls = internal + [headline]
    rec = D.diff_claim({"metric": "accuracy", "value": "0.80"}, [calls, calls])  # 0.80 = an internal fold
    assert rec["verdict"] == VD.REFUTED                         # bound to the headline (0.9667), 0.80 ≠ it
    assert rec["verdict"] not in VD.POSITIVE


def test_split_by_size_picks_heldout_and_train():
    train = acc_call(0.99, 120, True, seq=0)                    # larger split
    test = acc_call(0.95, 30, True, seq=1)                      # smaller held-out split
    calls = [train, test]
    rec_t = D.diff_claim(claim_for(test, split="test"), [calls, calls])
    assert rec_t["verdict"] == VD.CONFIRMED and "smaller held-out" in rec_t["binding"]["reason"]
    rec_tr = D.diff_claim(claim_for(train, split="train"), [calls, calls])
    assert rec_tr["verdict"] == VD.CONFIRMED and "larger training" in rec_tr["binding"]["reason"]


def test_wrong_split_claim_does_not_confirm():
    """Claiming the TEST number but it actually equals TRAIN's — must not confirm (binds test by size)."""
    train = acc_call(0.99, 120, True, seq=0)
    test = acc_call(0.95, 30, True, seq=1)
    rec = D.diff_claim({"metric": "accuracy", "value": "%.6f" % train["result"], "split": "test"}, [calls := [train, test], calls])
    assert rec["verdict"] != VD.CONFIRMED                       # test computation is 0.95, claim is train's 0.99


def test_multimodel_same_size_is_ambiguous():
    # 3 models, same test set, no split hint → cannot tell which → fail-closed INCONCLUSIVE (never guess)
    calls = [acc_call(0.90, 30, True, seq=0), acc_call(0.95, 30, True, seq=1), acc_call(0.97, 30, True, seq=2)]
    rec = D.diff_claim({"metric": "accuracy", "value": "0.95"}, [calls])
    assert rec["verdict"] == VD.INCONCLUSIVE and rec["binding"]["ambiguous"]


def test_nondeterministic_headline_across_runs():
    internal = [acc_call(0.90, 24, False, seq=0)]
    h1 = acc_call(29 / 30, 30, True, seq=1)
    h2 = acc_call(28 / 30, 30, True, seq=1)                     # different value in run 2
    rec = D.diff_claim(claim_for(h1), [internal + [h1], internal + [h2]])
    assert rec["verdict"] == VD.NON_DETERMINISTIC


def test_backward_compatible_single_candidate():
    # one call, no user_site field at all (legacy capture) → still binds
    c = {"metric": "accuracy", "result": 0.8, "inputs": {"y_true": [0, 1, 0, 1, 0], "y_pred": [0, 1, 0, 1, 1]},
         "captured_full": True, "seq": 0}
    rec = D.diff_claim({"metric": "accuracy", "value": "0.8"}, [[c], [c]])
    assert rec["verdict"] == VD.CONFIRMED


def test_gridsearch_real_capture_end_to_end():
    """REAL proof of user_site: run actual GridSearchCV through the capture shim. sklearn computes accuracy
    many times internally (user_site=False); the repo's final accuracy_score is the one user-site call, and
    the binder collapses to it → CONFIRMED on the headline."""
    from runner.local_runner import run_local
    repo = os.path.join(FIX, "gridsearch_multi")
    r = run_local(repo, ["eval.py"], k=2, python=sys.executable)
    assert r["ran_ok"], r.get("meta")
    accs = [c for c in r["runs"][0] if c["metric"] == "accuracy"]
    user = [c for c in accs if c.get("user_site")]
    assert len(accs) > len(user) >= 1            # several library-internal + exactly the repo's own
    assert len(user) == 1
    headline = user[0]["result"]
    rec = D.diff_claim({"metric": "accuracy", "value": "%.6f" % headline}, r["runs"])
    assert rec["verdict"] == VD.CONFIRMED
    assert "repo's own computation" in rec["binding"]["reason"]
