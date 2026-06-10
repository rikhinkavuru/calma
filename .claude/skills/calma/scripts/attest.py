"""calma.attest - content-addressed SBOM re-run manifest + the signed attestation bundle.

Manifest: SHA-256 over sorted `relpath:sha256` lines (the manifest's own hash excluded). Lets a
verdict be independently re-checked.

Bundle: a DSSE envelope (the exact envelope Sigstore countersigns) over an in-toto Statement v1
whose predicate embeds the FULL ledger + manifest, signed with a local Ed25519 key (ed25519.py,
pure stdlib). `verify_bundle` is the counterparty side and is fully offline: it checks the
signature, then re-derives every verdict label byte-for-byte via ledger.validate_obj - so even a
bundle re-signed by an attacker with their own key cannot carry a forged verdict label, and a
pinned key (--key) catches the re-signing itself. Sigstore later = append to envelope.signatures
and add tlog material under "verification"; the signed payload bytes never change.

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


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
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
        "predicateType": "https://calma.dev/attestation/verification/v1",
        "predicate": {
            "builder": {"id": "https://calma.dev/skill"},
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

BUNDLE_SCHEMA = "calma/attestation-bundle@1"
PAYLOAD_TYPE = "application/vnd.in-toto+json"
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://calma.dev/attestation/verification/v1"
BUNDLE_NAME = "attestation.bundle.json"
DEFAULT_KEY_DIR = "~/.calma/keys"


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


def keygen(kdir=None, force=False):
    """Generate a local Ed25519 keypair (hex seed at 0600 + hex public key). Refuses to overwrite."""
    sk_path, pk_path = _key_paths(kdir)
    if os.path.exists(sk_path) and not force:
        raise ValueError("a signing key already exists at %s (pass --force to overwrite)" % sk_path)
    os.makedirs(os.path.dirname(sk_path), exist_ok=True)
    seed = os.urandom(32)
    pub = ed25519.secret_to_public(seed)
    fd = os.open(sk_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w") as fh:
        fh.write(seed.hex() + "\n")
    with open(pk_path, "w") as fh:
        fh.write(pub.hex() + "\n")
    return {"key_path": sk_path, "pub_path": pk_path,
            "public_key": pub.hex(), "keyid": _keyid(pub)}


def load_signing_key(path=None):
    """The 32-byte seed from a key file (or the default location). None if absent/unreadable."""
    path = path or _key_paths()[0]
    try:
        seed = bytes.fromhex(open(path).read().strip())
    except (OSError, ValueError):
        return None
    return seed if len(seed) == 32 else None


def _pae(payload_type, payload):
    """DSSE v1 pre-authentication encoding - the exact bytes that are signed."""
    return b"DSSEv1 %d %s %d %s" % (len(payload_type), payload_type.encode(),
                                    len(payload), payload)


def bundle_statement(led, manifest):
    """in-toto Statement v1 whose subject is the canonical ledger digest and whose predicate
    embeds the full ledger + manifest, so the counterparty can re-derive every verdict offline."""
    return {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": led.get("target", "run"),
                     "digest": {"sha256": hashlib.sha256(_canonical(led)).hexdigest()}}],
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "builder": {"id": "https://calma.dev/skill"},
            "verdict": led.get("repo_verdict"),
            "scope": led.get("scope"),
            "ledger": led,
            "manifest": manifest,
            "materials": [{"uri": f["path"], "digest": {"sha256": f["sha256"]}}
                          for f in (manifest or {}).get("files", [])],
        },
    }


def make_bundle(led, manifest, seed):
    """Sign the statement into a self-contained DSSE bundle. Deterministic for a given key+ledger."""
    payload = _canonical(bundle_statement(led, manifest))
    pub = ed25519.secret_to_public(seed)
    sig = ed25519.sign(seed, _pae(PAYLOAD_TYPE, payload))
    return {
        "schema": BUNDLE_SCHEMA,
        "envelope": {
            "payloadType": PAYLOAD_TYPE,
            "payload": base64.b64encode(payload).decode(),
            "signatures": [{"keyid": _keyid(pub), "sig": base64.b64encode(sig).decode()}],
        },
        "verification": {
            "public_keys": [{"keyid": _keyid(pub), "scheme": "ed25519",
                             "public_key_hex": pub.hex()}],
        },
    }


def sign_run(run_dir, key_path=None, out=None):
    """Sign a completed run dir's ledger.json (+ manifest.json if present) into BUNDLE_NAME."""
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
    bundle = make_bundle(led, manifest, seed)
    out = out or os.path.join(run_dir, BUNDLE_NAME)
    json.dump(bundle, open(out, "w"), indent=2)
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

    env = bundle.get("envelope") or {}
    if not chk("schema", bundle.get("schema") == BUNDLE_SCHEMA,
               "expected %s" % BUNDLE_SCHEMA):
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
    signed_by = None
    for s in env.get("signatures", []):
        pub_hex = pinned_pub_hex or keys.get(s.get("keyid"))
        if not pub_hex:
            continue
        try:
            pub, sig = bytes.fromhex(pub_hex), base64.b64decode(s.get("sig", ""), validate=True)
        except (ValueError, TypeError):
            continue
        if ed25519.verify(pub, pae, sig):
            signed_by = _keyid(pub)
            break
    if not chk("signature", signed_by is not None,
               ("no signature verifies against the pinned key" if pinned_pub_hex
                else "no signature verifies against an embedded key"),
               ok_detail="ed25519, keyid %s%s" % ((signed_by or "")[:16],
                                                  " (pinned)" if pinned_pub_hex else "")):
        return False, checks

    # statement structure + subject digest binds the signature to the exact ledger bytes
    pred = statement.get("predicate") or {}
    led, manifest = pred.get("ledger"), pred.get("manifest") or {}
    if not chk("statement", statement.get("_type") == STATEMENT_TYPE
               and statement.get("predicateType") == PREDICATE_TYPE
               and isinstance(led, dict), "not a calma verification Statement v1"):
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
