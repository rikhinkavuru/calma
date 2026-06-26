"""calma.attest - content-addressed SBOM re-run manifest + the signed attestation bundle.

Manifest: SHA-256 over sorted `relpath:sha256` lines (the manifest's own hash excluded). Lets a
verdict be independently re-checked.

Bundle (three layers, each optional on top of the last - the in-toto/Sigstore stack):
  Layer 0 - a DSSE envelope (the exact envelope Sigstore countersigns) over an in-toto
    Statement v1 whose predicate is github.com/rikhinkavuru/calma/verdict/v1 (GitHub-rooted -
    a URI we control forever; the legacy calma.dev URIs are still ACCEPTED on verification,
    so v1 bundles signed under the old predicate remain valid), modeled on the SLSA Verification
    Summary Attestation (verifier id+version, policy = contract hash + calibration hashes,
    verdict, claims, scope) and embedding the FULL ledger + manifest. Signed twice with the
    same local Ed25519 key (ed25519.py, pure stdlib): a raw DSSE signature AND an OpenSSH
    SSHSIG (sshsig.py, namespace calma-attest@v1) - so a counterparty can check the signature
    with stock `ssh-keygen -Y verify` and ZERO installs. Sidecar files (payload + .sshsig +
    allowed_signers) are written next to the bundle for exactly that.
  Layer 1 - an RFC 3161 trusted timestamp over the DSSE signature (rfc3161.py), embedded under
    "timestamps". Proves the verdict existed before a point in time; verifies offline.
  Layer 2 - Sigstore keyless countersigning (lab tier; `calma attest sigstore`) = append to
    envelope.signatures + tlog material; the signed payload bytes never change.

`verify_bundle` is the counterparty side and is fully offline: it checks both signatures, then
re-derives every verdict label byte-for-byte via ledger.validate_obj - so even a bundle re-signed
by an attacker with their own key cannot carry a forged verdict label, and a pinned key (--key)
catches the re-signing itself.

Library: manifest_for(dir), sign_run(run_dir), verify_bundle(bundle).
CLI: attest.py --run DIR [--out manifest.json]   (manifest only; keygen/sign/verify live in calma.py)
"""
import argparse
import base64
import hashlib
import json
import os
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ed25519  # noqa: E402
import ledger as LED  # noqa: E402
import sshsig  # noqa: E402


def _sha256(path):
    h = hashlib.sha256()
    try:
        st = os.stat(path)
        if not stat.S_ISREG(st.st_mode):
            # a FIFO / socket / device under runs/ must NEVER be open()ed - a writer-less FIFO blocks
            # forever and would hang the verifier in the attestation stage (a hostile target's DoS).
            # Hash a structural marker instead.
            h.update(("special:%o" % stat.S_IFMT(st.st_mode)).encode())
        else:
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
    except OSError as e:
        # unreadable (permissions / vanished mid-walk) -> a deterministic marker, never an uncaught
        # crash that aborts the whole verification with a traceback.
        h.update(("unreadable:%s" % type(e).__name__).encode())
    return h.hexdigest()


def manifest_for(root):
    files = []
    for dirpath, _, names in os.walk(root):
        for n in sorted(names):
            if n == "manifest.json":
                continue
            full = os.path.join(dirpath, n)
            rel = os.path.relpath(full, root)
            files.append((rel, _sha256(full)))
    files.sort()
    lines = "".join("%s:%s\n" % (r, h) for r, h in files)
    root_hash = hashlib.sha256(lines.encode()).hexdigest()
    return {"root": os.path.basename(os.path.abspath(root)),
            "files": [{"path": r, "sha256": h} for r, h in files],
            "manifest_sha256": root_hash}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    man = manifest_for(a.run)
    text = json.dumps(man, indent=2)
    if a.out:
        open(a.out, "w").write(text)
    print(text)
    return 0


def intoto_statement(manifest, subject_name, verdict, scope=None):
    """An in-toto/SLSA-style attestation statement binding the verdict to the content-addressed inputs.
    Aligns to in-toto Statement v1 so it drops into SLSA/sigstore provenance pipelines."""
    scope = scope or {}
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": subject_name, "digest": {"sha256": manifest.get("manifest_sha256", "")}}],
        "predicateType": STATEMENT_PREDICATE_TYPE,
        "predicate": {
            "builder": {"id": VERIFIER_ID},
            "verdict": verdict,
            "isolation_tier": scope.get("isolation_tier"),
            "determinism_mode": scope.get("determinism_mode"),
            "reproducibility_scope": scope.get("reproducibility_scope"),
            "materials": [{"uri": f["path"], "digest": {"sha256": f["sha256"]}}
                          for f in manifest.get("files", [])],
        },
    }


