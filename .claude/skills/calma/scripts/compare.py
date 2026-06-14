"""calma.compare - build the calibrated tolerance budget and the full verdict_inputs from a recompute,
then call the shared verdict() (never the model). Emits the diff table + verdict + verdict_inputs.

M1 budget model (placeholders until the M2 corpus calibrates them - see BUILD-NOTES):
  effective_budget = max(ABS_FLOOR, REL_FLOOR*|claimed|, Z * claim_sampling_SE)
The deterministic path has k_spread ~= 0, so a fraud-grade gap (e.g. 147 vs a ~1e-6 budget) clears
the budget by an astronomic margin. The verdict() guards still gate REFUTED on binding/determinism/
isolation/claim-confirmation, so this never manufactures a false REFUTED.

Library: compare(recompute, contract, **env) -> dict.
CLI: compare.py --recompute recompute.json --contract verify.yaml --out diff.json [env flags]
"""
import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recipes as RCP  # noqa: E402
import verdict as V  # noqa: E402

ABS_FLOOR = 1e-9
REL_FLOOR = 1e-9
Z = 1.96  # ~95% two-sided for the sampling-SE term
CONV_RATIO = 3.0  # max claim/recompute ratio a periodicity-style convention can explain (calibrated)
FRAUD_M = 5.0  # gap must exceed budget by this multiple for an UNCONTROLLED (non-Python) run to REFUTE

_CALIB = None


def _load_calibration():
    global _CALIB, ABS_FLOOR, REL_FLOOR, Z, CONV_RATIO, FRAUD_M
    if _CALIB is not None:
        return _CALIB
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "calibration.json")
    try:
        c = json.load(open(path))
        ABS_FLOOR = c.get("abs_floor", ABS_FLOOR)
        REL_FLOOR = c.get("rel_floor", REL_FLOOR)
        Z = c.get("z", Z)
        CONV_RATIO = c.get("conv_ratio", CONV_RATIO)
        FRAUD_M = c.get("fraud_m", FRAUD_M)
        _CALIB = c
    except (OSError, ValueError):
        _CALIB = {}
    return _CALIB


def _infer_precision(claimed):
    """The half-ULP of the claim's REPORTED precision: '0.42' -> 0.005, integer -> 0.5, sci/long -> ~0.
    Claims scaled in parsing ('23.87%' -> 0.23870000000000002) have float-artifact reprs; the
    shortest decimal that round-trips within float tolerance recovers the reported precision."""
    c = float(claimed)
    s = repr(c)
    if "e" in s or "E" in s:
        return 0.0
    if "." not in s or c == int(c):
        # An integer claim in the unit range (0 / 1 / -1) is almost always a bounded metric stated
        # whole - "accuracy 1", "0 errors", "AUC 1" - meaning the exact value, NOT "value +/- 0.5".
        # Granting the half-ULP 0.5 there is half the entire [0,1]/[-1,1] range and false-CONFIRMS
        # gross overclaims (claim 1 vs true 0.85). Use a tight one-significant-figure tolerance so a
        # genuine perfect/zero score still confirms (recompute ~= the claim) but a material overclaim
        # refutes. Larger integers (counts, multiples) keep the half-ULP 0.5.
        return 0.05 if abs(c) <= 1.0 else 0.5
    d = len(s.split(".", 1)[1])
    if d > 6:
        tol = 1e-12 * max(1.0, abs(c))
        for k in range(1, 13):
            if abs(round(c, k) - c) <= tol:
                return 0.5 * 10 ** (-k)
        return 0.0
    return 0.5 * 10 ** (-d)


def _sign(x):
    return (x > 0) - (x < 0)


def _budget(claimed, sampling_se, claimed_precision=None):
    prec = claimed_precision if claimed_precision is not None else _infer_precision(claimed)
    terms = {"abs_floor": ABS_FLOOR, "rel_floor": REL_FLOOR * abs(claimed), "claim_precision": prec}
    if isinstance(sampling_se, float) and sampling_se == sampling_se and sampling_se > 0:
        terms["sampling_se"] = Z * sampling_se
    eff = max(terms.values())
    return eff, terms


