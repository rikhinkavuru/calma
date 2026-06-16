# Optional Rekor transparency-log backing

Calma's catch-history registry (`registry/`) is, on its own, an append-only **hash-chained,
SSHSIG-signed** log: every entry embeds the SHA-256 of the previous entry, the signed `HEAD.json`
makes tail-truncation detectable, and `calma registry verify` audits the whole chain offline. That
is the load-bearing tamper-evidence and it needs **zero infrastructure**.

This page documents the **optional** layer on top of it: backing each entry with a [Sigstore
Rekor](https://github.com/sigstore/rekor) transparency log so a third party can verify the
append-only property with **standard tooling** (`rekor-cli`) and **offline inclusion proofs**.

It is **belt-and-suspenders, never a replacement.** The custom hash-chain is unchanged; the Rekor
proof is additive metadata stored next to each entry.

## Why you might want it

- **Independent witness.** A Rekor log is an append-only Merkle tree operated outside calma. An
  inclusion proof shows your entry sits in a tree with a given root at a given size — evidence that
  the log (not just you) saw the entry, in order.
- **Standard, offline verification.** The proof is plain [RFC 6962](https://www.rfc-editor.org/rfc/rfc6962)
  Merkle math. A counterparty re-verifies it locally — with `calma registry verify`, with `rekor-cli`,
  or by hand — **without contacting or trusting the log**.
- **Apache-2.0 and self-hostable.** Rekor is open source ([sigstore/rekor](https://github.com/sigstore/rekor),
  Apache-2.0). You can run your **own** instance so the entire chain of custody is yours — no
  dependency on the public good instance.

## The Rekor v2 entry-type constraint

Rekor **v2** (GA October 2025, Tessera-backed) supports **only two** entry types: `hashedrekord`
and `dsse`. It **dropped** `intoto` and `rfc3161`. Calma therefore:

- logs each **registry entry** as a **`hashedrekord`** over the entry's content address (the same
  SHA-256 the hash-chain already commits to) — uniform across every entry kind, including
  `engagement-opened` entries that have no attestation bundle;
- can wrap an existing **DSSE attestation bundle** as a **`dsse`** entry (the bundle layer); and
- **hard-rejects** `intoto`/`rfc3161` (and any unknown type) with an error that names the v2
  constraint — never a silent fallback to a type no v2 log will accept.

`v2` is the default assumption. To target a pinned self-hosted **v1** instance, pass `--rekor-v1`.

## How logging is ordered (it cannot affect a verdict)

Rekor lives **strictly outside the hermetic boundary**:

1. `calma verify` runs the work in the sandbox, recomputes the metric, and **finalizes the verdict**
   (written to `ledger.json`) — all **before** anything is signed.
2. `calma publish` derives a redacted entry, chains it, and **SSHSIG-signs** it.
3. **Only then**, if `--rekor <URL>` is configured, the (now frozen) entry is submitted to Rekor —
   the one and only network egress — and the returned inclusion proof is stapled onto the entry.

The Rekor call has no access to the verdict computation. Rekor being slow, down, or hostile can at
worst block the post-verdict logging step; it can never change a verdict, a recompute, or a
determinism stamp.

**Fail-closed by default.** The entry's bytes are finalized in memory, Rekor is called, and the
files are written **only after** a proof is obtained — so if transparency logging was requested and
fails, **nothing is written** (no silently un-logged entry) and the command reports failure. Pass
`--rekor-optional` to opt into **fail-open**: the entry is written without a proof and marked
`rekor_error`, and `calma registry verify` reports it as `pending`.

## Self-hosting a Rekor v2 instance

Rekor v2 runs against a [Tessera](https://github.com/transparency-dev/tessera) storage backend. A
minimal local stack (adjust image tags to the current release):

```yaml
# docker-compose.yml  -  a local, self-hosted Rekor v2 for calma --rekor http://localhost:3000
services:
  mysql:
    image: mysql:8
    environment:
      MYSQL_ROOT_PASSWORD: rekor
      MYSQL_DATABASE: tessera
    ports: ["3306:3306"]
  rekor:
    image: ghcr.io/sigstore/rekor/rekor-server:latest   # pin a v2 tag in production
    command:
      - "serve"
      - "--http-address=0.0.0.0"
      - "--http-port=3000"
    depends_on: [mysql]
    ports: ["3000:3000"]
```

```
docker compose up -d
calma publish <run_dir> --registry registry/ --rekor http://localhost:3000
```

Capture the instance's checkpoint (signing) public key once; third parties use it to **anchor** the
proof's root (below). The exact bootstrap differs across Rekor releases — see the upstream
[Rekor docs](https://docs.sigstore.dev/logging/overview/) — but the calma surface is stable:
`--rekor <URL>` to log, `--rekor-log-key <hex|file>` to anchor.

> The repository's integration test (`scripts/tests/test_rekor.py`) stands up a **pure-stdlib,
> in-process Rekor stub** over real HTTP — the same role as the local OpenSSL TSA in the timestamp
> tests — so `append → log → fetch proof → offline verify` and the tamper cases run in CI with no
> Docker and no network.

## What gets stored, and how it verifies offline

Each logged entry gains a wrapper-level `rekor` block (a sibling of `entry`/`id`/`ssh`, so the
entry's content address and signature bytes are **byte-identical** with or without it):

```jsonc
"rekor": {
  "schema": "calma/rekor-inclusion@1",
  "entry_type": "hashedrekord",
  "log_url": "http://localhost:3000",   // provenance only - NOT trusted during offline verify
  "log_index": 7,
  "tree_size": 8,
  "root_hash": "…",
  "leaf_hash": "…",            // SHA-256(0x00 || body) - recomputable from body_b64
  "body_b64": "…",            // the canonical Rekor entry body
  "witnessed_digest": "…",    // == the registry entry's content address (cross-checked)
  "hashes": ["…", "…"],       // the RFC 6962 inclusion proof path
  "checkpoint": "…"            // the log's signed note (root + size + signature)
}
```

`calma registry verify` checks, for every entry that carries a block, **all offline**:

1. **body ↔ leaf** — `leaf_hash == SHA-256(0x00 ‖ body)`.
2. **body ↔ entry** — the body's witnessed digest equals the registry entry's content address.
   Tamper the published entry and this fails immediately.
3. **leaf ↔ root** — the inclusion proof re-folds the leaf to the stored root (RFC 6962). Tamper the
   proof or the root and the fold fails.
4. **root anchor** (when `--rekor-log-key` is supplied) — the checkpoint note's signature verifies
   against the **pinned** log key, so the root itself is non-repudiable.

Two honesty tiers, reported explicitly (mirroring the RFC 3161 timestamp discipline):

- **`anchored`** — a pinned log key verified the checkpoint signature. Full belt-and-suspenders.
- **`merkle`** — the proof folds to the stored root, but no log key was pinned, so the root is
  **self-asserted** (the log could have presented a different tree). Surfaced honestly, never as a
  proven anchor.

None of this requires trusting Rekor: the math is local and the inputs are stored with the entry.

## Third-party verification with `rekor-cli`

A counterparty who does not use calma verifies the same fact with Sigstore's own tool. The
`log_index` (and the entry's witnessed digest) are in the `rekor` block:

```
# fetch the entry and confirm its contents:
rekor-cli --rekor_server <URL> get --log-index <log_index>

# verify the inclusion proof against the log's checkpoint:
rekor-cli --rekor_server <URL> verify --log-index <log_index>
```

`rekor-cli` performs the same RFC 6962 inclusion-proof check; calma's offline verifier reproduces it
from the stored proof so the check also works after the log is gone.

## Summary

- Optional, **default off** — the endpoint must be explicitly configured.
- Rekor is **Apache-2.0** and **self-hostable**; the offline check never trusts it.
- Rekor **v2** ⇒ **`hashedrekord` + `dsse` only**; `intoto`/`rfc3161` are refused.
- Inclusion proofs are **offline-verifiable** (RFC 6962) and bound to the entry's content address.
- It is **additive** to the hash-chain and **cannot** influence any verdict.