def ml_bom(manifest, target, scope=None):
    """A CycloneDX ML-BOM (machine-learning bill of materials) - the artifact AI-BOM procurement rules
    and EU AI Act Art. 11 increasingly require: every input hashed, with the verification posture stamped."""
    scope = scope or {}
    return {
        "bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1,
        "metadata": {"component": {"type": "machine-learning-model", "name": target,
                                   "bom-ref": "calma:" + (manifest.get("manifest_sha256", "")[:16])}},
        "components": [{"type": "data", "name": f["path"], "bom-ref": f["path"],
                        "hashes": [{"alg": "SHA-256", "content": f["sha256"]}]}
                       for f in manifest.get("files", [])],
        "properties": [
            {"name": "calma:isolation_tier", "value": str(scope.get("isolation_tier"))},
            {"name": "calma:determinism_mode", "value": str(scope.get("determinism_mode"))},
            {"name": "calma:manifest_sha256", "value": manifest.get("manifest_sha256", "")},
        ],
    }


# ---------------------------------------------------------------------------
# Signed attestation bundle (DSSE + in-toto Statement v1, Ed25519)
# ---------------------------------------------------------------------------

BUNDLE_SCHEMA = "calma/attestation-bundle@2"
BUNDLE_SCHEMAS_ACCEPTED = {"calma/attestation-bundle@1", BUNDLE_SCHEMA}
PAYLOAD_TYPE = "application/vnd.in-toto+json"
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
# GitHub-rooted ids (we own this namespace permanently; calma.dev belongs to a stranger).
URI_ROOT = "https://github.com/rikhinkavuru/calma"
PREDICATE_TYPE = URI_ROOT + "/verdict/v1"  # modeled on the SLSA VSA
VERIFIER_ID = URI_ROOT + "/skill"
STATEMENT_PREDICATE_TYPE = URI_ROOT + "/attestation/verification/v1"
# legacy calma.dev URIs: existing bundles (incl. the genesis registry entry) were signed under
# them and MUST keep verifying - accepted forever, never emitted again
LEGACY_PREDICATE_TYPE = "https://calma.dev/verdict/v1"
PREDICATE_TYPES_ACCEPTED = {PREDICATE_TYPE, LEGACY_PREDICATE_TYPE,
                            STATEMENT_PREDICATE_TYPE,
                            "https://calma.dev/attestation/verification/v1"}
# predicate shapes that carry the VSA claims summary (binding-checked on verify)
PREDICATE_TYPES_VSA = {PREDICATE_TYPE, LEGACY_PREDICATE_TYPE}
BUNDLE_NAME = "attestation.bundle.json"
PAYLOAD_SIDECAR = "attestation.payload.json"
SSHSIG_SIDECAR = "attestation.sig.sshsig"
SIGNERS_SIDECAR = "attestation.allowed_signers"
DEFAULT_KEY_DIR = "~/.calma/keys"


def engine_version():
    """The calma engine version (lazy import - calma.py imports this module)."""
    try:
        import calma
        return calma.__version__
    except Exception:
        return "unknown"


def _asset_sha256(name):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", name)
    try:
        return _sha256(path)
    except OSError:
        return None


