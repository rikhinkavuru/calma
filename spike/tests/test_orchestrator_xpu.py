"""S3 — the dual-modality XPU experience store + its loop wiring. Hermetic: LocalXPU on a tmp path, injected
fake effectors, no sandbox, no Helix. Covers exact + vector retrieval, telemetry-gated demotion (delayed
audit), persistence, the Helix/local backend swap, and that a learned fix flows through the revise loop."""
import os

from orchestrator import orchestrate as O
from orchestrator import xpu as X
from orchestrator.types import RunApproach, RunResult


def _store(tmp_path):
    return X.LocalXPU(path=os.path.join(str(tmp_path), "xpu.json"))


# ── the store: record / retrieve / telemetry ──────────────────────────────────────────────────────────────────
def test_record_and_exact_signature_retrieve(tmp_path):
    s = _store(tmp_path)
    s.record("missing-dep:cv2", {"add_dep": "opencv-python-headless"}, symptom="ImportError: No module named cv2")
    hit = s.retrieve("missing-dep:cv2", "ImportError: No module named cv2")
    assert hit and hit[1] == 1.0 and hit[0].action == {"add_dep": "opencv-python-headless"}


def test_vector_retrieve_matches_symptom_across_differing_signature(tmp_path):
    s = _store(tmp_path)
    sym = "ImportError libGL.so.1 cannot open shared object file no such file or directory"
    s.record("missing-dep:cv2", {"add_dep": "opencv-python-headless"}, symptom=sym)
    # a NOVEL failure whose signature we don't recognize (None) but whose symptom is the same → vector hit.
    hit = s.retrieve(None, sym)
    assert hit and hit[0].action == {"add_dep": "opencv-python-headless"} and hit[1] >= X._VEC_THRESHOLD


def test_unrelated_symptom_does_not_match(tmp_path):
    s = _store(tmp_path)
    s.record("missing-dep:cv2", {"add_dep": "opencv-python-headless"}, symptom="ImportError libGL cannot open")
    assert s.retrieve(None, "SyntaxError invalid syntax on line 42 unexpected indent") is None


def test_telemetry_demotes_a_failing_unit(tmp_path):
    s = _store(tmp_path)
    s.record("missing-dep:x", {"add_dep": "x"}, symptom="ImportError x")
    assert s.retrieve("missing-dep:x", "ImportError x")            # live while unproven (benefit of the doubt)
    for _ in range(3):
        s.reward("missing-dep:x", success=False)                  # 0/3 → success-rate 0 < floor → demoted
    assert s.retrieve("missing-dep:x", "ImportError x") is None
    s.reward("missing-dep:x", success=True)                       # 1/4 = 0.25 still below the 0.34 floor
    assert s.retrieve("missing-dep:x", "ImportError x") is None
    for _ in range(3):
        s.reward("missing-dep:x", success=True)                   # 4/7 ≈ 0.57 → back above the floor → live again
    assert s.retrieve("missing-dep:x", "ImportError x")


def test_record_dedups_by_signature_and_persists(tmp_path):
    p = os.path.join(str(tmp_path), "xpu.json")
    s = X.LocalXPU(path=p)
    s.record("missing-dep:cv2", {"add_dep": "opencv"}, symptom="a")
    s.record("missing-dep:cv2", {"add_dep": "opencv-python-headless"}, symptom="a")   # update, not duplicate
    assert len(s) == 1
    # a fresh instance on the same path sees the persisted, updated unit (the cross-run 'over time' flywheel).
    s2 = X.LocalXPU(path=p)
    hit = s2.retrieve("missing-dep:cv2", "a")
    assert hit and hit[0].action == {"add_dep": "opencv-python-headless"}


# ── backend swap ──────────────────────────────────────────────────────────────────────────────────────────────
def test_store_selector_is_local_without_helix(monkeypatch):
    monkeypatch.delenv("CALMA_HELIX", raising=False)
    X._XPU = None
    try:
        assert X.xpu_store().name == "local"
    finally:
        X._XPU = None


def test_helix_backend_unavailable_without_instance():
    ok, why = X.HelixXPU(helix_bin=None).available()
    assert ok is False and "helix" in why.lower()


# ── loop wiring: a learned fix flows through revise, and a win is banked ───────────────────────────────────────
def _fail(stderr):
    return RunResult(ran_ok=False, runs=[], meta=[{"stderr_tail": stderr}])


def _ok():
    return RunResult(ran_ok=True, runs=[[{"metric": "accuracy", "result": 0.9}]], meta=[{}])


def test_revise_applies_a_learned_xpu_fix_before_the_heuristic(tmp_path):
    s = _store(tmp_path)
    s.record("missing-dep:cv2", {"add_dep": "opencv-python-headless"}, symptom="ImportError: No module named cv2")
    seen = {"n": 0}

    def run_approach(a):
        seen["n"] += 1
        if "opencv-python-headless" in a.deps:
            return _ok()
        return _fail("ModuleNotFoundError: No module named 'cv2'")

    res = O.execute([RunApproach(entry=["run.py"])], run_approach, revise=O.make_revise(None, s), xpu=s)
    assert res.ran_ok and "opencv-python-headless" in res.approach.deps    # the banked fix was applied
    assert seen["n"] == 2


def test_loop_banks_a_verified_fix_with_its_symptom(tmp_path):
    s = _store(tmp_path)
    seen = {"n": 0}

    def run_approach(a):
        seen["n"] += 1
        if "scikit-learn" in a.deps:
            return _ok()
        return _fail("ModuleNotFoundError: No module named 'sklearn'")

    res = O.execute([RunApproach(entry=["run.py"], deps=[])], run_approach,
                    revise=O.make_revise(None, s), xpu=s)
    assert res.ran_ok
    hit = s.retrieve("missing-dep:sklearn", "ModuleNotFoundError: No module named 'sklearn'")
    assert hit and hit[0].action.get("add_dep") == "scikit-learn"          # banked with its symptom text
    assert "sklearn" in hit[0].symptom
