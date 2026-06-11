# Changelog

All notable changes to the calma skill/CLI. Dates are UTC.

## 0.6.1 — 2026-06-11

- Site: the request-verification form now actually delivers (with an honest failure
  fallback and a visible direct email); contact, founder, and entity surface on every page;
  mobile navigation; favicon, Open Graph image, sitemap, robots; registry page shows
  human-readable numbers, a self-test badge on the genesis entry, and links to verify the
  chain yourself.
- CLI: a committed `verify.yaml` can no longer substitute a different claim than the one you
  typed — metric conflicts degrade to CAN'T-CONFIRM with a fix line; `calma demo` gives a
  zero-to-verdict path; `calma recipes` lists the library; bare `calma` prints guidance;
  verdict vocabulary is consistent (CAN'T-CONFIRM everywhere a human reads).
- Engine hardening: the verdict cache is validated against the ledger it points at (a stale
  run-dir can never serve the wrong verdict); the sandbox denies writes to the verifier's own
  state directory and passes a whitelisted environment; `--trust third-party` refuses to
  execute counterparty code without a verified sandbox; `--timeout` is configurable; the
  Stop hook checks the sandbox tier before auto-executing anything.
- Attestation identity migrated to GitHub-rooted URIs we control
  (`github.com/rikhinkavuru/calma/verdict/v1`); bundles signed under the legacy URI remain
  valid forever.
- Docs: SECURITY.md, this changelog, copy-pasteable stock-OpenSSH verification recipe in
  registry/README.md, accurate quickstart.

## 0.6.0 — 2026-06-11

- Zero-touch guardrail: plugin-registered Stop hook + precision-first claim sniffer.
  Checkable numeric claims in an agent's final message are auto-verified before the turn
  ends; the stop is blocked only on definitive REFUTED/MIXED. Fail-open everywhere,
  never-nag cache, kill switches. Survived a 270-case adversarial round; the contract is
  "a missed claim is free, a false fire is a release blocker."

## 0.5.0 — 2026-06-10

- Attestation chain to the full 3-layer spec: DSSE/in-toto bundle with a SLSA-VSA-shaped
  predicate, double-signed (raw DSSE + OpenSSH SSHSIG verifiable with stock `ssh-keygen`),
  RFC 3161 trusted timestamps, optional Sigstore/Rekor countersignature.
- Catch history: `calma publish` appends redacted, signed entries to a hash-chained public
  registry; `calma registry verify` audits it offline; `/registry` renders it.
- Recipe compiler: typed JSON expression DSL + deterministic CEGIS admission gate
  (differential vs reference implementation, metamorphic suite, degeneracy, bit-stability).
  First two compiled recipes admitted — the library reaches 120.

## 0.4.x and earlier — 2026-06

- 118 reviewed recipes across 11 packs, each validated against its published reference
  implementation via byte-reproducible reference vectors.
- Deterministic recompute kernels (no numpy, no platform libm), calibrated tolerance
  budgets, honesty guards (REFUTED structurally blocked on ambiguity), auto-drafted graded
  contracts, sandbox self-proof (plants a fake secret and tries to steal it before any run),
  content-hash verification cache, GitHub Action, cross-language black-box support
  (Python, R, Julia, C++, Rust).
