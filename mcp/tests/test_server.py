"""Calma MCP server acceptance tests -- an in-process MCP client session over the low-level server.

The calma_verify path is fully DETERMINISTIC: it shells out to `calma.py verify ... --json`, the engine
runs under system python3, and makes NO LLM call -- so these tests need no ANTHROPIC_API_KEY and no
fixtures. calma_verify_artifact wraps the A1 CLI seam (`python -m edges.extract`); the A1 LLM extraction
replays the committed edges fixtures (the server clears CALMA_EDGES_RECORD), so it too needs no key.

Every test sets CALMA_MCP_WORKSPACE to a known root so the workspace jail is deterministic regardless
of the pytest cwd.
"""
import json
import os
import shutil

import anyio
import pytest

from mcp.shared.memory import create_connected_server_and_client_session as connect

from calma_mcp import server
from calma_mcp.server import build_server

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BTC_ASSET = os.path.join(REPO_ROOT, ".claude", "skills", "calma", "assets", "btc")
NB_RUN = os.path.join(REPO_ROOT, "edges", "tests", "fixtures", "targets", "nb_run")


async def _list_tools():
    async with connect(build_server()) as session:
        await session.initialize()
        return await session.list_tools()


async def _call(name, arguments):
    async with connect(build_server()) as session:
        await session.initialize()
        return await session.call_tool(name, arguments)


def _payload(result):
    """The engine JSON the tool returned (verbatim, in the first text content block)."""
    assert not result.isError, getattr(result.content[0], "text", result)
    return json.loads(result.content[0].text)


# === ACCEPTANCE: list_tools advertises calma_verify with its documented schema =================
def test_list_tools_includes_calma_verify_schema():
    tools = anyio.run(_list_tools)
    by_name = {t.name: t for t in tools.tools}
    assert "calma_verify" in by_name
    assert "calma_verify_artifact" in by_name
    assert "calma_suggest" in by_name

    schema = by_name["calma_verify"].inputSchema
    assert schema["required"] == ["target"]
    props = schema["properties"]
    # the safety flags reach the engine -- they must be part of the advertised input
    for flag in ("target", "claim", "metric", "mode", "trust", "isolation", "timeout",
                 "check_determinism"):
        assert flag in props, flag
    assert props["trust"]["enum"] == ["own-code", "third-party"]


# === ACCEPTANCE: calma_verify on the btc asset -> REFUTED, recomputed ~ -0.32, run_dir exists ===
def test_calma_verify_btc_asset_is_refuted(monkeypatch):
    monkeypatch.setenv("CALMA_MCP_WORKSPACE", REPO_ROOT)
    res = _payload(anyio.run(_call, "calma_verify", {"target": BTC_ASSET}))

    assert res["verdict"] in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS", "REFUTED", "INVALIDATED",
                              "INCONCLUSIVE", "MIXED")
    assert res["verdict"] == "REFUTED"                        # the btc asset overstates its return
    assert res["recomputed"] is not None and -0.40 < res["recomputed"] < -0.25   # compounds to ~ -0.32
    assert os.path.isdir(res["run_dir"])                      # the engine run dir really exists
    # the transport never weakened the verdict: gate_exit reflects the catch
    assert res["gate_exit"] == 1


# === ACCEPTANCE: the workspace jail rejects a path that escapes the workspace ===================
def test_workspace_jail_rejects_escaping_target(monkeypatch, tmp_path):
    monkeypatch.setenv("CALMA_MCP_WORKSPACE", str(tmp_path))   # jail = an empty tmp dir
    res = anyio.run(_call, "calma_verify", {"target": BTC_ASSET})   # the asset is OUTSIDE the jail
    assert res.isError                                        # rejected before any subprocess ran
    assert "escapes the workspace" in result_text(res)


def result_text(res):
    return " ".join(getattr(b, "text", "") for b in res.content)


# === ACCEPTANCE: calma_verify_artifact -> an A1 Report with >=1 claim (catches first) ===========
def test_calma_verify_artifact_returns_report(monkeypatch, tmp_path):
    if not os.path.isdir(NB_RUN):
        pytest.skip("A1 CLI seam fixture (nb_run) not present")
    dst = os.path.join(str(tmp_path), "nb_run")
    shutil.copytree(NB_RUN, dst)
    monkeypatch.setenv("CALMA_MCP_WORKSPACE", str(tmp_path))

    res = _payload(anyio.run(_call, "calma_verify_artifact", {"target": dst, "mode": "flag"}))
    assert "claims" in res and len(res["claims"]) >= 1
    assert res["repo_verdict"] in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS", "REFUTED", "INVALIDATED",
                                   "INCONCLUSIVE", "MIXED")
    # the A1 report sorts catches first; nb_run's overstated total return is the catch
    assert res["claims"][0]["metric_id"] == "total_return"
    assert res["claims"][0]["verdict"] == "REFUTED"


# === SECURITY: a caller-controlled claim cannot smuggle an engine flag ==========================
def test_claim_cannot_smuggle_a_flag(monkeypatch):
    import subprocess
    seen = {}

    class _Done:
        returncode = 0
        stdout = '{"verdict":"REFUTED","metrics":[],"gate_exit":1,"run_dir":"/x"}'
        stderr = ""

    def _spy(argv, **kw):
        seen["argv"] = argv
        return _Done()

    monkeypatch.setenv("CALMA_MCP_WORKSPACE", REPO_ROOT)
    monkeypatch.setattr(subprocess, "run", _spy)
    server.verify(BTC_ASSET, claim="--restore")              # try to smuggle the network-using --restore
    argv = seen["argv"]
    # --restore is NOT a standalone token; the claim is bound via `--claim=...`, and the target sits
    # after a `--` end-of-options separator (so a target/claim beginning with '-' can't smuggle a flag).
    assert "--restore" not in argv
    assert any(a == "--claim=--restore" for a in argv)
    assert "--" in argv and argv.index("--") < argv.index(BTC_ASSET)


def test_isolation_and_trust_are_validated(monkeypatch):
    monkeypatch.setenv("CALMA_MCP_WORKSPACE", REPO_ROOT)
    import pytest as _pt
    with _pt.raises(ValueError):
        server.verify(BTC_ASSET, isolation="none-disable-sandbox")
    with _pt.raises(ValueError):
        server.verify(BTC_ASSET, trust="fully-trusted")


# === the calma_suggest surface returns ranked candidates =======================================
def test_calma_suggest_ranks_recipes():
    res = _payload(anyio.run(_call, "calma_suggest",
                             {"query": "my risk-adjusted return looked strong", "top": 3}))
    assert "candidates" in res and len(res["candidates"]) >= 1
    assert all("metric_id" in c for c in res["candidates"])
