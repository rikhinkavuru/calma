"""Phase 2 gate — the orchestrated make-runnable path, wired into verify_repo behind opts.orchestrate, must:
  * reproduce the heuristic baseline (find the entrypoint ITSELF, no explicit entry, and still CONFIRM), and
  * hold FCR==0 (a cheating custom metric is INVALIDATED, never falsely CONFIRMED), and
  * give up honestly (C3): no runnable entrypoint → DISCOVERED, never a fabricated eval.py.
Hermetic: local runner, harness python, no API key (conftest deletes it) → the orchestrator's static path."""
import os
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

import shutil  # noqa: E402

import pytest  # noqa: E402

from core import verdict as VD  # noqa: E402
from pipeline import VerifyOptions, verify_repo  # noqa: E402

FIX = os.path.join(_SPIKE, "fixtures")


@pytest.mark.skipif(not shutil.which("make"), reason="make not available")
def test_orchestrated_make_driven_repo_confirms(tmp_path):
    # a repo with NO detectable python entrypoint (compute hidden in steps/, not a known src dir) — only the
    # Makefile reproduces it. The orchestrator must classify it make-driven, run `make`, and CONFIRM through
    # the UNCHANGED verdict path (run_make routes exactly like run_local). Also the FCR proof for run_make:
    # the number is recomputed from the captured sklearn call, not trusted because make exited 0.
    repo = tmp_path / "mk"
    (repo / "steps").mkdir(parents=True)
    (repo / "steps" / "compute.py").write_text(
        "from sklearn.metrics import accuracy_score\n"
        "print('accuracy=%.4f' % accuracy_score([0,1,1,0],[0,1,1,1]))\n")     # = 0.75
    (repo / "Makefile").write_text("reproduce:\n\t%s steps/compute.py\n" % sys.executable)
    result = verify_repo(str(repo), VerifyOptions(deep=True, orchestrate=True, discover=True, k=2))
    assert result["run"]["ran"] is True
    accs = [c for c in result["claims"] if c["metric"] == "accuracy"]
    assert accs and any(c["verdict"] == VD.CONFIRMED for c in accs)


def test_orchestrated_confirms_clean_fixture_and_finds_its_own_entrypoint():
    # NOTE: no entry= given — the orchestrator must discover eval.py itself, then reproduce the baseline.
    result = verify_repo(os.path.join(FIX, "clean_eval"), VerifyOptions(
        deep=True, orchestrate=True, discover=False,
        claims=[{"id": "acc", "metric": "accuracy", "value": "0.831"},
                {"id": "auc", "metric": "roc_auc", "value": "0.942"}]))
    assert result["run"]["ran"] is True
    assert result["run"]["entry"].endswith("eval.py")      # found without being told
    assert result["counts"].get(VD.CONFIRMED) == 2         # same verdict as the heuristic path
    # the transparency requirement: the Assessment Report reached the trace/logs
    notes = [e["detail"] for e in result["trace"] if e.get("stage") == "note"]
    assert any("Assessment:" in n for n in notes)


def test_orchestrated_catches_cheating_metric_no_false_confirm():
    # main_metric_cheat reports accuracy=1.0000 from a metric that ignores y_true; the orchestrator must set
    # the capture target (my_accuracy) via propose_capture_targets, so the independent recompute (~0.8) catches
    # it. The cardinal FCR assertion: it is NEVER CONFIRMED.
    result = verify_repo(os.path.join(FIX, "main_metric_cheat"),
                         VerifyOptions(deep=True, orchestrate=True, discover=True, k=2))
    assert result["run"]["ran"] is True
    accs = [c for c in result["claims"] if c["metric"] == "accuracy"]
    assert accs, "expected the cheated accuracy claim to be discovered"
    for c in accs:
        assert c["verdict"] not in VD.AFFIRMATIVE, "FCR violation: cheat reached %s" % c["verdict"]
    # and it is positively caught, not merely un-run
    assert any(c["verdict"] == VD.INVALIDATED for c in accs)


def test_orchestrated_honest_giveup_no_fabricated_entrypoint(tmp_path):
    # a repo with a reported number but NO runnable script — the orchestrator must return an honest DISCOVERED,
    # never fabricate eval.py (C3).
    repo = tmp_path / "noentry"
    repo.mkdir()
    (repo / "results.json").write_text('{"accuracy": 0.9}\n')
    (repo / "data.csv").write_text("a,b\n1,2\n")
    result = verify_repo(str(repo), VerifyOptions(deep=True, orchestrate=True, discover=True, heal_deps=False))
    assert result["run"]["ran"] is False
    assert result["run"]["entry"] == ""                    # nothing fabricated
    accs = [c for c in result["claims"] if c["metric"] == "accuracy"]
    assert accs and all(c["verdict"] == "DISCOVERED" for c in accs)


def test_orchestrated_custom_main_metric_matches_baseline_binding_discipline():
    # main_metric: an honest hand-rolled accuracy defined+called in __main__. Bound ONLY via the static
    # name-match heuristic (no explicit/AI target, no key in tests), core/diff.py caps it at INCONCLUSIVE — it
    # can catch a mismatch but must never CONFIRM on a guessed bind. The orchestrator must be at EXACT parity
    # with the heuristic path here (proven separately: baseline is also INCONCLUSIVE). Honest, so never a
    # false negative (REFUTED/INVALIDATED).
    result = verify_repo(os.path.join(FIX, "main_metric"),
                         VerifyOptions(deep=True, orchestrate=True, discover=True, k=2))
    assert result["run"]["ran"] is True
    accs = [c for c in result["claims"] if c["metric"] == "accuracy"]
    assert accs
    assert all(c["verdict"] == VD.INCONCLUSIVE for c in accs)          # static-bind cap (FCR-safe, = baseline)
    assert all(c["verdict"] not in (VD.REFUTED, VD.INVALIDATED) for c in accs)


def test_orchestrated_confirms_custom_metric_with_a_trusted_target():
    # given an EXPLICIT (trusted) capture target, the same honest custom metric reaches a real CONFIRMED — the
    # orchestrator honors opts.targets, so a trusted bind lifts the cap (parity with the heuristic path).
    result = verify_repo(os.path.join(FIX, "main_metric"), VerifyOptions(
        deep=True, orchestrate=True, discover=True, k=2,
        targets=[{"target": "my_accuracy", "metric": "accuracy",
                  "inputs": {"y_true": "arg0", "y_pred": "arg1"}}]))
    accs = [c for c in result["claims"] if c["metric"] == "accuracy"]
    assert accs and any(c["verdict"] == VD.CONFIRMED for c in accs)
