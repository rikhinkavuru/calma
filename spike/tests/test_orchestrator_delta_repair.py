"""S6 — delta-repair discipline. Every revise must be a CONSTRAINED, additive delta over the current approach
(grow/relax deps, add env) — never a free regeneration that weakens the verification (switch the entry, drop
capture targets, remove env, drop a package). Plus a registry-vocabulary LLM revise for env errors the
key-free heuristic can't map. Hermetic: the model call is stubbed."""
import planner as PLAN
from orchestrator import orchestrate as O
from orchestrator.types import RunApproach, RunResult


def _fail(stderr):
    return RunResult(ran_ok=False, runs=[], meta=[{"stderr_tail": stderr}])


_BASE = dict(entry=["eval.py"], deps=["numpy==2.4.6"],
             capture_targets=[{"target": "m.f", "metric": "accuracy"}], env={"X": "1"})


# ── _safe_delta ───────────────────────────────────────────────────────────────────────────────────────────────
def test_safe_delta_allows_additive_and_relax():
    a = RunApproach(**_BASE)
    assert O._safe_delta(a, O._with_dep(a, "scipy", "n"))            # + a dep
    assert O._safe_delta(a, O._with_env(a, {"Y": "2"}, "n"))         # + an env var
    relaxed = RunApproach(entry=["eval.py"], deps=["numpy"],         # relax pins: same package set → additive
                          capture_targets=list(a.capture_targets), env=dict(a.env))
    assert O._safe_delta(a, relaxed)


def test_safe_delta_forbids_every_weakening():
    a = RunApproach(**_BASE)

    def variant(**kw):
        base = dict(entry=list(a.entry), deps=list(a.deps),
                    capture_targets=list(a.capture_targets), env=dict(a.env))
        base.update(kw)
        return RunApproach(**base)
    assert not O._safe_delta(a, variant(entry=["other.py"]))         # entrypoint swap = a regeneration, not a revise
    assert not O._safe_delta(a, variant(capture_targets=[]))         # dropped what we capture
    assert not O._safe_delta(a, variant(env={}))                     # removed an env var
    assert not O._safe_delta(a, variant(deps=[]))                    # dropped an installed package


# ── the gate in make_revise rejects a weakening candidate ─────────────────────────────────────────────────────
def test_make_revise_gate_rejects_a_weakening_candidate(monkeypatch):
    a = RunApproach(entry=["eval.py"], deps=["numpy"])
    # force the (hypothetical) LLM revise to regenerate a WEAKER approach — an entrypoint swap. The gate kills it.
    monkeypatch.setattr(O, "_llm_revise",
                        lambda r, ap, m: RunApproach(entry=["decoy.py"], deps=list(ap.deps)))
    assert O.make_revise(model="m")(_fail("a novel unmappable error"), a, []) is None


# ── the constrained LLM revise ────────────────────────────────────────────────────────────────────────────────
def test_llm_revise_adds_a_constrained_dep(monkeypatch):
    monkeypatch.setattr(PLAN, "_call_model", lambda *a, **k: '{"add_dep": "opencv-python-headless", "set_env": []}')
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    new = O._llm_revise(_fail("ImportError: libGL.so.1: cannot open shared object file"),
                        RunApproach(entry=["eval.py"], deps=[]), "m")
    assert new is not None and "opencv-python-headless" in new.deps and new.entry == ["eval.py"]   # additive


def test_propose_revise_sanitizes_injection_and_gates(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(PLAN, "_call_model", lambda *a, **k: '{"add_dep": "--index-url http://evil/", "set_env": []}')
    assert PLAN.propose_revise("err", [], "m") is None              # an injected pip spec is stripped → no fix
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert PLAN.propose_revise("err", [], "m") is None              # no key → gated off


def test_make_revise_applies_the_llm_fix_when_heuristic_misses(monkeypatch):
    # 'ImportError: libGL' isn't a ModuleNotFoundError → the key-free heuristic can't map it → the LLM revise
    # supplies the fix, and the gate lets it through (it's additive).
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setattr(PLAN, "_call_model",
                        lambda *a, **k: '{"add_dep": "opencv-python-headless", "set_env": [{"key": "MPLBACKEND", "value": "Agg"}]}')
    new = O.make_revise(model="m")(_fail("ImportError: libGL.so.1: cannot open shared object file"),
                                   RunApproach(entry=["eval.py"], deps=[]), [])
    assert new is not None and "opencv-python-headless" in new.deps and new.env.get("MPLBACKEND") == "Agg"
