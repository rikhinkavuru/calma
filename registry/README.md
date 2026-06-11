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
the audit. Verdicts can additionally be Sigstore-countersigned, landing in the public Rekor
transparency log as an independent witness — offered per engagement.

## Audit it yourself

From a checkout of this repo:

```bash
python3 .claude/skills/calma/scripts/calma.py registry verify registry/ [--key <lab pubkey>]
```

re-hashes every entry, walks the chain, and checks every signature — fully offline.

Or check any single entry with **stock OpenSSH and nothing else** — the signature, public
key, and allowed-signers line are embedded in the entry file. The signed payload is the
canonical JSON of the `entry` object (sorted keys, no whitespace):

```bash
python3 -c "import json,sys; d=json.load(open(sys.argv[1])); \
open('payload.bin','wb').write(json.dumps(d['entry'],sort_keys=True,separators=(',',':')).encode()); \
open('sig','w').write(d['ssh']['signature']); open('signers','w').write(d['ssh']['allowed_signers'])" \
  registry/entries/00001-dc236f5759bb.json
ssh-keygen -Y verify -f signers -I calma-ebf722e19cf7016d -n calma-attest@v1 -s sig < payload.bin
# → Good "calma-attest@v1" signature for calma-ebf722e19cf7016d with ED25519 key ...
```

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

## Lab key

Entries in this registry are signed with the Calma lab key. Pin it:

- hex (for `calma attest verify --key`):
  `f7ba66bff50e2348d95edab4280410a8dd34ef050fab67dba7a1b7c3335ca872`
- SSH form (for an allowed_signers file):
  `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPe6Zr/1DiNI2V7atCgEEKjdNO8FD6tn26eht8MzXKhy calma-ebf722e19cf7016d`
