"""calma.spike.core.anomaly — cross-run anomaly detection (feature 11).

Given a value and a history of INDEPENDENTLY-VERIFIED values for the same (dataset, metric), flag the value as
a cross-run outlier via the robust modified z-score (median + MAD, resistant to the very outliers we hunt).

FCR posture — this may only ADVISE or DOWNGRADE, never raise a verdict, and it must not AUTO-REFUTE: a genuine
SOTA is also an outlier, so an outlier alone is not evidence the number is wrong (only that it is unusual). It
is inert below `min_n` and when MAD is degenerate (fail-open on flagging, which is safe because flagging is
advisory). Pure stdlib.
"""
from __future__ import annotations

import statistics

_MAD_TO_SD = 0.6744897501960817     # 0.6745: scales MAD to a normal-consistent standard deviation


def robust_z(value, ref_values, min_n: int = 15, thresh: float = 3.5) -> dict:
    """Modified z-score of `value` against `ref_values`. Returns {z, is_outlier, n, degenerate, median, mad}.
    Degenerate (n<min_n or MAD==0) → no flag (is_outlier=False), never a crash."""
    vals = [float(v) for v in (ref_values or []) if isinstance(v, (int, float)) and v == v]
    n = len(vals)
    if value is None or n < min_n:
        return {"z": None, "is_outlier": False, "n": n, "degenerate": True,
                "reason": "insufficient history (n=%d < %d)" % (n, min_n)}
    med = statistics.median(vals)
    mad = statistics.median([abs(v - med) for v in vals])
    if mad == 0:
        # fall back to a std-based check only if there IS spread; otherwise no basis to flag.
        sd = statistics.pstdev(vals)
        if sd == 0:
            return {"z": None, "is_outlier": False, "n": n, "degenerate": True,
                    "reason": "reference has no spread (MAD=0, SD=0)", "median": med, "mad": 0.0}
        z = (float(value) - med) / sd
    else:
        z = _MAD_TO_SD * (float(value) - med) / mad
    return {"z": round(z, 4), "is_outlier": abs(z) > thresh, "n": n, "degenerate": False,
            "median": med, "mad": mad, "thresh": thresh}
