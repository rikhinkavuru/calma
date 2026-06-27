"""Claim-discovery (TDMR) extraction tests: metric-name → catalog mapping, value parsing, and end-to-end
discovery over a results.json + README + stdout."""
import json
import os

from discovery import extract as D

FIX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")


def test_map_metric_aliases_and_keywords():
    assert D.map_metric("test_accuracy")[:2] == ("accuracy", "test")
    assert D.map_metric("val_roc_auc")[:2] == ("roc_auc", "val")
    assert D.map_metric("Macro F1")[0] == "f1"
    assert D.map_metric("AUROC")[0] == "roc_auc"
    assert D.map_metric("R2")[0] == "r2"
    assert D.map_metric("training RMSE")[:2] == ("rmse", "train")
    assert D.map_metric("BLEU")[0] is None          # not in the catalog -> not mapped
    assert D.map_metric("loss")[0] is None


def test_from_results_json(tmp_path):
    p = tmp_path / "results.json"
    p.write_text(json.dumps({"test_accuracy": 0.755, "test_roc_auc": 0.8146,
                             "test_f1": 0.6726, "epoch": 10, "loss": 0.21}))
    claims = D.from_results_json(str(p))
    by = {c["metric"]: c for c in claims}
    assert set(by) == {"accuracy", "roc_auc", "f1"}        # epoch/loss are not catalog metrics
    assert by["accuracy"]["value"] == "0.755" and by["accuracy"]["split"] == "test"
    assert by["roc_auc"]["value"] == "0.8146"


def test_from_text_table_and_kv():
    text = """
    ## Results
    | Metric | Value |
    |---|---|
    | Accuracy | 0.92 |
    | Test AUC | 0.88 |

    We report a final Accuracy: 96.67% on the held-out set, F1 = 0.80.
    """
    claims = D.from_text(text, location="README.md")
    metrics = {c["metric"] for c in claims}
    assert {"accuracy", "roc_auc", "f1"} <= metrics
    vals = {(c["metric"], c["value"]) for c in claims}
    assert ("accuracy", "0.92") in vals and ("accuracy", "96.67%") in vals  # both, deduped on value


def test_discover_realistic_repo():
    # the realistic fixture ships a results.json (written by train.py) — discover its headline numbers
    claims = D.discover(os.path.join(FIX, "realistic_sklearn"),
                        stdout_text='{"test_accuracy": 0.755, "test_roc_auc": 0.8146, "test_f1": 0.6726}')
    metrics = {c["metric"] for c in claims}
    assert {"accuracy", "roc_auc", "f1"} <= metrics
    assert all("id" in c and 0.0 < c["confidence"] <= 1.0 for c in claims)
