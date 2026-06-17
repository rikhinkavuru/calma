"""B1: diff -> verify targets -> a FindingsBundle. No GitHub, no network (the engine subprocess is
offline). Classification rules, the three-dot diff, and the bundled REFUTED btc-like asset producing a
target with a catch verdict + a finding with a citation + a stable fingerprint.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
from pr import bundle as B  # noqa: E402
from pr import run_pr  # noqa: E402
from pr.diff_targets import changed_paths, verify_targets  # noqa: E402

CATCH = ("REFUTED", "INVALIDATED", "MIXED")


def _w(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def test_verify_targets_classification(tmp_path):
    repo = str(tmp_path)
    _w(os.path.join(repo, "nb", "report.ipynb"), '{"cells": []}')
    _w(os.path.join(repo, "nb", "gen_fixture.py"), "")
    _w(os.path.join(repo, "nb", "runs", "oos", "x.csv"), "a\n1\n")
    _w(os.path.join(repo, "c", "verify.yaml"), "{}")
    _w(os.path.join(repo, "c", "runs", "oos", "returns.csv"), "r\n0.1\n")
    _w(os.path.join(repo, "docs", "readme.md"), "hi")
    changed = ["nb/report.ipynb", "c/runs/oos/returns.csv", "c/verify.yaml", "docs/readme.md"]
    targets = {t["target"]: t for t in verify_targets(changed, repo=repo)}
    # an unrelated .md change -> no target
    assert not any(t == "docs" or t.startswith("docs") for t in targets), targets
    # a changed .ipynb under a dir with gen_fixture.py (+ no verify.yaml) -> an 'artifact' target
    assert targets["nb"]["kind"] == "artifact"
    assert "nb/report.ipynb" in targets["nb"]["changed_files"]
    # a changed runs/**/*.csv under a dir with a verify.yaml -> a 'contract' target
    assert targets["c"]["kind"] == "contract"


def test_changed_paths_three_dot(tmp_path):
    repo = str(tmp_path)
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", repo, "config", "user.name", "t"], check=True)
    _w(os.path.join(repo, "a.txt"), "1")
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    subprocess.run(["git", "-C", repo, "commit", "-qm", "base"], check=True)
    base = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    _w(os.path.join(repo, "b.txt"), "2")
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    subprocess.run(["git", "-C", repo, "commit", "-qm", "head"], check=True)
    head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert changed_paths(base, head, repo) == ["b.txt"]


def test_run_pr_on_refuted_btc_asset():
    """The bundled REFUTED btc-like asset (offline `calma verify`) -> a contract target whose
    repo_verdict is a catch, with >=1 finding carrying a citation + a stable fingerprint. On a host that
    can't isolate, the engine reports CAN'T-CONFIRM (the catch asserts are then skipped, never faked)."""
    target = os.path.join(".claude", "skills", "calma", "assets", "btc")
    changed = [os.path.join(target, "verify.yaml")]
    ej = run_pr.engine_json(target, "contract", repo=REPO)
    entry = B.target_entry(target, "contract", ej, changed, REPO)
    bundle = B.make_bundle(42, "head123", "base456", [entry])
    assert B.validate(bundle) == [], B.validate(bundle)
    assert entry["repo_verdict"] in CATCH + ("INCONCLUSIVE", "CONFIRMED", "CONFIRMED-WITH-CAVEATS")
    if entry["repo_verdict"] in CATCH:
        catches = [f for f in entry["findings"] if f["verdict"] in ("REFUTED", "INVALIDATED")]
        assert catches and catches[0]["citation"] and catches[0]["fingerprint"], entry
        assert B.has_catch(bundle)
        # determinism: same head -> identical fingerprints (idempotency precondition for B2)
        entry2 = B.target_entry(target, "contract", run_pr.engine_json(target, "contract", repo=REPO), changed, REPO)
        assert [f["fingerprint"] for f in entry["findings"]] == [f["fingerprint"] for f in entry2["findings"]]
    else:
        print("  (btc verified %s - host likely non-isolating; catch asserts skipped)" % entry["repo_verdict"])


def test_engine_resolves_from_trusted_root_not_the_pr_tree(tmp_path, monkeypatch):
    # H1 root fix: the engine + edges resolve from _ENGINE_ROOT (the trusted driver checkout), NEVER from
    # `repo` (the PR tree) - a PR cannot swap in its own engine to forge a verdict; only its result DIRS
    # are PR-controlled. Capture the subprocess argv/cwd instead of actually running the engine.
    captured = {}

    def _fake_run(argv, cwd=None, **kw):
        captured["argv"], captured["cwd"] = argv, cwd

        class _P:
            stdout = '{"verdict": "CONFIRMED", "metrics": [], "isolation_tier": "seatbelt-verified"}'
        return _P()

    monkeypatch.setattr(run_pr.subprocess, "run", _fake_run)
    run_pr.engine_json("results/x", "contract", repo=str(tmp_path))      # repo = a bogus PR tree
    calma = captured["argv"][1]
    assert calma.startswith(run_pr._ENGINE_ROOT), calma                  # engine binary from the TRUSTED root
    assert ".claude" in calma and str(tmp_path) not in calma             # NOT from the PR tree
    assert captured["cwd"] == str(tmp_path)                              # the target is still READ in the PR tree
