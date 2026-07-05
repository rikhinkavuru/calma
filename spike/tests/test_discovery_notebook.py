"""Discovery from a Jupyter notebook's committed cell outputs — a repo whose numbers live only in a rendered
notebook (no results.json/csv/README table) is no longer a 0-claim dead end."""
import json

from discovery import extract


def test_from_notebook_discovers_metrics_in_cell_outputs(tmp_path):
    nb = {"cells": [
        {"cell_type": "code", "outputs": [
            {"output_type": "stream", "text": ["Accuracy: 0.94\n", "test AUC = 0.88\n"]}]},
        {"cell_type": "markdown", "source": ["## Results\nF1 score of 0.72\n"]},
        {"cell_type": "code", "outputs": []},                          # no output -> contributes nothing
    ]}
    p = tmp_path / "analysis.ipynb"
    p.write_text(json.dumps(nb))
    claims = extract.from_notebook(str(p))
    assert claims and all(c["source"] == "notebook-output" for c in claims)
    assert len(claims) >= 2                                            # accuracy + AUC at minimum
    assert all(c.get("location", "").startswith("analysis.ipynb") for c in claims)


def test_from_notebook_execute_result_text_plain(tmp_path):
    nb = {"cells": [{"cell_type": "code", "outputs": [
        {"output_type": "execute_result", "data": {"text/plain": ["balanced accuracy: 0.831"]}}]}]}
    p = tmp_path / "r.ipynb"
    p.write_text(json.dumps(nb))
    assert extract.from_notebook(str(p))                              # recognized from a text/plain repr


def test_from_notebook_missing_or_empty_is_honest_empty(tmp_path):
    assert extract.from_notebook(str(tmp_path / "nope.ipynb")) == []
    (tmp_path / "blank.ipynb").write_text(json.dumps({"cells": []}))
    assert extract.from_notebook(str(tmp_path / "blank.ipynb")) == []


def test_discovers_arbitrary_result_jsons_under_results_dir(tmp_path):
    # the real ebv-ms shape: numbers committed in results/benchmark_ci.json (arbitrary name, nested, biomed
    # metric synonyms) — previously 0 claims because discovery only scanned root + fixed _RESULT_FILES names.
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "benchmark_ci.json").write_text(json.dumps(
        {"point": {"homology_sensitivity_testable": 0.9637, "homology_specificity": 0.9923}}))
    (tmp_path / "results" / "config.json").write_text(json.dumps({"seed": 42, "n_boot": 10000}))  # non-metric -> 0
    claims = extract.discover(str(tmp_path))
    assert any(c["metric"] == "recall" for c in claims)          # sensitivity == recall (TPR)
    assert any(c["metric"] == "specificity" for c in claims)
    assert not any(c["value"] in ("42", "10000") for c in claims)   # config numbers are not metrics


def test_map_metric_biomed_synonyms():
    from discovery.extract import map_metric
    assert map_metric("homology_sensitivity_testable")[0] == "recall"
    assert map_metric("specificity")[0] == "specificity"
