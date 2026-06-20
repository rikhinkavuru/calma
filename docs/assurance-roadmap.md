# The Stage-2 credibility rail (assurance) — a roadmap, not a launch

> **Read this as: don't lead here.** Calma's value is the *technical* act — re-execute the work,
> recompute the number from raw outputs, prove or break the claim, deterministically. That value stands
> on its own today. Formal assurance (ISO-42001 / AIUC-1 / a Schellman-style attestation) is a **Stage-2
> rung the catch-history flywheel earns into**, not a thing to sell before the record exists. A stamp is
> worth exactly the signal behind it; you build the signal first ([D1 credibility flywheel](../registry/README.md)),
> then let the certification *describe* what's already true. This page exists so the path is **lined up**,
> not so it gets walked early.

## What Calma already ships (the cryptographic substrate)

The hard part — a tamper-evident, independently-checkable proof — is already in the engine, with zero
third-party runtime deps:

- **DSSE + in-toto attestation.** Every verdict is a signed in-toto/SLSA-style statement binding the
  verdict to the content-addressed inputs (`attest.py`: `intoto_statement`, the VSA predicate).
- **OpenSSH SSHSIG dual-signing.** A counterparty verifies with **stock `ssh-keygen -Y verify`** — no
  Calma install, no SaaS (`sshsig.py`).
- **RFC-3161 trusted timestamp.** The verdict is anchored in time, offline-verifiable forever (`rfc3161.py`).
- **Hash-chained public registry + optional Sigstore/Rekor.** An append-only, signed catch-history with
  an optional external transparency-log witness ([rekor.md](rekor.md), `registry.py`).
- **Offline replay bundle.** A self-contained bundle re-derives the verdict byte-for-byte on a fresh
  machine — the "reproduce it yourself" deliverable an auditor actually wants (`report.py`).

These are the *evidence primitives* every assurance standard below asks for. Calma produces them as a
by-product of `verify` + `seal`; the [allocator evidence bundle](frameworks.md) (`calma seal --evidence`)
already re-projects them into GIPS-2026 / ODD language.

## The standards, and where Calma plugs in

| Standard | What it certifies | What Calma contributes | Gap to close |
|---|---|---|---|
| **ISO/IEC 42001** (AI management system) | An *organization's* AI governance process is managed + audited | Calma is the **control evidence**: a deterministic, logged, replayable verification gate over AI-produced numbers (an auditable control, with the `auto_history` trail + the catch registry as records) | A documented management system (policies, roles, risk treatment) wrapping the tool — org work, not engine work |
| **AIUC-1** (AI agent assurance, "SOC 2 for AI agents") | An AI agent/product meets a controls catalog (safety, security, reliability) | Calma is a **reliability/correctness control**: it stops a wrong number from being reported, with signed evidence per catch | Map Calma's controls to the AIUC-1 catalog; an assessor engagement |
| **Schellman-style attestation** (independent CPA/assessor report) | An independent assessor attests the controls operate as described | Calma's per-verdict signed bundle + the hash-chained registry are **the assessor's evidence** — already independent + re-checkable | Engage an assessor once a catch-history exists to attest *over* |
| **SOC 2** (trust-services criteria) | Service-org controls (security/availability/processing-integrity) | **Processing integrity** maps directly: Calma *is* a processing-integrity control for computed results | A SaaS/hosted tier with the usual SOC-2 operational scope (the engine is local-first today) |

## The sequence (why it's Stage-2)

1. **Build value (now).** The dev/CI beachhead + the quant/ML producer-side guardrail. The recompute +
   validity layer + the merge-gate are the product; they need no certification to be useful.
2. **Accumulate the record (D1).** Publish-by-default catch-history → a public, trusted, tamper-evident
   catch record grows. *This is the prerequisite* — there is nothing to attest over until it exists.
3. **Line up the rail (this doc).** Keep the evidence primitives standard-shaped (in-toto, SSHSIG,
   RFC-3161, Rekor, the GIPS/ODD evidence bundle) so an assessor engagement is a *mapping* exercise, not
   a re-build. Done — that's why each primitive above is already shipped to a recognized spec.
4. **Let the stamp emerge (later).** When the catch-history carries real signal and a buyer needs the
   formal rung, engage for ISO-42001 / AIUC-1 / a Schellman attestation. The certification then
   *describes* what's already cryptographically true, rather than substituting for it.

## The anti-goal

Do **not** market "ISO-42001 certified" / "SOC 2 for backtests" as the identity before the catch-history
earns it — a certification with no signal behind it is exactly the gameable stamp Calma exists to
replace. The moat is the *neutral, deterministic, re-derivable verdict*; assurance is a wrapper that
makes that legible to a procurement team, not the source of the trust.