def _canonical(obj):
    """The byte form everything is hashed and signed over: sorted keys, no whitespace, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def _keyid(pub):
    return hashlib.sha256(pub).hexdigest()


def key_dir():
    return os.path.expanduser(os.environ.get("CALMA_KEY_DIR", DEFAULT_KEY_DIR))


def _key_paths(kdir=None):
    kdir = kdir or key_dir()
    return os.path.join(kdir, "ed25519.key"), os.path.join(kdir, "ed25519.pub")


def keygen(kdir=None, force=False, import_key=None):
    """Generate a local Ed25519 keypair (hex seed at 0600 + hex public key + .pub SSH line).
    Refuses to overwrite. import_key: path to an existing UNENCRYPTED OpenSSH ed25519 private
    key (e.g. ~/.ssh/id_ed25519) to adopt that identity instead of generating a fresh one."""
    sk_path, pk_path = _key_paths(kdir)
    if os.path.exists(sk_path) and not force:
        raise ValueError("a signing key already exists at %s (pass --force to overwrite)" % sk_path)
    os.makedirs(os.path.dirname(sk_path), exist_ok=True)
    if import_key:
        seed = sshsig.load_openssh_private_key(open(import_key).read())
    else:
        seed = os.urandom(32)
    pub = ed25519.secret_to_public(seed)
    fd = os.open(sk_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w") as fh:
        fh.write(seed.hex() + "\n")
    with open(pk_path, "w") as fh:
        fh.write(pub.hex() + "\n")
    with open(pk_path + ".ssh", "w") as fh:
        fh.write(sshsig.pub_line(pub, comment="calma-" + _keyid(pub)[:16]) + "\n")
    return {"key_path": sk_path, "pub_path": pk_path,
            "public_key": pub.hex(), "keyid": _keyid(pub),
            "ssh_public_key": sshsig.pub_line(pub, comment="calma-" + _keyid(pub)[:16])}


def load_signing_key(path=None):
    """The 32-byte seed from a key file (or the default location): either calma's hex-seed form
    or an unencrypted OpenSSH ed25519 private key. None if absent/unreadable."""
    path = path or _key_paths()[0]
    if not os.path.isfile(path):
        return None  # FIFO/socket/device (or absent): never open() (would block); no key here
    try:
        text = open(path).read()
    except OSError:
        return None
    try:
        seed = bytes.fromhex(text.strip())
        return seed if len(seed) == 32 else None
    except ValueError:
        pass
    try:
        return sshsig.load_openssh_private_key(text)
    except ValueError:
        return None


def _pae(payload_type, payload):
    """DSSE v1 pre-authentication encoding - the exact bytes that are signed."""
    return b"DSSEv1 %d %s %d %s" % (len(payload_type), payload_type.encode(),
                                    len(payload), payload)


def claims_summary(led):
    """The human-auditable claim digest the VSA predicate carries (derived from the ledger;
    verify_bundle re-derives it and rejects any drift between the two)."""
    return [{"id": c.get("id"), "metric": c.get("metric"), "headline": bool(c.get("headline")),
             "claimed": c.get("claimed_value"), "recomputed": c.get("recomputed_value"),
             "verdict": c.get("verdict")} for c in led.get("claims", [])]


def _policy(manifest, contract_sha256=None):
    """What the verdict was evaluated AGAINST (the VSA `policy`): the contract that bound the
    claim and the calibration corpus the engine's budgets + reference vectors come from."""
    if contract_sha256 is None:
        for f in (manifest or {}).get("files", []):
            if f.get("path") in ("verify.yaml", "verify.lock.json"):
                contract_sha256 = f.get("sha256")
                break
    return {
        "contract_sha256": contract_sha256,
        "calibration_sha256": _asset_sha256("calibration.json"),
        "reference_vectors_sha256": _asset_sha256("reference_vectors.json"),
    }


def bundle_statement(led, manifest, time_verified=None, contract_sha256=None):
    """in-toto Statement v1, predicate github.com/rikhinkavuru/calma/verdict/v1 modeled on the SLSA Verification
    Summary Attestation: a verifier (calma + version) evaluated subjects against a policy
    (contract + calibration hashes) and reached a verdict. The predicate also embeds the full
    ledger + manifest, so the counterparty can re-derive every verdict label offline."""
    subjects = [{"name": led.get("target", "run"),
                 "digest": {"sha256": hashlib.sha256(_canonical(led)).hexdigest()}}]
    if (manifest or {}).get("manifest_sha256"):
        subjects.append({"name": "%s/manifest" % led.get("target", "run"),
                         "digest": {"sha256": manifest["manifest_sha256"]}})
    return {
        "_type": STATEMENT_TYPE,
        "subject": subjects,
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "verifier": {"id": VERIFIER_ID, "engine": "calma",
                         "version": engine_version()},
            "timeVerified": time_verified,
            "policy": _policy(manifest, contract_sha256),
            "verdict": led.get("repo_verdict"),
            "claims": claims_summary(led),
            "scope": led.get("scope"),
            "ledger": led,
            "manifest": manifest,
            "materials": [{"uri": f["path"], "digest": {"sha256": f["sha256"]}}
                          for f in (manifest or {}).get("files", [])],
        },
    }


