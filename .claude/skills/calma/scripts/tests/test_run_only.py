"""C3: `calma verify --run-only` - the no-verdict / no-gate debug path the calma_debug MCP tool wraps.
It re-runs + recomputes + diffs and emits the binding + recomputed value + gap, but NEVER assembles a
verdict or gates (always usable mid-task to iterate). COR-1 strict invariant: even on a host that can't
verify a sandbox it STILL returns a no-verdict run_only view (empty metrics + a note) - only the
recompute-DETAIL asserts are skipped, never the no-verdict invariant. Pure stdlib, offline (the bundled
btc fixture). Run: python3 test_run_only.py
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, SCR)
import calma as C  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


BTC = os.path.realpath(os.path.join(SCR, "..", "assets", "btc"))
tmp = tempfile.mkdtemp()
tgt = os.path.join(tmp, "btc")
shutil.copytree(BTC, tgt, ignore=shutil.ignore_patterns(".calma"))

res = C.verify(tgt, "+14,698%", "total_return", run_id="ro", opts=C.VerifyOptions(run_only=True))

# COR-1 strict invariant: --run-only ALWAYS returns a no-verdict debug view, on EVERY host (isolating or
# not). The verdict/gate path is NEVER reached - asserted UNCONDITIONALLY, never tolerated away (the old
# test let a non-isolating host return an INCONCLUSIVE *verdict*; the engine no longer does that).
truth(res.get("run_only") is True,
      "run-only: ALWAYS a run_only view (never falls through to the verdict path)")
truth("repo_verdict" not in res and "gate_exit" not in res,
      "run-only: NO verdict and NO gate in the result, unconditionally (pure recompute view)")
truth(bool(res.get("isolation_tier")) and bool(res.get("run_dir")),
      "run-only: carries the isolation tier + run_dir (proof / raw outputs live there)")
truth(not os.path.exists(os.path.join(res["run_dir"], "ledger.json")),
      "run-only: NO ledger.json - the verdict path was short-circuited")

mets = res.get("metrics") or []
if mets:
    # the sandbox executed -> the recompute is real and the headline metric is reported
    truth(len(mets) == 1 and mets[0]["metric"] == "total_return",
          "run-only: the headline metric is reported")
    m = mets[0]
    truth(m.get("binding") == {"return": "strat_return"}, "run-only: the binding is surfaced")
    truth(isinstance(m.get("recomputed"), float) and m["recomputed"] < 0,
          "run-only: the metric is RECOMPUTED from the raw outputs (btc strategy recomputes negative)")
    truth(isinstance(m.get("gap"), float) and m["gap"] > 100,
          "run-only: the gap vs the claimed +14,698% is reported and large")
    truth(os.path.exists(os.path.join(res["run_dir"], "diff.json")),
          "run-only: diff.json written (the recompute is real)")
else:
    # a host that could NOT verify a sandbox still returns a run_only view (asserted above) with empty
    # metrics + a note - and STILL no verdict. Only the recompute-DETAIL asserts are skipped here; the
    # no-verdict invariant above is asserted regardless of host.
    truth(bool(res.get("note")),
          "run-only: a non-isolating host explains why there's nothing to recompute (still no verdict)")
    print("  (run-only: host could not verify a sandbox; recompute-detail asserts skipped)")

shutil.rmtree(tmp, ignore_errors=True)
print("run_only: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
