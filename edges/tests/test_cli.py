"""A1 CLI seam acceptance tests -- `python -m edges.extract <target>` end to end.

The CLI orchestrates ingest -> route(extract) -> to_contract(engine.verify) -> reconcile(render).
The extraction step calls the LLM for the moderate/complex spans (the markdown intro + the two CSV
data-summary spans), so the suite REPLAYS recorded fixtures (edges/tests/fixtures/<hash>.json);
conftest forces replay (CALMA_EDGES_RECORD off) so no ANTHROPIC_API_KEY is needed. The 3 metric
OUTPUT spans (accuracy/auc/total_return) take the no-LLM heuristic path, so the asserted verdicts do
NOT depend on any model output -- only on the deterministic engine recompute.

Record the fixtures ONCE with the models live (the request hashes embed only span text + BASENAME
provenance, so a tmp copy of the target replays the same fixtures):

    CALMA_EDGES_RECORD=1 ANTHROPIC_API_KEY=... \
        PYTHONPATH=. ~/.cache/calma-edges-venv/bin/python -m edges.extract \
        edges/tests/fixtures/targets/nb_run --json --mode fix

The "fixture target" is nb_run: report.ipynb prints accuracy=0.90 (reproduces), auc=1.0 (reproduces),
and an overstated total return of +14,698% that the OOS return series (compounding to ~ -32%) REFUTES.
Each test runs on a FRESH tmp copy so the engine's verify.yaml + .calma run dir never touch the
committed fixture; the engine subprocesses to system python3, so the runtime is available under the
edges venv.
"""
import hashlib
import json
import os
import shutil

import pytest

from edges.extract import cli

HERE = os.path.dirname(__file__)
FIXT_TARGET = os.path.join(HERE, "fixtures", "targets", "nb_run")
SCRIPTS = os.path.abspath(os.path.join(HERE, "..", "..", ".claude", "skills", "calma", "scripts"))


@pytest.fixture
def nb_run(tmp_path):
    dst = os.path.join(str(tmp_path), "nb_run")
    shutil.copytree(FIXT_TARGET, dst)
    return dst


def _scripts_manifest():
    """(rel_path, size, mtime_ns) for every file under scripts/ -- a fingerprint to prove the CLI
    writes NOTHING there (the firewall guarantees no import; this guarantees no side-effect write)."""
    out = {}
    for dp, _dirs, names in os.walk(SCRIPTS):
        for n in names:
            p = os.path.join(dp, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out[os.path.relpath(p, SCRIPTS)] = (st.st_size, st.st_mtime_ns)
    return out


def _refuted(report):
    return [c for c in report.claims if c.verdict in ("REFUTED", "INVALIDATED")]


# === ACCEPTANCE: the catch sorts first with a cell citation; exit code is a catch ==============
def test_cli_flags_overstated_metric_as_refuted_first(nb_run):
    report, stats, handoffs = cli.run(nb_run, mode="flag")

    # >= 1 claim extracted, and the run is a catch (exit 1) -- never a crash, never exit 2 here
    assert len(report.claims) >= 1
    assert cli.exit_code_for(report.repo_verdict) in (0, 1)
    assert cli.exit_code_for(report.repo_verdict) == 1          # total_return is REFUTED -> a catch

    # the overstated metric the data refutes sorts FIRST, citing its own notebook cell
    first = report.claims[0]
    assert first.metric_id == "total_return"
    assert first.verdict == "REFUTED"
    assert "cell 5" in first.citation                           # the citation names the source cell
    assert "+14,698%" in first.citation                         # the claimed literal, engine-formatted
    assert first.claimed is not None and first.claimed > 0      # the ORIGINAL claim, not the recompute
    assert first.recomputed is not None and first.recomputed < 0  # OOS compounds to ~ -32%

    # the heuristic-path metrics reproduce (model-independent: pure engine recompute)
    by = {c.metric_id: c for c in report.claims}
    assert by["accuracy"].verdict == "CONFIRMED"
    assert by["auc"].verdict == "CONFIRMED"

    # the cheap-first router carried the simple spans with no LLM; the cost line is real
    assert stats.heuristic == 3                                 # accuracy/auc/total_return outputs
    assert stats.claims == 6                                    # 6 spans seen (one classify each)
    assert handoffs == []                                       # flag mode never packages handoffs


# === ACCEPTANCE: --json parses to a Report with >=1 claim; exit code propagates =================
def test_cli_json_output_parses_and_exit_code(nb_run, capsys):
    rc = cli.main([nb_run, "--json"])
    assert rc == 1                                              # a catch
    payload = json.loads(capsys.readouterr().out)
    assert payload["repo_verdict"] in ("REFUTED", "INVALIDATED", "MIXED")
    assert len(payload["claims"]) >= 1
    assert payload["claims"][0]["metric_id"] == "total_return"
    assert payload["claims"][0]["verdict"] == "REFUTED"
    assert "route_stats" in payload and payload["route_stats"]["claims"] == 6

    # the JSON validates against reconcile's published Report schema (no invented fields)
    from jsonschema import validate
    from edges.extract import reconcile as RC
    report_only = {k: payload[k] for k in ("target", "repo_verdict", "summary", "fix", "claims")}
    validate(instance=report_only, schema=RC.REPORT_SCHEMA)


# === ACCEPTANCE: --mode fix hands off every REFUTED/INVALIDATED with an existing run_dir ========
def test_cli_fix_mode_packages_handoffs(nb_run):
    report, _stats, handoffs = cli.run(nb_run, mode="fix")

    catches = _refuted(report)
    assert len(catches) >= 1
    assert len(handoffs) == len(catches)                       # one handoff per catch
    for h in handoffs:
        assert h.metric_id in {c.metric_id for c in catches}
        assert h.claimed_value is not None and h.claimed_value > 0   # ORIGINAL claim (anti-test-hacking)
        assert os.path.isdir(h.run_dir)                        # the engine run dir really exists
    # the total_return catch is handed off with its original +14,698% (146.98), not the recompute
    tr = next(h for h in handoffs if h.metric_id == "total_return")
    assert abs(tr.claimed_value - 146.98) < 0.01


# === ACCEPTANCE: writes NOTHING under scripts/; a second run is deterministic ===================
def test_cli_no_scripts_write_and_deterministic(tmp_path):
    before = _scripts_manifest()

    def run_once():
        dst = os.path.join(str(tmp_path), "run_%d" % run_once.n)
        run_once.n += 1
        shutil.copytree(FIXT_TARGET, dst)
        report, stats, _ = cli.run(dst, mode="flag")
        return report, stats
    run_once.n = 0

    r1, s1 = run_once()
    r2, s2 = run_once()

    assert _scripts_manifest() == before                       # the CLI touched NOTHING under scripts/

    # determinism: same claims (metric/verdict/citation), same routing -- target/run_dir paths aside
    def shape(rep):
        return [(c.metric_id, c.verdict, c.claimed, c.recomputed, c.citation) for c in rep.claims]
    assert shape(r1) == shape(r2)
    assert r1.repo_verdict == r2.repo_verdict and r1.summary == r2.summary
    assert s1.to_json() == s2.to_json()

    # a stable content hash over the path-independent shape (belt and suspenders against drift)
    def digest(rep):
        return hashlib.sha256(json.dumps(shape(rep), default=str).encode()).hexdigest()
    assert digest(r1) == digest(r2)