def make_bundle(led, manifest, seed, time_verified=None, contract_sha256=None):
    """Sign the statement into a self-contained DSSE bundle, twice with the same key:
    a raw DSSE Ed25519 signature (what Sigstore later countersigns) and an OpenSSH SSHSIG over
    the exact payload bytes (what `ssh-keygen -Y verify` checks with zero installs).
    Deterministic for a given (key, ledger, time_verified)."""
    payload = _canonical(bundle_statement(led, manifest, time_verified, contract_sha256))
    pub = ed25519.secret_to_public(seed)
    sig = ed25519.sign(seed, _pae(PAYLOAD_TYPE, payload))
    principal = "calma-" + _keyid(pub)[:16]
    return {
        "schema": BUNDLE_SCHEMA,
        "envelope": {
            "payloadType": PAYLOAD_TYPE,
            "payload": base64.b64encode(payload).decode(),
            "signatures": [{"keyid": _keyid(pub), "sig": base64.b64encode(sig).decode()}],
        },
        "ssh": {
            "namespace": sshsig.NAMESPACE,
            "principal": principal,
            "public_key": sshsig.pub_line(pub, comment=principal),
            "allowed_signers": sshsig.allowed_signers_line(pub, principal),
            "signature": sshsig.sign(seed, payload),
        },
        "verification": {
            "public_keys": [{"keyid": _keyid(pub), "scheme": "ed25519",
                             "public_key_hex": pub.hex()}],
        },
    }


def write_ssh_sidecars(bundle, run_dir):
    """The three files a counterparty needs to verify with ONLY stock OpenSSH (>= 8.0),
    plus VERIFY-THIS.txt - the human instructions, with every value filled in, so nobody
    ever has to construct the command by hand."""
    ssh = bundle.get("ssh") or {}
    payload = base64.b64decode(bundle["envelope"]["payload"])
    paths = {
        PAYLOAD_SIDECAR: payload,
        SSHSIG_SIDECAR: ssh.get("signature", "").encode(),
        SIGNERS_SIDECAR: (ssh.get("allowed_signers", "") + "\n").encode(),
        "VERIFY-THIS.txt": verify_instructions(bundle).encode(),
    }
    for name, data in paths.items():
        with open(os.path.join(run_dir, name), "wb") as fh:
            fh.write(data)
    return sorted(paths)


def verify_instructions(bundle):
    """Counterparty instructions for THIS bundle, every value filled in."""
    ssh = bundle.get("ssh") or {}
    keyid = ((bundle.get("envelope") or {}).get("signatures") or [{}])[0].get("keyid", "")
    ts = bundle.get("timestamps") or []
    lines = [
        "HOW TO VERIFY THIS ATTESTATION (offline; pick either path)",
        "=" * 60,
        "",
        "This folder contains a signed verdict from calma - a verification",
        "by re-execution: the code was re-run in a sandbox and the claimed",
        "number was recomputed from the raw output files.",
        "",
        "PATH A - full check (needs the free calma CLI, no dependencies):",
        "",
        "    calma attest verify attestation.bundle.json [--replay]",
        "",
        "  Checks both signatures, every content hash, and re-derives the",
        "  verdict byte-for-byte from its stored inputs. --replay also",
        "  re-executes the run. Get calma: github.com/rikhinkavuru/calma",
        "",
        "PATH B - signature check with ZERO installs (stock OpenSSH >= 8.0,",
        "already on every Mac/Linux machine). From this folder:",
        "",
        "    ssh-keygen -Y verify -f attestation.allowed_signers \\",
        "      -I %s -n %s \\" % (ssh.get("principal", "<principal>"),
                                  ssh.get("namespace", sshsig.NAMESPACE)),
        "      -s attestation.sig.sshsig < attestation.payload.json",
        "",
        "  Prints 'Good \"%s\" signature ...' if the verdict bytes" % sshsig.NAMESPACE,
        "  are authentic and unaltered.",
        "",
        "TRUST NOTE: the key in attestation.allowed_signers ships WITH this",
        "bundle, so Path B alone proves integrity, not identity. Pin the",
        "signer by obtaining their public key from a channel you trust and",
        "comparing (keyid %s...)." % keyid[:16],
    ]
    if ts:
        lines += ["",
                  "TIMESTAMP: an RFC 3161 token from %s proves this verdict" % ts[0].get("tsa_url"),
                  "existed by %s. calma attest verify checks it offline." % ts[0].get("gen_time")]
    return "\n".join(lines) + "\n"


