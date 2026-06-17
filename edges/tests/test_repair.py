"""P4.1 acceptance tests -- the catch -> diagnose -> minimal-patch -> re-verify orchestrator.

Develops against the bundled REFUTED btc fixture. The LLM diagnosis is REPLAYED from recorded fixtures
(conftest forces replay), so the suite is green with NO ANTHROPIC_API_KEY.

DEVIATION FROM THE DEEP PROMPT (matched to reality, as the gate instructs):
The deep prompt's primary test expects the LLM-driven repair to return accepted=True. With Opus as the
proposer the principled outcome is the OPPOSITE and it is the RIGHT one: the btc claim (146.977) is the
in-sample, best-of-N, zero-cost grid-search winner, and the recompute reads the OOS-with-cost series, so
NO honest code-only patch can make an in-sample best-of-N equal an out-of-sample result. Opus follows the
system prompt's RULE 5 ("an in-sample best-of-N number can never be an out-of-sample result -> emit an
EMPTY diff") and honestly declines on all four hypotheses -> accepted=False. This is the deep prompt's
explicitly-sanctioned fallback ("if no code-only patch is viable, the load-bearing assertion is: a gamed
fix is rejected and a no-op is rejected"). The ACCEPT path (the deep prompt's intent -- a genuine minimal
code fix flips the verdict) is proven separately by INJECTING a known-good patch and re-verifying it
through the real engine, so the end-to-end accept machinery is covered without the proposer fabricating a
dishonest fix.
"""
import difflib
import json
import os

import pytest

from edges.common import engine
from edges.repair import orchestrate as ORC
from edges.repair.types import Diagnosis

BTC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                   ".claude", "skills", "calma", "assets", "btc"))
CALMA = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                     ".claude", "skills", "calma", "scripts", "calma.py"))
CLAIM = 146.97697947938846


@pytest.fixture
def btc_run_dir():
    """A fresh REFUTED btc run_dir (system python3 runs the engine; .calma is gitignored)."""
    res = engine.verify(BTC)
    assert res["verdict"] == "REFUTED"
    return res["run_dir"]


def _good_patch(scratch):
    """A robust unified diff (correct line numbers via difflib) that emits the in-sample series the
    claim is actually about -- the genuine code-only fix the engine confirms (gap ~6e-13 <= budget)."""
    p = os.path.join(scratch, "gen_fixture.py")
    src = open(p).read().splitlines(keepends=True)
    patched = ["    _, oos_rets = backtest(IS, bf, bs, bl, fee=0.0)\n"
               if ln.strip() == "_, oos_rets = backtest(OOS, bf, bs, bl, fee=fee)" else ln
               for ln in src]
    assert patched != src
    return "".join(difflib.unified_diff(src, patched, fromfile="a/gen_fixture.py",
                                        tofile="b/gen_fixture.py"))


# === ACCEPTANCE (reality): the honest proposer finds NO code-only fix for an in-sample-vs-OOS lie ===
def test_llm_repair_btc_honestly_finds_no_code_only_fix(btc_run_dir, tmp_path):
    ep = os.path.join(str(tmp_path), "episodes.jsonl")        # empty -> no prior (matches recording)
    result = ORC.repair(btc_run_dir, budget=4, episodes_path=ep)

    assert result.before_verdict == "REFUTED"
    assert result.accepted is False                           # Opus honestly emits empty diffs (RULE 5)
    assert result.patch is None
    assert len(result.trajectory) == 4                        # all four hypotheses tried
    for h in result.trajectory:
        assert h.accepted is False
        assert h.after_verdict is None                        # empty diff never re-verified


# === ACCEPTANCE: a genuine minimal code patch IS accepted, gap closed, patch touches only the code ===
def test_injected_minimal_patch_is_accepted(btc_run_dir, tmp_path, monkeypatch):
    def fake_diagnose(scratch, claim, finding, diff, goalposts, **kw):
        return Diagnosis(cause="emits the OOS-with-cost series while the claim is the in-sample backtest",
                         locator=(finding or {}).get("locator", ""),
                         dimension=(finding or {}).get("dimension", "metric-mismatch"),
                         unified_diff=_good_patch(scratch), target_files=("gen_fixture.py",),
                         rationale="emit the in-sample series the claim is about")
    monkeypatch.setattr(ORC, "diagnose", fake_diagnose)

    ep = os.path.join(str(tmp_path), "episodes.jsonl")
    result = ORC.repair(btc_run_dir, budget=2, episodes_path=ep)

    assert result.accepted is True
    assert result.before_verdict == "REFUTED"
    assert result.after_verdict in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS")
    assert result.one_shot is True                            # accepted on the first hypothesis
    # the accepted patch touches ONLY the producing code, and it is minimal
    assert result.patch and "verify.yaml" not in result.patch
    assert "gen_fixture.py" in result.patch
    changed = sum(1 for ln in result.patch.splitlines()
                  if ln[:1] in "+-" and not ln.startswith(("+++", "---")))
    assert changed < 40

    # the gap genuinely closed: before > budget, after <= budget (read from diff.json by the engine)
    acc = result.trajectory[result.trajectory.index(
        next(h for h in result.trajectory if h.accepted))]
    assert acc.before_gap > acc.effective_budget
    assert acc.after_gap <= acc.effective_budget

    # the accepted repair was recorded as an episode (P4.4 wiring)
    eps = [json.loads(ln) for ln in open(ep)]
    assert len(eps) == 1 and eps[0]["one_shot"] is True and eps[0]["metric_id"] == "total_return"


# === ACCEPTANCE: a no-op patch (empty diff) is rejected ========================================
def test_injected_noop_patch_is_rejected(btc_run_dir, tmp_path, monkeypatch):
    def noop(scratch, claim, finding, diff, goalposts, **kw):
        return Diagnosis(cause="no honest code-only fix exists", locator="", dimension="metric-mismatch",
                         unified_diff="", target_files=(), rationale="empty")
    monkeypatch.setattr(ORC, "diagnose", noop)
    monkeypatch.setattr(ORC, "next_hypothesis", noop)

    ep = os.path.join(str(tmp_path), "episodes.jsonl")
    result = ORC.repair(btc_run_dir, budget=3, episodes_path=ep)

    assert result.accepted is False
    assert result.patch is None
    assert all(h.after_verdict is None for h in result.trajectory)   # nothing applied -> nothing flipped
    assert not os.path.exists(ep)                                    # no accepted episode recorded
