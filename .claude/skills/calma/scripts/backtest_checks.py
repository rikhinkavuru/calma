"""calma.backtest_checks - the backtest-soundness validity family (V0): omitted costs, cherry-picked
window, survivorship universe. A first-class INVALIDATED family on the findings rail, called from
calma._assemble_ledger exactly like leakage/overfitting/realism/contamination.

  - omitted costs (gross-sold-as-net): apply the declared fee/slippage to the per-period returns and
    flag when the claimed return is the GROSS number while net-of-cost is materially lower.
  - cherry-picked window: compare the claimed window against the history actually present in the
    bound artifact; flag when the claim implies more history than the data covers.
  - survivorship universe: flag a declared survivors-only / non-point-in-time universe (returns may
    be upward-biased); detection + explanation, never a silent pass.

Each sub-check owns its OWN validity dimension (`omitted-costs` / `window` / `survivorship`,
registered in ledger.DIMENSIONS) - distinct from realism's `execution-realism`, which owns the
`frictions` surface (backtest owns the older `costs`/`universe`/`window` surface; no double-counting,
see realism_checks). Deterministic arithmetic only - no model.

The verdict follows the claim's own scope (mirrors the leakage/contamination scope-guards): a finding
whose clean property the CLAIM positively asserts (net-of-cost / representative-period / point-in-time)
-> INVALIDATED on that dimension; the SAME finding next to a bare reproduced number -> a CAVEAT. The
contract block is the SIGNAL (it makes the check fire); the claim text is the ASSERTION that gates
INVALIDATED. REFUTED is never manufactured here (deck-vs-code mismatch is the core recompute path;
omitted-cost net-deflation REFUTED is realism's friction-deflated job). Each ABSTAINS (NOT-APPLICABLE)
when its contract block isn't declared - never guesses.

Library: run_checks(contract, base, claim_id="c1", claim_text=None) -> [finding,...];
apply_validity(claims, findings, contract, claim_text, base=None); family_status(contract, findings).
"""
import csv
import os
import re

import verdict as V

_RETURN_TAGS = {"return"}
_BT_DIMS = {"omitted-costs", "window", "survivorship"}

# Claim-scope guards (keyed on the claim TEXT only). INVALIDATED fires ONLY when the claim positively
# asserts the clean property the data violates - mirrors leakage.oos_status / contamination_status.
_NET_RE = re.compile(
    r"net.?of.?(cost|fee|friction|commission|expense)|net of |"
    r"after (cost|fee|expense|friction|commission)|net[\s-]?of[\s-]?cost|"
    # a bare "net <metric>" (e.g. "net return", "net total return", "net CAGR") also asserts net:
    r"\bnet\b[\w\s-]{0,18}\b(return|profit|performance|pnl|p&l|cagr|sharpe|yield)", re.I)
_REPRESENTATIVE_RE = re.compile(
    r"representative|full (history|sample|period|year|track|window)|entire (period|history|sample)|"
    r"robust (across|over|to) (the )?(period|window|sample|time|regime)|across all (period|year)|"
    r"\b(19|20)\d{2}\s*(?:[-]|to|through|–)+\s*(19|20)\d{2}\b|since (inception|(19|20)\d{2})|"
    r"over the (full|entire|whole|complete)", re.I)
_PIT_RE = re.compile(
    r"point.?in.?time|survivorship.?(free|adjusted|bias.?free)|free of survivorship|"
    r"includes? (the )?delist|no survivorship|delisting.?adjusted|with delisted|"
    r"survivorship.?bias.?(free|adjusted)", re.I)


def _claim_asserts(kind, claim_text):
    """Does the CLAIM positively assert the clean property `kind` would invalidate?"""
    t = claim_text or ""
    if kind == "omitted-costs":
        return bool(_NET_RE.search(t))
    if kind == "window":
        return bool(_REPRESENTATIVE_RE.search(t))
    if kind == "survivorship":
        return bool(_PIT_RE.search(t))
    return False
_COST_NAME = re.compile(r"(cost|fee|commission|slippage|expense|carry)", re.I)
_DATE_NAME = re.compile(r"(date|time|timestamp|dt|day|month|period)$", re.I)
# the fraction by which net must fall below the claim before we call it gross-sold-as-net (5%
# of the claimed magnitude) - small rounding/accrual differences never trip it.
_COST_MATERIAL = 0.05


