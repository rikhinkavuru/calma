"""Roadmap #4 — the message-intake guard, as an engine invariant.

The packaged stop-hook (old engine, `legacy/`) false-REFUTED a bare number "0.89" scraped from a chat
message: it bound the number to an auto-picked artifact with no repo producing-code behind it and let the
verdict reach REFUTED. The rebuild's rule: a bare number with NO producing computation in the repo must be
DISCOVERED / INCONCLUSIVE (fail-closed), never REFUTED — you cannot refute a number you never reproduced.

This test locks that behavior in the spike engine (the correct backend for any future hook), so the
message-intake path inherits the guard for free instead of re-deriving it in a separate codebase. It also
checks the guard does NOT over-suppress a real catch: when the repo genuinely computes the metric, a wrong
number is still REFUTED."""
import tempfile

import pipeline


def _opts(claims, **kw):
    return pipeline.VerifyOptions(runner="local", deep=True, entry="eval.py", discover=False, k=2,
                                  timeout=60, plan=False, hooks="sklearn", claims=claims, **kw)


def _repo(src):
    d = tempfile.mkdtemp()
    with open("%s/eval.py" % d, "w") as fh:
        fh.write(src)
    return d


def test_bare_number_with_no_producing_code_is_not_refuted():
    # a repo that computes nothing; a bare "0.89" from a message must NOT be refuted (nothing to reproduce).
    d = _repo("print('hello, no metric computed here')\n")
    out = pipeline.verify_repo(d, _opts([{"metric": "accuracy", "value": "0.89"}]))
    v = out["claims"][0]["verdict"]
    assert v in ("DISCOVERED", "INCONCLUSIVE"), out["claims"][0]
    assert v not in ("REFUTED", "CONFIRMED", "CONFIRMED-STOCHASTIC")


def test_wrong_number_is_still_refuted_when_the_repo_computes_it():
    # the guard must not over-suppress: when the repo actually produces the metric, a wrong claim is caught.
    src = ("from sklearn.metrics import accuracy_score\n"
           "y_true = [0, 1, 0, 1, 0, 1, 0, 1, 0, 1]\n"
           "y_pred = [0, 1, 0, 1, 0, 1, 0, 1, 0, 1]\n"      # perfect: accuracy 1.0
           "print('accuracy', accuracy_score(y_true, y_pred))\n")
    out = pipeline.verify_repo(_repo(src), _opts([{"metric": "accuracy", "value": "0.50"}]))
    assert out["claims"][0]["verdict"] == "REFUTED", out["claims"][0]
