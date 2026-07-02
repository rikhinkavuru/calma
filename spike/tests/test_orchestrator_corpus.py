"""The orchestrator corpus gate (build plan §7 Phase 2/3 gate): on the fixture set, the orchestrated
make-runnable path must (a) reproduce the heuristic baseline exactly — same count of affirmative (CONFIRMED)
verdicts, so coverage never regresses — and (b) hold FCR==0 — no cheat/trivial fixture ever reaches an
affirmative verdict. This is the fast, hermetic stand-in for the full 10-repo GO/NO-GO corpus run.

A parity DIFF here means the orchestrator changed a verdict vs the deterministic baseline (it must not — it
only changes HOW a repo runs). An FCR failure means a wrong number went green (the cardinal sin)."""
import os
import sys

import pytest

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from core import verdict as VD  # noqa: E402
from pipeline import VerifyOptions, verify_repo  # noqa: E402

FIX = os.path.join(_SPIKE, "fixtures")
_POS = set(VD.AFFIRMATIVE)

# representative subset: the fixtures that CONFIRM (parity must hold) + the adversarial ones (FCR must hold).
CONFIRMING = ["clean_eval", "mcc_eval", "e2b_smoke", "gridsearch_multi"]
ADVERSARIAL = ["main_metric_cheat", "finance_sharpe_cheat", "trivial_baseline", "main_metric_cheat"]


def _affirmative_count(repo, orchestrate):
    r = verify_repo(repo, VerifyOptions(deep=True, orchestrate=orchestrate, discover=True, k=2, plan=False))
    return sum(v for k, v in r["counts"].items() if k in _POS), r


@pytest.mark.parametrize("name", CONFIRMING)
def test_orchestrated_reproduces_heuristic_confirmations(name):
    repo = os.path.join(FIX, name)
    if not os.path.isdir(repo):
        pytest.skip("fixture %s absent" % name)
    heuristic, _ = _affirmative_count(repo, False)
    orchestrated, _ = _affirmative_count(repo, True)
    assert orchestrated == heuristic, ("%s: orchestrated affirmative=%d != heuristic=%d (coverage regression)"
                                       % (name, orchestrated, heuristic))
    assert orchestrated >= 1, "%s should confirm at least one claim on both paths" % name


@pytest.mark.parametrize("name", sorted(set(ADVERSARIAL)))
def test_orchestrated_never_confirms_a_cheat(name):
    repo = os.path.join(FIX, name)
    if not os.path.isdir(repo):
        pytest.skip("fixture %s absent" % name)
    orchestrated, r = _affirmative_count(repo, True)
    assert orchestrated == 0, "FCR VIOLATION: %s reached an affirmative verdict via the orchestrator: %s" % (
        name, r["counts"])
