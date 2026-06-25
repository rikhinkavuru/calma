# Calma proof-signing key — custody, rotation & compromise runbook
*(D6-03. The ed25519 key that signs every control-plane proof is the trust root: a compromise makes every
past CONFIRMED repudiable and every future one forgeable. Treat it like a CA key.)*

## What the key is
- ed25519 signing key. Private seed = the `CALMA_SIGNING_KEY` env secret on the `calma-api` Vercel project
  (base64 of the 32-byte seed). Public key = committed at `control_plane/signing_pubkey.json` and served at
  `GET /v1/signing-key`. Current keyid: `6828f0ad98306a21`.
- Used by `control_plane/api/signing.py::sign_envelope` to DSSE-sign the evidence bundle; verified offline
  by `control_plane/verify_proof.py` against the **pinned** committed public key (never a key in the envelope).

## Standing custody posture (current → target)
- **Now:** raw seed in a Vercel env secret. Any code in the API runtime can read `os.environ` — so a
  supply-chain compromise of a control-plane dep, or a Vercel env leak, exfiltrates the trust root in one step.
- **Target (D6-01/D6-02, founder-gated):** move signing to a **non-exportable KMS/HSM key** (sign via API,
  never load the seed into the function), in a separate key account; and **anchor every proof in a
  transparency log** (Rekor v2 — `control_plane/.../rekor.py` exists; wire it into `collect_and_store` and
  populate `verdicts.rekor_log_index`) so a key compromise is forced into the open and history can't be
  silently rewritten. Until then, the SCA gate (`calma-sca.yml`) + dep pinning shrink the supply-chain path.

## Routine rotation (no compromise) — zero downtime
1. Generate a new ed25519 keypair (same method as the current key).
2. Add the new public key to `control_plane/signing_pubkey.json` as an **additional** trusted keyid (keep
   the old one valid for the overlap so old proofs still verify); update `verify_proof.py` to accept the set.
3. Set the new seed as `CALMA_SIGNING_KEY` on `calma-api`; deploy. New proofs sign under the new keyid.
4. After the overlap window (≥ the proof-relevance horizon), drop the old keyid from the trusted set.
5. Record the keyid → validity-range in the runbook log below.

## Compromise response (seed leaked / suspected)
1. **Revoke + rotate immediately:** generate a new key, swap `CALMA_SIGNING_KEY`, deploy. Mark the
   compromised keyid **revoked** in `signing_pubkey.json` with the revocation timestamp.
2. **Scope the blast:** without a transparency log you cannot prove which proofs predate the compromise —
   so treat **every** proof under the compromised keyid as suspect from the suspected-leak time. Publish the
   revocation + the cutover time.
3. **Re-attest:** re-sign (re-verify if needed) the still-relied-upon verifications under the new keyid.
4. **Rotate the surrounding secrets** (service token, DB, R2, provider tokens) in case the same vector
   exposed them.
5. **Post-incident:** wire the transparency-log anchor (D6-02) before re-opening signed proofs to customers,
   so the next compromise is detectable and history is tamper-evident.

## Key log
| keyid | algorithm | created | retired | note |
|---|---|---|---|---|
| 6828f0ad98306a21 | ed25519 | 2026-06-24 | — | initial key (env-held seed; pre-KMS) |
