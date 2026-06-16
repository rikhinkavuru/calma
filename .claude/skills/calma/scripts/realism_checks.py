"""calma.realism_checks - execution-realism deflators on the findings rail (dimension
"execution-realism", an EXEC dim), called from calma._assemble_ledger like leakage_checks /
overfitting_checks.

Idea: an optimistic backtest assumes frictionless fills. Deflate the per-period returns to realistic
frictions - transaction cost + slippage per unit turnover, short-borrow carry, and a square-root market-
impact term from claimed size vs ADV - then RE-RUN the headline recipe net-of-friction. The verdict
follows the claim's own scope (mirrors the leakage OOS scope-guard, here keyed on NET / LIVE vs GROSS):

  - claim asserts NET / LIVE and the friction-deflated recompute lands outside budget
        -> REFUTED via the gap path (the claimed "net" number is really gross), driving execution-realism.
  - claim asserts NET / LIVE but the result is uninvestable at the claimed size (participation >= 1 ADV),
    or the net number can't be substantiated -> INVALIDATED (the live result is invalid).
  - claim is GROSS / paper -> CONFIRMED-WITH-CAVEATS (the number is literally true gross, but the net /
    live result is materially lower / uninvestable).
  - claim does NOT say net vs gross (indeterminate) + a material friction -> CAN'T-CONFIRM ("declare
    whether the headline is net-of-cost or gross").
  - friction declared but not applicable as given (no turnover / ADV) on a net claim -> CAN'T-CONFIRM.
  - an optimistic FILL assumption alone (close / vwap with no recompute) -> soft caveat.

Activates ONLY when a `frictions:{...}` block is declared - a friction the author did not declare is
NEVER guessed. The older `costs` / `universe` surface stays with backtest_checks (no double-counting).
Deterministic arithmetic only; the deflated recompute re-runs the SAME registered recipe on net returns.

Library: run_checks(contract, base, claim_id, claim_text) -> [finding,...];
apply_validity(claims, findings, contract, claim_text, base); net_status(contract, claim_text).
"""
import csv
import math
import os
import re

import numeric as N
import verdict as V

# the fraction by which the net-of-friction metric must fall below the gross before we call the
# deflation material (5% of the gross magnitude) - small accrual/rounding drift never trips it.
_MATERIAL = 0.05
# the realism-deflated recompute applies to a return-based headline. sharpe/sortino are ratio metrics
# (a clean REFUTED when the net collapses); total_return/calmar are path-dependent in the verdict
# machinery's eyes (calmar via max-drawdown) - their net collapse can't be a gap-gated REFUTED (a path-
# dependent metric blocks it), so apply_validity routes that to INVALIDATED instead. All re-run the SAME
# registered recipe on the net returns.
_DEFLATABLE = {"sharpe", "total_return", "sortino", "calmar"}
# fills that overstate the achievable price vs a conservative arrival/next-open assumption.
_OPTIMISTIC_FILLS = {"close", "vwap", "midpoint", "mid", "touch"}

_NET_RE = re.compile(
    r"net[\s-]?of|net[\s-]?return|after[\s-](costs?|fees?|slippage|commission)|"
    r"\blive\b|tradeable|tradable|executable|implementab|realistic|after costs|investable", re.I)
_GROSS_RE = re.compile(
    r"\bgross\b|before[\s-](costs?|fees?)|frictionless|\bpaper\b|theoretical|pre[\s-]?cost|"
    r"ex[\s-]?cost|no[\s-](costs?|fees?)", re.I)


# ---- io ----------------------------------------------------------------------

def _safe_join(base, rel):
    """Resolve rel under base and refuse anything that escapes it (absolute path, .. traversal, symlink
    out). Mirrors recompute._safe_join - a detector must never be coerced into reading a file outside the
    contract base (path-traversal / file-exfiltration via an attacker-authored verify.yaml)."""
    full = os.path.realpath(os.path.join(base, rel))
    rb = os.path.realpath(base)
    if full != rb and not full.startswith(rb + os.sep):
        raise ValueError("path escapes the contract base: %r" % rel)
    return full


def _read_csv(path):
    if not os.path.isfile(path):
        return {}  # FIFO/socket/device: never open() (would block); treated as unreadable
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


