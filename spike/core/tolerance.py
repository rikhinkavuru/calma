"""calma.spike.core.tolerance — numeric closeness with two distinct regimes.

1. **Recompute closeness** (`close`): repo-produced vs our independent recompute. Both are full-precision
   floats, so this is tight (rtol 1e-6, atol 1e-9). A real disagreement here is an INVALIDATED.

2. **Claim closeness** (`claim_close`): the *reported* number (a README/table string like "0.987" or
   "2.3x") vs a full-precision value. The report is almost always **rounded**, so comparing it at 1e-9
   would false-REFUTE every legitimately-rounded claim. We infer the report's precision from how it was
   written and accept anything that rounds to it (half-ULP of the last printed digit) plus a hair.

Getting #2 right is load-bearing: a too-tight claim tolerance manufactures false REFUTEDs; a too-loose one
lets a misreport pass. We bind the tolerance to the *as-written precision* of the claim.
"""
from __future__ import annotations

import math
import re

RTOL = 1e-6
ATOL = 1e-9


def close(a: float, b: float, rtol: float = RTOL, atol: float = ATOL) -> bool:
    """Tight symmetric closeness for two full-precision values."""
    if a is None or b is None:
        return False
    if not (a == a and b == b):  # NaN never matches
        return False
    if a in (float("inf"), float("-inf")) or b in (float("inf"), float("-inf")):
        return a == b
    return abs(a - b) <= atol + rtol * max(abs(a), abs(b))


_NUM_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def parse_claim(raw) -> tuple[float | None, int | None, str]:
    """Parse a claimed value that may be a number or a string like '0.987', '98.7%', '2.3x', '1,234'.
    Returns (value, decimals, kind) where `decimals` is the count of fractional digits as written
    (None if not inferable, e.g. an integer or scientific notation) and `kind` ∈ {plain, percent, factor}.
    The value is normalized: percent -> /100, factor 'x' kept as-is (a speedup ratio)."""
    if isinstance(raw, bool):
        return (1.0 if raw else 0.0, None, "plain")
    if isinstance(raw, (int, float)):
        return (float(raw), None, "plain")
    if not isinstance(raw, str):
        return (None, None, "plain")
    s = raw.strip()
    kind = "plain"
    if s.endswith("%"):
        kind = "percent"
    elif s[-1:].lower() == "x":
        kind = "factor"
    m = _NUM_RE.search(s.replace(",", ""))
    if not m:
        return (None, None, kind)
    tok = m.group(0)
    try:
        val = float(tok)
    except ValueError:
        return (None, None, kind)
    decimals = None
    if "e" not in tok.lower() and "." in tok:
        decimals = len(tok.split(".", 1)[1])
    elif "e" not in tok.lower():
        decimals = 0
    if kind == "percent":
        val = val / 100.0
        decimals = (decimals + 2) if decimals is not None else None  # 98.7% -> 0.987 (2 more places)
    return (val, decimals, kind)


def claim_close(claimed_raw, produced: float, kind_hint: str | None = None) -> tuple[bool, dict]:
    """Is the full-precision `produced` consistent with the as-written `claimed_raw` (rounding-aware)?
    Returns (ok, detail). `detail` carries the parsed claim + the tolerance used, for the report."""
    val, decimals, kind = parse_claim(claimed_raw)
    if val is None or produced is None or not (produced == produced):
        return (False, {"claimed_value": val, "reason": "unparseable claim or non-finite value"})
    if decimals is not None:
        # half-ULP of the last printed digit, + a small epsilon for float noise in the producer
        tol = 0.5 * (10 ** (-decimals)) + 1e-9 + 1e-9 * abs(val)
        ok = abs(val - produced) <= tol
        return (ok, {"claimed_value": val, "decimals": decimals, "kind": kind, "tol": tol,
                     "delta": abs(val - produced)})
    # no inferable precision (integer / scientific): fall back to a modest relative tolerance
    ok = close(val, produced, rtol=5e-4, atol=1e-9)
    return (ok, {"claimed_value": val, "kind": kind, "tol": "rel5e-4", "delta": abs(val - produced)})
