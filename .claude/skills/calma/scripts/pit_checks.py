"""calma.pit_checks - V1: point-in-time survivorship + look-ahead/availability, the SOTA programmatic
deepening of V0's declared-flag heuristics (backtest_checks). On the findings rail, called from
calma._assemble_ledger like the other validity families. Pure stdlib, deterministic - no model.

Two rigorous checks, each ABSTAINING unless its contract block is declared (never guesses):

  (1) POINT-IN-TIME SURVIVORSHIP (dimension "survivorship", deepens V0):
      a `universe` block with a point-in-time MEMBERSHIP file (date,ticker,delisted[,delist_return]).
      - explicit: `universe.point_in_time == false` (a single current snapshot applied retroactively).
      - programmatic: attrition = n_delisted / n_total over the membership window. A real multi-year
        equity universe sheds names (bankruptcy/M&A ~ several %/yr); attrition ~ 0 over a multi-year
        window is implausible -> survivorship. Terminal DELISTING returns must be present (bankruptcies
        ~ -100%); their absence is itself the bias. When delist returns ARE present, bound the bias by
        the survivorship-adjusted gap (mean active return vs mean incl. delisted terminal returns).

  (2) LOOK-AHEAD / AVAILABILITY (dimension "look-ahead", new):
      an `availability` block. Two sub-checks:
      - availability_date <= effective_date: for each declared column, the datum that fed a signal at t
        must have been KNOWABLE by t (catches restated fundamentals keyed on fiscal-period-end not
        filing date, future-timestamp joins). A declared (effective_date, availability_date) pair with
        availability_date > effective_date is a look-ahead.
      - the +1-PERIOD-LAG ROBUSTNESS PROBE: with a declared signal+return binding, compare same-bar
        performance perf0 = sum(S[t]*R[t]) against the legally-laggable perf1 = sum(S[t-1]*R[t]). If the
        edge is MEANINGFUL same-bar but COLLAPSES one period back, the signal was using same-bar
        (not-yet-knowable) information -> look-ahead was load-bearing.

The verdict follows the claim's scope (mirrors leakage/contamination): a survivorship violation under a
point-in-time / survivorship-free claim -> INVALIDATED; a load-bearing look-ahead under a forward /
out-of-sample / tradeable claim -> INVALIDATED; the same finding next to a bare reproduced number -> a
CAVEAT. REFUTED is never manufactured here.

Library: run_checks(contract, base, claim_id, claim_text) -> [finding,...];
apply_validity(claims, findings, contract, claim_text, base=None); family_status(contract, findings).
"""
import csv
import os
import re

import verdict as V

_PIT_DIMS = {"survivorship", "look-ahead"}

# attrition below this over a multi-year membership window is implausibly low -> survivorship bias.
_MIN_ATTRITION = 0.02
# the +1-lag probe: the same-bar edge must be at least this fraction of the gross |return| to be
# "meaningful" (else there is no edge to collapse), and perf1 below COLLAPSE_FRAC*perf0 is a collapse.
_LOOKAHEAD_MIN_EDGE = 0.20
_COLLAPSE_FRAC = 0.25
_MAX_ROWS = 2_000_000  # bound memory on a hostile membership/returns file

# claim-scope guards (keyed on the claim TEXT). Reuse the point-in-time language for survivorship; the
# look-ahead guard is the forward/tradeable/out-of-sample assertion the probe would invalidate.
_PIT_RE = re.compile(
    r"point.?in.?time|survivorship.?(free|adjusted|bias.?free)|free of survivorship|"
    r"includes? (the )?delist|no survivorship|delisting.?adjusted|with delisted|"
    r"survivorship.?bias.?(free|adjusted)", re.I)
_FORWARD_RE = re.compile(
    r"out.?of.?sample|\boos\b|forward|trade?able|tradable|live|real.?time|implementable|investable|"
    r"no look.?ahead|point.?in.?time|as.?of|ex.?ante|walk.?forward|deployable", re.I)