def compare(recompute, contract, isolation_tier="tier0", container_present=None,
            determinism_mode="controlled-to-bit", sufficient_k=True, m2_calibrated=False,
            untrusted=False, killed=False, exit_codes=(0,), outputs_unstable=False):
    _load_calibration()
    m2_calibrated = m2_calibrated or bool(_CALIB)
    if container_present is None:
        container_present = isolation_tier in ("vm", "container", "tier0", "seatbelt-verified")
    by_id = {m["metric_id"]: m for m in recompute["metrics"]}
    base_by_id = {b["metric_id"]: b for b in recompute.get("baselines", [])}
    # true no-claim mode: NO metric in the whole contract carries a claimed value. A single
    # numberless metric next to claimed ones stays INCONCLUSIVE (nothing was claimed for it).
    any_claimed = any(m.get("claimed_value") is not None for m in contract.get("metrics", []))
    metrics_out = []
    for m in contract.get("metrics", []):
        mid = m["metric_id"]
        rec = by_id.get(mid, {})
        claimed = m.get("claimed_value")
        # a non-finite claimed value (inf/NaN) is not a checkable finite target: drop it to "no
        # numeric diff" so it can never produce an inf budget that CONFIRMs anything (defense in
        # depth - parse_claim already rejects overflowing claims at the CLI boundary).
        if claimed is not None and not (isinstance(claimed, (int, float)) and math.isfinite(claimed)):
            claimed = None
        recomputed = rec.get("value")
        sampling_se = (rec.get("terms") or {}).get("sampling_se")
        eff, bterms = _budget(claimed if claimed is not None else 0.0, sampling_se,
                              m.get("claimed_precision"))
        # convention cap: a declared, in-set convention can explain a periodicity-scale gap -> CAVEAT
        conv = m.get("convention")
        conv_capped = False
        if conv is not None and claimed not in (None, 0) and isinstance(recomputed, float) and recomputed not in (None, 0.0):
            fn = RCP.get(mid)
            accepted = set((fn.manifest.get("accepted_conventions") if fn else []) or [])
            if str(conv) in accepted:
                ratio = max(abs(recomputed / claimed), abs(claimed / recomputed)) if claimed and recomputed else 1e9
                # a legitimate convention (periodicity, k, units) rescales - it never flips sign
                conv_capped = ratio <= CONV_RATIO and _sign(recomputed) == _sign(claimed)
        gap = None
        if claimed is not None and isinstance(recomputed, float) and recomputed == recomputed:
            gap = abs(recomputed - claimed)
        # recompute CI half-width ~ k_spread (deterministic path -> ~0)
        ci = rec.get("k_spread", 0.0) or 0.0
        claim_outside_ci = gap is not None and gap > (ci + eff)
        vinputs = {
            "gap": gap, "effective_budget": eff, "margin": 1.0,
            "claim_outside_ci": bool(claim_outside_ci),
            "sign_agrees": (claimed is None or recomputed is None
                            or _sign(recomputed) == _sign(claimed)),
            "band_coverage_ok": determinism_mode == "controlled-to-bit" or sufficient_k,
            "binding_status": m.get("binding_status", "author-asserted"),
            "isolation_tier": isolation_tier, "container_present": container_present,
            "untrusted": untrusted, "exit_codes": list(exit_codes), "killed": killed,
            "determinism_mode": determinism_mode, "sufficient_k": sufficient_k,
            "unbounded_op_present": False, "path_dependent": bool(rec.get("path_dependent")),
            "m2_calibrated": m2_calibrated, "recompute_degenerate": bool(rec.get("degenerate")),
            # a confirmed claim target can REFUTE whether or not it is THE headline metric - this is
            # what lets a committed multi-metric contract catch a fabricated SECONDARY metric (-> MIXED).
            # claim_confirmed already implies a claimed value on a pinned/independently-bound metric, so
            # the old `and headline` was redundant for drafted contracts and swallowed secondary lies.
            "claim_confirmed_target": bool(m.get("claim_confirmed")),
            "convention_capped": conv_capped,
            "fraud_multiple_met": bool(gap is not None and gap > FRAUD_M * eff),
            "outputs_unstable": bool(outputs_unstable),
            # no-claim mode: nothing to diff, but the metric DID recompute from raw outputs after a
            # clean re-execution -> verdict() reports reproduction instead of demanding a claim
            "no_claim_reproduced": bool(not any_claimed and claimed is None
                                        and isinstance(recomputed, float)
                                        and recomputed == recomputed and not rec.get("degenerate")),
        }
        label, reason = V.verdict_with_reason(vinputs)
        metrics_out.append({
            "metric_id": mid, "headline": bool(m.get("headline")),
            "claimed": claimed, "recomputed": recomputed, "gap": gap,
            "budget": eff, "budget_terms": bterms, "verdict": label, "reason": reason,
            "verdict_inputs": vinputs,
            # the precise recompute/binding error (e.g. "binding failed: column X not found"), so the
            # report can surface the actual cause instead of the generic "NaN/Inf" fix line
            "recompute_error": rec.get("error"),
        })
    # baseline edge (recompute - baseline); informational finding for the baseline family
    baseline = None
    if recompute.get("baselines") and recompute["metrics"]:
        strat = recompute["metrics"][0].get("value")
        base_v = recompute["baselines"][0].get("value")
        if isinstance(strat, float) and isinstance(base_v, float):
            edge = strat - base_v
            baseline = {
                "strat": strat, "baseline": base_v, "edge": edge,
                "beats_baseline": edge > 0,
                "finding": None if edge > 0 else
                "strategy underperforms the trivial baseline (edge %.4f <= 0)" % edge,
            }
    return {"metrics": metrics_out, "baseline": baseline}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recompute", required=True)
    ap.add_argument("--contract", required=True)
    ap.add_argument("--isolation", default="tier0")
    ap.add_argument("--determinism", default="controlled-to-bit")
    ap.add_argument("--m2-calibrated", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    recompute = json.load(open(a.recompute))
    contract = json.load(open(a.contract))
    res = compare(recompute, contract, isolation_tier=a.isolation,
                  determinism_mode=a.determinism, m2_calibrated=a.m2_calibrated)
    text = json.dumps(res, indent=2)
    if a.out:
        open(a.out, "w").write(text)
    print(text)
    return 1 if any(m["verdict"] in (V.REFUTED, V.CAVEATS) for m in res["metrics"]) else 0


if __name__ == "__main__":
    sys.exit(main())
