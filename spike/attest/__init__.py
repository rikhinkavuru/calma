"""calma.spike.attest — the trust layer (features 3, 12, 16, 18). Everything here operates strictly
DOWNSTREAM of verdict.decide: it serializes, hashes, signs, and logs an ALREADY-decided verdict. It never
imports or influences the decision, so its FCR surface is zero — a signing/logging outage yields an
unsigned-but-well-formed artifact (fail-open on production), while VERIFICATION is fail-closed (an invalid or
unsigned attestation is never shown as CONFIRMED).
"""
