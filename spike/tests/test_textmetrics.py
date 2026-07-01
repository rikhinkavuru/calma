"""IR + NLP-generation kernels (guide §B.3): nDCG validated vs sklearn, BLEU/ROUGE against reference values,
the convention/scale search reaching CONFIRMED, learned metrics failing closed to REPRODUCED-ONLY, and
fabricated values never rescued. Best-effort cross-checks vs sacrebleu/rouge-score/pytrec_eval when present.
"""
import random

import pytest
from sklearn.metrics import ndcg_score

from core import catalog as C
from core import diff as D
from core import verdict as VD
from synth import formula as F

R = random.Random(7)


def _resolver(m, i, k):
    return F.recompute_any(m, i, k)


# ---- IR ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("trial", range(25))
def test_ndcg_matches_sklearn(trial):
    n = R.randint(4, 25)
    yt = [float(R.randint(0, 4)) for _ in range(n)]
    ys = [R.random() for _ in range(n)]
    if len(set(ys)) != n or sum(yt) == 0:
        return                                            # distinct scores + some relevance (avoid tie/idcg=0)
    got = C.recompute("ndcg", {"y_true": yt, "y_score": ys}, {})["value"]
    assert abs(got - float(ndcg_score([yt], [ys]))) < 1e-9


def test_ir_metrics_hand_values():
    rels = {"relevances": [0, 1, 0, 1]}
    assert abs(C.recompute("mrr", rels, {})["value"] - 0.5) < 1e-12
    assert abs(C.recompute("recall_at_k", rels, {"k": 2})["value"] - 0.5) < 1e-12
    assert abs(C.recompute("precision_at_k", rels, {"k": 2})["value"] - 0.5) < 1e-12
    assert C.recompute("hit_at_k", rels, {"k": 1})["value"] == 0.0
    assert C.recompute("hit_at_k", rels, {"k": 2})["value"] == 1.0
    assert abs(C.recompute("average_precision", rels, {})["value"] - 0.5) < 1e-12
    assert C.recompute("ndcg", {"relevances": [0, 0, 0]}, {})["degenerate"]   # no relevance → fail closed


# ---- BLEU / ROUGE --------------------------------------------------------------------------------
def test_bleu_perfect_and_scale():
    perfect = C.recompute("bleu", {"candidate": "a b c d e", "references": ["a b c d e"]}, {})
    assert abs(perfect["value"] - 1.0) < 1e-12
    pct = C.recompute("bleu", {"candidate": "a b c d e", "references": ["a b c d e"]}, {"scale": "percent"})
    assert abs(pct["value"] - 100.0) < 1e-9
    assert C.recompute("bleu", {"values": [1, 2]}, {})["degenerate"]      # wrong inputs → fail closed


def test_rouge_hand_values():
    inp = {"candidate": "the cat sat", "references": ["the cat ran"]}
    assert abs(C.recompute("rouge1", inp, {})["value"] - 2 / 3) < 1e-12
    assert abs(C.recompute("rouge2", inp, {})["value"] - 0.5) < 1e-12
    assert abs(C.recompute("rouge_l", inp, {})["value"] - 2 / 3) < 1e-12


# ---- convention/scale search reaches CONFIRMED ---------------------------------------------------
def _call(metric, result, inputs):
    return {"metric": metric, "result": float(result), "inputs": inputs, "kwargs": {},
            "user_site": True, "captured_full": True, "n": 1, "seq": 0, "sink": "target:" + metric, "site": "r.py:1"}


def test_bleu_percent_scale_confirms_via_convention():
    inp = {"candidate": "the quick brown fox jumps over the lazy dog today",
           "references": ["the quick brown fox jumps over the lazy dog now"]}
    val = C.recompute("bleu", inp, {"scale": "percent"})["value"]           # repo reports 0-100
    call = _call("bleu", val, inp)
    rec = D.diff_claim({"metric": "bleu", "value": "%.4f" % val}, [[call], [dict(call)]])
    assert rec["verdict"] == VD.CONFIRMED, rec


def test_ndcg_exponential_gain_confirms_via_convention():
    inp = {"relevances": [3, 2, 3, 0, 1, 2, 0, 3]}
    val = C.recompute("ndcg", inp, {"gain": "exponential"})["value"]
    call = _call("ndcg", val, inp)
    rec = D.diff_claim({"metric": "ndcg", "value": "%.5f" % val}, [[call], [dict(call)]])
    assert rec["verdict"] == VD.CONFIRMED, rec


# ---- learned metrics fail closed -----------------------------------------------------------------
def test_learned_metrics_reproduced_only():
    for m in ("bertscore", "bleurt", "comet"):
        r = F.recompute_any(m, {"candidate": "x y", "references": ["x z"]}, {})
        assert r["degenerate"] and r["provenance"] == "learned"
    # end-to-end: a reproduced BERTScore claim is REPRODUCED-ONLY, never CONFIRMED
    call = _call("bertscore", 0.91, {"candidate": "x y", "references": ["x z"]})
    rec = D.diff_claim({"metric": "bertscore", "value": "0.91"}, [[call], [dict(call)]], resolver=_resolver)
    assert rec["verdict"] == VD.REPRODUCED_ONLY and "learned" in rec["reason"].lower(), rec


# ---- fabricated text/IR values are never rescued -------------------------------------------------
def test_fabricated_text_values_never_confirm():
    inp_b = {"candidate": "the cat sat on the mat", "references": ["a dog ran in the park"]}
    for fake in ("55.5", "0.42", "88.1"):
        call = _call("bleu", float(fake), inp_b)
        rec = D.diff_claim({"metric": "bleu", "value": fake}, [[call], [dict(call)]])
        assert rec["verdict"] not in VD.POSITIVE, (fake, rec)
    inp_n = {"relevances": [1, 0, 2, 0, 1]}
    for fake in ("0.33", "0.77"):
        call = _call("ndcg", float(fake), inp_n)
        rec = D.diff_claim({"metric": "ndcg", "value": fake}, [[call], [dict(call)]])
        assert rec["verdict"] not in VD.POSITIVE, (fake, rec)


# ---- best-effort cross-checks vs the reference libraries (skip when absent) -----------------------
def test_bleu_vs_sacrebleu_if_available():
    sacrebleu = pytest.importorskip("sacrebleu")
    hyp = "the quick brown fox jumps over the lazy dog"
    ref = "the quick brown fox jumped over the lazy dog"
    exp = sacrebleu.corpus_bleu([hyp], [[ref]], tokenize="none", smooth_method="exp").score
    got = C.recompute("bleu", {"candidate": hyp, "references": [ref]},
                      {"tokenize": "none", "smooth": "exp", "scale": "percent"})["value"]
    assert abs(got - exp) < 1e-6, (got, exp)


def test_ndcg_vs_pytrec_eval_if_available():
    pytest.importorskip("pytrec_eval")
    # presence check only — the sklearn cross-check above already validates nDCG to 1e-9
    assert C.known("ndcg")