def _floats(vals):
    out = []
    for v in vals:
        try:
            out.append(float(str(v).strip()))
        except (TypeError, ValueError):
            out.append(float("nan"))
    return out


def _headline_metric(contract):
    mets = contract.get("metrics") or []
    for m in mets:
        if m.get("headline") and m.get("claimed_value") is not None:
            return m
    for m in mets:
        if m.get("claimed_value") is not None:
            return m
    return mets[0] if mets else None


def _return_col(m, cols):
    b = m.get("binding") or {}
    rc = b.get("return")
    if rc and "::" not in str(rc) and rc in cols:
        return rc
    for name in cols:
        if name.lower() in ("return", "daily_return", "ret", "returns", "strat_return",
                            "net_return", "gross_return", "pnl_return"):
            return name
    return None


# ---- the friction model (elementary, declared-only; no special functions) --------------------------

def _frictions(contract):
    fr = contract.get("frictions")
    return fr if isinstance(fr, dict) else None


def _turnover_series(fr, cols, n):
    """Per-period turnover (the traded fraction each period). A declared turnover_col, else a flat
    `turnover` scalar, else 1.0/period (full turnover) only when a per-turnover cost is declared. Returns
    a list of length n, or None when no turnover basis is available."""
    tcol = fr.get("turnover_col")
    if tcol and tcol in cols:
        t = _floats(cols[tcol])
        return [(x if x == x else 0.0) for x in t[:n]] + [0.0] * max(0, n - len(t))
    tv = fr.get("turnover")
    if isinstance(tv, (int, float)) and not isinstance(tv, bool):
        return [float(tv)] * n
    return None


def _participation(fr):
    """size / ADV - the fraction of a day's volume the claimed trade represents (>=1 == a full day's
    volume or more, i.e. uninvestable at size). Returns None when size or ADV is not declared."""
    adv = fr.get("adv")
    size = fr.get("size")
    part = fr.get("participation")
    if isinstance(part, (int, float)) and not isinstance(part, bool) and part >= 0:
        return float(part)
    if all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (adv, size)) and adv > 0:
        return float(size) / float(adv)
    return None


def sqrt_impact(participation, sigma, coef=1.0):
    """Square-root market-impact cost as a per-period return fraction (Almgren et al.): the cost to
    execute a `participation` fraction of ADV is coef * sigma * sqrt(participation), where sigma is the
    per-period return volatility. Elementary closed form (no special functions) - deterministic and exact;
    that is why it needs no scipy/numpy reference vector, unlike the DSR/PBO kernels."""
    if not (participation is not None and participation >= 0 and sigma == sigma and sigma >= 0):
        return float("nan")
    return coef * sigma * math.sqrt(participation)


