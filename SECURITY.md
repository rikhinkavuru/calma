# Security policy

Calma is a verification tool: it re-executes code and signs attestations. Security reports
are treated as release blockers.

## Reporting a vulnerability

Email **rikhinkavuru@gmail.com** with subject `SECURITY: <short title>`. You will get a
human reply, normally within 2 business days. Please include a reproduction if you can.
Coordinated disclosure is respected — tell us your timeline and we will meet it or explain.

Do **not** open a public issue for anything exploitable.

## Scope — what we consider a vulnerability

- A way to make `calma verify` emit a wrong verdict label (CONFIRMED for a refuted claim or
  vice versa), including via cache poisoning, contract manipulation, or output forgery.
- Sandbox escape: code under verification reading secrets, reaching the network, or writing
  outside its target directory on a machine where `calma` reports the sandbox tier as verified.
- Attestation forgery: producing a bundle that passes `calma attest verify` without the
  signing key, or a registry entry that passes `calma registry verify` after tampering.
- The Stop hook executing code in a project where the guardrail should not have fired.

## Known design boundaries (not vulnerabilities)

- On hosts without a verified sandbox, re-execution runs with reduced isolation — and the
  ledger **says so**: every verdict records the isolation tier it actually achieved. Treat
  third-party code accordingly.
- The verdict is only as good as the raw outputs the run produces; a program that fabricates
  its own raw outputs deterministically will reproduce. This is documented in README
  limitations ("reproducible is not the same as right").

## Key compromise

If the lab signing key is compromised: the key is rotated, the new public key is published in
`registry/README.md` via a signed commit, and all entries signed after the compromise window
are re-issued. Pin the key fingerprint, not the file.