def _read_csv(path):
    if not os.path.isfile(path):
        return {}  # FIFO/socket/device: never open() (would block); treated as unreadable
    try:
        with open(path, newline="") as fh:
            rd = csv.reader(fh)
            header = next(rd, [])
            cols = {h: [] for h in header}
            for row in rd:
                for h, v in zip(header, row):
                    cols[h].append(v)
            return cols
    except (OSError, StopIteration):
        return {}


def _floats(vals):
    out = []
    for v in vals:
        s = (v or "").strip()
        try:
            out.append(float(s))
        except ValueError:
            out.append(float("nan"))
    return out


def _prod_total(rets):
    t = 1.0
    for r in rets:
        if r == r:  # skip NaN
            t *= (1.0 + r)
    return t - 1.0


def _headline_metric(contract):
    metrics = contract.get("metrics") or []
    for m in metrics:
        if m.get("headline") and m.get("claimed_value") is not None:
            return m
    for m in metrics:
        if m.get("claimed_value") is not None:
            return m
    return metrics[0] if metrics else None


def _artifact_path(base, m):
    return os.path.realpath(os.path.join(base, m.get("artifact", "")))


def _return_col(m, cols):
    """The bound return column name, or a name-based guess."""
    b = m.get("binding") or {}
    for tag in _RETURN_TAGS:
        if b.get(tag) and "::" not in str(b[tag]) and b[tag] in cols:
            return b[tag]
    for name in cols:
        if name.lower() in ("return", "daily_return", "ret", "returns", "strat_return", "net_return",
                            "gross_return", "pnl_return"):
            return name
    return None


def _cost_spec(contract, m, cols):
    """How costs are declared. Either a contract `costs` block {fee_bps, turnover_col} OR a
    cost-like per-period column in the bound artifact. Returns (kind, payload) or (None, None)."""
    costs = contract.get("costs") or (m.get("costs") if isinstance(m, dict) else None)
    if isinstance(costs, dict) and costs.get("fee_bps") is not None:
        tcol = costs.get("turnover_col")
        if tcol and tcol in cols:
            return "fee_bps", (float(costs["fee_bps"]), tcol)
        # a flat per-period drag (no turnover column): fee applied every period
        return "fee_bps_flat", (float(costs["fee_bps"]),)
    for name in cols:
        if _COST_NAME.search(name):
            return "cost_col", (name,)
    return None, None


def check_omitted_costs(contract, base, claim_id="c1"):
    m = _headline_metric(contract)
    if not m:
        return None
    cols = _read_csv(_artifact_path(base, m))
    if not cols:
        return None
    rcol = _return_col(m, cols)
    if not rcol:
        return None
    rets = _floats(cols[rcol])
    if not rets:
        return None
    kind, payload = _cost_spec(contract, m, cols)
    if kind is None:
        return None
    gross = _prod_total(rets)
    if kind == "cost_col":
        cost = _floats(cols[payload[0]])
        net_rets = [r - (c if c == c else 0.0) for r, c in zip(rets, cost)]
        how = "per-period cost column %r" % payload[0]
    elif kind == "fee_bps":
        fee, tcol = payload
        turn = _floats(cols[tcol])
        net_rets = [r - (fee / 1e4) * (t if t == t else 0.0) for r, t in zip(rets, turn)]
        how = "declared %.1f bps/turnover (%s)" % (fee, tcol)
    else:  # fee_bps_flat
        fee = payload[0]
        net_rets = [r - (fee / 1e4) for r in rets]
        how = "declared %.1f bps/period flat" % fee
    net = _prod_total(net_rets)
    claimed = m.get("claimed_value")
    if claimed is None:
        return None
    # gross-sold-as-net: the claim tracks GROSS, and net-of-cost is materially below it.
    drag = gross - net
    tracks_gross = abs(claimed - gross) <= max(1e-9, _COST_MATERIAL * max(abs(gross), 1e-9))
    material = drag > _COST_MATERIAL * max(abs(gross), 1e-9) and net < claimed
    if tracks_gross and material:
        return {
            "id": "f-%s-cost" % claim_id, "claim_id": claim_id, "dimension": "omitted-costs",
            "severity": "blocker", "status": "open", "confidence": "deterministic",
            "fixable_by": "author",
            "locator": ("costs omitted (gross sold as net): the claimed return tracks the GROSS series "
                        "(%.4f); applying %s gives net %.4f - a %.4f cost drag"
                        % (gross, how, net, drag)),
            "unblock": ("report the NET-of-cost return (apply the fee/slippage model to the position "
                        "series), or state the headline is gross"),
            "reverify": {"kind": "artifact-recheck", "source": rcol,
                         "expected": "claimed return equals the net-of-cost recompute"},
            "assumed": "the per-period returns are pre-cost (gross) and the declared cost model applies",
            "validity_class": "authoritative", "backtest_kind": "omitted-costs",
        }
    return None


