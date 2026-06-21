"""M2 (the calibration moat, made legible): the per-recipe VALIDATION-COVERAGE surface.

For every one of calma's recipes, classify how its correctness is independently established - and turn
"how many recipes are actually verified?" from a vague claim into a published, monotonically-improving
metric. Tiers (strongest first):

  live-framework : asserted == the LIVE framework number in CI (gen_framework_vectors --check-live:
                   sklearn / numpy) AND == an independent pure-python reference. The gold standard.
  numerai-tools  : validated == the official numerai_tools.scoring to <=1e-9 (the tournament recipes).
  ref-vector     : a frozen reference vector whose expected value was generated against an INDEPENDENT
                   published implementation (numpy / scipy / sklearn) - assets/reference_vectors.json.
  uncovered      : no independent reference vector (may still have a metamorphic / property test, or be
                   a compiled-validated DSL recipe admitted by frozen-program-hash).

This is honest about Tier-1 (independently verified) vs the rest - never a self-generated "golden" passed
off as a correctness proof (the SciPy xsref trap). Run:
  python3 benchmark/coverage_report.py            # the human report + writes results/coverage.json
  python3 benchmark/coverage_report.py --check     # CI gate: FAIL if `uncovered` grew vs the frozen baseline
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(HERE, "..", ".claude", "skills", "calma", "scripts")
sys.path.insert(0, SKILL)
import recipes as R  # noqa: E402

# recipes validated == the LIVE framework (gen_framework_vectors.py VECTORS' metric_ids) and == the
# official numerai_tools.scoring (test_numerai_mmc_fnc + test_numerai_recipes). Kept in sync with those.
_LIVE_FRAMEWORK = {"accuracy", "f1", "mcc", "auc", "r2", "rmse", "mae", "log_loss", "brier", "total_return"}
_NUMERAI_TOOLS = {"numerai_corr", "numerai_sharpe", "mmc", "feature_neutral_corr", "max_feature_exposure"}
# the frozen no-regression baseline (the count of `uncovered` recipes that is allowed). Lower it when you
# add coverage; --check FAILS if `uncovered` ever EXCEEDS it (coverage may only improve).
_BASELINE_UNCOVERED = 31


def _ref_vector_kinds():
    """Recipe ids that have a frozen reference vector (expected value generated vs numpy/scipy/sklearn)."""
    path = os.path.join(SKILL, "..", "assets", "reference_vectors.json")
    try:
        cases = json.load(open(path)).get("cases", [])
    except (OSError, ValueError):
        return set()
    return {c.get("kind") for c in cases if c.get("kind")}


def classify():
    ids = set(R.ids())
    ref = _ref_vector_kinds()
    out = {"live-framework": [], "numerai-tools": [], "ref-vector": [], "uncovered": []}
    for rid in sorted(ids):
        if rid in _LIVE_FRAMEWORK:
            out["live-framework"].append(rid)
        elif rid in _NUMERAI_TOOLS:
            out["numerai-tools"].append(rid)
        elif rid in ref:
            out["ref-vector"].append(rid)
        else:
            out["uncovered"].append(rid)
    return out, len(ids)


def run(check=False):
    tiers, total = classify()
    verified = total - len(tiers["uncovered"])
    rows = [
        ("live-framework (== the live sklearn/numpy in CI + an independent ref)", len(tiers["live-framework"])),
        ("numerai-tools  (== the official numerai_tools.scoring to <=1e-9)", len(tiers["numerai-tools"])),
        ("ref-vector     (frozen vector vs an independent numpy/scipy/sklearn impl)", len(tiers["ref-vector"])),
        ("uncovered      (no independent reference vector)", len(tiers["uncovered"])),
    ]
    print("=== calma recipe validation coverage (%d recipes) ===" % total)
    for label, n in rows:
        print("  %-72s %4d  %5.1f%%" % (label, n, 100.0 * n / total))
    print("  %-72s %4d  %5.1f%%" % ("-> INDEPENDENTLY VERIFIED (Tier-1, the top three)", verified,
                                    100.0 * verified / total))
    if tiers["uncovered"]:
        u = tiers["uncovered"]
        print("\n  uncovered (%d) - candidates for a reference vector / metamorphic relation:\n    %s%s"
              % (len(u), ", ".join(u[:24]), " ..." if len(u) > 24 else ""))
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    json.dump({"total": total, "verified": verified, "tiers": {k: len(v) for k, v in tiers.items()},
               "uncovered_ids": tiers["uncovered"]},
              open(os.path.join(HERE, "results", "coverage.json"), "w"), indent=2)
    if check:
        n_unc = len(tiers["uncovered"])
        if n_unc > _BASELINE_UNCOVERED:
            print("\nFAIL: uncovered recipes grew to %d (baseline %d) - add a reference vector for the new "
                  "recipe(s), or lower the baseline only when you cannot." % (n_unc, _BASELINE_UNCOVERED))
            return 1
        if n_unc < _BASELINE_UNCOVERED:
            print("\nnote: coverage IMPROVED (uncovered %d < baseline %d) - lower _BASELINE_UNCOVERED to %d "
                  "to ratchet it in." % (n_unc, _BASELINE_UNCOVERED, n_unc))
        print("\nOK: coverage did not regress (uncovered %d <= baseline %d)." % (n_unc, _BASELINE_UNCOVERED))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="CI gate: fail if uncovered recipes grew vs baseline")
    return run(check=ap.parse_args().check)


if __name__ == "__main__":
    sys.exit(main())
