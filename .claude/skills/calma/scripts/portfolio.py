"""calma.portfolio - W7: the IC portfolio view. Aggregate the REDACTED verdicts across an allocator's mandates
into the at-a-glance summary + the family-scope heatmap the control-plane dashboard renders.

The IC sees, in one line, sorted so the action-required mandates lead:
    "3 CONFIRMED clean, 1 FLAG_FOR_DECLARATION (undeclared train/test structure), 1 CAN'T-CONFIRM (data over
     the streaming cap)"
and a managers × families heatmap (who declared which validity blocks; where the inferred-flags sit).

PURE LOGIC over Verification records (metadata only — repo_verdict, family_scope, inferred_flags; never raw
data). No creds. Reuses the engine's catch-loudness rank (CANONICAL §3) + the display names; ties the
FLAG_FOR_DECLARATION verdict this session shipped into the multi-mandate IC view.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import report as REP  # noqa: E402 - display names
import verdict as V  # noqa: E402

# catch-loudness rank (CANONICAL §3): REFUTED >= INVALIDATED > FLAG > MIXED > CAVEATS > CONFIRMED;
# CAN'T-CONFIRM is non-clean-but-neutral (an unverified mandate the IC must still chase, ranked above CAVEAT).
_RANK = {"REFUTED": 6, V.INVALIDATED: 5, V.FLAG_FOR_DECLARATION: 4, "MIXED": 3, V.INCONCLUSIVE: 2,
         V.CAVEATS: 1, V.CONFIRMED: 0}
# the order verdicts are summarised in the IC one-liner (loudest first, clean last).
_SUMMARY_ORDER = ("REFUTED", V.INVALIDATED, V.FLAG_FOR_DECLARATION, "MIXED", V.INCONCLUSIVE)
_HEATMAP_MARK = {"checked": "✅", "flagged": "⚠️", "flag-for-declaration": "\U0001f6a9", "not-assessed": "⛔"}


def _verdict_of(v):
    return v.get("repo_verdict") or v.get("verdict")


def summarize(verifications):
    """`verifications`: a list of redacted Verification dicts (manager, metric, repo_verdict, family_scope,
    inferred_flags, ...). Returns the IC portfolio summary: verdict counts, the one-line headline, the
    action-required mandates (non-clean, loudest first), and whether the whole book is clean."""
    counts = {}
    for v in verifications:
        vd = _verdict_of(v)
        counts[vd] = counts.get(vd, 0) + 1
    clean = sum(counts.get(k, 0) for k in (V.CONFIRMED, V.CAVEATS))
    action = sorted((v for v in verifications if not V.is_clean(_verdict_of(v))),
                    key=lambda v: -_RANK.get(_verdict_of(v), 2))
    parts = []
    if clean:
        parts.append("%d CONFIRMED clean" % clean)
    for k in _SUMMARY_ORDER:
        n = counts.get(k, 0)
        if n:
            parts.append("%d %s" % (n, REP.display(k)))
    return {
        "n": len(verifications),
        "counts": counts,
        "clean": clean,
        "headline": "; ".join(parts) if parts else "no mandates",
        "all_clean": not action,
        "action_required": [{
            "manager": v.get("manager"),
            "metric": v.get("metric"),
            "verdict": _verdict_of(v),
            "display": REP.display(_verdict_of(v)),
            "inferred_flags": v.get("inferred_flags") or [],
        } for v in action],
    }


def family_heatmap(verifications):
    """managers × families -> a status mark (✅ checked / ⚠️ flagged / 🚩 flag-for-declaration / ⛔ not-assessed).
    A pure projection of each verification's `family_scope` (the engine families dict) + `inferred_flags` (the
    FLAG findings, which override their family to flag-for-declaration). Returns
    {families: [...sorted union...], rows: [{manager, cells: {family: mark}}]}."""
    fams = set()
    rows = []
    for v in verifications:
        scope = v.get("family_scope") or {}
        flag_dims = {f.get("dimension") for f in (v.get("inferred_flags") or []) if f.get("dimension")}
        cells = {}
        for fam, status in scope.items():
            if fam == "inferred-flags":
                continue
            s = str(status)
            mark = ("flag-for-declaration" if fam in flag_dims else
                    "checked" if s.startswith("checked") else
                    "flagged" if s == "flagged" else "not-assessed")
            cells[fam] = _HEATMAP_MARK[mark]
            fams.add(fam)
        for fam in flag_dims:                            # an inferred flag on an otherwise-unlisted dimension
            if fam not in cells:
                cells[fam] = _HEATMAP_MARK["flag-for-declaration"]
                fams.add(fam)
        rows.append({"manager": v.get("manager"), "cells": cells})
    return {"families": sorted(fams), "rows": rows, "legend": dict(_HEATMAP_MARK)}