def deflate(contract, base):
    """Deflate the headline return series to realistic frictions and recompute the headline metric net.
    Returns {gross, net, deflated_metric, claimed, components, turnover_ok, participation, metric_id} or
    None when not applicable (no frictions / not a deflatable metric / no return column). The recompute
    re-runs the SAME registered recipe on the net returns (no full re-execution)."""
    fr = _frictions(contract)
    m = _headline_metric(contract)
    if not fr or not m or m.get("metric_id") not in _DEFLATABLE:
        return None
    try:
        cols = _read_csv(_safe_join(base, m.get("artifact", "")))
    except ValueError:  # artifact path escapes the contract base
        return None
    rcol = _return_col(m, cols) if cols else None
    if not rcol:
        return None
    gross_rets = _floats(cols[rcol])
    gross_rets = [r for r in gross_rets if r == r]
    if len(gross_rets) < 2:
        return None
    n = len(gross_rets)
    sigma = N.fstd(gross_rets, ddof=1)
    turn = _turnover_series(fr, cols, n)
    part = _participation(fr)

    fee = float(fr.get("fee_bps") or 0.0) / 1e4
    slip = float(fr.get("slippage_bps") or 0.0) / 1e4
    borrow = float(fr.get("borrow_bps") or 0.0) / 1e4
    short_frac = float(fr.get("short_frac") or 0.0)
    coef = float(fr.get("impact_coef") or 1.0)
    impact_model = str(fr.get("impact_model") or "").strip().lower()
    leverage = float(fr.get("leverage") or 1.0)

    per_turn_bps = (fee + slip)
    # turnover is required to apply a per-turnover cost; if a per-turnover cost is declared but no
    # turnover basis exists, default to flat full turnover so the cost is still applied (conservative).
    # `!= 0` (not `> 0`): a NEGATIVE declared cost (fee_bps:-50) is nonsensical, not "no cost" - apply
    # it so the net exceeds gross and check_deflation's degenerate-net guard fires, instead of silently
    # dropping it and CONFIRMING a net claim with zero friction applied.
    if per_turn_bps != 0 and turn is None:
        turn = [1.0] * n
    impact_per = float("nan")
    if impact_model == "sqrt" and part is not None:
        impact_per = sqrt_impact(part, sigma, coef)
    # financing the levered portion: a book run at Lx borrows (L-1)x capital at the borrow rate every
    # period. Only charged when a borrow rate is declared (never guess the financing rate).
    financing = (leverage - 1.0) * borrow if (leverage > 1.0 and borrow > 0) else 0.0

    components, applied = {}, False
    net = []
    for t in range(n):
        c = 0.0
        tt = (turn[t] if turn is not None else 0.0)
        if per_turn_bps != 0 and turn is not None:
            c += per_turn_bps * tt
            applied = True
        if borrow > 0 and short_frac > 0:
            c += borrow * short_frac
            applied = True
        if financing > 0:
            c += financing
            applied = True
        if impact_per == impact_per and impact_model == "sqrt" and part is not None:
            # impact scales with the traded fraction; flat (turnover-less) books pay it once per period.
            c += impact_per * (tt if turn is not None else 1.0)
            applied = True
        net.append(gross_rets[t] - c)
    if per_turn_bps > 0:
        components["cost"] = "%.1f bps fee+slippage / turnover" % (per_turn_bps * 1e4)
    if borrow > 0 and short_frac > 0:
        components["borrow"] = "%.1f bps/period borrow on %.0f%% short" % (borrow * 1e4, short_frac * 100)
    if financing > 0:
        components["financing"] = "%.1f bps/period financing on %.1fx leverage" % (financing * 1e4, leverage)
    if impact_per == impact_per and impact_model == "sqrt" and part is not None:
        components["impact"] = "sqrt impact at %.1f%% of ADV (sigma %.4f)" % (part * 100, sigma)

    # unphysical regime: a declared friction that drives a per-period NET return below -100% (you can't
    # lose more than your capital in a period) breaks the compounding metrics - total_return / calmar
    # compound (1+net_r) through a NEGATIVE base, which for an even period count flips to a large POSITIVE
    # (a nonsensical "+39,000,000%"). Treat that as a degenerate deflation (net NaN) so it routes to
    # INVALIDATED ("the declared frictions are not realizable"), never a garbage-positive REFUTED.
    unphysical = applied and net and min(net) <= -1.0 and m.get("metric_id") in ("total_return", "calmar")

    import recipes as RCP  # lazy: avoids any import-time coupling
    fn = RCP.get(m.get("metric_id"))
    if not fn:
        return None
    try:
        gross_v = fn({rcol: gross_rets}, m.get("binding") or {rcol: rcol}, m.get("convention")).get("value")
        net_v = fn({rcol: net}, m.get("binding") or {rcol: rcol}, m.get("convention")).get("value") \
            if applied else gross_v
    except (ValueError, KeyError, TypeError, ZeroDivisionError, OverflowError):
        return None
    if not (isinstance(gross_v, float) and gross_v == gross_v):
        return None
    if unphysical:
        net_v = float("nan")
    return {
        "gross": gross_v, "net": net_v, "claimed": m.get("claimed_value"),
        "components": components, "applied": applied, "participation": part,
        "metric_id": m.get("metric_id"), "n": n, "sigma": sigma,
    }


# ---- detectors (pure detection; severity reflects authoritativeness, not yet the net scope) --------

