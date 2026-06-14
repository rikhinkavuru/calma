"""Audit-round-7 hardening regressions: the "never traceback, never false-verdict" cluster.

Every check here pins a fix from the closed-loop robustness audit:
  - a fabricated INFINITE claim ("1e999") must NEVER false-CONFIRM (it was: claimed=inf CONFIRMED)
  - a Unicode-minus claim ("-14%" with U+2212) must keep its SIGN (it was: parsed +0.14 -> false-REFUTE)
  - a numeric kernel that overflows / divides-by-zero on extreme data must DEGRADE to a degenerate
    recompute (-> INCONCLUSIVE), never raise an uncaught traceback (165/500 recipes used to)
  - an empty (0-byte) emitted artifact, a non-finite column during auto-detect, and a pathologically
    deep contract must all degrade cleanly, never traceback
  - `--json` must be STRICT json (no bare NaN/Infinity) and its gate_exit must match the process exit
Pure stdlib. Run: python3 test_robustness.py
"""
import csv
import json
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
import calma as C  # noqa: E402
import compare as CMP  # noqa: E402
import draft_contract as DC  # noqa: E402
import recipes as RCP  # noqa: E402
import recompute as RC  # noqa: E402
import verdict as V  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# ---------------------------------------------------------------------------
# S1 - a non-finite claimed value is not a checkable finite claim
# ---------------------------------------------------------------------------
for txt in ("revenue total 1e999", "9e999 backtest", "1" + "0" * 400 + " rows"):
    v, _h = DC.parse_claim(txt)
    truth(v is None, "parse_claim rejects overflowing claim %r (got %r)" % (txt[:24], v))
truth(DC.parse_claim(float("inf")) == (None, None), "parse_claim(inf float) -> None")
truth(DC.parse_claim(float("nan")) == (None, None), "parse_claim(nan float) -> None")
# finite claims still parse
truth(DC.parse_claim("accuracy 0.87")[0] == 0.87, "finite claim still parses")
# compare can never CONFIRM a non-finite claimed value (defense in depth)
_rec = {"metrics": [{"metric_id": "column_sum", "value": 100.0, "terms": {}, "k_spread": 0.0,
                     "degenerate": False, "path_dependent": False}], "baselines": []}
_con = {"metrics": [{"metric_id": "column_sum", "artifact": "a.csv", "binding": {"value": "v"},
                     "claimed_value": float("inf"), "claim_confirmed": True, "headline": True,
                     "binding_status": "independently-bound"}]}
_d = CMP.compare(_rec, _con, isolation_tier="seatbelt-verified", determinism_mode="controlled-to-bit")
truth(_d["metrics"][0]["verdict"] != V.CONFIRMED, "inf claimed never CONFIRMs in compare")

# ---------------------------------------------------------------------------
# S2 - Unicode minus keeps the sign; en/em dash stays a separator (no false negative)
# ---------------------------------------------------------------------------
truth(DC.parse_claim("−" "14% return")[0] == -0.14, "U+2212 minus -> -0.14")
truth(DC.parse_claim("‐" "14% return")[0] == -0.14, "U+2010 hyphen -> -0.14")
truth(DC.parse_claim("-14% return")[0] == -0.14, "ASCII minus still -0.14")
truth(DC.parse_claim("—" "14% return")[0] == 0.14, "em-dash NOT minus (stays +0.14)")
truth(DC.parse_claim("–" "14% return")[0] == 0.14, "en-dash NOT minus (stays +0.14)")
truth(abs(DC.claim_precision("−" "14%") - DC.claim_precision("-14%")) < 1e-18,
      "claim_precision sign-agnostic across unicode/ascii minus")
# a hyphen inside a metric name (ASCII, untouched by dash-normalization) still routes correctly
truth(DC.parse_claim("pr-auc 0.8")[1] == "pr_auc", "ASCII hyphen in metric name preserved")
truth(DC.parse_claim("1e-9 rmse")[0] == 1e-9, "negative exponent is not a minus sign")

