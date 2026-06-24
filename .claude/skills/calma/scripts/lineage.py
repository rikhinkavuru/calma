"""calma.lineage - W8(d): input-lineage / content-hash provenance attestation, honest by construction.

`evidence_json.input_lineage` already proves WHICH BYTES the recompute consumed (the tier-1 content hash from
the signed in-toto materials). It does not say WHERE the bytes came from, or whether an independent party
corroborates the number. W8(d) adds a three-tier lineage statement that is EXPLICIT ABOUT ITS LIMITS — the
operational form of the L2 "input-data authenticity" ceiling (hashing != truth).

In-toto Statement v1 (subject = ResourceDescriptor with `digest`), predicateType `https://calma.dev/InputLineage/v1`:
  - tier 1  content hash         -- WHAT we have (the bytes recomputed), already in input_lineage.
  - tier 2  declared source       -- WHERE the manager says they came from (uri, retrieved_at/by, the
            manifest                  transport digest hashed AT FETCH TIME, provider immutability handles).
  - tier 3  external corroboration-- the ONLY tier that touches external reality: a fund administrator's NAV
            (optional)                (the independent regulated party that strikes NAV), paired against the
                                      manager's headline via a recompute under the same tolerance.

Every statement carries a fixed, always-present `proves` / `does_not_prove` honesty block so the deliverable
can NEVER over-claim provenance. `corroborate_nav` is the partial answer to data-authenticity: we still can't
audit raw market data, but we can pin the manager's number to an administrator's NAV and report match/mismatch.

This module ships the LAYER (schema + honesty + the NAV-pairing math + the evidence projection). The W7 BYOC
connector that POPULATES tier-2 at fetch time, and the attest.py/merkle.py signing of the predicate, are the
wiring that lands with W7 — until then a run carries the tier-1-only honest default (see provenance_section).

Pure stdlib. Library: build_statement(...), source_descriptor(...), corroborate_nav(...),
transport_integrity(...), provenance_section(statement_or_None).
"""
from __future__ import annotations

STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://calma.dev/InputLineage/v1"

# The fixed honesty block — ALWAYS present in every statement and every provenance section. It is the L2
# ceiling made operational; it must never be edited down to over-claim.
PROVES = (
    "the bytes recomputed are identical to the bytes fetched from the named source at fetch time (the "
    "tier-1 content hash is chained to the tier-2 transport digest; a mismatch flags tamper-in-transit-or-after)",
    "non-substitution after the fact, when the provider supplies an immutability handle (e.g. S3 version_id / "
    "object-lock / ETag) — the manager cannot silently swap the file post-attestation",
    "when a tier-3 fund-admin NAV corroboration is present and matched: that the headline is consistent with "
    "an independent administrator's NAV on the matched field/date",
)
DOES_NOT_PROVE = (
    "that the SOURCE ITSELF is authentic — if the manager's bucket contains fabricated returns, the hash "
    "chain faithfully attests fabricated data (hashing != truth; the L2 ceiling)",
    "that the data is the manager's real production data vs. a curated subset — content-hashing a file does "
    "not prove it is the file that drove real P&L",
    "anything about the underlying market data when no fund-admin corroboration is present — then provenance "
    "is 'manager-asserted source + integrity-preserved transport', and the report says exactly that",
)


def source_descriptor(uri, *, retrieved_at=None, retrieved_by=None, transport_sha256=None,
                      etag=None, version_id=None):
    """A tier-2 declared-source entry. `transport_sha256` is the hash AT FETCH TIME, before any local touch —
    chaining it to the tier-1 subject digest is what proves the recomputed bytes are the fetched bytes."""
    d = {"uri": uri}
    if retrieved_at is not None:
        d["retrieved_at"] = retrieved_at
    if retrieved_by is not None:
        d["retrieved_by"] = retrieved_by
    if transport_sha256 is not None:
        d["transport_digest"] = {"sha256": transport_sha256}
    if etag is not None:
        d["etag"] = etag
    if version_id is not None:
        d["version_id"] = version_id
    return d


