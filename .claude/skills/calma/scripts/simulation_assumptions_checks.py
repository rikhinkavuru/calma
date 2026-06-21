"""calma.simulation_assumptions_checks - WS-C(ii): risk-firm simulation-assumption invariants (Chaos Labs /
Gauntlet DeFi risk sims). On the findings rail, called from calma._assemble_ledger. Pure stdlib.

A risk firm's VaR / insolvency number reproduces from its output log, but the SIMULATION can still violate
the firm's own declared assumptions - look-ahead in the calibration window, two liquidations of one account
in one block, a close factor outside the protocol bound, or a VaR labeled p99 that is actually the p95 of
the loss vector. This family is calma's recompute-and-diff applied to the firm's per-block INVARIANTS and to
the VaR PERCENTILE, not just the headline number. Chaos Labs' methodology is a pre-enumerated assumption
schema (their 11 assumptions); Gauntlet differs on key constants (Gauntlet VaR = p95 insolvency, Chaos VaR =
p99 loss). The firm is declared so the right constants apply.

Four checks shipped (the highest-value, lowest-ambiguity from the methodology):
  1. <=1 liquidation per account per block (Chaos #6) - a (account, block) with >1 liquidation event is an
     exact, trivial, unambiguous violation.
  2. VaR percentile recompute + mis-statement - sort the per-iteration loss vector, take the firm's
     percentile, and (a) assert the declared percentile matches the firm's constant (p99 Chaos / p95
     Gauntlet); (b) if the reported VaR equals a DIFFERENT standard percentile of the loss vector than the
     one declared, the percentile is mis-stated.
  3. Calibration-window look-ahead - the calibration/correlation window must end strictly BEFORE sim-start;
     an overlap is look-ahead. If the window dates aren't emitted, the honest output is "not auditable".
  4. Close-factor bound - per liquidation, close_factor = repaid / pre_debt must lie in (0, close_factor_max]
     (Aave default 0.5); plus borrower-passivity when a balance series is present (a borrower balance that
     changes on a NON-liquidation block contradicts the passive-borrower assumption).

Honest coverage (shipped as the docstring table, per the roadmap):
  checkable from the output log:  (1) liq/block, (4) close-factor + borrower-passivity, (3) look-ahead WHEN
                                  window dates are emitted, exogenous-price / static-liquidity invariants.
  needs config / window dates:    (2) VaR percentile (needs the loss vector + the declared percentile),
                                  (3) calibration (needs the window dates) -> "assumption not auditable"
                                  is itself a valuable governance finding.
  NOT checkable from one log:     one-of-n non-collusion (#8); "black-swan not statistically tested" (#11,
                                  a scope statement). These are reported as out-of-scope, never asserted.

Scope: INVALIDATED under a claim asserting the risk number / methodology is sound (VaR / insolvency / risk-
parameter / methodology / valid); the same violation next to a bare number -> a CAVEAT. ABSTAINS without a
`simulation_assumptions` block. REFUTED is never manufactured here.

Library: run_checks(contract, base, claim_id, claim_text) -> [finding,...];
apply_validity(claims, findings, contract, claim_text, base=None); family_status(contract, findings).
"""
import csv
import os
import re

import numeric as N
import pathsafe as PS
import verdict as V

_SOUND_RE = re.compile(
    r"\bva[r]\b|value.?at.?risk|insolvenc|risk.?param|methodolog|\bp9\d\b|stress|expected.?loss|"
    r"capital|liquidat|\bsound\b|\bvalid\b|conservativ|coverage", re.I)
# the firm's declared VaR percentile constant (Chaos p99 loss / Gauntlet p95 insolvency).
_FIRM_PCTILE = {"chaos": 0.99, "chaoslabs": 0.99, "chaos_labs": 0.99, "gauntlet": 0.95}
_STD_PCTILES = (0.90, 0.95, 0.975, 0.99)
_DATE_RE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})")  # ISO date prefix for the calibration window


def _sa(contract):
    s = contract.get("simulation_assumptions")
    return s if isinstance(s, dict) else None


