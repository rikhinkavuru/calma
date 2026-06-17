"""P2.3 acceptance tests -- the repo-shape library: fingerprints, nearest-shape priors, mined rules.

Priors only SPEED the proposer; the data-regrade still decides every grade on every run. The one-shot
draft is replayed (no API key). Two fixture repos of the SAME shape (decoy_score, decoy_score_2: both
sklearn, both a logit decoy + p_hat + y, different file name/column order).
"""
import json
import os
import shutil

import pytest

from edges.common import store
from edges.contract import draft as D
from edges.contract import library as L

REPOA = os.path.join(os.path.dirname(__file__), "fixtures", "repos", "decoy_score")
REPOB = os.path.join(os.path.dirname(__file__), "fixtures", "repos", "decoy_score_2")

_FIXED_A_CONTRACT = {
    "run": {"entrypoint": "gen_fixture.py", "network": "off", "cwd": "."},
    "env": {"ecosystem": "python-stdlib", "trust": "own-code"},
    "artifacts": [{"path": "out/preds.csv", "re_emit": True,
                   "columns": {"score": {"tag": "score"}, "p_hat": {"tag": "prob"},
                               "y": {"tag": "label"}}}],
    "metrics": [{"metric_id": "auc", "artifact": "out/preds.csv",
                 "binding": {"prob": "p_hat", "label": "y"}, "claimed_value": 0.93, "headline": True}],
}


def _ce(violation, tag, bad_column, suggested):
    return {"metric_id": "auc", "tag": tag, "bad_column": bad_column, "artifact": "out/preds.csv",
            "violation": violation, "stats": {"min": 2.0, "max": 6.0, "mean": 4.0,
                                              "frac_violating": 1.0, "n": 60, "examples": [2.0]},
            "suggested_columns": suggested, "data_grade": "plausibly-bound", "feedback": "x"}


# === ACCEPTANCE: remember a shape, then retrieve the nearest for a same-shape repo =============
def test_remember_then_nearest(tmp_path):
    shapes = os.path.join(str(tmp_path), "shapes.jsonl")
    L.remember_shape(REPOA, _FIXED_A_CONTRACT, shapes_path=shapes, ts=1)
    hit = L.nearest_shape(REPOB, shapes_path=shapes)
    assert hit is not None and hit["similarity"] >= 0.5
    # the skeleton is a PRIOR, not the literal contract: claimed nulled, paths globbed, bindings kept
    sk = hit["skeleton"]
    assert sk["metrics"][0]["claimed_value"] is None
    assert sk["metrics"][0]["artifact"] == "out/*.csv"
    assert sk["metrics"][0]["binding"] == {"prob": "p_hat", "label": "y"}


def test_seed_for_returns_the_nearest_skeleton(tmp_path):
    shapes = os.path.join(str(tmp_path), "shapes.jsonl")
    L.remember_shape(REPOA, _FIXED_A_CONTRACT, shapes_path=shapes, ts=1)
    seed = L.seed_for(REPOB, shapes_path=shapes)
    assert seed is not None and seed["metrics"][0]["metric_id"] == "auc"
    assert L.seed_for(REPOB, shapes_path=os.path.join(str(tmp_path), "empty.jsonl")) is None


# === ACCEPTANCE: a one-shot draft on a known shape resolves binding p_hat (priors don't bypass data) ==
def test_draft_oneshot_resolves_and_binds_phat(tmp_path):
    dst = os.path.join(str(tmp_path), "decoy_score_2")
    shutil.copytree(REPOB, dst)
    shapes = os.path.join(str(tmp_path), "shapes.jsonl")
    L.remember_shape(REPOA, _FIXED_A_CONTRACT, shapes_path=shapes, ts=1700000000)

    contract, trace = L.draft_oneshot(
        dst, budget=3, shapes_path=shapes, rules_path=os.path.join(str(tmp_path), "rules.json"),
        ce_log=os.path.join(str(tmp_path), "ce.jsonl"),
        drafts_log=os.path.join(str(tmp_path), "d.jsonl"), ts=1700000000)

    assert trace["resolved"] is True
    assert trace["iterations_used"] <= 1                  # one-shot on a known shape
    auc = next(m for m in contract["metrics"] if m["metric_id"] == "auc")
    score_col = auc["binding"].get("score") or auc["binding"].get("prob")
    assert score_col == "p_hat"                           # priors didn't bypass the data check
    assert auc["artifact"] == "out/scores.csv"            # the glob adapted to THIS repo's real file
    assert sum(1 for _ in store.iter_records(shapes)) == 2  # the new shape was remembered


# === ACCEPTANCE: rule mining requires support and produces the logit rule =======================
def test_mined_rule_has_support_and_mentions_logit(tmp_path):
    ce_log = os.path.join(str(tmp_path), "ce.jsonl")
    rules_path = os.path.join(str(tmp_path), "rules.json")
    store.append(ce_log, {"round": 1, **_ce("out_of_unit_range", "score", "score", ["p_hat"])})
    store.append(ce_log, {"round": 1, **_ce("out_of_unit_range", "score", "logit", ["p_hat"])})

    rules = L.mine_binding_rules(min_support=2, ce_log=ce_log, rules_path=rules_path)
    assert any("logit" in r and "probability" in r for r in rules)
    data = json.load(open(rules_path))
    assert all(x["support"] >= 2 for x in data["rules"]) and data["rules"]


def test_rule_below_support_not_emitted(tmp_path):
    ce_log = os.path.join(str(tmp_path), "ce.jsonl")
    rules_path = os.path.join(str(tmp_path), "rules.json")
    store.append(ce_log, {"round": 1, **_ce("out_of_unit_range", "score", "score", ["p_hat"])})
    rules = L.mine_binding_rules(min_support=3, ce_log=ce_log, rules_path=rules_path)
    assert rules == []                                    # one record < min_support -> no rule (no overfit)


# === ACCEPTANCE: a stale seed glob cannot smuggle a phantom artifact past _sanitize =============
def test_seed_cannot_smuggle_phantom_artifact():
    inputs = D.assemble_inputs(REPOB)
    # a "draft" carrying the seed's stale glob as a literal artifact path (no such file in repoB)
    raw = {
        "run": {"entrypoint": "gen_fixture.py"},
        "artifacts": [
            {"path": "out/preds.csv", "columns": {"x": {"tag": "score"}}},   # phantom (repoB has scores.csv)
            {"path": "out/scores.csv", "columns": {"p_hat": {"tag": "prob"}, "y": {"tag": "label"}}},
        ],
        "metrics": [{"metric_id": "auc", "artifact": "out/scores.csv",
                     "binding": {"prob": "p_hat", "label": "y"}, "headline": True}],
    }
    clean = D._sanitize(raw, inputs)
    import draft_contract as DC
    assert "out/preds.csv" not in [a["path"] for a in clean["artifacts"]]   # phantom dropped
    assert DC.validate_contract(clean) == []