def sign_run(run_dir, key_path=None, out=None, time_verified=None):
    """Sign a completed run dir's ledger.json (+ manifest.json if present) into BUNDLE_NAME,
    plus the ssh-keygen sidecar files. time_verified defaults to now (UTC, ISO 8601)."""
    led_path = os.path.join(run_dir, "ledger.json")
    if not os.path.exists(led_path):
        raise ValueError("no ledger.json under %s - run `calma verify` first" % run_dir)
    seed = load_signing_key(key_path)
    if seed is None:
        raise ValueError("no signing key at %s - run `calma attest keygen` first"
                         % (key_path or _key_paths()[0]))
    led = json.load(open(led_path))
    try:
        manifest = json.load(open(os.path.join(run_dir, "manifest.json")))
    except (OSError, ValueError):
        manifest = {}
    if time_verified is None:
        import datetime
        time_verified = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # the contract: drafted ones live in the run dir, committed ones at the target root
    contract_sha = None
    rd = os.path.abspath(run_dir)
    for cand in (os.path.join(rd, "verify.yaml"),
                 os.path.join(os.path.dirname(os.path.dirname(rd)), "verify.yaml")):
        if os.path.exists(cand):
            contract_sha = _sha256(cand)
            break
    bundle = make_bundle(led, manifest, seed, time_verified, contract_sha)
    out = out or os.path.join(run_dir, BUNDLE_NAME)
    json.dump(bundle, open(out, "w"), indent=2)
    write_ssh_sidecars(bundle, os.path.dirname(out) or ".")
    return bundle, out


def _manifest_root_consistent(manifest):
    """Recompute the manifest root hash from its own (path, sha256) lines."""
    if not manifest:
        return True  # no manifest was produced for this run; nothing to cross-check
    lines = "".join("%s:%s\n" % (f["path"], f["sha256"])
                    for f in sorted(manifest.get("files", []), key=lambda f: f["path"]))
    return hashlib.sha256(lines.encode()).hexdigest() == manifest.get("manifest_sha256")


