# The Calma registry — public catch history

An append-only, hash-chained, signed log of verification outcomes. Clinical-trial style:
engagements are logged when they **open**, so a missing outcome is itself visible. Withdrawn
and refuted engagements stay in the record.

## What an entry is — and is not

Every entry is **redacted by construction**: claim text, metric, claimed vs recomputed value,
verdict, dates, and content hashes (SHA-256 of the manifest, ledger, and contract). Code and
data never enter the registry — the field whitelist is enforced at append *and* at audit
(`registry.py: ALLOWED_FIELDS`), so a leak fails closed.

Every entry is derived from a **verified attestation bundle** (`calma publish` refuses
anything else), embeds the SHA-256 of the previous entry (a hash chain), and is SSHSIG-signed
with the lab key. `HEAD.json` is signed too, so silently dropping the newest entries breaks
the audit. Each Sigstore-countersigned verdict additionally lands in the public Rekor
transparency log, which independently witnesses this registry's contents.

## Audit it yourself

```bash
python3 .claude/skills/calma/scripts/calma.py registry verify registry/ [--key <lab pubkey>]
```

re-hashes every entry, walks the chain, and checks every signature — fully offline. Or check
any single entry with stock OpenSSH: the signature, public key, and allowed-signers line are
embedded in the entry file itself.

## Layout

```
registry/
  HEAD.json            signed pointer to the newest entry (seq + id)
  entries/
    00001-<hash>.json  { entry, id, ssh }  — id = sha256(canonical entry)
    00002-<hash>.json  each entry embeds the previous entry's hash
```

v2 (additive, when volume warrants): a Merkle tree over the same hash-addressed entries per
the C2SP tlog-tiles spec, served as static files, with checkpoints cosigned by the public
witness network.
