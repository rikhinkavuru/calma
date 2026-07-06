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
    assert D.map_metric("BLEU")[0] == "bleu"         # now a catalog metric (guide §B.3)
    assert D.map_metric("nDCG")[0] == "ndcg"
    assert D.map_metric("loss")[0] is None           # still not a recomputable metric


def test_plausible_value_drops_support_count_kept_percent_and_fraction():
    # a [0,1] metric written as a bare integer > 1 is a count (classification_report support column), not a score
    assert D._plausible_value({"metric": "accuracy", "value": "72"}) is False
    assert D._plausible_value({"metric": "f1", "value": "114"}) is False
    assert D._plausible_value({"metric": "recall", "value": "11"}) is False
    # valid forms survive: a percentage, a fraction, and exactly 1.0 / 100%
    assert D._plausible_value({"metric": "accuracy", "value": "95%"}) is True
    assert D._plausible_value({"metric": "accuracy", "value": "0.98"}) is True
    assert D._plausible_value({"metric": "accuracy", "value": "1.0"}) is True
    assert D._plausible_value({"metric": "accuracy", "value": "100%"}) is True
    # unbounded metrics can legitimately exceed 1 → never dropped
    assert D._plausible_value({"metric": "rmse", "value": "72"}) is True
    assert D._plausible_value({"metric": "sharpe", "value": "2"}) is True


def test_discover_drops_classification_report_support_counts(tmp_path):
    # the exact false-REFUTE shape from the 2026-07-06 eval: a classification_report block in a README whose
    # SUPPORT column integers (42, 72, 114) were being mined as "accuracy" claims
    (tmp_path / "README.md").write_text(
        "The model achieved 98% accuracy on the test set.\n\n"
        "## Results\n```\n"
        "              precision    recall  f1-score   support\n"
        "       0       0.98      0.98      0.98        42\n"
        "       1       0.99      0.99      0.99        72\n"
        "    accuracy                           0.98       114\n"
        "```\n")
    claims = D.discover(str(tmp_path))
    vals = {c["value"] for c in claims}
    assert "72" not in vals and "114" not in vals and "42" not in vals   # support counts dropped, no false REFUTE
    # a genuine prose accuracy claim still survives the filter
    assert any(c["metric"] == "accuracy" and c["value"] == "98%" for c in claims)


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


def test_from_results_json_nested_carries_context():
    """A nested leaderboard JSON must bind per-cell: each metric leaf keeps its dataset/model ancestors as
    context, so identical metric+value cells across datasets stay distinct (fixes the ambiguous→INCONCLUSIVE
    collapse). Handles both metric-inner and metric-outer nestings."""
    import json as _j
    import tempfile
    import os as _os
    data = {"resnet": {"cifar10": {"test_accuracy": 0.91}, "mnist": {"test_accuracy": 0.99}},
            "accuracy": {"svhn": 0.88}}   # metric-outer transpose too
    fd, p = tempfile.mkstemp(suffix=".json")
    _os.write(fd, _j.dumps(data).encode())
    _os.close(fd)
    claims = D.from_results_json(p)
    _os.unlink(p)
    by_ctx = {frozenset(c.get("context", "").split()): c for c in claims if c["metric"] == "accuracy"}
    # three distinct cells, each with its own context — none collapsed
    assert any("cifar10" in k and "resnet" in k for k in by_ctx)
    assert any("mnist" in k and "resnet" in k for k in by_ctx)
    assert any("svhn" in k for k in by_ctx)
    cif = next(c for k, c in by_ctx.items() if "cifar10" in k)
    assert cif["value"] == "0.91" and cif["split"] == "test"


def test_from_markdown_wide_leaderboard_table():
    """The 'paper Table 3' shape: metrics as COLUMNS, one row per model/dataset. Each cell → its own claim
    carrying Model=/Dataset= context; the 2-col transpose form is left to _ROW_RE (not double-counted)."""
    text = """
    ## Leaderboard
    | Model  | Dataset | Accuracy | Macro F1 |
    |--------|---------|----------|----------|
    | ResNet | CIFAR10 | 0.912    | 0.889    |
    | ViT    | CIFAR10 | 0.934    | 0.901    |
    | ResNet | MNIST   | 0.993    | 0.990    |
    """
    claims = D.from_markdown_tables(text, location="README.md")
    # each cell's context (as the binder sees it, after stop-word stripping) must carry its row's identifiers
    cells = {(c["metric"], c["value"]): _ctx_toks(c.get("context", "")) for c in claims}
    assert {"resnet", "cifar10"} <= cells[("accuracy", "0.912")]
    assert {"vit", "cifar10"} <= cells[("accuracy", "0.934")]
    assert {"resnet", "mnist"} <= cells[("f1", "0.990")]
    # six data cells (3 rows × 2 metric cols), none collapsed
    assert len([c for c in claims if c["metric"] in ("accuracy", "f1")]) == 6


def test_from_markdown_skips_transpose_table():
    """A | Metric | Value | table has no metric-mapped header → skipped here (handled by from_text/_ROW_RE),
    so it isn't double-counted."""
    text = "| Metric | Value |\n|---|---|\n| Accuracy | 0.92 |\n"
    assert D.from_markdown_tables(text) == []
    # but from_text still catches it via _ROW_RE
    assert any(c["metric"] == "accuracy" and c["value"] == "0.92" for c in D.from_text(text))


def _ctx_toks(s):
    import re as _re
    return {t for t in _re.split(r"[^a-z0-9]+", (s or "").lower()) if len(t) >= 2 and not t.isdigit()}


def test_discover_realistic_repo():
    # the realistic fixture ships a results.json (written by train.py) — discover its headline numbers
    claims = D.discover(os.path.join(FIX, "realistic_sklearn"),
                        stdout_text='{"test_accuracy": 0.755, "test_roc_auc": 0.8146, "test_f1": 0.6726}')
    metrics = {c["metric"] for c in claims}
    assert {"accuracy", "roc_auc", "f1"} <= metrics
    assert all("id" in c and 0.0 < c["confidence"] <= 1.0 for c in claims)


def test_discover_scans_the_entrys_own_subdirectory(tmp_path):
    """A repo-root README claim and a nested-entrypoint's OWN README claim must both surface — a monorepo
    with a runnable example nested under its own subfolder (demo-repo/, examples/mnist/, ...) is a real,
    common shape. Before this fix, discover() only ever scanned repo_dir's root, so a claim documented next
    to the entry it's actually about (not repo_dir's own top-level README) was silently invisible — exactly
    what happened running calma's own live demo (entry=demo-repo/eval.py inside the calma monorepo)."""
    (tmp_path / "README.md").write_text("Top-level project. See subfolders for examples.\n")
    sub = tmp_path / "demo-repo"
    sub.mkdir()
    (sub / "README.md").write_text("Test accuracy: 94.2%\n")
    claims = D.discover(str(tmp_path), entry="demo-repo/eval.py")
    assert any(c["metric"] == "accuracy" and c["value"] == "94.2%" for c in claims), claims


def test_discover_entry_at_repo_root_is_unaffected(tmp_path):
    (tmp_path / "README.md").write_text("Accuracy: 90.0%\n")
    claims_with_entry = D.discover(str(tmp_path), entry="eval.py")
    claims_without = D.discover(str(tmp_path))
    assert claims_with_entry == claims_without
