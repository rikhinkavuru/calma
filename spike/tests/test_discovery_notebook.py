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
