"""P1.6 acceptance tests -- the adaptive loop (corrections -> guarded few-shot promotion).

evaluate()/refresh() go through the LLM extractor, so the recall-lift and precision-drop are REPLAYED
from recorded fixtures (edges/tests/fixtures/<hash>.json); the suite needs no ANTHROPIC_API_KEY.
Record once with the model live:

    CALMA_EDGES_RECORD=1 ANTHROPIC_API_KEY=... \
        PYTHONPATH=. ~/.cache/calma-edges-venv/bin/python edges/tests/test_learn.py --record

(conftest.py pops CALMA_EDGES_RECORD so the suite never records.) Then pytest replays with it unset.
The few-shot text is a deterministic function of the corrections (ranked by weight+ts, serialized with
sorted keys), so the same correction set always produces the same request hash.

NOTE on the guard scenario (matched to reality, as the gate instructs): the bare HAIKU extractor is
already maximally recall-biased, so the canonical "raise recall AND drop precision" cannot be
co-induced on one candidate -- teaching a measure both lifts recall and removes its mislabeled FP, so
precision rises with it. We therefore exercise the precision guard directly: the spurious candidate
holds recall flat (>= before) while teaching the model to extract a cohort YEAR the gold excludes,
which REGRESSES precision -> the guard rejects (adopt requires BOTH conditions). That is exactly the
branch the guard exists to defend.
"""
import json
import os

import pytest

from edges.common import store
from edges.extract import eval as EV, learn

EVAL = os.path.join(os.path.dirname(__file__), "eval", "labeled_set.jsonl")


# --- correction builders -----------------------------------------------------------------------
def _claim(measure, value, vt, quote, section="cell 3", formula=None):
    return {"value": value, "value_text": vt, "measure": measure, "subject": "",
            "claimed_provenance": {"file": None, "column": None, "cell": section,
                                   "computation": None, "formula_hint": formula},
            "source_span": {"quote": quote, "page": None, "bbox": None,
                            "element_type": "output", "section": section},
            "confidence": 0.6}


def _good_corrections():
    """5 corrections, 3 'missed' that name claims the bare extractor drops (obscure metrics HAIKU
    labels 'unknown' without guidance: KS-PME, implementation shortfall, Amihud illiquidity)."""
    return [
        dict(artifact_hash="h_kspme", correction_type="missed", claim_before=None,
             claim_after=_claim("ks_pme", 1.20, "1.20",
                                "the fund's KS-PME ratio came to 1.20 over 2014-2019", "cell 3"),
             ts_from_args=1_700_000_001),
        dict(artifact_hash="h_is", correction_type="missed", claim_before=None,
             claim_after=_claim("implementation_shortfall", 15, "15",
                                "the implementation shortfall was 15 bps on the parent order",
                                "cell 4"),
             ts_from_args=1_700_000_002),
        dict(artifact_hash="h_amihud", correction_type="missed", claim_before=None,
             claim_after=_claim("amihud", 0.0002, "0.0002",
                                "the Amihud illiquidity ratio measured 0.0002 that month", "cell 5"),
             ts_from_args=1_700_000_003),
        dict(artifact_hash="h_wm", correction_type="wrong-measure",
             claim_before=_claim("f1", 0.70, "0.70", "macro F1 of 0.70", "cell 6"),
             claim_after=_claim("macro_f1", 0.70, "0.70", "macro F1 of 0.70", "cell 6"),
             ts_from_args=1_700_000_004),
        dict(artifact_hash="h_wc", correction_type="wrong-cell",
             claim_before=_claim("sharpe", 1.5, "1.5", "Sharpe ratio of 1.5", "cell 1"),
             claim_after=_claim("sharpe", 1.5, "1.5", "Sharpe ratio of 1.5", "cell 2"),
             ts_from_args=1_700_000_005),
    ]


def _spurious_corrections():
    """A correction set that teaches the model to extract a cohort YEAR (a number the gold excludes)
    -> over-extraction -> precision regresses while recall holds flat."""
    return [
        dict(artifact_hash="s1", correction_type="missed", claim_before=None,
             claim_after=_claim("unknown", 2016, "2016",
                                "the 2016 cohort was assessed across all sites", "cell 4"),
             ts_from_args=1_700_000_010),
        dict(artifact_hash="s2", correction_type="missed", claim_before=None,
             claim_after=_claim("unknown", 2013, "2013",
                                "the 2013 vintage portfolio was included in the panel", "cell 5"),
             ts_from_args=1_700_000_011),
    ]


def _write(path, corrections):
    for c in corrections:
        learn.record_correction(path=path, **c)


# === ACCEPTANCE: a guarded refresh ADOPTS a recall-lifting few-shot ============================
def test_refresh_adopts_on_recall_lift(tmp_path):
    corr = str(tmp_path / "corr.jsonl")
    fewshot = str(tmp_path / "fewshot.json")
    templates = str(tmp_path / "templates.json")

    base = EV.evaluate(EV.load_labeled(EVAL), fewshot=None)
    _write(corr, _good_corrections())
    out = learn.refresh(eval_path=EVAL, ts_from_args=1_700_000_000,
                        corr_path=corr, fewshot_path=fewshot, templates_path=templates)

    assert out["after"]["recall"] > base["recall"]              # measurable recall lift
    assert out["after"]["precision"] >= base["precision"]       # no precision regression
    assert out["adopted"] is True
    assert os.path.exists(fewshot)                              # adopted -> written to disk
    assert json.load(open(fewshot))                            # a non-empty few-shot block


