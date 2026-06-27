"""Auto-entrypoint detection: deep verify should find the repo's run script without the user naming it."""
from runner import build


def test_detect_common_entrypoint_name(tmp_path):
    (tmp_path / "main.py").write_text("print(1)")
    assert build.detect_entrypoint(str(tmp_path)) == ["main.py"]


def test_readme_run_command_wins(tmp_path):
    (tmp_path / "run_benchmark.py").write_text("print(1)")
    (tmp_path / "helper.py").write_text("print(2)")
    (tmp_path / "README.md").write_text("## Reproduce\n```bash\npython run_benchmark.py --all\n```\n")
    assert build.detect_entrypoint(str(tmp_path)) == ["run_benchmark.py"]


def test_detect_module_invocation(tmp_path):
    (tmp_path / "README.md").write_text("Train with `python -m training.train` to reproduce.")
    assert build.detect_entrypoint(str(tmp_path)) == ["-m", "training.train"]


def test_no_entrypoint(tmp_path):
    (tmp_path / "data.csv").write_text("a,b\n1,2\n")
    assert build.detect_entrypoint(str(tmp_path)) is None