def verify_bundle(bundle, pinned_pub_hex=None):
    """Counterparty verification, fully offline. Returns (ok, checks) where checks is an ordered
    list of (name, ok, detail). ok means: authentically signed AND every embedded verdict label
    re-derives byte-for-byte. It does NOT mean the verdict is clean - a REFUTED bundle verifies."""
    checks = []

    def chk(name, ok, detail="", ok_detail=""):
        # detail explains a failure; ok_detail is the (rare) success annotation worth showing
        checks.append((name, bool(ok), ok_detail if ok else detail))
        return bool(ok)

    # a bundle that is valid JSON but not an object (a bare array/scalar) must FAIL cleanly, never
    # crash on .get() - fail-closed (never a false VERIFIED).
    if not isinstance(bundle, dict):
        chk("schema", False, "proof bundle is not a JSON object")
        return False, checks

    env = bundle.get("envelope") or {}
    if not chk("schema", bundle.get("schema") in BUNDLE_SCHEMAS_ACCEPTED,
               "expected one of %s" % ", ".join(sorted(BUNDLE_SCHEMAS_ACCEPTED))):
        return False, checks
    if not chk("payload-type", env.get("payloadType") == PAYLOAD_TYPE,
               "expected %s" % PAYLOAD_TYPE):
        return False, checks
    try:
        payload = base64.b64decode(env.get("payload", ""), validate=True)
        statement = json.loads(payload)
    except (ValueError, TypeError):
        chk("payload-decode", False, "payload is not base64 JSON")
        return False, checks
    chk("payload-decode", True)

    # signature: at least one envelope signature must verify; with a pinned key, against THAT key
    keys = {k.get("keyid"): k.get("public_key_hex")
            for k in (bundle.get("verification") or {}).get("public_keys", [])}
    pae = _pae(PAYLOAD_TYPE, payload)
    signed_by, signer_pub = None, None
    for s in env.get("signatures", []):
        pub_hex = pinned_pub_hex or keys.get(s.get("keyid"))
        if not pub_hex:
            continue
        try:
            pub, sig = bytes.fromhex(pub_hex), base64.b64decode(s.get("sig", ""), validate=True)
        except (ValueError, TypeError):
            continue
        if ed25519.verify(pub, pae, sig):
            signed_by, signer_pub = _keyid(pub), pub
            break
    if not chk("signature", signed_by is not None,
               ("no signature verifies against the pinned key" if pinned_pub_hex
                else "no signature verifies against an embedded key"),
               ok_detail="ed25519, keyid %s%s" % ((signed_by or "")[:16],
                                                  " (pinned)" if pinned_pub_hex else "")):
        return False, checks

    # the SSHSIG: same payload, same key, OpenSSH envelope - the `ssh-keygen -Y verify` path.
    # The DSSE key and SSH key must be the SAME key (no mix-and-match split possible).
    ssh = bundle.get("ssh") or {}
    # Require the SSH layer whenever the bundle CLAIMS to be current. `schema` lives OUTSIDE the
    # signed payload, so trusting it alone lets an attacker strip the ssh block and relabel a
    # modern bundle `@1` to skip this check. The predicateType is INSIDE the signed statement and
    # is the modern (GitHub-rooted) URI on every current bundle -> gate on it too. Genuine pre-0.5
    # bundles carry the legacy calma.dev predicate and stay SSH-optional.
    modern = statement.get("predicateType") == PREDICATE_TYPE
    if ssh or bundle.get("schema") == BUNDLE_SCHEMA or modern:
        ok_ssh, detail = (sshsig.verify(ssh.get("signature", ""), payload, expect_pub=signer_pub)
                          if ssh.get("signature") else (False, "ssh block missing"))
        if ok_ssh:
            try:
                ok_ssh, detail = (sshsig.parse_pub_line(ssh.get("public_key", "")) == signer_pub,
                                  detail)
                if not ok_ssh:
                    detail = "ssh.public_key line is not the DSSE signing key"
            except ValueError as e:
                ok_ssh, detail = False, str(e)
        if not chk("ssh-signature", ok_ssh, detail,
                   ok_detail="verifiable with ssh-keygen -Y verify (namespace %s)" % sshsig.NAMESPACE):
            return False, checks
    else:
        chk("ssh-signature", True, ok_detail="absent (pre-0.5 bundle; DSSE signature still binds)")

    # statement structure + subject digest binds the signature to the exact ledger bytes
    pred = statement.get("predicate") or {}
    led, manifest = pred.get("ledger"), pred.get("manifest") or {}
    if not chk("statement", statement.get("_type") == STATEMENT_TYPE
               and statement.get("predicateType") in PREDICATE_TYPES_ACCEPTED
               and isinstance(led, dict), "not a calma verdict Statement v1"):
        return False, checks
    subj = (statement.get("subject") or [{}])[0]
    if not chk("subject-digest",
               (subj.get("digest") or {}).get("sha256") == hashlib.sha256(_canonical(led)).hexdigest(),
               "subject sha256 != canonical embedded ledger"):
        return False, checks
    chk("manifest", _manifest_root_consistent(manifest),
        "manifest root hash != recomputed from its file lines")

    # the teeth: every stored verdict label must re-derive byte-for-byte from its verdict_inputs
    code, info = LED.validate_obj(led)
    chk("ledger-rederive", code != 2,
        "; ".join(info.get("errors", []))[:300] if code == 2 else "",
        ok_detail="all verdict labels re-derive; gate %s" % ("clean" if code == 0 else "not-clean"))
    chk("verdict-binding", pred.get("verdict") == led.get("repo_verdict"),
        "statement verdict %r != ledger repo_verdict %r"
        % (pred.get("verdict"), led.get("repo_verdict")))
    # the VSA claim summary must be exactly what the ledger derives (no split between the
    # human-auditable predicate.claims and the machine-validated ledger). Applies to both the
    # GitHub-rooted predicate and the legacy calma.dev one (same VSA shape).
    if statement.get("predicateType") in PREDICATE_TYPES_VSA:
        chk("claims-binding", pred.get("claims") == claims_summary(led),
            "predicate claims summary != derived from the embedded ledger")

    # Layer 1: RFC 3161 timestamps, when present (offline structural + openssl-backed check)
    if bundle.get("timestamps"):
        import rfc3161
        ok_ts, ts_detail = rfc3161.verify_bundle_timestamps(bundle)
        chk("timestamp", ok_ts, ts_detail, ok_detail=ts_detail)

    return all(ok for _, ok, _ in checks), checks


def render_verify(bundle, ok, checks):
    """Human report for `calma attest verify`. Line 1 is the outcome, like every calma report."""
    led = {}
    try:
        led = (json.loads(base64.b64decode(bundle["envelope"]["payload"]))
               .get("predicate", {}).get("ledger") or {})
    except (KeyError, ValueError, TypeError):
        pass
    lines = ["%s  -  %s" % ("ATTESTATION VERIFIED" if ok else "ATTESTATION FAILED",
                            led.get("target", "bundle"))]
    for name, cok, detail in checks:
        lines.append("  %-16s %s%s" % (name, "OK" if cok else "FAIL",
                                       ("  (%s)" % detail) if detail else ""))
    if ok:
        lines.append("  verdict          %s" % led.get("repo_verdict"))
        lines.append("  the bundle is authentically signed and every verdict label re-derives "
                     "from its stored inputs")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