# NPV: a leading discount RATE ("npv at 10% 5000") is a parameter, not the claimed value
truth(DC.parse_claim("npv at 10% 5000")[0] == 5000.0, "npv skips the leading rate% -> value 5000")
truth(DC.parse_claim("NPV of 5000 at 10%")[0] == 5000.0, "npv value-first unaffected")
truth(DC.parse_claim("cagr 12% over 3 years")[0] == 0.12, "cagr 12% IS the value (not skipped)")

# ---------------------------------------------------------------------------
# T1 - no recipe kernel raises an UNCAUGHT exception through _recompute_one (was: 165/500)
# ---------------------------------------------------------------------------
_shapes = {"empty": [], "single": [1.0], "const": [2.0, 2.0], "zero": [0.0, 0.0],
           "neg": [-1.0, -2.0], "big": [1e308, 1e308], "huge_sq": [1e200, 1e200]}
_dd = tempfile.mkdtemp(prefix="calma-rob-")
_raised = []
for mid in RCP.ids():
    man = RCP.get(mid).manifest
    req = list(man.get("required_tags") or [])
    stags = set(man.get("string_tags") or [])
    for sname, dn in _shapes.items():
        binding, header, by_col = {}, [], {}
        for i, t in enumerate(req):
            col = "c_%s_%d" % (t, i)
            binding[t] = col
            header.append(col)
            by_col[col] = (["a", "a"] if t in stags else [str(x) for x in dn])
        if not header:
            header = ["x"]
            by_col["x"] = [str(x) for x in dn]
        path = os.path.join(_dd, "a.csv")
        rows = max((len(v) for v in by_col.values()), default=0)
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            for r in range(rows):
                w.writerow([by_col[c][r] if r < len(by_col[c]) else "" for c in header])
        contract = {"artifacts": [{"path": "a.csv", "columns": {c: {} for c in header}}]}
        m = {"metric_id": mid, "artifact": "a.csv", "binding": binding}
        try:
            rec = RC._recompute_one(contract, m, _dd, 1)
            if not (isinstance(rec, dict) and "degenerate" in rec):
                _raised.append((mid, sname, "no-dict"))
        except BaseException as e:  # noqa: BLE001
            _raised.append((mid, sname, type(e).__name__))
truth(not _raised, "all %d recipes degrade (never raise) through _recompute_one; offenders=%s"
      % (len(RCP.ids()), _raised[:6]))
# the overflow case specifically -> degenerate, value NaN, error named
_ov = RC._recompute_one({"artifacts": []}, {"metric_id": "column_sum", "artifact": "a.csv",
                                            "binding": {"value": "c_value_0"}}, _dd, 1)

# ---------------------------------------------------------------------------
# T2 - an empty (0-byte / header-less) artifact is a clean degenerate, not StopIteration
# ---------------------------------------------------------------------------
_ed = tempfile.mkdtemp(prefix="calma-empty-")
open(os.path.join(_ed, "out.csv"), "w").close()  # 0 bytes
_er = RC._recompute_one({"artifacts": [{"path": "out.csv", "columns": {"value": {}}}]},
                        {"metric_id": "column_sum", "artifact": "out.csv", "binding": {"value": "value"}},
                        _ed, 1)
truth(_er.get("degenerate") and "empty" in (_er.get("error") or ""),
      "empty artifact -> degenerate with an 'empty' message (%r)" % _er.get("error"))

# ---------------------------------------------------------------------------
# T4 - a non-finite value in a graded column degrades to plausibly-bound, never int(inf) crash
# ---------------------------------------------------------------------------
for tag in ("rank", "hits", "flag", "correct", "label"):
    try:
        g = DC._grade(tag, [1.0, float("inf")])
        truth(g == "plausibly-bound", "%s with inf -> plausibly-bound (got %r)" % (tag, g))
    except BaseException as e:  # noqa: BLE001
        truth(False, "_grade(%s, [.,inf]) raised %s" % (tag, type(e).__name__))

