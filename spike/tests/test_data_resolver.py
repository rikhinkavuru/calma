"""External-data resolver: hint extraction, URL preference, and the gated no-key path. (The live Exa search
is validated out-of-band — it finds raw CSV mirrors of the dataset; here we pin the pure logic.)"""
from runner import data_resolver as DR


def test_dataset_hints_extracts_kaggle_slugs(tmp_path):
    (tmp_path / "nb.py").write_text("# ! kaggle datasets download -d uciml/breast-cancer-wisconsin-data\n")
    (tmp_path / "README.md").write_text("data from https://www.kaggle.com/datasets/zynicide/wine-reviews\n")
    h = DR.dataset_hints(str(tmp_path))
    assert "uciml/breast-cancer-wisconsin-data" in h
    assert "zynicide/wine-reviews" in h


def test_pick_url_prefers_raw_csv_and_normalizes_blob():
    urls = ["https://www.kaggle.com/datasets/x/y",
            "https://github.com/u/r/blob/main/data.csv",
            "https://raw.githubusercontent.com/u/r/main/data.csv"]
    assert DR._pick_url(urls) == "https://raw.githubusercontent.com/u/r/main/data.csv"
    # a lone blob URL is normalized to its raw form (directly fetchable)
    assert DR._pick_url(["https://github.com/u/r/blob/main/d.csv"]) == \
        "https://raw.githubusercontent.com/u/r/main/d.csv"
    # no data-extension URL → nothing to fetch
    assert DR._pick_url(["https://www.kaggle.com/datasets/x/y"]) is None


def test_resolve_no_key_is_gated_not_an_error(tmp_path, monkeypatch):
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    ok, note = DR.resolve_missing_data(str(tmp_path), "/content/data.csv", key=None)
    assert ok is False
    assert "paid-tier" in note
