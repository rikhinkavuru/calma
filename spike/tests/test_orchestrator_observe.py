"""S2 — the Prosecutor–Judge observe step + its loop wiring. Hermetic: temp repos + injected fake effectors,
no sandbox, no LLM. Asserts observe LABELS setup-induced vs repo-bug and picks the right next move, and that
the execute loop's behavior is preserved (missing-data remediate→retry; honest environmental stop)."""
import os

from orchestrator import observe as OBS
from orchestrator import orchestrate as O
from orchestrator.types import RunApproach, RunResult


def _fail(stderr):
    return RunResult(ran_ok=False, runs=[], meta=[{"stderr_tail": stderr}])


def _repo(tmp_path, **files):
    for rel, body in files.items():
        p = os.path.join(str(tmp_path), rel)
        os.makedirs(os.path.dirname(p) or str(tmp_path), exist_ok=True)
        with open(p, "w") as fh:
            fh.write(body)
    return str(tmp_path)


# ── observe: the label + next move ────────────────────────────────────────────────────────────────────────────
def test_observe_missing_data_with_committed_file_is_setup_induced_remediate(tmp_path):
    d = _repo(tmp_path, **{"data/train.csv": "x\n1\n"})
    obs = OBS.observe(_fail("No such file or directory: '/abs/train.csv'"), d,
                      can_remediate=True, already_resolved=False)
    assert obs.next_move == "remediate" and obs.label == "setup-induced"
    assert obs.plan is not None and "committed" in obs.detail


def test_observe_missing_data_exhausted_is_repo_bug_stop(tmp_path):
    d = _repo(tmp_path, **{"data/train.csv": "x\n1\n"})
    # resolution already tried on this approach → the loop must stop and surface, labeled repo-bug.
    obs = OBS.observe(_fail("No such file or directory: '/abs/train.csv'"), d,
                      can_remediate=True, already_resolved=True)
    assert obs.next_move == "stop" and obs.label == "repo-bug"


def test_observe_needs_gpu_is_environmental_stop(tmp_path):
    obs = OBS.observe(_fail("RuntimeError: No CUDA GPUs are available"), str(tmp_path), can_remediate=True)
    assert obs.next_move == "stop" and obs.label == "environmental"


def test_observe_missing_module_is_revise(tmp_path):
    obs = OBS.observe(_fail("ModuleNotFoundError: No module named 'sklearn'"), str(tmp_path), can_remediate=True)
    assert obs.next_move == "revise" and obs.fault == "missing-dep"


def test_observe_degrades_without_repo_dir():
    # the hermetic loop path passes no repo_dir → signature-only classification, no plan, same control flow.
    obs = OBS.observe(_fail("No such file or directory: '/abs/x.csv'"), None, can_remediate=False)
    assert obs.next_move == "stop" and obs.label == "repo-bug" and obs.plan is None


# ── loop wiring: behavior preserved + the label reaches the trace ─────────────────────────────────────────────
def test_loop_remediates_then_retries_and_records_evidence(tmp_path):
    d = _repo(tmp_path, **{"data/train.csv": "x\n1\n"})
    seen = {"n": 0}

    def run_approach(a):
        seen["n"] += 1
        if seen["n"] == 1:
            return _fail("FileNotFoundError: [Errno 2] No such file or directory: '/abs/train.csv'")
        return RunResult(ran_ok=True, runs=[[{"metric": "accuracy", "result": 0.9}]], meta=[{}])

    def resolve_data(_stderr):
        return True                                            # pretend the relink placed the file

    res = O.execute([RunApproach(entry=["run.py"])], run_approach, resolve_data=resolve_data, repo_dir=d)
    assert res.ran_ok and res.runs and res.runs[0]             # remediated, retried, captured
    assert seen["n"] == 2
    ev = [s for s in res.trace if s.get("event") == "data-resolved"]
    assert ev and "committed" in ev[0].get("evidence", "")     # the Prosecutor evidence is in the audit trace


def test_loop_stops_honestly_with_repo_bug_label_when_unresolvable(tmp_path):
    d = _repo(tmp_path)                                         # no committed data

    def run_approach(a):
        return _fail("FileNotFoundError: [Errno 2] No such file or directory: '/abs/missing.csv'")

    def resolve_data(_stderr):
        return False                                           # nothing to relink, no fetch source

    res = O.execute([RunApproach(entry=["run.py"])], run_approach, resolve_data=resolve_data, repo_dir=d)
    assert res.ran_ok is False and res.runs == []              # honest give-up (→ DISCOVERED), never fabricated
    stop = [s for s in res.trace if s.get("event") == "environmental-stop"]
    assert stop and stop[0]["label"] == "repo-bug"             # the setup-induced-vs-repo-bug distinction
