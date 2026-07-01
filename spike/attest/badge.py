"""calma.spike.attest.badge — reproducibility badges + registry projection (feature 13).

A badge is a STRICT function of the verdict taxonomy: green/"CONFIRMED" is emitted ONLY for verdict ==
CONFIRMED; REFUTED/INVALIDATED render red; every fail-closed verdict (REPRODUCED-ONLY / NON-DETERMINISTIC /
INCONCLUSIVE / DISCOVERED) renders amber/grey with an honest label. So the fail-closed taxonomy maps 1:1 onto
badge states — a fail-closed verdict CANNOT surface as a green "verified." Registry entries pin
{repo, commit_sha, claim_id, verdict, signature}: a badge whose repo moved past the pinned SHA renders
"stale — re-verify" rather than green. This DISTRIBUTES FCR=0 without ever creating a new confirm path.
"""
from __future__ import annotations

from core import verdict as VD

# verdict -> (badge message, shields color). ONLY the hard CONFIRMED is green; CONFIRMED-STOCHASTIC is a
# distinct affirmative (yellowgreen, NOT green — is_green stays false for it) so the "green == hard confirm"
# invariant holds while a stochastically-confirmed claim still gets an honest, non-grey label.
_BADGE = {
    VD.CONFIRMED: ("CONFIRMED", "brightgreen"),
    VD.CONFIRMED_STOCHASTIC: ("confirmed (stochastic)", "yellowgreen"),
    VD.REFUTED: ("REFUTED", "red"),
    VD.INVALIDATED: ("INVALIDATED", "red"),
    VD.REPRODUCED_ONLY: ("reproduced-only", "yellow"),
    VD.NON_DETERMINISTIC: ("non-deterministic", "yellow"),
    VD.INCONCLUSIVE: ("inconclusive", "lightgrey"),
    "DISCOVERED": ("discovered", "lightgrey"),
}
_STALE = ("stale — re-verify", "lightgrey")


def badge(verdict: str, *, label: str = "calma", stale: bool = False) -> dict:
    """The shields.io endpoint JSON for a verdict. `stale=True` (repo moved past the pinned SHA) overrides to
    a non-green 'stale' badge — never green."""
    msg, color = _STALE if stale else _BADGE.get(verdict, ("unknown", "lightgrey"))
    return {"schemaVersion": 1, "label": label, "message": msg, "color": color}


def is_green(b: dict) -> bool:
    return b.get("color") in ("brightgreen", "green", "success")


def registry_entry(repo: str, commit_sha: str, claim_id: str, verdict: str, *, metric=None,
                   delta=None, signature=None, ts=None) -> dict:
    """A pinned, auditable registry record. The signature makes it un-forgeable; the SHA pin makes it
    un-reusable on a moved repo."""
    return {"repo": repo, "commit_sha": commit_sha, "claim_id": claim_id, "metric": metric,
            "verdict": verdict, "delta": delta, "signature": signature, "ts": ts}


def is_stale(entry: dict, current_sha: str) -> bool:
    """True when the repo has moved past the pinned commit — the badge must then render 'stale', not green."""
    pinned = (entry or {}).get("commit_sha")
    return bool(pinned and current_sha and pinned != current_sha)


def badge_for_entry(entry: dict, current_sha: str | None = None, *, label: str = "calma") -> dict:
    stale = is_stale(entry, current_sha) if current_sha else False
    return badge(entry.get("verdict") or "DISCOVERED", label=label, stale=stale)
