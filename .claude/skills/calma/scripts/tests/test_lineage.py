"""Tests for lineage.py - W8(d): the three-tier input-lineage provenance attestation, honest by construction.
Pure stdlib. Run: python3 test_lineage.py

Covers the in-toto Statement v1 + InputLineage/v1 shape, the ALWAYS-present proves/does_not_prove honesty
block (the L2 ceiling), the tier-1<->tier-2 transport-integrity chain (tamper detection), the fund-admin-NAV
pairing (matched/mismatch/unavailable under the recompute tolerance), and the provenance projection (the
honest tier-1-only default + the populated case).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import lineage as LIN  # noqa: E402

_n = _fail = 0


def expect(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# --- build_statement: in-toto Statement v1 + the InputLineage predicate + the honesty block ---
src = LIN.source_descriptor("s3://mgr/validation.parquet", retrieved_at="2026-03-31T00:00:00Z",
                            retrieved_by="calma-connector@host", transport_sha256="abc123",
                            etag="etag1", version_id="v1")
stmt = LIN.build_statement("validation.parquet", "abc123", sources=[src])
expect(stmt["_type"] == LIN.STATEMENT_TYPE and stmt["predicateType"] == LIN.PREDICATE_TYPE,
       "statement is in-toto Statement v1 + InputLineage/v1")
expect(stmt["subject"][0]["digest"]["sha256"] == "abc123", "subject carries the tier-1 content hash")
expect(stmt["predicate"]["sources"][0]["uri"].startswith("s3://")
       and stmt["predicate"]["sources"][0]["version_id"] == "v1",
       "tier-2 source manifest present with the immutability handle")
expect(bool(stmt["predicate"]["proves"]) and bool(stmt["predicate"]["does_not_prove"]),
       "the proves + does_not_prove honesty block is present")
expect(any("hashing != truth" in d for d in stmt["predicate"]["does_not_prove"]),
       "does_not_prove states the L2 ceiling (hashing != truth)")

# --- transport_integrity: the tier-1 <-> tier-2 chain (tamper detection) ---
expect(LIN.transport_integrity(stmt) == "verified", "transport_integrity verified when transport == subject hash")
bad = LIN.build_statement("v.parquet", "abc123",
                          sources=[LIN.source_descriptor("s3://x", transport_sha256="DIFFERENT")])
expect(LIN.transport_integrity(bad) == "mismatch", "transport_integrity mismatch flags tamper-in-transit-or-after")
nod = LIN.build_statement("v.parquet", "abc123", sources=[LIN.source_descriptor("s3://x")])
expect(LIN.transport_integrity(nod) == "not-declared", "transport_integrity not-declared with no transport digest")

# --- corroborate_nav: the fund-admin NAV pairing (the only tier touching external reality) ---
# NAV 100 -> 114.7 implies a +14.7% period return; a headline of 0.147 within tolerance -> matched
m = LIN.corroborate_nav(0.147, [100.0, 114.7], tolerance=0.01, as_of="2026-03-31")
expect(m["result"] == "matched" and abs(m["implied_value"] - 0.147) < 1e-9,
       "NAV pairing matched: implied return agrees with the headline within tolerance")
mm = LIN.corroborate_nav(0.50, [100.0, 114.7], tolerance=0.01)
expect(mm["result"] == "mismatch" and mm["gap"] > 0.01, "NAV pairing mismatch outside tolerance")
expect(LIN.corroborate_nav(0.1, [], 0.01)["result"] == "unavailable", "NAV pairing unavailable with no NAV series")
expect(LIN.corroborate_nav(None, [100.0, 110.0], 0.01)["result"] == "unavailable",
       "NAV pairing unavailable with no headline")
expect(LIN.corroborate_nav(0.1, [0.0, 110.0], 0.01)["result"] == "unavailable",
       "NAV pairing unavailable when the start NAV is zero (no implied return)")

# --- provenance_section: the honest tier-1-only default + the populated case ---
default = LIN.provenance_section(None)
expect(default["tier"] == "content-hash-only" and bool(default["does_not_prove"]),
       "no statement -> the honest tier-1-only default")
expect(default["transport_integrity"] == "not-declared" and "no source manifest" in default["note"],
       "the tier-1-only default says exactly that no source manifest was recorded")
stmt2 = LIN.build_statement("v.parquet", "abc123", sources=[src], corroboration=[m])
sec = LIN.provenance_section(stmt2)
expect(sec["tier"] == "source-manifest+corroboration" and sec["nav_corroboration"] == "matched",
       "the populated provenance section carries the source manifest + the NAV corroboration result")
expect(sec["transport_integrity"] == "verified", "the populated section chains transport integrity")
expect(bool(sec["does_not_prove"]) and bool(default["does_not_prove"]),
       "the honesty block is present in BOTH projections (never over-claims)")

print("lineage: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