def _safe_join(base, rel):
    """Resolve rel under base; refuse escapes (abs/.. /symlink-out). Mirrors recompute._safe_join."""
    full = os.path.realpath(os.path.join(base, rel))
    rb = os.path.realpath(base)
    if full != rb and not full.startswith(rb + os.sep):
        raise ValueError("path escapes the contract base: %r" % rel)
    return full


def _read_csv(path):
    if not os.path.isfile(path):
        return [], []  # FIFO/socket/device: never open() (would block); treated as unreadable
    try:
        with open(path, newline="", encoding="utf-8", errors="replace") as fh:
            rd = csv.reader(fh)
            header = next(rd, [])
            rows = []
            for r in rd:
                rows.append(r)
                if len(rows) >= _MAX_ROWS:
                    break
        return header, rows
    except (OSError, StopIteration, csv.Error):
        return [], []


def _col(header, rows, name):
    if name not in header:
        return None
    i = header.index(name)
    return [(r[i] if i < len(r) else "") for r in rows]


def _floats(vals):
    out = []
    for v in vals or []:
        try:
            out.append(float((v or "").strip()))
        except (ValueError, AttributeError):
            out.append(float("nan"))
    return out


def _truthy(s):
    return str(s).strip().lower() in ("1", "true", "yes", "y", "delisted", "dead", "t")


# ---- (1) point-in-time survivorship -----------------------------------------

def _universe(contract):
    u = contract.get("universe")
    return u if isinstance(u, dict) else None


def check_point_in_time(contract, base, claim_id="c1"):
    """Programmatic survivorship: an explicit non-PIT declaration, or a membership file whose attrition
    is implausibly low / carries no delisting returns. Authoritative."""
    u = _universe(contract)
    if not u:
        return None
    explicit_violation = (u.get("point_in_time") is False) or (u.get("snapshot") in ("current", "latest"))
    membership = u.get("membership")
    attrition = n_total = n_delisted = None
    gap = None
    if membership:
        try:
            header, rows = _read_csv(_safe_join(base, membership))
        except ValueError:
            header, rows = [], []
        if header and rows:
            tcol = u.get("ticker_col") or next((h for h in header if h.lower() in
                                                ("ticker", "symbol", "name", "id", "permno")), None)
            dcol = u.get("delisted_col") or next((h for h in header if h.lower() in
                                                  ("delisted", "dead", "status", "is_delisted")), None)
            rcol = u.get("delist_return_col") or next((h for h in header if "return" in h.lower()), None)
            if tcol:
                ti = header.index(tcol)
                tickers = {}
                for r in rows:
                    if ti >= len(r):
                        continue
                    name = r[ti]
                    di = header.index(dcol) if dcol else None
                    dead = _truthy(r[di]) if (di is not None and di < len(r)) else False
                    tickers[name] = tickers.get(name, False) or dead
                n_total = len(tickers)
                n_delisted = sum(1 for v in tickers.values() if v)
                if n_total:
                    attrition = n_delisted / n_total
                # bound the bias when delisting terminal returns are present
                if rcol:
                    rets = _floats(_col(header, rows, rcol))
                    fin = [x for x in rets if x == x]
                    if fin:
                        allmean = sum(fin) / len(fin)
                        live = [x for x in fin if x > -0.5]  # non-terminal (delisting ~ -100%)
                        if live:
                            gap = (sum(live) / len(live)) - allmean  # survivors-only overstates by this
    low_attrition = attrition is not None and attrition < _MIN_ATTRITION
    no_delist_returns = (membership and n_total and n_delisted == 0)
    if not (explicit_violation or low_attrition or no_delist_returns):
        return None
    if explicit_violation:
        why = ("the universe is a single current snapshot applied retroactively (point_in_time=false) - "
               "names that delisted are absent at every historical date")
    else:
        why = ("the point-in-time membership shows implausibly low attrition: %d of %d names ever "
               "delisted (%.1f%%) over a multi-year window - a real equity universe sheds several %%/yr"
               % (n_delisted, n_total, 100.0 * (attrition or 0.0)))
        if gap is not None:
            why += ("; including delisted terminal returns lowers the mean per-name return by %.4f "
                    "(the survivorship-adjusted gap)" % gap)
    return {
        "id": "f-%s-pit-surv" % claim_id, "claim_id": claim_id, "dimension": "survivorship",
        "severity": "major", "status": "open", "confidence": "deterministic", "fixable_by": "author",
        "locator": "survivorship (point-in-time): " + why,
        "unblock": ("rebuild the universe point-in-time (include each name's membership window and its "
                    "delisting return), then recompute over the survivorship-free universe"),
        "reverify": {"kind": "artifact-recheck", "source": membership or "universe",
                     "expected": "a point-in-time universe whose attrition + delisting returns are present"},
        "validity_class": "authoritative", "pit_kind": "survivorship",
    }


