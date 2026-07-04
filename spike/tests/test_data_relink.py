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
    placed, note = REG.call("resolve_data_path", d, "FileNotFoundError: [Errno 2] No such file or directory: 'sub/iris.csv'")
    assert placed and "relinked" in note


def test_tool_is_verdict_free():
    t = REG.get("resolve_data_path")
    assert t.touches_verdict is False