def corroborate_nav(headline_value, nav_series, tolerance, *, source="fund_admin",
                    as_of=None, matched_field="period_return"):
    """Tier-3 corroboration: recompute the period return implied by an administrator's NAV series and diff it
    against the manager's headline under the recompute tolerance. The strongest provenance signal Calma can
    offer (the number agrees with an independent regulated party) — but framed as corroboration, never as
    "we verified the underlying data." Returns the corroboration dict; result ∈ matched | mismatch | unavailable."""
    base = {"kind": "fund_admin_nav", "source": source, "as_of": as_of, "matched_field": matched_field}
    nav = [v for v in (nav_series or []) if isinstance(v, (int, float)) and v == v]
    if len(nav) < 2 or nav[0] == 0 or headline_value is None or headline_value != headline_value:
        return {**base, "result": "unavailable"}
    implied = nav[-1] / nav[0] - 1.0                     # total period return implied by the NAV endpoints
    gap = abs(implied - float(headline_value))
    return {**base, "result": "matched" if gap <= max(tolerance, 0.0) else "mismatch",
            "implied_value": implied, "headline_value": float(headline_value), "gap": gap}


def build_statement(subject_name, subject_sha256, *, sources=(), corroboration=()):
    """The in-toto Statement v1 carrying the InputLineage/v1 predicate (tier-1 subject + tier-2 sources +
    optional tier-3 corroboration + the always-present honesty block). Unsigned — attest.py adds it to the
    signed bundle (W7 wiring); the statement is content-addressable as-is."""
    return {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": subject_name, "digest": {"sha256": subject_sha256}}],
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "sources": list(sources),
            "corroboration": list(corroboration),
            "proves": list(PROVES),
            "does_not_prove": list(DOES_NOT_PROVE),
        },
    }


def transport_integrity(statement):
    """Tier-1↔tier-2 chain check: does the recomputed subject digest match the source's fetch-time transport
    digest? Returns 'verified' (a source's transport_digest equals the subject), 'mismatch' (a transport
    digest differs — tamper-in-transit-or-after), or 'not-declared' (no transport digest to chain to)."""
    subs = statement.get("subject") or []
    subj_hashes = {(s.get("digest") or {}).get("sha256") for s in subs}
    subj_hashes.discard(None)
    sources = (statement.get("predicate") or {}).get("sources") or []
    transports = [(s.get("transport_digest") or {}).get("sha256") for s in sources]
    transports = [t for t in transports if t]
    if not transports or not subj_hashes:
        return "not-declared"
    return "verified" if any(t in subj_hashes for t in transports) else "mismatch"


def provenance_section(statement):
    """Project a lineage statement into the evidence-bundle `provenance` section. When no statement was
    emitted (no W7 connector in this run), return the HONEST tier-1-only default: the content hashes exist,
    but no source manifest / corroboration was recorded — and say exactly that. The honesty block is always
    present either way, so the deliverable can never over-claim provenance."""
    if not statement:
        return {
            "tier": "content-hash-only",
            "sources": [], "corroboration": [], "transport_integrity": "not-declared",
            "proves": [PROVES[0]],          # only the tier-1 content-identity claim holds with no source manifest
            "does_not_prove": list(DOES_NOT_PROVE),
            "note": "no source manifest was recorded (the BYOC connector that captures tier-2/tier-3 "
                    "provenance was not part of this run); provenance is the content hash only.",
        }
    pred = statement.get("predicate") or {}
    corr = pred.get("corroboration") or []
    nav = next((c for c in corr if c.get("kind") == "fund_admin_nav"), None)
    return {
        "tier": "source-manifest+corroboration" if corr else "source-manifest",
        "subject": statement.get("subject"),
        "sources": pred.get("sources") or [],
        "corroboration": corr,
        "transport_integrity": transport_integrity(statement),
        "nav_corroboration": (nav or {}).get("result", "unavailable"),
        "proves": pred.get("proves") or list(PROVES),
        "does_not_prove": pred.get("does_not_prove") or list(DOES_NOT_PROVE),
    }
