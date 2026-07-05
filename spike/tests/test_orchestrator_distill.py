"""S7 — offline experience distillation: aggregate the run-journal into conflict-free XPU units with REAL
telemetry (failures included). Hermetic: temp journal + LocalXPU, no sandbox/LLM. Covers the journal store,
the distill conflict-resolution + delayed-audit prune, absorb, and the loop→journal→distill roundtrip."""
import os

from orchestrator import distill as D
from orchestrator import orchestrate as O
from orchestrator.cache import RunJournal
from orchestrator.types import RunApproach, RunResult
from orchestrator.xpu import LocalXPU, XPUnit


def _j(tmp_path, **kw):
    return RunJournal(path=os.path.join(str(tmp_path), "journal.jsonl"), **kw)


def _x(tmp_path):
    return LocalXPU(path=os.path.join(str(tmp_path), "xpu.json"))


# ── RunJournal ────────────────────────────────────────────────────────────────────────────────────────────────
def test_journal_append_read_and_bound(tmp_path):
    j = _j(tmp_path, max_records=100)
    j.append({"sig": "s", "action": {"add_dep": "x"}, "success": True})
    j.append({"sig": "", "action": {"add_dep": "x"}})          # bad (no sig) → ignored
    j.append({"sig": "s", "action": {}})                       # bad (no action) → ignored
    recs = j.records()
    assert len(recs) == 1 and recs[0]["sig"] == "s"
    # persists + rings: a fresh instance on the same path sees the record
    assert len(RunJournal(path=j._path).records()) == 1


def test_journal_ring_drops_oldest(tmp_path):
    j = _j(tmp_path, max_records=100)                          # floor is 100
    for i in range(130):
        j.append({"sig": "s%d" % i, "action": {"add_dep": "d"}, "success": True})
    recs = j.records()
    assert len(recs) == 100 and recs[0]["sig"] == "s30" and recs[-1]["sig"] == "s129"


# ── distill: conflict resolution + prune ──────────────────────────────────────────────────────────────────────
def test_distill_picks_winning_action_and_prunes_losers(tmp_path):
    x = _x(tmp_path)
    records = [
        {"sig": "missing-dep:cv2", "action": {"add_dep": "opencv-python-headless"}, "symptom": "libGL", "success": True},
        {"sig": "missing-dep:cv2", "action": {"add_dep": "opencv-python-headless"}, "symptom": "libGL", "success": True},
        {"sig": "missing-dep:cv2", "action": {"add_dep": "opencv"}, "success": False},          # a losing variant
        {"sig": "missing-dep:bad", "action": {"add_dep": "nope"}, "success": False},            # never works
        {"sig": "missing-dep:bad", "action": {"add_dep": "nope"}, "success": False},
        {"sig": "flaky", "action": {"add_dep": "p"}, "success": True},                          # 1 win / 3 fail
        {"sig": "flaky", "action": {"add_dep": "p"}, "success": False},
        {"sig": "flaky", "action": {"add_dep": "p"}, "success": False},
        {"sig": "flaky", "action": {"add_dep": "p"}, "success": False},
    ]
    summary = D.distill(records, x)
    assert summary == {"absorbed": 1, "pruned": 2, "signatures": 3}
    hit = x.retrieve("missing-dep:cv2", "libGL")
    assert hit and hit[0].action == {"add_dep": "opencv-python-headless"}
    assert (hit[0].successes, hit[0].failures) == (2, 0)       # aggregated telemetry from the journal
    assert x.retrieve("missing-dep:bad", "x") is None          # net-negative → pruned, never banked
    assert x.retrieve("flaky", "x") is None                    # rate 0.25 < demote floor → pruned


def test_distill_is_idempotent(tmp_path):
    x = _x(tmp_path)
    records = [{"sig": "s", "action": {"add_dep": "d"}, "success": True},
               {"sig": "s", "action": {"add_dep": "d"}, "success": True}]
    D.distill(records, x)
    D.distill(records, x)                                      # absorb OVERWRITES telemetry, never doubles
    assert len(x) == 1
    hit = x.retrieve("s", "s")
    assert (hit[0].successes, hit[0].failures) == (2, 0)


def test_absorb_overwrites_telemetry(tmp_path):
    x = _x(tmp_path)
    x.absorb(XPUnit(signature="s", symptom="sym", action={"add_dep": "d"}, successes=5, failures=1))
    assert x.retrieve("s", "sym")[0].successes == 5
    x.absorb(XPUnit(signature="s", symptom="sym", action={"add_dep": "d"}, successes=2, failures=0))
    assert x.retrieve("s", "sym")[0].successes == 2 and len(x) == 1


# ── loop → journal → distill roundtrip ────────────────────────────────────────────────────────────────────────
def test_loop_journals_a_win_and_distill_banks_it(tmp_path):
    j, x = _j(tmp_path), _x(tmp_path)
    seen = {"n": 0}

    def run_approach(a):
        seen["n"] += 1
        if "scikit-learn" in a.deps:
            return RunResult(ran_ok=True, runs=[[{"metric": "accuracy", "result": 0.9}]], meta=[{}])
        return RunResult(ran_ok=False, runs=[], meta=[{"stderr_tail": "ModuleNotFoundError: No module named 'sklearn'"}])

    res = O.execute([RunApproach(entry=["run.py"], deps=[])], run_approach, journal=j)
    assert res.ran_ok
    recs = j.records()
    assert any(r["success"] and r["action"].get("add_dep") == "scikit-learn" for r in recs)   # the WIN was logged
    D.distill(recs, x)
    hit = x.retrieve("missing-dep:sklearn", "ModuleNotFoundError: No module named 'sklearn'")
    assert hit and hit[0].action.get("add_dep") == "scikit-learn"    # the fix distilled into the XPU store