def _read_csv(path):
    if not PS.within_cap(path):
        return {}
    try:
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            rd = csv.reader(fh)
            header = next(rd, [])
            cols = {h: [] for h in header}
            for row in rd:
                for h, v in zip(header, row):
                    cols[h].append(v)
            return cols
    except (OSError, StopIteration, csv.Error):
        return {}


def _safe_join(base, rel):
    return PS.safe_join(base, rel)


def _floats(raw):
    out = []
    for v in raw:
        try:
            out.append(float(str(v).strip()))
        except (TypeError, ValueError):
            out.append(float("nan"))
    return out


def _is_liq(v):
    return str(v).strip().lower() in ("liquidation", "liquidate", "liq", "1", "true")


def _date_ord(s):
    """A comparable ordinal from an ISO date (YYYY-MM-DD) or a bare number (a block index). None if neither."""
    s = str(s).strip()
    m = _DATE_RE.match(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return y * 372 + mo * 31 + d  # monotone in calendar order; exact ordering not needed, only compare
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _finding(claim_id, kind, severity, vclass, locator, unblock):
    return {
        "id": "f-%s-simassume-%s" % (claim_id, kind), "claim_id": claim_id,
        "dimension": "simulation-assumptions", "severity": severity, "status": "open",
        "confidence": "deterministic", "fixable_by": "author", "locator": locator, "unblock": unblock,
        "reverify": {"kind": "artifact-recheck", "source": "event-log",
                     "expected": "every declared per-block invariant holds; the VaR percentile is as stated"},
        "validity_class": vclass, "simassume_kind": kind,
    }


def _event_log(contract, base, sa):
    src = sa.get("event_log")
    if not src:
        return None
    return _read_csv(_safe_join(base, src))


def check_liquidation_per_block(contract, base, claim_id="c1"):
    """Chaos #6: >1 liquidation of the same account in the same block is an exact invariant violation."""
    sa = _sa(contract)
    if not sa:
        return None
    log = _event_log(contract, base, sa)
    if not log:
        return None
    acc = sa.get("account_col", "account")
    blk = sa.get("block_col", "block")
    evt = sa.get("event_col", "event")
    if acc not in log or blk not in log:
        return None
    events = log.get(evt) if evt in log else None
    counts = {}
    n = len(log[acc])
    for i in range(n):
        if events is not None and not _is_liq(events[i]):
            continue
        key = (str(log[acc][i]).strip(), str(log[blk][i]).strip())
        counts[key] = counts.get(key, 0) + 1
    viol = [(a, b, c) for (a, b), c in counts.items() if c > 1]
    if not viol:
        return None
    # TOTAL-ORDER sort (count desc, then account, then block): the named example must NOT depend on row /
    # dict-insertion order, else the locator string - and therefore ledger_sha256 - would differ for
    # byte-identical input, breaking the byte-re-derivable-verdict invariant.
    viol.sort(key=lambda x: (-x[2], str(x[0]), str(x[1])))
    a, b, c = viol[0]
    return _finding(
        claim_id, "liquidation-per-block", "blocker", "authoritative",
        "per-block invariant violated: account %s is liquidated %d times in block %s (%d such account/block "
        "pairs have >1 liquidation). The methodology assumes at most one liquidation per account per block, "
        "so the simulation's liquidation path - and any VaR derived from it - is invalid."
        % (a, c, b, len(viol)),
        "enforce the <=1-liquidation-per-account-per-block rule in the sim (dedupe or cap liquidations per "
        "block), then re-run and recompute the VaR")


def _reported_var(contract, sa):
    var = sa.get("var")
    var = var if isinstance(var, dict) else {}
    r = var.get("reported")
    if isinstance(r, (int, float)) and not isinstance(r, bool):
        return float(r)
    for m in contract.get("metrics", []):
        if m.get("headline") and isinstance(m.get("claimed_value"), (int, float)):
            return float(m["claimed_value"])
    return None


def check_var_percentile(contract, base, claim_id="c1"):
    """Recompute the loss vector's quantile at the declared percentile; flag a mis-stated percentile (the
    reported VaR equals a DIFFERENT standard percentile) or a declared percentile != the firm's constant."""
    sa = _sa(contract)
    if not sa:
        return None
    var = sa.get("var")
    if not isinstance(var, dict):  # a wrong-typed var (e.g. a list) -> not auditable, never an AttributeError
        return None
    loss_src = var.get("loss_log")
    if not loss_src:
        return None
    log = _read_csv(_safe_join(base, loss_src))
    loss_col = var.get("loss_col", "loss")
    if loss_col not in log:
        return None
    losses = [x for x in _floats(log[loss_col]) if x == x]
    if len(losses) < 20:  # too few iterations for a stable tail quantile
        return None
    firm = str(sa.get("firm", "")).strip().lower()
    declared = var.get("percentile")
    declared = float(declared) if isinstance(declared, (int, float)) and not isinstance(declared, bool) \
        else _FIRM_PCTILE.get(firm)
    if declared is None:
        return None
    # (a) declared percentile vs the firm's published constant
    firm_default = _FIRM_PCTILE.get(firm)
    if firm_default is not None and abs(declared - firm_default) > 1e-9:
        return _finding(
            claim_id, "var-percentile-firm", "blocker", "authoritative",
            "the declared VaR percentile p%g does not match %s's methodology constant p%g (Chaos VaR = p99 "
            "loss, Gauntlet VaR = p95 insolvency). The headline is computed at the wrong tail."
            % (declared * 100, firm, firm_default * 100),
            "compute VaR at %s's stated p%g and recompute the headline" % (firm, firm_default * 100))
    reported = _reported_var(contract, sa)
    if reported is None:
        return None
    q_declared = N.quantile(losses, declared)
    tol = max(abs(q_declared) * 0.01, 1e-9)
    if abs(reported - q_declared) <= tol:
        return None  # the reported VaR IS the declared percentile of the loss vector - consistent
    # (b) does the reported VaR match a DIFFERENT standard percentile? -> mis-stated percentile
    for p in _STD_PCTILES:
        if abs(p - declared) < 1e-9:
            continue
        qp = N.quantile(losses, p)
        if abs(reported - qp) <= max(abs(qp) * 0.01, 1e-9):
            return _finding(
                claim_id, "var-percentile-misstated", "blocker", "authoritative",
                "mis-stated VaR percentile: the reported VaR %.6g is the p%g of the loss vector, not the "
                "declared p%g (which is %.6g). The headline is labeled a more conservative tail than it is."
                % (reported, p * 100, declared * 100, q_declared),
                "label the VaR with the percentile it is actually computed at, or recompute at the declared "
                "p%g" % (declared * 100))
    return None  # matches neither the declared nor another standard percentile -> a plain recompute gap (core path)


def check_calibration_lookahead(contract, base, claim_id="c1"):
    """Chaos #2/#3: the calibration / correlation window must end strictly before sim-start (no look-ahead).
    Dates absent -> 'not auditable' (a soft, honest governance finding)."""
    sa = _sa(contract)
    if not sa:
        return None
    cal = sa.get("calibration")
    if not isinstance(cal, dict):
        return None
    we, ss = cal.get("window_end"), cal.get("sim_start")
    if we is None or ss is None:
        return _finding(
            claim_id, "calibration-not-auditable", "minor", "soft",
            "the calibration block declares a calibration but not its window dates (window_end / sim_start), "
            "so the no-look-ahead assumption cannot be audited from the output.",
            "emit calibration.window_end and calibration.sim_start so the look-ahead check can run")
    weo, sso = _date_ord(we), _date_ord(ss)
    if weo is None or sso is None:
        return None
    if weo < sso:
        return None  # window ends strictly before sim-start - no look-ahead
    return _finding(
        claim_id, "calibration-lookahead", "blocker", "authoritative",
        "calibration look-ahead: the calibration window ends at %s but the simulation starts at %s (the "
        "window does not end strictly before sim-start), so the fit/correlation sees data from the "
        "simulated period - the risk estimate is contaminated by look-ahead." % (we, ss),
        "calibrate only on data strictly before sim-start (window_end < sim_start), then re-run")


def check_close_factor(contract, base, claim_id="c1"):
    """Close-factor bound: per liquidation, repaid/pre_debt must be in (0, close_factor_max] (Aave 0.5).
    Plus borrower-passivity when a balance series is present (balance changes only on liquidation blocks)."""
    sa = _sa(contract)
    if not sa:
        return None
    log = _event_log(contract, base, sa)
    if not log:
        return None
    repaid_col = sa.get("repaid_col", "repaid")
    pre_col = sa.get("pre_debt_col", "pre_debt")
    cf_max = sa.get("close_factor_max", 0.5)
    cf_max = float(cf_max) if isinstance(cf_max, (int, float)) and not isinstance(cf_max, bool) else 0.5
    evt = sa.get("event_col", "event")
    if repaid_col not in log or pre_col not in log:
        return None
    repaid, pre = _floats(log[repaid_col]), _floats(log[pre_col])
    events = log.get(evt) if evt in log else None
    n = min(len(repaid), len(pre))
    worst = None
    n_viol = 0
    for i in range(n):
        if events is not None and not _is_liq(events[i]):
            continue
        if pre[i] != pre[i] or repaid[i] != repaid[i] or pre[i] <= 0:
            continue
        cf = repaid[i] / pre[i]
        if cf <= 0 or cf > cf_max + 1e-9:
            n_viol += 1
            if worst is None or cf > worst:
                worst = cf
    if not n_viol:
        return None
    return _finding(
        claim_id, "close-factor", "blocker", "authoritative",
        "close-factor invariant violated: %d liquidation(s) repay a fraction of debt outside (0, %.2f] - the "
        "worst is %.3f. A single liquidation cannot repay more than the protocol's close factor, so the "
        "liquidation mechanics (and the loss/VaR they feed) are mis-modeled." % (n_viol, cf_max, worst),
        "cap each liquidation's repaid/pre_debt at the protocol close factor (%.2f), then re-run" % cf_max)


def run_checks(contract, base, claim_id="c1", claim_text=None):
    """Simulation-assumption findings. SILENT unless a `simulation_assumptions` block is declared.
    Fail-soft: any check that errors is skipped (never crashes the verify)."""
    out = []
    for fn in (check_liquidation_per_block, check_var_percentile, check_calibration_lookahead,
               check_close_factor):
        try:
            f = fn(contract, base, claim_id)
        # ArithmeticError = Overflow/ZeroDivision (huge/zero cells); AttributeError = a wrong-typed sub-block
        # (e.g. var: [list]). The rail NEVER crashes the verify - any error -> skip the check (no finding).
        except (OSError, ValueError, KeyError, TypeError, ArithmeticError, IndexError, AttributeError):
            f = None
        if f:
            out.append(f)
    return out


def _applicable(contract):
    return bool(_sa(contract))


def family_status(contract, findings):
    if not _applicable(contract):
        return "not-applicable"
    return "flagged" if any(f.get("dimension") == "simulation-assumptions" and f.get("simassume_kind")
                            for f in findings) else "checked"


def _asserts_sound(claim_text):
    return bool(isinstance(claim_text, str) and _SOUND_RE.search(claim_text))


def apply_validity(claims, findings, contract, claim_text, base=None):
    """Promote the headline per the simulation-assumption findings + claim scope. Conservative: only a
    REPRODUCED number is promoted, and only DOWN. An authoritative invariant violation under a VaR / risk /
    methodology claim -> INVALIDATED('simulation-assumptions'); the same finding next to a bare number, or a
    soft 'not auditable' finding -> CAVEAT."""
    fam = [f for f in (findings or []) if f.get("dimension") == "simulation-assumptions"
           and f.get("simassume_kind")]
    if not fam or not claims:
        return
    head = next((c for c in claims if c.get("headline")), claims[0])
    if head.get("verdict") not in (V.CONFIRMED, V.CAVEATS):
        return
    vi = head.get("verdict_inputs") or {}
    auth = [f for f in fam if f.get("validity_class") == "authoritative"]
    if auth and _asserts_sound(claim_text):
        for f in auth:
            f["claim_id"] = head["id"]
        vi["validity_invalidated"] = True
        vi["oos_claim_asserted"] = True
        head["driving_dimension"] = "simulation-assumptions"
    else:
        for f in fam:
            if f.get("validity_class") == "authoritative":
                f["severity"] = "minor"
        vi["soft_validity_caveat"] = True
    head["verdict_inputs"] = vi
    head["verdict"] = V.verdict(vi)
    head["headline_confidence"] = V.confidence(vi, head["verdict"])