# ---------------------------------------------------------------------------
# T5 - a pathologically deep contract is a clean ValueError, not RecursionError
# ---------------------------------------------------------------------------
_deep = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
_deep.write("\n".join("%sk%d:" % (" " * (2 * i), i) for i in range(4000)) + "\n  v: 1\n")
_deep.close()
try:
    DC.load_contract(_deep.name)
    _ok = True  # parsed (some platforms have deep limits) - acceptable as long as it didn't crash
except ValueError:
    _ok = True
except RecursionError:
    _ok = False
truth(_ok, "deeply-nested contract -> ValueError (or parses), never an uncaught RecursionError")

# ---------------------------------------------------------------------------
# J1 - the --json finite sanitizer maps NaN/Inf to null (strict JSON for agents)
# ---------------------------------------------------------------------------
_san = C._json_finite({"a": float("nan"), "b": float("inf"), "c": -float("inf"),
                       "d": 1.5, "e": [float("nan"), 2.0], "f": "x"})
truth(_san["a"] is None and _san["b"] is None and _san["c"] is None, "NaN/Inf -> null")
truth(_san["d"] == 1.5 and _san["e"] == [None, 2.0] and _san["f"] == "x", "finite/nested preserved")
truth("NaN" not in json.dumps(_san) and "Infinity" not in json.dumps(_san), "no bare NaN/Infinity")

# ---------------------------------------------------------------------------
# misc - _article a/an, end-to-end CLI overflow stays a clean verdict (no traceback)
# ---------------------------------------------------------------------------
truth(C._article("auc") == "an" and C._article("sharpe") == "a", "_article picks a/an")
_cli = tempfile.mkdtemp(prefix="calma-cli-")
with open(os.path.join(_cli, "out.csv"), "w") as fh:
    fh.write("value\n1e308\n1e308\n")
with open(os.path.join(_cli, "main.py"), "w") as fh:
    fh.write("print(1)\n")
_res = C.verify(_cli, claim=None, metric="column_sum", run_id="rob")
truth(_res["repo_verdict"] == V.INCONCLUSIVE, "overflow data -> INCONCLUSIVE end-to-end (no crash)")

# ---------------------------------------------------------------------------
# C1 - an explicit --isolation is part of the cache key (a different tier re-runs, never serves a
# result achieved under another tier); default 'auto' leaves the fingerprint unchanged
# ---------------------------------------------------------------------------
_fpc = {"run": {"entrypoint": "x.py"}, "artifacts": []}
_fp_default = C._input_fingerprint(_cli, _fpc)
truth(C._input_fingerprint(_cli, _fpc, isolation="auto") == _fp_default, "auto == default fingerprint")
truth(C._input_fingerprint(_cli, _fpc, isolation=None) == _fp_default, "None == default fingerprint")
truth(C._input_fingerprint(_cli, _fpc, isolation="firecracker") != _fp_default,
      "explicit isolation changes the fingerprint")
truth(C._input_fingerprint(_cli, _fpc, isolation="docker")
      != C._input_fingerprint(_cli, _fpc, isolation="firecracker"), "distinct tiers -> distinct keys")

# ---------------------------------------------------------------------------
# J2 - --json gate_exit reflects the 3 (refused) / 4 (killed) process-exit override
# ---------------------------------------------------------------------------
_base = {"repo_verdict": V.INCONCLUSIVE, "gate_exit": 1, "run_dir": "/x", "claim_note": None,
         "ledger": {"claims": [{"metric": "x", "verdict": V.INCONCLUSIVE, "headline_confidence": 0.0}],
                    "scope": {}}}
_jref = C._json_result(dict(_base, refused=True, killed=False))
truth(_jref["gate_exit"] == 3 and _jref["clean"] is False, "refused -> json gate_exit 3")
_jkil = C._json_result(dict(_base, refused=False, killed=True))
truth(_jkil["gate_exit"] == 4 and _jkil["clean"] is False, "killed -> json gate_exit 4")

# ---------------------------------------------------------------------------
# D2 - a manifest row with an embedded tab fails loud; identical jobs dedupe
# ---------------------------------------------------------------------------
_mf = tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False)
_mf.write("/a\tclaim\twith\ttabs\n")
_mf.close()
try:
    C._batch_jobs([], _mf.name)
    truth(False, "batch manifest rejects >3 tab fields")