# ---- (2) look-ahead / availability ------------------------------------------

def _availability(contract):
    a = contract.get("availability")
    return a if isinstance(a, dict) else None


def _availability_violation(av):
    """Declared (effective_date, availability_date) columns/pairs where availability_date > effective_date
    (the datum wasn't knowable when it fed the signal). Supports a list of {column, effective, available}
    or a single pair. Returns a describing string or None."""
    pairs = av.get("columns") if isinstance(av.get("columns"), list) else None
    items = pairs if pairs else ([av] if (av.get("effective_date") and av.get("available_date")) else [])
    for it in items:
        eff, avail = it.get("effective_date"), it.get("available_date")
        if eff and avail and str(avail) > str(eff):
            return ("column %r became available %s but fed a signal effective %s (availability_date > "
                    "effective_date - the value was not knowable in time)"
                    % (it.get("column", "?"), avail, eff))
    return None


def _lag_probe(contract, base, av):
    """The +1-period-lag robustness probe. Returns (perf0, perf1, gross) over the aligned range, or None
    when a signal+return binding/data isn't available."""
    scol, rcol = av.get("signal"), av.get("return")
    art = av.get("artifact")
    if not art:
        mets = contract.get("metrics") or []
        head = next((m for m in mets if m.get("headline")), mets[0] if mets else None)
        art = head.get("artifact") if head else None
    if not (scol and rcol and art):
        return None
    try:
        header, rows = _read_csv(_safe_join(base, art))
    except ValueError:
        return None
    S, R = _floats(_col(header, rows, scol)), _floats(_col(header, rows, rcol))
    if not S or not R or len(S) != len(R) or len(S) < 4:
        return None
    n = len(S)
    perf0 = perf1 = gross = 0.0
    for t in range(1, n):  # same aligned range for both, so they are comparable
        if R[t] != R[t] or S[t] != S[t] or S[t - 1] != S[t - 1]:
            continue
        perf0 += S[t] * R[t]
        perf1 += S[t - 1] * R[t]
        gross += abs(R[t])
    return perf0, perf1, gross


def check_lookahead(contract, base, claim_id="c1"):
    """Look-ahead: a declared availability_date violation, or the +1-lag probe collapsing a meaningful
    same-bar edge. Authoritative."""
    av = _availability(contract)
    if not av:
        return None
    viol = _availability_violation(av)
    if viol:
        return _lookahead_finding(claim_id, "availability: " + viol,
                                  "key every input on its availability_date (filing/publication), not "
                                  "the event/fiscal-period date; recompute with no future information")
    probe = _lag_probe(contract, base, av)
    if probe is None:
        return None
    perf0, perf1, gross = probe
    meaningful = gross > 0 and perf0 > 0 and perf0 >= _LOOKAHEAD_MIN_EDGE * gross
    collapses = perf1 <= 0 or perf1 < _COLLAPSE_FRAC * perf0
    if not (meaningful and collapses):
        return None
    return _lookahead_finding(
        claim_id,
        ("the +1-period-lag probe collapses the edge: same-bar PnL=%.4f (%.0f%% of gross |return|) "
         "falls to %.4f when the signal is lagged one period - the signal used same-bar, not-yet-"
         "knowable information (look-ahead was load-bearing)"
         % (perf0, 100.0 * perf0 / gross, perf1)),
        "execute on the NEXT bar after the signal is knowable (lag the signal one period), then recompute")


