"""Artifact-reproduction verification — snapshot committed result files, then diff against a regenerated run.
Pure + FCR-firewalled (no verdict authorship here); it reports whether committed numbers regenerate."""

import json

from core import artifact_repro as AR


def test_csv_cells_id_keyed_and_telemetry_skipped(tmp_path):
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "leaderboard.csv").write_text(
        "model,accuracy,runtime_sec\nGPT,0.87,3.2\nQwen,0.85,4.1\n")
    snap = AR.snapshot(str(tmp_path))
    cells = snap["results/leaderboard.csv"]
    assert cells["GPT|accuracy"] == 0.87 and cells["Qwen|accuracy"] == 0.85   # id-keyed by model name
    assert not any("runtime" in k for k in cells)                             # telemetry excluded


def test_json_nested_leaves(tmp_path):
    (tmp_path / "metrics.json").write_text(json.dumps(
        {"reliability": {"split_half_r": 0.51, "spearman_brown": 0.68}, "elapsed": 12.3,
         "models": [{"name": "A", "acc": 0.9}]}))
    cells = AR.snapshot(str(tmp_path))["metrics.json"]
    assert cells["reliability.split_half_r"] == 0.51
    assert cells["models[0].acc"] == 0.9
    assert "elapsed" not in cells                                             # telemetry excluded


def test_reproduced_when_identical(tmp_path):
    (tmp_path / "results.json").write_text(json.dumps({"acc": 0.912, "f1": 0.88}))
    snap = AR.snapshot(str(tmp_path))
    rep = AR.diff(snap, snap)
    assert rep["status"] == "reproduced" and rep["n_changed"] == 0 and rep["n_match"] == 2


def test_not_reproduced_names_the_cell(tmp_path):
    (tmp_path / "results.json").write_text(json.dumps({"acc": 0.912, "f1": 0.88}))
    before = AR.snapshot(str(tmp_path))
    (tmp_path / "results.json").write_text(json.dumps({"acc": 0.951, "f1": 0.88}))   # acc drifted
    after = AR.snapshot(str(tmp_path))
    rep = AR.diff(before, after)
    assert rep["status"] == "not-reproduced" and rep["n_changed"] == 1
    c = rep["changed"][0]
    assert c["cell"] == "acc" and c["committed"] == 0.912 and c["regenerated"] == 0.951


def test_tolerance_absorbs_float_noise(tmp_path):
    (tmp_path / "results.json").write_text(json.dumps({"acc": 0.9120000}))
    before = AR.snapshot(str(tmp_path))
    (tmp_path / "results.json").write_text(json.dumps({"acc": 0.9120001}))
    assert AR.diff(before, AR.snapshot(str(tmp_path)))["status"] == "reproduced"


def test_no_artifacts_is_incomplete(tmp_path):
    (tmp_path / "src.py").write_text("x = 1\n")
    assert AR.diff(AR.snapshot(str(tmp_path)), {})["status"] == "incomplete"


def test_missing_regeneration_is_not_a_mismatch(tmp_path):
    # a committed file the run didn't regenerate is 'not_regenerated', never counted as a value mismatch
    (tmp_path / "results.json").write_text(json.dumps({"acc": 0.9}))
    before = AR.snapshot(str(tmp_path))
    rep = AR.diff(before, {})                       # nothing regenerated
    assert rep["status"] == "incomplete" and rep["n_changed"] == 0 and rep["n_not_regenerated"] == 1