def _finding(claim_id, kind, severity, vclass, locator, unblock, magnitude=None):
    f = {
        "id": "f-%s-realism-%s" % (claim_id, kind), "claim_id": claim_id,
        "dimension": "execution-realism", "severity": severity, "status": "open",
        "confidence": "deterministic", "fixable_by": "author", "locator": locator, "unblock": unblock,
        "reverify": {"kind": "artifact-recheck", "source": "frictions",
                     "expected": "the edge survives the declared friction model"},
        "validity_class": vclass, "realism_kind": kind,
    }
    if magnitude is not None:  # omit a null magnitude (the deflation finding has none) - dead bytes
        f["magnitude"] = magnitude
    return f


def check_capacity(contract, base, claim_id="c1"):
    """Capacity / market-impact: claimed traded size at/above a full day's ADV (participation >= 1) ->
    uninvestable at size, authoritative. A high-but-<1 participation is a soft capacity caveat."""
    fr = _frictions(contract)
    if not fr:
        return None
    part = _participation(fr)
    if part is None:
        return None
    if part >= 1.0:
        return _finding(
            claim_id, "capacity", "blocker", "authoritative",
            "uninvestable at the claimed size: the trade is %.1f%% of ADV (>= a full day's volume) - "
            "market impact makes the live result unrealizable at this size" % (part * 100),
            "size the book to a tradeable participation of ADV (typically <=10-20%) and recompute net "
            "of the resulting market impact", magnitude=part)
    if part >= 0.10:
        return _finding(
            claim_id, "capacity-soft", "minor", "soft",
            "capacity caution: the claimed trade is %.1f%% of ADV - material market impact is likely at "
            "this size (declare impact_model:sqrt with adv/size to deflate it)" % (part * 100),
            "confirm the strategy scales to the claimed size, or report the capacity-constrained size",
            magnitude=part)
    return None


def check_fill(contract, claim_id="c1"):
    """An optimistic fill assumption (close / vwap / midpoint) overstates the achievable price - a
    labeled soft caveat (we cannot recompute the fill gap without tick data)."""
    fr = _frictions(contract)
    if not fr:
        return None
    fill = str(fr.get("fill") or "").strip().lower()
    if fill in _OPTIMISTIC_FILLS:
        return _finding(
            claim_id, "fill", "minor", "soft",
            "optimistic fill: the backtest assumes a %r fill, which is not reliably achievable in live "
            "trading (you cannot guarantee the close / VWAP) - the realized fill is typically worse" % fill,
            "re-run assuming a conservative fill (arrival price or next-open) and report the difference")
    return None


def check_leverage(contract, claim_id="c1"):
    """Leverage sanity: a declared leverage > 1 means the headline is levered - the un-levered (1x) result
    is ~1/L of the gross return and the strategy carries L x the drawdown plus financing cost. A labeled
    soft caveat (no arbitrary threshold - any leverage > 1 is surfaced; the financing drag itself is
    already folded into the deflated recompute when a borrow rate is declared)."""
    fr = _frictions(contract)
    if not fr:
        return None
    try:
        lev = float(fr.get("leverage") or 1.0)
    except (TypeError, ValueError):
        return None
    if lev <= 1.0:
        return None
    note = " (financing drag folded into the net recompute)" if fr.get("borrow_bps") else \
        " (declare borrow_bps to deflate the financing cost too)"
    return _finding(
        claim_id, "leverage", "minor", "soft",
        "levered headline: the result is run at %.1fx leverage - the un-levered (1x) return is ~1/%.1f of "
        "this and the strategy carries ~%.1fx the drawdown%s" % (lev, lev, lev, note),
        "report the un-levered (1x) figure alongside, and confirm the leverage is fundable at the claimed "
        "size", magnitude=lev)


