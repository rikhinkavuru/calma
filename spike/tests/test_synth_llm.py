"""Productionized LLM synthesis (guide §B.3): AI proposes a recompute, _validate_synth disposes. The FCR gate
is the validation — an unvalidated (or wrong) LLM formula is never banked; it falls back to the grounded
registry code or refuses. Also the text/IR reference-oracle scaffolding + the pytrec_eval empty-qrels guard.
"""
import random

from sklearn.metrics import matthews_corrcoef

from synth import formula as F
from synth.store import LocalStore

_GARBAGE = "def recompute(I, K):\n    return 0.12345\n"          # constant — fails validation vs sklearn


def test_llm_synthesize_no_key_returns_none(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert F._llm_synthesize("mcc", "Matthews correlation coefficient") is None


import pytest  # noqa: E402


@pytest.mark.parametrize("escape", [
    "def recompute(I, K):\n    return ().__class__.__bases__[0].__subclasses__()",   # object-graph walk
    "import os\ndef recompute(I, K):\n    return 0.0",                                # import
    "def recompute(I, K):\n    return __import__('os').getpid()",                      # dunder name
    "def recompute(I, K):\n    return type(I).__mro__",                                 # dunder attr
])
def test_exec_formula_blocks_sandbox_escapes(escape):
    """A synthesised formula that reaches for a sandbox escape (object-graph walk, import, dunder access) is
    rejected by the AST guard BEFORE it runs — restricting __builtins__ alone is not a real sandbox."""
    with pytest.raises(ValueError):
        F.exec_formula(escape, {}, {})


def test_exec_formula_runs_legit_recompute():
    v = F.exec_formula(F._MCC, {"y_true": [0, 1, 0, 1, 1], "y_pred": [0, 1, 1, 1, 0]}, {})
    assert isinstance(v, float)


def test_synthesize_prefers_validated_llm_code(tmp_path, monkeypatch):
    """When the LLM emits code that PASSES validation, it is banked (source tagged +llm)."""
    good = F.SYNTH_REGISTRY["mcc"]["code"]                        # a correct recompute (stands in for the LLM's)
    monkeypatch.setattr(F, "_llm_synthesize", lambda metric, definition, model=None: good)
    store = LocalStore(path=str(tmp_path / "s.json"))
    rec = F._synthesize_and_validate("mcc", store)
    assert rec is not None and rec.metric == "mcc" and rec.source.endswith("+llm")
    rng = random.Random(1)
    yt = [rng.randint(0, 1) for _ in range(120)]
    yp = [rng.randint(0, 1) for _ in range(120)]
    assert abs(F.exec_formula(rec.code, {"y_true": yt, "y_pred": yp}, {}) - matthews_corrcoef(yt, yp)) < 1e-9


def test_synthesize_falls_back_when_llm_code_is_wrong(tmp_path, monkeypatch):
    """A WRONG LLM formula fails validation → fall back to the grounded registry code (never bank the guess)."""
    monkeypatch.setattr(F, "_llm_synthesize", lambda metric, definition, model=None: _GARBAGE)
    store = LocalStore(path=str(tmp_path / "s.json"))
    rec = F._synthesize_and_validate("mcc", store)
    assert rec is not None and rec.metric == "mcc"
    assert not rec.source.endswith("+llm")                       # the wrong LLM code was rejected
    assert rec.code == F.SYNTH_REGISTRY["mcc"]["code"]           # banked the grounded registry code instead


def test_empty_qrels_guard_never_produces_empty_qrels():
    rng = random.Random(0)
    for _ in range(200):
        case = F._nonempty_qrels_case(rng)
        assert sum(case["relevances"]) > 0                        # guards the pytrec_eval NDCG>1 bug (#57)


def test_text_oracle_fails_closed_without_the_library():
    rng = random.Random(0)
    # sacrebleu is not installed in this env → no BLEU oracle → (None, None, why); a synthesized BLEU can't be
    # validated, so it would fail closed rather than be trusted.
    case, refval, why = F._text_oracle("bleu", rng)
    assert case is None and refval is None and "sacrebleu" in why
    # the ndcg oracle uses the sklearn-validated catalog kernel (always available) + the empty-qrels guard
    ncase, nref, _why = F._text_oracle("ndcg", rng)
    assert ncase is not None and sum(ncase()["relevances"]) > 0