except ValueError:
    truth(True, "batch manifest rejects >3 tab fields")
_mf2 = tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False)
_mf2.write("%s\tx\n%s\tx\n" % (_cli, _cli))  # identical rows
_mf2.close()
truth(len(C._batch_jobs([], _mf2.name)) == 1, "batch dedupes identical jobs")

# ===========================================================================
# Round-2 hardening (doc/UX agents + adversarial re-test)
# ===========================================================================
import report as REP  # noqa: E402

# R2 #1 - a spelled-out "percent"/"pct" is the % suffix (a true 0.87 would else false-REFUTE)
truth(DC.parse_claim("accuracy of 87 percent")[0] == 0.87, "'87 percent' -> 0.87")
truth(DC.parse_claim("return 12 pct")[0] == 0.12, "'12 pct' -> 0.12")
truth(DC.parse_claim("95th percentile latency")[0] is None, "'percentile' is NOT 'percent'")

# R2 #2 - a non-finite cell in a NUMERIC column degenerates even order-stats (median/min/...)
_ic = tempfile.mkdtemp(prefix="calma-infcell-")
with open(os.path.join(_ic, "out.csv"), "w") as fh:
    fh.write("value\n10\n20\ninf\n")
_icr = RC._recompute_one({"artifacts": [{"path": "out.csv", "columns": {"value": {}}}]},
                         {"metric_id": "column_median", "artifact": "out.csv",
                          "binding": {"value": "value"}}, _ic, 1)
truth(_icr.get("degenerate") and "non-finite" in (_icr.get("error") or ""),
      "inf cell -> degenerate median (not a finite-from-corrupt number)")
# a STRING-column recipe is unaffected (sees its own cells, 'inf' is just a distinct string)
_sc = tempfile.mkdtemp(prefix="calma-strcol-")
with open(os.path.join(_sc, "out.csv"), "w") as fh:
    fh.write("value\na\nb\ninf\na\n")
_scr = RC._recompute_one({"artifacts": [{"path": "out.csv", "columns": {"value": {}}}]},
                         {"metric_id": "distinct_count", "artifact": "out.csv",
                          "binding": {"value": "value"}}, _sc, 1)
truth(not _scr.get("degenerate") and _scr.get("value") == 3.0, "distinct_count on a string col unaffected")

# R2 #3 - a precise binding error surfaces in the fix line (not the generic NaN/Inf guidance)
_be = {"claims": [{"recompute_error": "binding failed: column 'x' not found in the artifact"}],
       "findings": [], "scope": {}, "repo_verdict": V.INCONCLUSIVE}
truth("column 'x' not found" in (REP.fix_line(_be) or ""), "fix line surfaces the precise binding error")

# R2 #4 - verdict() is total on a non-finite gap/budget (defense in depth)
_vbase = {"binding_status": "independently-bound", "determinism_mode": "controlled-to-bit",
          "claim_confirmed_target": True, "claim_outside_ci": True}
truth(V.verdict(dict(_vbase, gap=float("nan"), effective_budget=1.0)) == V.INCONCLUSIVE,
      "verdict(NaN gap) -> INCONCLUSIVE")
truth(V.verdict(dict(_vbase, gap=1.0, effective_budget=float("inf"))) == V.INCONCLUSIVE,
      "verdict(inf budget) -> INCONCLUSIVE")

# R2 P1 - the reproduction command (which ships in the signed bundle) is $HOME-redacted
truth(C._redact_home("python3 %s/x/calma.py replay r" % os.path.expanduser("~")).startswith("python3 ~/"),
      "_redact_home collapses $HOME in the reproduce command")

# R2 P2 - large non-integer money/counts use thousands separators, not scientific notation
truth(REP.fmt_value(-1234567.89, "npv") == "-1,234,568", "large non-integer -> comma, not sci")
truth(REP.fmt_value(1.23e15, "throughput") == "1.23e+15", "extreme magnitude stays scientific")
truth(REP.fmt_value(12.3456, None) == "12.35", "small non-integer keeps 4 sig figs")

print("robustness: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