def check_deflation(contract, base, claim_id="c1"):
    """The realism-deflated recompute: re-run the headline recipe net of declared frictions. Fires an
    authoritative finding iff the net metric falls materially below the gross. Carries the gross/net pair
    so apply_validity can route REFUTED / INVALIDATED / CAVEAT / CAN'T-CONFIRM."""
    d = deflate(contract, base)
    if not d or not d["applied"]:
        return None
    gross, net = d["gross"], d["net"]
    finite = isinstance(net, float) and net == net and abs(net) != float("inf")
    # frictions can only REDUCE the metric. A net that is non-finite or *exceeds* gross is a DEGENERATE
    # deflation (e.g. total_return overflow when a declared per-period cost drives a net return below
    # -100%), never a surviving edge - fire the finding so apply_validity routes it (INVALIDATED /
    # CAN'T-CONFIRM), and NEVER let `drop <= threshold` swallow a sign-flipped/non-finite net into a
    # false CONFIRM (adversarial finding, 2026-06-15).
    if finite and net <= gross and (gross - net) <= _MATERIAL * max(abs(gross), 1e-9):
        return None  # frictions don't materially move the metric -> clean (no finding)
    if finite:
        body = "nets %.4f after %s - a %.4f drag" % (net, "; ".join(d["components"].values()), gross - net)
    else:
        body = ("nets a non-finite value after %s (the declared frictions drive a per-period net return "
                "below -100%%) - the net result is not realizable" % "; ".join(d["components"].values()))
    return _finding(
        claim_id, "deflation", "blocker", "authoritative",
        "friction-deflated: the headline %s reproduces gross at %.4f but %s" % (d["metric_id"], gross, body),
        "report the NET-of-friction %s (apply the declared cost / impact model to the position series), "
        "or state the headline is gross" % d["metric_id"])


def _is_trading_headline(contract):
    """The realism family only applies to a return-based (trading) headline - a `frictions` block declared
    on a non-trading metric (e.g. accuracy) is a contract authoring error, not a friction to apply. The
    signal: the headline metric binds a `return` column (sharpe / total_return / max_drawdown all do)."""
    m = _headline_metric(contract)
    return bool(m and (m.get("binding") or {}).get("return"))


def run_checks(contract, base, claim_id="c1", claim_text=None):
    """All realism catches against one engagement. Returns the findings that fired (possibly empty).
    Fail-soft: any check that errors is skipped (a check must never crash a verification). SILENT when
    no `frictions` block is declared, or the headline is not a return-based (trading) metric (realism
    NOT-APPLICABLE - a friction the author did not declare, and a non-trading headline, are never assumed)."""
    if not _frictions(contract) or not _is_trading_headline(contract):
        return []
    out = []
    checks = (
        lambda: check_deflation(contract, base, claim_id),
        lambda: check_capacity(contract, base, claim_id),
        lambda: check_fill(contract, claim_id),
        lambda: check_leverage(contract, claim_id),
    )
    for fn in checks:
        try:
            f = fn()
        except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
            f = None
        if f:
            out.append(f)
    return out


def family_status(contract, findings):
    """Honest scope.families.realism status."""
    if not _frictions(contract) or not _is_trading_headline(contract):
        return "not-applicable"
    return "flagged" if any(f.get("realism_kind") for f in findings) else "checked"


# ---- claim-scope guard + verdict promotion ----------------------------------

def net_status(contract, claim_text):
    """Does the claim assert a NET / LIVE result (the thing frictions would invalidate)? 'net' |
    'gross' | 'indeterminate'. Drives the scope-guard: INVALIDATED/REFUTED require a POSITIVE net/live
    assertion; an explicit gross claim degrades to a caveat; anything ambiguous degrades to CAN'T-CONFIRM
    (declare net vs gross) - never a manufactured invalidation."""
    t = claim_text or ""
    if _GROSS_RE.search(t):
        return "gross"
    if _NET_RE.search(t):
        return "net"
    return "indeterminate"


