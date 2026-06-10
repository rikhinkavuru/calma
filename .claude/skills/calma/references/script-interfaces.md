# Script interfaces (the inter-script wire contract)

Every pipeline script has a defined argv, a JSON `--out` payload, and an exit-code table. The model
invokes scripts via Bash and READS the JSON; it never computes a statistic or a verdict label itself.

## Exit-code table (all scripts)

| code | meaning |
|---|---|
| 0 | done / clean |
| 1 | done, findings present / not-clean gate |
| 2 | invalid input (schema or contract error) |
| 3 | refused - no verified isolation primitive for untrusted code |
| 4 | killed - resource limit / timeout / OOM / sandbox denial -> INCONCLUSIVE |

## `verdict.py`
- import-only: `verdict(verdict_inputs: dict) -> str` and `verdict_with_reason(...) -> (str, str)`.
- The full input vector and conservative defaults are in `DEFAULTS`. Total function; never raises.

## `ledger.py validate <ledger.json>`
- Structural + semantic validation, then the gate. Re-derives every claim's verdict from its
  `verdict_inputs`. `--out` (stdout JSON): `{clean, repo_verdict, open_blocking}` or `{stage, errors}`.
- exit: 0 clean / 1 not-clean / 2 invalid.

## `draft_contract.py <target> [--claim "..."] --out verify.yaml`  (M1.1)
- Read-only. Emits a schema-valid `verify.yaml`: entrypoint, typed+graded input binding, claim grounding,
  dependency-trust, recipe match. Never installs/runs; writes a consent token only on user confirm.

## `run_hermetic.py --contract verify.yaml --out run.json`  (M1.2)
- Installs + runs the entrypoint under one verified tier; applies the determinism config; re-emits raw
  artifacts. `--out`: per-phase exit codes, isolation/determinism/hermeticity tiers, SBOM, fingerprint.

## `recompute.py --contract verify.yaml --runs <dir> --out recompute.json`  (M1.3)
- Recomputes each metric from raw outputs via the canonical recipe on the reference-deterministic path
  (K times). `--out`: `{metric_id, value, terms, k_spread, degenerate}` per metric.

## `compare.py --recompute recompute.json --contract verify.yaml --out diff.json`  (M1.3)
- Builds the calibrated tolerance budget and the full `verdict_inputs`, then calls `verdict()`.
  `--out`: diff table + budget breakdown + `verdict` + `verdict_inputs`.

## `attest.py --run <dir> --out manifest.json`  (M1.3)
- Content-addressed SBOM manifest (SHA-256 over sorted `relpath:sha256`, own hash excluded).

## `attest` bundle library (signing lives here; CLI is `calma attest ...`)
- `keygen(kdir=None, force=False)` -> Ed25519 keypair at `$CALMA_KEY_DIR` or `~/.calma/keys/`
  (`ed25519.key` hex seed, 0600; `ed25519.pub` hex). keyid = sha256(raw 32-byte pubkey).
- `sign_run(run_dir, key_path=None, out=None)` -> `attestation.bundle.json`: a DSSE envelope
  (payloadType `application/vnd.in-toto+json`, PAE-signed) over an in-toto Statement v1 whose
  predicate embeds the FULL `ledger.json` + `manifest.json`; subject digest = sha256 of the
  canonical (sorted-keys, compact) ledger JSON. Deterministic: same key + same run -> same bytes.
  `calma verify` auto-signs every run once a key exists. Sigstore later = countersignature
  appended to `envelope.signatures`; the signed payload bytes never change.
- `verify_bundle(bundle, pinned_pub_hex=None)` -> `(ok, checks)`. Fully offline. Checks, in order:
  schema, payload type, base64/JSON decode, signature (against the pinned key if given, else the
  embedded key), statement shape, subject digest == canonical embedded ledger, manifest root-hash
  cross-check, **ledger re-derivation via `ledger.validate_obj`** (every verdict label must
  re-derive byte-for-byte - this is what kills a forged-label bundle re-signed under a new key),
  and statement-verdict == ledger repo_verdict. ok means authentic + internally consistent;
  a REFUTED bundle verifies (the verdict is the payload, not the pass condition).
- `ed25519.py`: pure-stdlib RFC 8032 (sign/verify/secret_to_public), strict s < L verify,
  validated against the RFC section 7.1 vectors in `tests/test_attest.py`.
