"""Committed-data relink + the resolve_data_path orchestrator tool: make a missing-data run RUNNABLE by
placing a file already committed under a different path where the code reads it — inputs only, no compute
edit (full verdict eligible), no network, FCR-safe."""
import os
import tempfile

from runner import data_resolver as DR
from orchestrator import registry as REG
import orchestrator.tools_exec  # noqa: F401 — registers resolve_data_path


def _repo():
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "iris.csv"), "w") as fh:      # committed at ROOT
        fh.write("a,y\n1,0\n2,1\n")
    return d


def test_relink_places_committed_file_at_read_path():
    d = _repo()
    placed = DR.relink_committed_data(d, "data/iris.csv")    # code reads data/iris.csv
    assert placed == os.path.join("data", "iris.csv")
    assert os.path.isfile(os.path.join(d, "data", "iris.csv"))


def test_relink_none_when_absolute_path():
    d = _repo()
    assert DR.relink_committed_data(d, "/content/iris.csv") is None      # abs — out of scope
    assert DR.relink_committed_data(d, "D:\\ml\\iris.csv") is None


def test_relink_none_when_not_committed():
    d = _repo()
    assert DR.relink_committed_data(d, "data/absent.csv") is None


def test_resolve_data_path_tool_registered_and_relinks():
    assert REG.has("resolve_data_path")
    d = _repo()
    placed, note, modified = REG.call("resolve_data_path", d, "FileNotFoundError: [Errno 2] No such file or directory: 'sub/iris.csv'")
    assert placed and "relinked" in note
    assert modified == []                               # same-basename relink → no cap (repo's own file)


def test_tool_is_verdict_free():
    t = REG.get("resolve_data_path")
    assert t.touches_verdict is False


def test_make_data_available_relative_relinks_no_rewrite():
    d = _repo()
    placed, modified = DR.make_data_available(d, "data/iris.csv")
    assert placed == os.path.join("data", "iris.csv") and modified == []   # no source edit


def test_make_data_available_absolute_places_and_rewrites():
    import tempfile
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "magic04.data"), "w") as fh:
        fh.write("1,2,g\n")
    with open(os.path.join(d, "run.py"), "w") as fh:
        fh.write('import pandas as pd\ndf = pd.read_csv("/content/magic04.data")\n')
    placed, modified = DR.make_data_available(d, "/content/magic04.data")
    assert placed == "magic04.data" and modified == ["run.py"]   # source edit -> caller caps to REPRODUCED-ONLY
    assert 'read_csv(\'magic04.data\')' in open(os.path.join(d, "run.py")).read()


def test_sole_dataset_substitution_is_capped():
    """FCR (B1): a DIFFERENT-named sole committed dataset placed for the requested relative path is a data
    SUBSTITUTION — make_data_available must return a marker so the verdict caps at REPRODUCED-ONLY, never a
    silent CONFIRM on the wrong file. Same-basename relink stays uncapped (tested above)."""
    import tempfile
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "heart_cleveland.csv"), "w") as fh:   # the ONE committed dataset, different name
        fh.write("age,target\n60,1\n")
    placed, modified = DR.make_data_available(d, "data/heart.csv")  # code asks for heart.csv (not committed)
    assert placed == os.path.join("data", "heart.csv")             # placed at the requested read path
    assert modified and any("data-substituted" in m for m in modified)   # → source_modified → REPRODUCED-ONLY cap
    assert "heart_cleveland.csv" in modified[0]                     # discloses which file was actually used


def test_rewrite_only_touches_the_matching_literal():
    import tempfile
    d = tempfile.mkdtemp()
    with open(os.path.join(d, "run.py"), "w") as fh:
        fh.write('a = "/content/x.csv"\nb = "keep_me.csv"\n')
    DR.rewrite_data_path(d, "/content/x.csv", "x.csv")
    src = open(os.path.join(d, "run.py")).read()
    assert "'x.csv'" in src and "keep_me.csv" in src        # other literals untouched


def test_catalog_resolves_common_ml_dataset():
    from runner import data_catalog as DC
    assert "uci.edu" in (DC.resolve_path("magic04.data") or "")
    assert "wine-quality" in (DC.resolve_path("winequality-red.csv") or "")
    assert DC.resolve_path("random_unknown_file.csv") is None