def _lookahead_finding(claim_id, locator, unblock):
    return {
        "id": "f-%s-lookahead" % claim_id, "claim_id": claim_id, "dimension": "look-ahead",
        "severity": "major", "status": "open", "confidence": "deterministic", "fixable_by": "author",
        "locator": "look-ahead: " + locator, "unblock": unblock,
        "reverify": {"kind": "requires-reexecution", "source": "availability",
                     "expected": "no input feeds a signal before its availability_date; the +1-lag edge holds"},
        "validity_class": "authoritative", "pit_kind": "look-ahead",
    }


# ---- run / status / promotion -----------------------------------------------

def run_checks(contract, base, claim_id="c1", claim_text=None):
    """Point-in-time survivorship + look-ahead findings. SILENT unless a `universe` (membership/PIT) or
    `availability` block is declared. Fail-soft: any check that errors is skipped."""
    out = []
    for fn in (check_point_in_time, check_lookahead):
        try:
            f = fn(contract, base, claim_id)
        except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
            f = None
        if f:
            out.append(f)
    return out


def _applicable(contract):
    u = _universe(contract)
    if u and (u.get("membership") or u.get("point_in_time") is False or u.get("snapshot")):
        return True
    return bool(_availability(contract))


def family_status(contract, findings):
    """Honest scope.families.point-in-time status."""
    if not _applicable(contract):
        return "not-applicable"
    return "flagged" if any(f.get("dimension") in _PIT_DIMS and f.get("pit_kind") for f in findings) \
        else "checked"


def _claim_asserts(kind, claim_text):
    t = claim_text or ""
    if kind == "survivorship":
        return bool(_PIT_RE.search(t))
    if kind == "look-ahead":
        return bool(_FORWARD_RE.search(t))
    return False


def apply_validity(claims, findings, contract, claim_text, base=None):
    """Promote the headline claim per the point-in-time / look-ahead findings + the claim scope.
    Conservative: only a REPRODUCED number (CONFIRMED/CAVEATS) is promoted, and only DOWN. A finding
    whose clean property the claim asserts (point-in-time / forward) -> INVALIDATED on its dimension;
    the same finding next to a bare reproduced number -> a CAVEAT. REFUTED is never manufactured."""
    pit = [f for f in findings if f.get("dimension") in _PIT_DIMS and f.get("pit_kind")]
    if not pit or not claims:
        return
    head = next((c for c in claims if c.get("headline")), claims[0])
    if head.get("verdict") not in (V.CONFIRMED, V.CAVEATS):
        return
    vi = head.get("verdict_inputs") or {}
    invalidated = False
    for f in pit:
        if _claim_asserts(f.get("pit_kind"), claim_text):
            f["severity"] = "blocker"          # INVALIDATED needs a linked blocker of this dimension
            f["claim_id"] = head["id"]
            vi["validity_invalidated"] = True
            vi["oos_claim_asserted"] = True
            head["driving_dimension"] = f["dimension"]
            invalidated = True
        else:
            vi["soft_validity_caveat"] = True
    if not invalidated and not vi.get("soft_validity_caveat"):
        return
    head["verdict_inputs"] = vi
    head["verdict"] = V.verdict(vi)
    head["headline_confidence"] = V.confidence(vi, head["verdict"])
