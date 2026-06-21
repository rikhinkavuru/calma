"""ICP capabilities for Numerai/CrunchDAO (the tournament quant ICP):
  - inv_norm_cdf matches scipy.stats.norm.ppf to ~1e-9 (the gaussianize step's quantile),
  - numerai_corr_series is the rank->norm.ppf->^1.5 / center->^1.5 / Pearson transform (NOT plain Pearson),
  - the numerai_corr / numerai_sharpe recipes group PER ERA then aggregate (the metrics a DS stakes on),
  - `calma init numerai|crunchdao` produce valid, headline-pinned, precision-tight contracts,
  - an EXPLICIT claimed_precision CAPS the verdict budget (holds a claim to its digits instead of widening
    to the metric's sampling-SE band) - so a tournament overclaim REFUTES instead of being confirmed.
Pure stdlib, offline. Run: python3 test_numerai_recipes.py
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
import compare as CMP  # noqa: E402
import draft_contract as DC  # noqa: E402
import frameworks as FW  # noqa: E402
import numeric as N  # noqa: E402
import recipes as R  # noqa: E402
import verdict as V  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# --- inv_norm_cdf == scipy.stats.norm.ppf (reference values) ---
for p, ref in [(0.5, 0.0), (0.975, 1.959963984540054), (0.025, -1.959963984540054),
               (0.99, 2.3263478740408408), (0.9, 1.2815515594657203), (0.1, -1.2815515594657203),
               (0.001, -3.090232306167813)]:
    truth(abs(N.inv_norm_cdf(p) - ref) < 1e-7, "inv_norm_cdf(%.3f) ~ scipy norm.ppf %.10f (Acklam ~1e-9)" % (p, ref))
truth(N.inv_norm_cdf(0.0) != N.inv_norm_cdf(0.0) and N.inv_norm_cdf(2.0) != N.inv_norm_cdf(2.0),
      "inv_norm_cdf returns NaN outside the open (0,1) interval")


# --- numerai_corr_series: an INDEPENDENT reference of the rank->ppf->^1.5 transform ---
def _ref_nc(pred, tgt):
    n = len(pred)
    order = sorted(range(n), key=lambda i: pred[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n and pred[order[j]] == pred[order[i]]:
            j += 1
        for k in range(i, j):
            ranks[order[k]] = (i + 1 + j) / 2.0
        i = j
    gp = []
    for r in ranks:
        z = N.inv_norm_cdf(min(max((r - 0.5) / n, 1e-6), 1 - 1e-6))
        gp.append((1 if z >= 0 else -1) * abs(z) ** 1.5)
    mt = sum(tgt) / len(tgt)
    pt = [(1 if (t - mt) >= 0 else -1) * abs(t - mt) ** 1.5 for t in tgt]
    mg, mp = sum(gp) / n, sum(pt) / n
    cov = sum((gp[i] - mg) * (pt[i] - mp) for i in range(n))
    sg = math.sqrt(sum((x - mg) ** 2 for x in gp))
    sp = math.sqrt(sum((x - mp) ** 2 for x in pt))
    return cov / (sg * sp)


pred = [0.1, 0.5, 0.3, 0.9, 0.2, 0.7, 0.4, 0.6]
tgt = [0.0, 0.5, 0.25, 1.0, 0.25, 0.75, 0.5, 0.5]
truth(abs(N.numerai_corr_series(pred, tgt) - _ref_nc(pred, tgt)) < 1e-12,
      "numerai_corr_series matches the independent rank-gaussianize-^1.5 reference")
truth(abs(N.numerai_corr_series(pred, tgt) - N.pearson_r(pred, tgt)) > 1e-6,
      "numerai_corr_series is NOT plain Pearson (the whole point of the gap calma had)")


# --- the recipes group PER ERA then aggregate ---
cols = {"p": [0.1, 0.5, 0.3, 0.9, 0.2, 0.7, 0.4, 0.6],
        "t": [0.0, 0.5, 0.25, 1.0, 0.25, 0.75, 0.5, 0.5],
        "e": ["0001"] * 4 + ["0002"] * 4}
binding = {"prediction": "p", "target": "t", "era": "e"}
c1, c2 = _ref_nc(cols["p"][:4], cols["t"][:4]), _ref_nc(cols["p"][4:], cols["t"][4:])
rc = R.get("numerai_corr")(cols, binding)
truth(abs(rc["value"] - (c1 + c2) / 2) < 1e-12, "numerai_corr recipe = mean of the per-era corr")
truth(rc["terms"].get("eras") == 2, "numerai_corr reports the era count")
rs = R.get("numerai_sharpe")(cols, binding)
mean = (c1 + c2) / 2
sd = math.sqrt(((c1 - mean) ** 2 + (c2 - mean) ** 2) / 2)  # population std, ddof=0
truth(sd > 0 and abs(rs["value"] - mean / sd) < 1e-9, "numerai_sharpe = mean/std(ddof=0) of per-era corr")


# --- the on-ramps: calma init numerai / crunchdao ---
for plat, mid in (("numerai", "numerai_corr"), ("crunchdao", "auc")):
    c = FW.starter_contract(plat)
    c.pop("_note", None)
    truth(not DC.validate_contract(c), "%s starter contract validates" % plat)
    head = [m for m in c["metrics"] if m.get("headline")]
    truth(bool(head) and head[0]["metric_id"] == mid, "%s headline metric is %s" % (plat, mid))
    truth(all(m.get("claimed_precision") for m in c["metrics"]),
          "%s starter pins a tight claimed_precision (tournament-grade tolerance)" % plat)
truth(FW.starter_contract("numer.ai") is not None and FW.starter_contract("adia") is not None,
      "platform aliases resolve (numer.ai -> numerai, adia -> crunchdao)")


# --- claimed_precision CAPS the verdict budget (the effectiveness fix) ---
def cmp1(rec_val, claimed, precision=None, se=None):
    terms = {"sampling_se": se} if se is not None else {}
    rec = {"metrics": [{"metric_id": "auc", "value": rec_val, "terms": terms, "k_spread": 0.0,
                        "degenerate": False, "near_zero_vol": False, "path_dependent": False}],
           "baselines": []}
    m = {"metric_id": "auc", "artifact": "x", "binding": {}, "convention": None,
         "claimed_value": claimed, "headline": True, "binding_status": "independently-bound",
         "claim_confirmed": True}
    if precision is not None:
        m["claimed_precision"] = precision
    return CMP.compare(rec, {"metrics": [m], "baselines": []}, isolation_tier="tier0",
                       determinism_mode="controlled-to-bit")["metrics"][0]["verdict"]


# no explicit precision: the sampling-SE band (Z*0.03 ~ 0.059) covers the 0.0545 gap -> NOT refuted (the
# statistical-robustness reading, the historical default - unchanged)
truth(cmp1(0.6855, 0.74, se=0.03) != V.REFUTED,
      "default (no explicit precision): the sampling-SE band still governs - a within-band claim is not REFUTED")
# explicit precision 0.005: the same 0.0545 overclaim is now OUTSIDE budget -> REFUTED
truth(cmp1(0.6855, 0.74, precision=0.005, se=0.03) == V.REFUTED,
      "explicit claimed_precision caps the budget -> the 0.05 AUC overclaim REFUTES (was falsely CONFIRMED)")
# an honest claim within the declared precision still confirms (the cap never false-refutes the truth)
truth(cmp1(0.6855, 0.6855, precision=0.005, se=0.03) in (V.CONFIRMED, V.CAVEATS),
      "honest claim within the declared precision still confirms")

# SECURITY: claimed_precision is a COUNTERPARTY-CONTROLLED contract field and may only ever TIGHTEN the
# budget. A huge / invalid value must NOT widen it into a false-CONFIRM of an overclaim (the number
# reproduces honestly; only the self-declared tolerance lies, so the determinism/binding guards don't fire).
truth(cmp1(0.8, 3.0, precision=5.0) == V.REFUTED,
      "security: a hostile claimed_precision=5.0 cannot false-CONFIRM a 3.0-vs-0.8 overclaim")
truth(cmp1(0.5, 1.0, precision=1e9) == V.REFUTED,
      "security: claimed_precision=1e9 cannot widen the budget (clamped to the claim's inferred precision)")
truth(cmp1(0.5, 1.0, precision=-5) == V.REFUTED,
      "security: a non-positive claimed_precision is ignored, never honored as a wide band")

print("numerai-recipes: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
