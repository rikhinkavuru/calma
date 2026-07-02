"""Phase 4 — the flywheel: approach cache (fingerprint→approach) + error→fix hint store, tier-scaled budgets,
and the re-runnable launch artifact. All FCR-safe (HOW-only) and all hermetic (tmp-dir-backed stores)."""
import os
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from orchestrator import cache as C  # noqa: E402
from orchestrator import orchestrate as O  # noqa: E402
from orchestrator.types import RunApproach, RunResult  # noqa: E402


# ── ApproachCache ─────────────────────────────────────────────────────────────────────────────────────────────
def test_approach_cache_roundtrip_and_persist(tmp_path):
    path = str(tmp_path / "approaches.json")
    ca = C.ApproachCache(path)
    a = RunApproach(entry=["eval.py"], deps=["numpy"], builder="venv-pip")
    ca.put("fp1", a)
    assert ca.get("fp1").entry == ["eval.py"]
    assert ca.get("missing") is None
    # persisted across instances
    assert C.ApproachCache(path).get("fp1").deps == ["numpy"]


# ── HintStore + error_signature ───────────────────────────────────────────────────────────────────────────────
def test_error_signature():
    assert C.error_signature("ModuleNotFoundError: No module named 'cv2'") == "missing-dep:cv2"
    assert C.error_signature("FileNotFoundError: 'data/x.csv'") == "missing-data"
    assert C.error_signature("some generic message") is None


def test_hint_store_roundtrip(tmp_path):
    hs = C.HintStore(str(tmp_path / "hints.json"))
    hs.record("missing-dep:cv2", {"add_dep": "opencv-python-headless"})
    assert hs.get("missing-dep:cv2") == {"add_dep": "opencv-python-headless"}
    assert hs.get("unknown") is None


# ── orchestrate() cache hit prepends + stores the winner ──────────────────────────────────────────────────────
def test_orchestrate_caches_and_reuses_winning_approach(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "eval.py").write_text("import sklearn\nif __name__=='__main__':\n    print(1)\n")
    ca = C.ApproachCache(str(tmp_path / "c.json"))          # store OUTSIDE the repo dir
    calls = []

    def run_approach(a):
        calls.append(list(a.entry))
        return RunResult(ran_ok=True, runs=[[{"metric": "accuracy", "result": 0.9}]])

    r1 = O.orchestrate(str(repo), run_approach, use_llm=False, cache=ca)
    assert r1.ran_ok and len(ca) == 1                       # winner cached
    assert isinstance(r1.cost.get("launch"), str) and "python" in r1.cost["launch"]

    # second run: the cached approach is tried FIRST (flywheel)
    logs = []
    O.orchestrate(str(repo), run_approach, use_llm=False, cache=ca, log=logs.append)
    assert any("flywheel cache hit" in ln for ln in logs)


def test_orchestrate_learns_a_verified_fix(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    # no third-party import → deps start EMPTY, so the missing-module heal path is actually exercised
    (repo / "eval.py").write_text("if __name__=='__main__':\n    print(1)\n")
    hs = C.HintStore(str(tmp_path / "h.json"))              # store OUTSIDE the repo dir
    state = {"n": 0}

    def run_approach(a):
        state["n"] += 1
        if "scikit-learn" in a.deps:
            return RunResult(ran_ok=True, runs=[[{"metric": "accuracy", "result": 0.9}]])
        return RunResult(ran_ok=False, runs=[],
                         meta=[{"stderr_tail": "ModuleNotFoundError: No module named 'sklearn'"}])

    O.orchestrate(str(repo), run_approach, use_llm=False, hints=hs)
    # the heal (sklearn→scikit-learn) verifiably worked → learned against its error signature
    assert hs.get("missing-dep:sklearn") == {"add_dep": "scikit-learn"}


def test_hint_applied_on_a_fresh_repo(tmp_path):
    # a NOVEL repo hitting a KNOWN error gets the learned fix applied by make_revise (no heuristic needed)
    hs = C.HintStore(str(tmp_path / "h.json"))
    hs.record("missing-dep:weirdmod", {"add_dep": "the-weird-dist"})
    revise = O.make_revise(hs)
    failed = RunResult(ran_ok=False, meta=[{"stderr_tail": "ModuleNotFoundError: No module named 'weirdmod'"}])
    out = revise(failed, RunApproach(entry=["e.py"], deps=[]), [])
    assert out is not None and "the-weird-dist" in out.deps


# ── tier budgets ──────────────────────────────────────────────────────────────────────────────────────────────
def test_budget_for_tier():
    from core import limits as LIM
    free = O.budget_for_tier(LIM.TIERS["free"])
    assert free.max_approaches == 1 and free.step_cap == 1   # free: one shot, no revise
    pro = O.budget_for_tier(LIM.TIERS["pro"])
    assert pro.max_approaches > 1 and pro.step_cap > 1        # paid: full loop


# ── launch artifact ───────────────────────────────────────────────────────────────────────────────────────────
def test_launch_command_variants(tmp_path):
    repo = str(tmp_path / "myrepo")
    a = RunApproach(entry=["eval.py"], deps=["numpy", "scikit-learn"])
    cmd = O.launch_command(a, repo)
    assert "cd myrepo" in cmd and "pip install numpy scikit-learn" in cmd and "python eval.py" in cmd
    nb = O.launch_command(RunApproach(entry=["nb:analysis.ipynb"]), repo)
    assert "papermill analysis.ipynb" in nb
    mk = O.launch_command(RunApproach(entry=["make:reproduce"], env={"SEED": "0"}), repo)
    assert "make reproduce" in mk and "SEED=0" in mk