def _coverage(cols):
    """(n_rows, first, last) using a date-like column if present, else (n, None, None)."""
    n = max((len(v) for v in cols.values()), default=0)
    for name in cols:
        if _DATE_NAME.search(name):
            vals = [v.strip() for v in cols[name] if v and v.strip()]
            if vals:
                return n, vals[0], vals[-1], name
    return n, None, None, None


def check_window(contract, base, claim_id="c1"):
    m = _headline_metric(contract)
    if not m:
        return None
    cols = _read_csv(_artifact_path(base, m))
    if not cols:
        return None
    n, first, last, dcol = _coverage(cols)
    # claimed window: explicit contract fields take precedence (deterministic, no parsing guesswork)
    cw = contract.get("claimed_window") or {}
    claimed_periods = contract.get("claimed_periods")
    if isinstance(cw, list) and len(cw) == 2:
        cw = {"start": cw[0], "end": cw[1]}
    cstart, cend = (cw.get("start"), cw.get("end")) if isinstance(cw, dict) else (None, None)
    # catch 1: claimed period count materially exceeds the rows actually present (cherry-picked /
    # padded history). 10% slack absorbs an off-by-a-few-rows boundary.
    if isinstance(claimed_periods, (int, float)) and n and claimed_periods > n * 1.10:
        return {
            "id": "f-%s-window" % claim_id, "claim_id": claim_id, "dimension": "window",
            "severity": "blocker", "status": "open", "confidence": "deterministic",
            "fixable_by": "author",
            "locator": ("window mismatch: the claim states %s periods but the bound artifact covers "
                        "only %d rows%s" % (int(claimed_periods), n,
                                            (" (%s..%s)" % (first, last)) if first else "")),
            "unblock": "compute the metric over the same window you claim, or correct the claimed window",
            "reverify": {"kind": "artifact-recheck", "source": dcol or "rows",
                         "expected": "claimed window matches the data coverage"},
            "assumed": "one row per claimed period in the bound artifact",
            "validity_class": "authoritative", "backtest_kind": "window",
        }
    # catch 2: claimed date window falls (partly) outside the data coverage
    if cstart and cend and first and last and (str(cstart) < str(first) or str(cend) > str(last)):
        return {
            "id": "f-%s-window" % claim_id, "claim_id": claim_id, "dimension": "window",
            "severity": "blocker", "status": "open", "confidence": "deterministic",
            "fixable_by": "author",
            "locator": ("window mismatch: claimed %s..%s but the bound artifact covers only %s..%s"
                        % (cstart, cend, first, last)),
            "unblock": "recompute over the claimed window using data that actually spans it",
            "reverify": {"kind": "artifact-recheck", "source": dcol or "rows",
                         "expected": "claimed window within the data coverage"},
            "assumed": "the date column delimits the realized track record",
            "validity_class": "authoritative", "backtest_kind": "window",
        }
    return None


