# Trust & data-flow architecture

> The companion to the runnable controls (`make controls` → `soc2_controls.py`): this is the *human-readable*
> half — the data-flow that makes "data never leaves" true, the four controls that make it *attestable*, what
> a security questionnaire can therefore answer trivially, and the limits we never claim away. Code-grounded;
> nothing here is aspirational. (For the execution-platform threat model see `docs/internal/W1-…`.)

## The one load-bearing fact

Calma runs **untrusted customer code OFFLINE (network-off) in a sandbox**, with **raw data that never leaves
the customer environment** (BYOC / on-prem). Only the **verdict + proof + metadata** egress. Everything below
follows from this one fact — and it is a *testable, attestable* property, not a slogan.

## Data flow (where the bytes go, and don't)

```
  manager / customer data ──┐
                            ▼
        ┌──────────────────────────────────────────────┐   network-OFF (two layers:
        │  SANDBOX  (Seatbelt / bubblewrap / microVM)    │   provider flag + host deny);
        │  • the untrusted entrypoint RE-EXECUTES here   │   egress to DNS / 169.254.169.254
        │  • raw inputs + raw outputs stay INSIDE        │   / IPv6 / any IP is DENIED and
        └───────────────┬────────────────────────────────┘   proven (control #2).
                        │  raw output FILES (still local)
                        ▼
        ┌──────────────────────────────────────────────┐
        │  HOST-SIDE RECOMPUTE  (the verifier, offline)  │   recompute the headline number
        │  • reads the raw outputs, recomputes the number│   from the raw outputs; decide the
        │  • verdict() — one deterministic function      │   verdict by code, never a model.
        └───────────────┬────────────────────────────────┘
                        │  ONLY: verdict + recomputed number + hashes + validity results
                        │        + signature  (NO raw data — redaction by construction)
                        ▼
        ┌──────────────────────────────────────────────┐
        │  CONTROL PLANE / REGISTRY / OTel backend       │   metadata only. If this were fully
        │  • a metadata-only whitelist (control #3)      │   compromised, the attacker gets
        │  • the ledger / proof / OTel eval span         │   hashes + verdicts, never raw data.
        └──────────────────────────────────────────────┘
```

In **BYOC / on-prem**, the sandbox + host-recompute run *in the customer's own account/cluster*; Calma's
control plane only ever receives the redacted verdict + proof. No subprocessor sees raw customer data.

## The four controls (run them: `make controls`)

Each is a real, CI-run check (`soc2_controls.py`), emitting a dated JSON evidence pack. A control is
`verified`, honestly `skipped` (no local sandbox to attest — never a false pass), or `FAILED`.

| # | Control | What it proves | Mechanism |
|---|---|---|---|
| 1 | **sandbox-isolation** | a sandbox-per-run under a verified tier denies egress **and** secret-reads | `run_hermetic.doctor` self-test |
| 2 | **egress-blocked** | a sandboxed job cannot reach DNS / an external IP / the `169.254.169.254` cloud-metadata endpoint / IPv6 | `egress_audit.py` probe under the tier |
| 3 | **no-raw-data-retention** | published records are a metadata-only whitelist; the chain fails closed on any non-whitelisted key — raw inputs *structurally* can't be retained | `registry.ALLOWED_FIELDS` + chain guard |
| 4 | **verdict-integrity** | every stored verdict re-derives byte-for-byte from its `verdict_inputs` — a label can't be forged or model-set | `ledger.semantic_validate` re-derivation |

## What this makes the questionnaire answer trivially

The architecture short-circuits the data-handling domains of CAIQ / SIG / SOC 2:

- **Data retention / deletion / residency / cross-border (DSP):** we don't retain raw data — inputs are
  processed in an ephemeral, network-isolated sandbox in the customer's own environment and TTL-deleted; only
  hashes + verdict + validity results persist. Most of DSP collapses to one paragraph; residency/cross-border
  become **non-applicable** (data never crosses the boundary).
- **Encryption in transit (CEK):** raw data never transits to Calma → entire classes of in-transit-exposure
  questions are N/A (we still answer at-rest encryption for *metadata*).
- **Multi-tenancy / isolation:** sandbox-per-run, never reused cross-tenant — control #1.
- **Subprocessors (STA):** in BYOC, **no subprocessor sees raw customer data**.
- **Network / egress:** default-deny in two layers, the named threats probed and proven — control #2.
- **Breach blast-radius:** a full control-plane compromise yields hashes + verdicts, never raw data.

## What it does NOT help with (we do the work)

The architecture is silent on the corporate-hygiene domains, and *creates* one new burden:

- **IAM / change-management / incident-response / BC-DR / HR / vulnerability-management / vendor-management /
  logging** — ordinary engineering + policy work (WorkOS + the SOC 2 program), not relieved by the architecture.
- **The sandbox boundary itself** — running untrusted adversarial code *creates* the question "prove the
  boundary holds." Answered by controls #1/#2 (continuous evidence) + a microVM (not container) choice for the
  hosted tier + an annual bundled pentest.

## The limits we never claim away (structural ceilings)

These ship *in the product* — the IDD/ODD report's fixed L1–L3 limitations and the input-lineage provenance's
`does_not_prove` block — so the deliverable can't over-claim:

- **Reproducible ≠ correct (L1):** we attest a number was *faithfully recomputed from the provided artifacts*;
  we do **not** certify the artifacts/methodology are the semantically right ones.
- **Input-data authenticity (L2):** we content-hash the inputs we were given; we do **not** independently
  source market/return data. Mitigated (not cured) by the input-lineage attestation + the optional fund-admin
  NAV corroboration — never claimed away.
- **Scope is the declared scope (L3):** families the producer did not declare were not authoritatively
  assessed (see `did_not_assess` + any `FLAG_FOR_DECLARATION` inferred-flags).

---

*Verify any of this yourself: `make controls` for the evidence pack, `calma attest verify <bundle> --replay`
to re-derive a verdict offline, `calma registry verify` to re-walk the redacted public log. Nothing here is
computed by a model.*