def apply_validity(claims, findings, contract, claim_text, base=None):
    """Promote the headline claim's verdict per the realism findings + the claim's net/gross scope.
    Conservative: only a REPRODUCED number (CONFIRMED/CAVEATS) is ever promoted, and only DOWN. On a
    NET/LIVE claim with a feasible deflated recompute outside budget the claim is REFUTED via the gap-
    gated path (driving execution-realism); a NET/LIVE claim that can't be substantiated (uninvestable at
    size, or the net number isn't recomputable) -> INVALIDATED; a GROSS claim -> CAVEAT; an indeterminate
    claim -> CAN'T-CONFIRM. Soft findings (fill / capacity caution) -> CAVEAT."""
    real = [f for f in findings if f.get("dimension") == "execution-realism" and f.get("realism_kind")]
    if not real or not claims:
        return
    head = next((c for c in claims if c.get("headline")), claims[0])
    if head.get("verdict") not in (V.CONFIRMED, V.CAVEATS):
        return  # the number didn't reproduce; realism findings stay additive, no promotion
    auth = [f for f in real if f.get("validity_class") == "authoritative"]
    soft = [f for f in real if f.get("validity_class") == "soft"]
    vi = head.get("verdict_inputs") or {}
    if not auth:
        if soft:
            vi["soft_validity_caveat"] = True
            head["verdict_inputs"] = vi
            head["verdict"] = V.verdict(vi)
            head["headline_confidence"] = V.confidence(vi, head["verdict"])
        return

    status = net_status(contract, claim_text)
    deflater = next((f for f in auth if f.get("realism_kind") == "deflation"), None)
    capacity = next((f for f in auth if f.get("realism_kind") == "capacity"), None)
    claimed = head.get("claimed_value")
    budget = vi.get("effective_budget") or 0.0
    for f in auth:
        f["claim_id"] = head["id"]

    if status == "net":
        # capacity precedence: if the trade is uninvestable at size (>= a full day's ADV), the live claim
        # is invalid regardless of the exact deflated number - skip the substantiation path below.
        # Otherwise try the friction-deflated recompute (the differentiator) before settling on a verdict.
        d = deflate(contract, base) if (base and deflater is not None and capacity is None) else None
        net_finite = d is not None and isinstance(d.get("net"), float) and d["net"] == d["net"] \
            and abs(d["net"]) != float("inf")
        if net_finite and claimed is not None:
            net, mid = d["net"], d["metric_id"]
            if abs(net - claimed) > budget:
                # try the gap-gated REFUTED first. The deflated recompute uses the SAME convention as the
                # claim, so a legitimate-convention difference can't explain the gap - clear the convention
                # cap the core Sharpe/sortino path sets for annualization choices.
                trial = dict(vi)
                trial["gap"] = abs(net - claimed)
                trial["claim_outside_ci"] = True
                trial["convention_capped"] = False
                # the net recompute is carried structurally (head.recomputed_value below + the render's
                # claimed->recomputed line); keep a machine field on the finding but DON'T restate it in
                # the human locator (the base locator already says "reproduces gross at X but nets Y").
                deflater["net_recompute"] = round(net, 6)
                if V.verdict(trial) == V.REFUTED:
                    head["verdict_inputs"] = trial
                    head["recomputed_value"] = net
                    head["driving_dimension"] = "execution-realism"
                    head["reproduction_or_reverify"] = {
                        "kind": "artifact-recheck", "source": "frictions",
                        "expected": "the friction-deflated recompute of %s differs from the claim beyond "
                                    "budget" % mid}
                    head["verdict"] = V.REFUTED
                    head["headline_confidence"] = V.confidence(trial, V.REFUTED)
                    return
                # the net claim collapses but a gap-gated REFUTED is blocked (a path-dependent metric like
                # calmar, or another refute guard) - the net/live result is still invalid. Fall through to
                # INVALIDATED below; the base deflation locator already carries the gross->net evidence.
            else:
                # the friction-deflated recompute SUBSTANTIATES the net claim (within budget) - the edge
                # survives realistic frictions. No promotion: leave the (reproduced) headline clean.
                return
        # net/live claim we cannot reduce to a refuting gap (uninvestable at size, a non-finite net, or a
        # path-dependent metric's collapse) -> the live result is invalid.
        vi["validity_invalidated"] = True
        vi["oos_claim_asserted"] = True
        head["driving_dimension"] = "execution-realism"
    elif status == "gross":
        for f in auth:  # a gross/paper claim: the number is true gross -> a noted caveat, not invalidating
            f["severity"] = "minor"
            f["unblock"] = f.get("unblock", "") + " (or confirm the headline is explicitly gross/paper)"
        vi["soft_validity_caveat"] = True
    else:  # indeterminate -> CAN'T-CONFIRM: declare net vs gross, don't guess
        vi["validity_unresolved"] = True
        for f in auth:
            f["unblock"] = ("declare whether the headline is net-of-cost or gross - then re-verify; "
                            + f.get("unblock", ""))
    head["verdict_inputs"] = vi
    head["verdict"] = V.verdict(vi)
    head["headline_confidence"] = V.confidence(vi, head["verdict"])
