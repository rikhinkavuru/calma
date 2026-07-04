"""The google.colab shim: outside Colab, `from google.colab import files; files.upload()` must succeed and
return the repo's committed data, so Colab-exported notebooks run instead of dying on cell 1."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "capture"))


def test_upload_returns_committed_data(tmp_path, monkeypatch):
    import colab_shim
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    (tmp_path / "notes.md").write_text("not data")
    monkeypatch.chdir(tmp_path)
    # ensure a clean slate, then install the shim
    for m in [k for k in sys.modules if k.startswith("google.colab")]:
        del sys.modules[m]
    colab_shim.install()
    from google.colab import files, drive
    up = files.upload()
    assert "data.csv" in up and up["data.csv"] == b"a,b\n1,2\n"
    assert "notes.md" not in up            # only data files
    drive.mount("/content/drive")          # no-op, must not raise