def check_survivorship(contract, base, claim_id="c1"):
    uni = contract.get("universe")
    flag = False
    if isinstance(uni, str) and uni.lower() in ("survivors-only", "survivorship", "survivors"):
        flag = True
    if isinstance(uni, dict) and (uni.get("survivorship") or uni.get("survivors_only")):
        flag = True
    if contract.get("survivorship") is True:
        flag = True
    if not flag:
        return None
    return {
        "id": "f-%s-surv" % claim_id, "claim_id": claim_id, "dimension": "survivorship",
        "severity": "major", "status": "open", "confidence": "deterministic", "fixable_by": "author",
        "locator": ("universe is survivorship-biased (declared survivors-only / not point-in-time): "
                    "names that delisted or blew up are absent, so the reported return is upward-biased"),
        "unblock": ("rebuild the universe point-in-time (include delisted names at each rebalance) and "
                    "recompute"),
        "reverify": {"kind": "static-reread", "source": "contract",
                     "expected": "a point-in-time universe with delisted names included"},
        "assumed": "the universe declaration reflects how the backtest selected names",
        "validity_class": "authoritative", "backtest_kind": "survivorship",
    }


def run_checks(contract, base, claim_id="c1", claim_text=None):
    """All backtest-soundness catches against one engagement. Returns the findings that fired (possibly
    empty). claim_text is accepted for signature parity with the other four families (the detectors fire
    on the contract+data; the claim text gates the INVALIDATED promotion in apply_validity, not the
    detection). Fail-soft: any check that errors is skipped (a check must never crash a verification)."""
    out = []
    for fn in (check_omitted_costs, check_window, check_survivorship):
        try:
            f = fn(contract, base, claim_id)
        except (OSError, ValueError, KeyError, TypeError):
            f = None
        if f:
            out.append(f)
    return out


def _applicable(contract):
    """The backtest family is applicable iff a backtest surface is declared: a `costs` block, a
    `claimed_window`/`claimed_periods`, or a survivors-only `universe`. ABSTAINS (NOT-APPLICABLE)
    otherwise - never guesses, exactly like the other four families."""
    if contract.get("costs"):
        return True
    if contract.get("claimed_window") or contract.get("claimed_periods") is not None:
        return True
    uni = contract.get("universe")
    if isinstance(uni, str) and uni.lower() in ("survivors-only", "survivorship", "survivors"):
        return True
    if isinstance(uni, dict) and (uni.get("survivorship") or uni.get("survivors_only")):
        return True
    if contract.get("survivorship") is True:
        return True
    return False


def family_status(contract, findings):
    """Honest scope.families.backtest status (mirrors the other four families)."""
    if not _applicable(contract):
        return "not-applicable"
    return "flagged" if any(f.get("dimension") in _BT_DIMS for f in findings) else "checked"


def apply_validity(claims, findings, contract, claim_text, base=None):
    """Promote the headline claim per the backtest findings + the claim scope. Conservative: only a
    REPRODUCED number (CONFIRMED/CAVEATS) is promoted, and only DOWN. A sub-check whose clean property
    the claim asserts (net / representative-window / point-in-time) -> INVALIDATED on that dimension; the
    SAME finding next to a bare reproduced number -> a CAVEAT (soft). REFUTED is never manufactured here.
    `base` is accepted for signature parity (the V0 detectors need no extra artifact read; V1 will)."""
    bt = [f for f in findings if f.get("dimension") in _BT_DIMS]
    if not bt or not claims:
        return
    head = next((c for c in claims if c.get("headline")), claims[0])
    if head.get("verdict") not in (V.CONFIRMED, V.CAVEATS):
        return  # the number didn't reproduce; backtest findings stay additive, no promotion
    vi = head.get("verdict_inputs") or {}
    invalidated = False
    for f in bt:
        if _claim_asserts(f.get("backtest_kind"), claim_text):
            f["severity"] = "blocker"          # an INVALIDATED needs a linked blocker of this dimension
            f["claim_id"] = head["id"]
            vi["validity_invalidated"] = True
            vi["oos_claim_asserted"] = True    # the generic clean-property assertion gate (verdict.py)
            head["driving_dimension"] = f["dimension"]
            invalidated = True
        else:
            vi["soft_validity_caveat"] = True  # bare reproduced number + a backtest finding -> a caveat
    if not invalidated and not vi.get("soft_validity_caveat"):
        return
    head["verdict_inputs"] = vi
    head["verdict"] = V.verdict(vi)
    head["headline_confidence"] = V.confidence(vi, head["verdict"])
