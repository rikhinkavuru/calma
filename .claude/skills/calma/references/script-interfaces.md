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
- `keygen(kdir=None, force=False, import_key=None)` -> Ed25519 keypair at `$CALMA_KEY_DIR` or
  `~/.calma/keys/` (`ed25519.key` hex seed, 0600; `ed25519.pub` hex; `ed25519.pub.ssh` the
  authorized_keys line). keyid = sha256(raw 32-byte pubkey). `import_key` adopts an existing
  UNENCRYPTED OpenSSH ed25519 identity (`~/.ssh/id_ed25519`); `load_signing_key` reads either form.
- `sign_run(run_dir, key_path=None, out=None, time_verified=None)` -> `attestation.bundle.json`:
  a DSSE envelope (payloadType `application/vnd.in-toto+json`, PAE-signed) over an in-toto
  Statement v1, predicate `https://calma.dev/verdict/v1` modeled on the SLSA VSA: `verifier`
  {id, engine, version}, `timeVerified`, `policy` {contract_sha256, calibration_sha256,
  reference_vectors_sha256}, `verdict`, `claims` summary, plus the FULL `ledger.json` +
  `manifest.json`; subjects = sha256(canonical ledger) + the manifest root. The same key signs
  TWICE: the raw DSSE signature (what Sigstore countersigns) and an OpenSSH SSHSIG over the exact
  payload bytes (`bundle.ssh`: namespace `calma-attest@v1`, principal, public_key line,
  allowed_signers line, armored signature). Sidecars written next to the bundle for the
  zero-install counterparty path: `attestation.payload.json`, `attestation.sig.sshsig`,
  `attestation.allowed_signers` ->
  `ssh-keygen -Y verify -f attestation.allowed_signers -I <principal> -n calma-attest@v1
  -s attestation.sig.sshsig < attestation.payload.json`.
  Deterministic for (key, ledger, time_verified). `calma verify` auto-signs once a key exists.
- `verify_bundle(bundle, pinned_pub_hex=None)` -> `(ok, checks)`. Fully offline. Checks, in order:
  schema (@1 or @2), payload type, base64/JSON decode, DSSE signature (against the pinned key if
  given, else the embedded key), SSHSIG (same payload, MUST be the same key as the DSSE signer -
  no mix-and-match; required on @2 bundles, no silent downgrade), statement shape (verdict/v1 or
  the legacy predicate), subject digest == canonical embedded ledger, manifest root-hash
  cross-check, **ledger re-derivation via `ledger.validate_obj`** (every verdict label must
  re-derive byte-for-byte - this is what kills a forged-label bundle re-signed under a new key),
  statement-verdict == ledger repo_verdict, claims summary == derived-from-ledger, and every
  embedded RFC 3161 timestamp (imprint binds to THIS bundle's signature; chain-verified via
  `openssl ts` when available, honestly reported as "structural only" when not). ok means
  authentic + internally consistent; a REFUTED bundle verifies (the verdict is the payload, not
  the pass condition).
- `ed25519.py`: pure-stdlib RFC 8032 (sign/verify/secret_to_public), strict s < L verify,
  validated against the RFC section 7.1 vectors in `tests/test_attest.py`.
- `sshsig.py`: pure-stdlib OpenSSH SSHSIG (PROTOCOL.sshsig v1, ssh-ed25519, sha512). Interop is
  tested BOTH directions against the system ssh-keygen. Namespace-bound (anti cross-protocol
  reuse). Also parses unencrypted openssh-key-v1 private keys.
- `rfc3161.py`: Layer 1. `timestamp_bundle(bundle, tsa_url)` builds a DER TimeStampReq
  (sha256 imprint over the DSSE signature bytes, certReq), POSTs it (freetsa.org default), embeds
  the token + TSA CA cert under `bundle.timestamps` - the ONLY networked step; verification is
  offline forever. `verify_bundle_timestamps` parses TSTInfo pure-stdlib (imprint + genTime) and
  chain-verifies via `openssl ts -verify` when openssl exists.
- `sigstore_l2.py`: Layer 2, lab tier. `calma attest sigstore <bundle>` keyless-countersigns the
  SAME payload bytes via sigstore-python (OIDC -> Fulcio -> Rekor) into a standard Sigstore
  bundle. Optional dependency; a missing install raises exact instructions, never a traceback.

## `registry.py` (the catch history; CLI: `calma publish`, `calma registry verify`)
- `derive_entry(bundle, engagement=None, note=None)` -> a REDACTED entry from a VERIFIED bundle:
  claim line, metric, claimed vs recomputed, verdict, dates, content hashes (manifest / ledger /
  contract), keyid. `ALLOWED_FIELDS` is the redaction boundary - enforced at append AND at audit,
  so a leak fails closed. `opened_entry(id)` logs an engagement at contract signing (kind
  `engagement-opened`, verdict PENDING) - a missing outcome is structurally visible.
- `append_entry(reg_dir, entry, seed)` -> chains (entry embeds prev sha256; id = sha256(canonical
  entry); seq strictly increments), SSHSIG-signs the entry AND re-signs `HEAD.json` (tail
  truncation breaks the audit). Files: `entries/NNNNN-<id12>.json` `{entry, id, ssh}`.
- `verify_chain(reg_dir, pinned_pub_hex=None)` -> `(ok, checks, summary)`. Re-hashes every entry,
  walks prev/seq links, verifies every signature + the signed HEAD, rejects non-whitelisted
  fields. summary = verdict counts + open engagements. Publish REQUIRES attest: `calma publish`
  refuses a run dir without a verifying `attestation.bundle.json`.

## `dsl.py` + `compiler.py` (the recipe compiler)
- `dsl.py`: the constrained composition language - JSON expression trees over whitelisted
  `numeric.py` kernels (col / lit / call / scalar op / elementwise zip / len), typed bottom-up
  (list / rawlist / scalar), no loops or recursion (total by construction), MAX_DEPTH 16 /
  MAX_NODES 256 (DoS-safe). `validate(program)`, `execute(program, tag_values)` (degrades to NaN,
  never raises on numeric content), `program_hash` (sha256 of canonical JSON - the frozen identity).
- `compiler.py admit <draft.json> [--venv PY]`: the deterministic admission gate over a
  `calma/recipe-draft@1` (see `references/recipe-draft.schema.json`): structural -> differential
  vs the NAMED oracle in the reference venv over LCG datasets (sizes 3..256, rel tol 1e-9) ->
  metamorphic relations (permutation/scale/shift/duplicate/bounds; venv-free) -> degeneracy
  (empty/single/constant/NaN must degrade, never raise, never +-inf) -> bit-stability double-run.
  Failures print structured counterexamples (CEGIS feedback for the drafting model). Pass ->
  frozen into `assets/compiled_recipes.json` (program + sha256 + pinned vectors + admission
  metadata + SSHSIG when a lab key exists), loaded by `recipes.py` at import with the hash
  RE-VALIDATED (tampered assets are skipped with a warning - fails closed), registered with
  `set_maturity: compiled-validated`, claim hints inserted before the generic hint tail.
  `check` runs the venv-free stages only and never freezes.
