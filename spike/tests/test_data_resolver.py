"""External-data resolver: hint extraction, URL preference, and the gated no-key path. (The live Exa search
is validated out-of-band — it finds raw CSV mirrors of the dataset; here we pin the pure logic.)"""
import os

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


def test_contained_rejects_outside_paths_and_traversal(tmp_path):
    root = str(tmp_path)
    assert DR._contained(root, root)
    assert DR._contained(os.path.join(root, "a", "b.csv"), root)
    assert not DR._contained("/etc/passwd", root)
    assert not DR._contained(os.path.join(root, "..", "outside.csv"), root)
    assert not DR._contained("/", root)


def test_resolve_missing_data_never_writes_outside_repo_dir(tmp_path, monkeypatch):
    """The attacker controls `missing_path` (it's parsed straight out of the repo's OWN stderr — see
    missing_data_path's regex). A crafted 'FileNotFoundError: '/etc/cron.d/x'' must never reach a real write
    outside repo_dir, even though the resolver's whole job is to fetch-and-write a file for the re-run."""
    repo_dir = str(tmp_path / "repo")
    os.makedirs(repo_dir)
    monkeypatch.setattr(DR, "_exa_search", lambda q, k: ["https://raw.githubusercontent.com/u/r/main/x.csv"])
    writes = []

    def fake_fetch_to(url, dest, **kw):
        writes.append(dest)
        with open(dest, "wb") as fh:
            fh.write(b"data")
        return 4
    monkeypatch.setattr(DR, "fetch_to", fake_fetch_to)

    outside = "/etc/cron.d/evil-payload.csv"
    ok, note = DR.resolve_missing_data(repo_dir, outside, key="fake-key")
    assert ok is True                                # the safe repo_dir/name write still succeeds
    assert all(DR._contained(w, repo_dir) for w in writes), writes
    assert outside not in writes                      # the attacker-controlled absolute path was refused
    assert not os.path.exists(outside)


def test_resolve_missing_data_allows_absolute_path_inside_repo_dir(tmp_path, monkeypatch):
    """A repo that computes its own absolute path via os.path.abspath() and it happens to land inside
    repo_dir is the legitimate case the second write exists for — that one should still work."""
    repo_dir = str(tmp_path / "repo")
    os.makedirs(os.path.join(repo_dir, "data"))
    monkeypatch.setattr(DR, "_exa_search", lambda q, k: ["https://raw.githubusercontent.com/u/r/main/x.csv"])
    writes = []

    def fake_fetch_to(url, dest, **kw):
        writes.append(dest)
        return 4
    monkeypatch.setattr(DR, "fetch_to", fake_fetch_to)

    inside = os.path.join(repo_dir, "data", "train.csv")
    ok, _ = DR.resolve_missing_data(repo_dir, inside, key="fake-key")
    assert ok is True
    assert inside in writes