# === ACCEPTANCE: the GUARD rejects a precision-regressing candidate ============================
def test_guard_rejects_precision_regression(tmp_path):
    corr = str(tmp_path / "corr.jsonl")
    fewshot = str(tmp_path / "fewshot.json")
    templates = str(tmp_path / "templates.json")
    json.dump([], open(fewshot, "w"))                          # current adopted = none

    _write(corr, _spurious_corrections())
    out = learn.refresh(eval_path=EVAL, ts_from_args=1_700_000_020,
                        corr_path=corr, fewshot_path=fewshot, templates_path=templates)

    assert out["after"]["recall"] >= out["before"]["recall"]    # recall did NOT fall
    assert out["after"]["precision"] < out["before"]["precision"]   # ... but precision regressed
    assert out["adopted"] is False
    assert json.load(open(fewshot)) == []                      # FEWSHOT unchanged on disk


# === ACCEPTANCE: grow_templates extends the library AND the new template parses =================
def test_grow_templates_extends_and_is_parseable(tmp_path):
    from edges.extract import route as R
    corr = str(tmp_path / "corr.jsonl")
    templates = str(tmp_path / "templates.json")
    json.dump([], open(templates, "w"))

    learn.record_correction(
        path=corr, artifact_hash="hf", correction_type="missed", claim_before=None,
        claim_after=_claim("precision", 0.9, "0.90", "precision = TP/(TP+FP)", "cell 1",
                           formula="TP/(TP+FP)"),
        ts_from_args=1_700_000_030)

    before = json.load(open(templates))
    tmpl = learn.grow_templates(corr_path=corr, templates_path=templates)
    assert len(tmpl) > len(before)                             # the library grew
    entry = next(t for t in tmpl if t["measure"] == "precision")
    assert R._eval_formula(entry["formula"], {"TP": 90.0, "FP": 10.0}) == 0.9   # route can parse it
    # idempotent: re-growing the same corpus adds nothing
    assert len(learn.grow_templates(corr_path=corr, templates_path=templates)) == len(tmpl)


# === UNIT: corrections schema + recall-first ranking (pure, no LLM) =============================
def test_record_correction_schema_and_ranking(tmp_path):
    from jsonschema import validate
    corr = str(tmp_path / "corr.jsonl")
    _write(corr, _good_corrections())

    recs = list(store.iter_records(corr))
    assert len(recs) == 5
    for r in recs:
        validate(instance=r, schema=learn.CORRECTION_SCHEMA)

    fs = learn.build_fewshot(path=corr, k=6)
    measures = [ex["claims"][0]["measure"] for ex in fs if ex["claims"]]
    # recall-first: the 'missed' examples outrank the wrong-measure/wrong-cell fixes
    assert measures.index("ks_pme") < measures.index("sharpe")
    assert "ks_pme" in measures and "implementation_shortfall" in measures and "amihud" in measures


def test_record_correction_rejects_unknown_type(tmp_path):
    with pytest.raises(ValueError):
        learn.record_correction(path=str(tmp_path / "c.jsonl"), artifact_hash="h",
                                correction_type="bogus", claim_before=None, claim_after=None,
                                ts_from_args=1)


# --- recording entrypoint (NOT pytest; run as a script with CALMA_EDGES_RECORD=1) --------------
def _record_all():
    import tempfile
    assert os.environ.get("CALMA_EDGES_RECORD") == "1", \
        "set CALMA_EDGES_RECORD=1 (and ANTHROPIC_API_KEY) to record"
    d = tempfile.mkdtemp()
    base = EV.evaluate(EV.load_labeled(EVAL), fewshot=None)
    print("BASE     :", {k: base[k] for k in ("precision", "recall", "tp", "fp", "fn")})

    cg = os.path.join(d, "good.jsonl")
    _write(cg, _good_corrections())
    og = learn.refresh(eval_path=EVAL, ts_from_args=1, corr_path=cg,
                       fewshot_path=os.path.join(d, "fg.json"), templates_path=os.path.join(d, "tg.json"))
    print("GOOD     : adopted=%s before=%s after=%s" % (og["adopted"], og["before"], og["after"]))

    cs = os.path.join(d, "spur.jsonl")
    _write(cs, _spurious_corrections())
    osr = learn.refresh(eval_path=EVAL, ts_from_args=2, corr_path=cs,
                        fewshot_path=os.path.join(d, "fs.json"), templates_path=os.path.join(d, "ts.json"))
    print("SPURIOUS : adopted=%s before=%s after=%s" % (osr["adopted"], osr["before"], osr["after"]))


if __name__ == "__main__":
    _record_all()
