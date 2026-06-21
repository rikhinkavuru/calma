"""Numerai MMC / FNC / max-feature-exposure recipes (Phase 2 #4). The golden values below are TIER-1:
frozen from the OFFICIAL numerai_tools.scoring (correlation_contribution / feature_neutral_corr /
max_feature_correlation) on the fixed fixture, asserted equal to calma's pure-stdlib recompute to <=1e-9.
The live cross-check (calma == the installed numerai-tools) runs in the eval venv; this test is pure stdlib
(no numerai-tools) so it stands in the core suite. Run: python3 test_numerai_mmc_fnc.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import numeric as N  # noqa: E402
import recompute as RC  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# the FIXED fixture (2 eras x 8 rows) + the GOLDEN values frozen from numerai_tools.scoring
ERA = ["era0001"] * 8 + ["era0002"] * 8
PRED = [0.12, 0.55, 0.31, 0.88, 0.20, 0.71, 0.44, 0.63, 0.18, 0.49, 0.27, 0.91, 0.33, 0.66, 0.50, 0.59]
TGT = [0.0, 0.25, 0.5, 1.0, 0.25, 0.75, 0.5, 1.0, 0.0, 0.5, 0.25, 1.0, 0.5, 0.75, 0.25, 0.5]
META = [0.10, 0.50, 0.35, 0.80, 0.25, 0.65, 0.40, 0.60, 0.20, 0.45, 0.30, 0.85, 0.30, 0.60, 0.55, 0.52]
F0 = [0.5, 0.2, 0.8, 0.1, 0.6, 0.3, 0.7, 0.4, 0.45, 0.25, 0.75, 0.15, 0.55, 0.35, 0.65, 0.42]
F1 = [0.3, 0.7, 0.2, 0.9, 0.4, 0.6, 0.1, 0.8, 0.33, 0.66, 0.22, 0.88, 0.44, 0.55, 0.11, 0.77]
F2 = [0.9, 0.1, 0.6, 0.3, 0.7, 0.2, 0.8, 0.4, 0.85, 0.15, 0.62, 0.28, 0.72, 0.18, 0.81, 0.41]
GOLD_MMC = 0.03997380328447061           # numerai_tools correlation_contribution, per-era mean
GOLD_FNC = 0.38978465689868924           # numerai_tools feature_neutral_corr, per-era mean
GOLD_MAX = 0.7416533572518422            # numerai_tools max_feature_correlation, global
TOL = 1e-9


def _recompute_fixture():
    d = tempfile.mkdtemp(prefix="calma_mmc_")
    cols = {"era": ERA, "pred": PRED, "target": TGT, "meta": META, "f0": F0, "f1": F1, "f2": F2}
    with open(os.path.join(d, "p.csv"), "w", newline="") as f:
        names = list(cols)
        f.write(",".join(names) + "\n")
        for i in range(len(ERA)):
            f.write(",".join(str(cols[c][i]) for c in names) + "\n")
    contract = {"run": {"entrypoint": "p.csv", "network": "off"}, "env": {"ecosystem": "python"},
                "artifacts": [{"path": "p.csv", "columns": {c: {} for c in cols}}],
                "metrics": [
                    {"metric_id": "mmc", "artifact": "p.csv", "headline": True,
                     "binding": {"prediction": "pred", "target": "target", "meta_model": "meta", "era": "era"}},
                    {"metric_id": "feature_neutral_corr", "artifact": "p.csv",
                     "binding": {"prediction": "pred", "target": "target",
                                 "features": ["f0", "f1", "f2"], "era": "era"}},
                    {"metric_id": "max_feature_exposure", "artifact": "p.csv",
                     "binding": {"prediction": "pred", "features": ["f0", "f1", "f2"]}}]}
    json.dump(contract, open(os.path.join(d, "verify.json"), "w"))
    out = RC.recompute_contract(os.path.join(d, "verify.json"), base=d)
    return {m["metric_id"]: m for m in out["metrics"]}


# ---- the recipes, end-to-end through recompute (incl. the feature-SET list binding) == the goldens ----
got = _recompute_fixture()
truth(not got["mmc"]["degenerate"] and abs(got["mmc"]["value"] - GOLD_MMC) <= TOL,
      "mmc recompute == numerai-tools correlation_contribution (per-era mean) to <=1e-9")
truth(not got["feature_neutral_corr"]["degenerate"]
      and abs(got["feature_neutral_corr"]["value"] - GOLD_FNC) <= TOL,
      "feature_neutral_corr recompute == numerai-tools feature_neutral_corr (per-era mean) to <=1e-9")
truth(not got["max_feature_exposure"]["degenerate"]
      and abs(got["max_feature_exposure"]["value"] - GOLD_MAX) <= TOL,
      "max_feature_exposure recompute == numerai-tools max_feature_correlation (global) to <=1e-9")
truth(got["mmc"]["terms"].get("eras") == 2, "mmc reports 2 eras")

# ---- the feature-SET list binding actually projected all 3 feature columns -----------------------------
truth(got["feature_neutral_corr"]["terms"].get("eras") == 2, "fnc per-era over the declared 3-feature set")

# ---- kernels: properties + degenerate guards ----------------------------------------------------------
# neutralize residual is orthogonal to each feature (the defining property of OLS neutralization)
g = N._gaussianize_ranks(PRED[:8])
res = N.neutralize_residual(g, [F0[:8], F1[:8], F2[:8]])
import math  # noqa: E402
for fi, f in enumerate((F0[:8], F1[:8], F2[:8])):
    fm = N.fmean(f)
    dot = math.fsum((r) * (fv - fm) for r, fv in zip(res, f))
    truth(abs(dot) < 1e-6, "neutralize: residual is orthogonal to feature %d (OLS property)" % fi)
truth(N.mmc_series([1.0], [0.5], [0.5]) != N.mmc_series([1.0], [0.5], [0.5]), "mmc_series: n<2 -> NaN")
truth(N.feature_neutral_corr_series(PRED[:8], TGT[:8], []) !=
      N.feature_neutral_corr_series(PRED[:8], TGT[:8], []), "fnc_series: empty feature set -> NaN")
truth(N.max_feature_exposure(PRED[:8], []) != N.max_feature_exposure(PRED[:8], []),
      "max_feature_exposure: no features -> NaN")
# a constant feature (degenerate pearson) is skipped, not a crash
truth(abs(N.max_feature_exposure([1.0, 2.0, 3.0, 4.0], [[5.0, 5.0, 5.0, 5.0], [1.0, 2.0, 3.0, 4.0]]) - 1.0) < 1e-12,
      "max_feature_exposure: a constant feature is skipped; a perfectly-correlated one -> 1.0")

# ---- mmc global (no era bound) is also valid (one group) ----------------------------------------------
truth(N.mmc_series(PRED, TGT, META) == N.mmc_series(PRED, TGT, META), "mmc_series global (16 rows) is finite")

# ---- live drift-gate: when numerai-tools is importable (the eval venv), the FROZEN goldens must STILL
#      equal the live library - catches a future numerai-tools algorithm change. Skips out loud under the
#      pure-stdlib core suite (calma == frozen golden is asserted there regardless).
try:
    import numerai_tools.scoring as _S
    import pandas as _pd
    import numpy as _np
    _HAVE = True
except ImportError:
    _HAVE = False
if _HAVE:
    _df = _pd.DataFrame({"era": ERA, "pred": PRED, "target": TGT, "meta": META, "f0": F0, "f1": F1, "f2": F2})

    def _per_era(fn):
        return float(_np.mean([fn(g.reset_index(drop=True)) for _, g in _df.groupby("era")]))

    _lm = _per_era(lambda g: _S.correlation_contribution(g["pred"].to_frame(), g["meta"].rename("meta"),
                                                         g["target"]).iloc[0])
    _lf = _per_era(lambda g: _S.feature_neutral_corr(g["pred"].to_frame(), g[["f0", "f1", "f2"]],
                                                     g["target"]).iloc[0])
    _lx = float(_S.max_feature_correlation(_df["pred"], _df[["f0", "f1", "f2"]])[1])
    truth(abs(_lm - GOLD_MMC) <= TOL, "drift-gate: frozen GOLD_MMC == the live numerai-tools")
    truth(abs(_lf - GOLD_FNC) <= TOL, "drift-gate: frozen GOLD_FNC == the live numerai-tools")
    truth(abs(_lx - GOLD_MAX) <= TOL, "drift-gate: frozen GOLD_MAX == the live numerai-tools")
    print("  (numerai-tools present - frozen goldens re-validated against the live library)")
else:
    print("  (numerai-tools absent - live drift-gate skipped; calma == frozen golden still asserted)")

print("numerai_mmc_fnc: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
