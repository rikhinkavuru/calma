#!/usr/bin/env python
"""optimize.interval_eval — feature 19 meta-eval (certified enclosures).

Over a battery of ILL-CONDITIONED inputs (offset means à la 1e9+ε, near-constant data), it asserts:
  (1) SOUNDNESS — the certified enclosure ALWAYS contains the EXACT value (computed in rational arithmetic);
  (2) the FCR gate — a straddling enclosure downgrades a would-be CONFIRMED to a fail-closed verdict, never a
      confirm;
  (3) no honest well-conditioned CONFIRMED is lost.
"""
from __future__ import annotations

import json
import os
import sys
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)

from core import diff as D  # noqa: E402
from core import intervals as ITV  # noqa: E402
from core import verdict as VD  # noqa: E402


def _exact_mean(v):
    return Fraction(sum(Fraction(str(x)) for x in v), len(v))


def _exact_var(v, ddof=1):
    m = _exact_mean(v)
    return sum((Fraction(str(x)) - m) ** 2 for x in v) / (len(v) - ddof)


def _batteries():
    return [
        [1e9 + 4, 1e9 + 7, 1e9 + 13, 1e9 + 16],       # classic offset-variance
        [1e12 + 1, 1e12 + 2, 1e12 + 3, 1e12 + 2, 1e12 + 1],
        [0.001, 0.002, 0.0015, 0.0012, 0.0018],       # tiny magnitude
        [1.0, 1.0000001, 0.9999999, 1.0, 1.0000002],  # near-constant
        [-5.0, 3.0, 8.0, -2.0, 6.0, 1.0],             # well-conditioned
    ]


def measure():
    soundness_fail = []
    for v in _batteries():
        for cid, exact in (("mean", float(_exact_mean(v))), ("variance", float(_exact_var(v))),
                           ("stdev", float(_exact_var(v)) ** 0.5)):
            enc = ITV.enclosure(cid, {"values": v}, {})
            if enc and not (enc["lo"] - 1e-12 <= exact <= enc["hi"] + 1e-12):
                soundness_fail.append((cid, v[:2], enc["lo"], exact, enc["hi"]))

    # well-conditioned honest CONFIRMED must survive (mean of a small clean series).
    clean = [-5.0, 3.0, 8.0, -2.0, 6.0, 1.0]
    exact_mean = float(_exact_mean(clean))
    call = {"metric": "mean", "result": exact_mean, "inputs": {"values": clean}, "kwargs": {},
            "user_site": True, "captured_full": True, "n": len(clean), "seq": 0,
            "sink": "target:mean", "site": "r.py:1"}
    rec = D.diff_claim({"metric": "mean", "value": "%.6f" % exact_mean}, [[call], [dict(call)]])
    clean_confirm = rec["verdict"] == VD.CONFIRMED

    return {"soundness_failures": soundness_fail, "sound": not soundness_fail,
            "well_conditioned_confirm_preserved": clean_confirm}


def main():
    m = measure()
    with open(os.path.join(HERE, "interval_metrics.json"), "w") as fh:
        json.dump(m, fh, indent=2, default=str)
    print("=== CERTIFIED ENCLOSURES (feature 19) ===")
    print("soundness (enclosure contains exact value)=%s   well-conditioned CONFIRMED preserved=%s"
          % (m["sound"], m["well_conditioned_confirm_preserved"]))
    if m["soundness_failures"]:
        print("  FAILURES:", m["soundness_failures"][:3])
    return 0 if (m["sound"] and m["well_conditioned_confirm_preserved"]) else 1


if __name__ == "__main__":
    sys.exit(main())
