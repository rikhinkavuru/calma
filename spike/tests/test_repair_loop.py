"""Feature 1 — the get-it-running repair loop. It only ever changes the ENVIRONMENT (the action space has no
source-edit), so a bad step ends in a still-failed run (→ DISCOVERED downstream), never a confirm. These pin:
the loop converges when an env action fixes the run, gives up when nothing helps, refuses an out-of-enum
(injected) action, and the source-modified rail caps a CONFIRMED at REPRODUCED-ONLY."""
import os
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from core import verdict as VD  # noqa: E402
from runner import repair as R  # noqa: E402
import pipeline as P  # noqa: E402


def _fail(err="No module named 'foo'"):
    return {"ran_ok": False, "meta": [{"stderr_tail": err}]}


def _ok():
    return {"ran_ok": True, "meta": [{"stderr_tail": ""}]}


def test_is_safe_pip_accepts_specs_rejects_injection():
    for ok in ("numpy", "scikit-learn", "pandas==2.1.0", "torch>=2.0", "uvicorn[standard]", "pkg~=1.2"):
        assert R.is_safe_pip(ok), ok
    for bad in ("--index-url=http://evil/simple", "git+https://evil/repo", ".", "/tmp/x", "a b",
                "pkg; rm -rf /", "http://evil/x.whl", "-e .", "", None, "x" * 200):
        assert not R.is_safe_pip(bad), bad


def test_action_space_is_env_only():
    assert "SOURCE_EDIT" not in R.ACTIONS and "EDIT" not in R.ACTIONS
    assert R.GIVE_UP in R.ACTIONS and "PIP" in R.ACTIONS


def test_loop_installs_then_succeeds():
    state = {"installed": False}

    def run(_a):
        return _ok() if state["installed"] else _fail()

    def apply(action):
        if action["type"] == "PIP":
            state["installed"] = True
            return True
        return False

    def propose(result, history):
        return {"type": "PIP", "arg": "foo"} if not history else {"type": R.GIVE_UP}
    result, man = R.repair_loop(run, propose, apply, max_steps=4)
    assert result["ran_ok"] and man["succeeded"] and man["steps_taken"] == 1
    assert man["steps"][0]["type"] == "PIP"


def test_loop_gives_up_when_unfixable():
    result, man = R.repair_loop(lambda a: _fail("KeyError"),
                                R.heuristic_propose(lambda r: None),   # no module to install
                                lambda a: True, max_steps=4)
    assert not result["ran_ok"] and not man["succeeded"] and man["gave_up"]
    assert man["steps_taken"] == 0


def test_loop_respects_max_steps():
    calls = {"n": 0}

    def propose(result, history):
        calls["n"] += 1
        return {"type": "PIP", "arg": "pkg%d" % calls["n"]}   # always a fresh package, never converges
    _r, man = R.repair_loop(lambda a: _fail(), propose, lambda a: True, max_steps=3)
    assert man["steps_taken"] == 3 and not man["succeeded"]


def test_injected_out_of_enum_action_is_refused():
    """A prompt-injected 'edit the metric' action is not in the enum → the loop refuses it and gives up, with
    no step applied. The structural guarantee behind FCR-safety."""
    def evil(result, history):
        return {"type": "SOURCE_EDIT", "arg": "metric.py"}
    _r, man = R.repair_loop(lambda a: _fail(), evil, lambda a: True, max_steps=4)
    assert man["gave_up"] and man["steps"] == [] and not man["succeeded"]


def test_source_modified_is_detected():
    box = {"snap": {"a.py": "h1"}}

    def run(_a):
        box["snap"] = {"a.py": "h2"}         # a step changed a source file
        return _fail()

    def propose(result, history):
        return {"type": "PIP", "arg": "foo"} if not history else {"type": R.GIVE_UP}
    _r, man = R.repair_loop(run, propose, lambda a: True, max_steps=2, snapshot_fn=lambda: dict(box["snap"]))
    assert man["source_modified"] == ["a.py"]


def test_heuristic_installs_missing_module_once():
    propose = R.heuristic_propose(lambda r: "numpy")
    a1 = propose(_fail(), [])
    assert a1 == {"type": "PIP", "arg": "numpy"}
    a2 = propose(_fail(), [{"type": "PIP", "arg": "numpy"}])   # already tried → don't loop
    assert a2["type"] == R.GIVE_UP


def test_source_modified_cap_only_touches_confirmed():
    conf = {"verdict": VD.CONFIRMED, "validity": {"invalidating": [], "advisory": []}}
    ref = {"verdict": VD.REFUTED, "validity": {"invalidating": [], "advisory": []}}
    P._apply_agent_modified_cap([conf, ref], ["metric.py"])
    assert conf["verdict"] == VD.REPRODUCED_ONLY      # a confirm is capped
    assert ref["verdict"] == VD.REFUTED               # a refute is untouched (edit doesn't un-misreport it)


def test_source_modified_cap_noop_when_clean():
    conf = {"verdict": VD.CONFIRMED, "validity": {"invalidating": [], "advisory": []}}
    P._apply_agent_modified_cap([conf], [])
    assert conf["verdict"] == VD.CONFIRMED
