"""calma.rekor - OPTIONAL Sigstore Rekor transparency-log backing for the catch-history registry.

Belt-and-suspenders ON TOP OF the registry's custom hash-chain (registry.py), never a replacement.
When a Rekor endpoint is configured, each registry entry is ALSO submitted to a Rekor transparency
log; the returned inclusion proof is stored alongside the entry so a third party can later verify
the append-only property OFFLINE - with this module, with `rekor-cli`, or by hand - without ever
contacting (or trusting) the log again.

WHY this is safe by construction (the hermetic boundary):
  Rekor lives STRICTLY outside the hermetic boundary. The verdict, the recompute, and the
  determinism stamp are all finalized and written to ledger.json BEFORE anything is signed
  (calma.verify), and the Rekor call happens later still - inside registry.append_entry, only
  AFTER the entry is chained, SSHSIG-signed, and its bytes are frozen. log_entry() is the ONLY
  network egress in this module, and it has no access to (and cannot influence) any verdict
  computation. Rekor being down can at worst block the post-verdict logging step; it can never
  change a verdict, a recompute, or a determinism stamp.

Rekor v2 (GA Oct 2025, tessera-backed) supports ONLY `hashedrekord` + `dsse` entry types - it
dropped `intoto` and `rfc3161`. This module emits only the two supported types and HARD-REJECTS
the dropped ones (assert_v2_entry_type); v2 is the default, a pinned self-hosted v1 is opt-in.

Rekor is Apache-2.0 and self-hostable (github.com/sigstore/rekor); the default is NONE (the
endpoint must be explicitly configured), and the offline inclusion check is pure RFC 6962 Merkle
math - it does not depend on Rekor's API quirks, its availability, or its honesty.

Library:
  assert_v2_entry_type(kind)                      - the v2 entry-type guard
  build_entry(entry_type, ...)                    - a hashedrekord or dsse entry body
  log_entry(url, body, version=)                  - POST to Rekor (the ONLY network egress)
  build_block(entry_type, witnessed_digest, ...)  - the offline-verifiable block we store
  verify_inclusion_offline(block, ...)            - LOCAL cryptographic check; (ok, tier, detail)
  root_from_inclusion_proof(...) / verify_inclusion(...) - RFC 6962 primitives
"""
import base64
import hashlib
import hmac
import json

REKOR_BLOCK_SCHEMA = "calma/rekor-inclusion@1"

# Rekor v2 accepts exactly these. Everything else is refused - intoto/rfc3161 were DROPPED at v2
# GA and must never be emitted (a silent fallback would produce entries no v2 log will accept).
ACCEPTED_ENTRY_TYPES = ("hashedrekord", "dsse")
REJECTED_V2_ENTRY_TYPES = ("intoto", "rfc3161")

DEFAULT_VERSION = "v2"


def _canonical(obj):
    """The byte form a Rekor entry body is hashed over: sorted keys, no whitespace, UTF-8 - the
    same canonicalization discipline the rest of calma uses, so the stored bytes are reproducible."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


# ---- RFC 6962 Merkle inclusion proof (pure stdlib) ---------------------------
# Standard transparency-log math (RFC 6962 sec. 2.1.1), ported from transparency-dev/merkle. The
# OFFLINE verifier's teeth: a stored proof must re-fold the entry's leaf hash to the stored root.

def _hash_leaf(leaf_data):
    """RFC 6962 leaf hash: SHA-256(0x00 || leaf_data). The 0x00 domain-separates leaves from nodes."""
    return hashlib.sha256(b"\x00" + leaf_data).digest()


def _hash_children(left, right):
    """RFC 6962 interior node: SHA-256(0x01 || left || right)."""
    return hashlib.sha256(b"\x01" + left + right).digest()


def _inner_proof_size(index, size):
    return (index ^ (size - 1)).bit_length()


def _chain_inner(seed, proof, index):
    for i, h in enumerate(proof):
        seed = _hash_children(seed, h) if ((index >> i) & 1) == 0 else _hash_children(h, seed)
    return seed


def _chain_border_right(seed, proof):
    for h in proof:
        seed = _hash_children(h, seed)
    return seed


def root_from_inclusion_proof(index, size, leaf_hash, proof):
    """Recompute the Merkle root implied by `leaf_hash` at `index` in a tree of `size` leaves,
    following the inclusion `proof` (a list of sibling hashes, leaf-to-root). Raises on a malformed
    (index, size, proof-length) triple - a wrong-length proof is itself tamper evidence."""
    if size <= 0:
        raise ValueError("tree size must be positive")
    if index >= size:
        raise ValueError("leaf index %d out of range for tree size %d" % (index, size))
    inner = _inner_proof_size(index, size)
    border = bin(index >> inner).count("1")
    if len(proof) != inner + border:
        raise ValueError("inclusion proof has %d hashes, expected %d for (index=%d,size=%d)"
                         % (len(proof), inner + border, index, size))
    res = _chain_inner(leaf_hash, proof[:inner], index)
    return _chain_border_right(res, proof[inner:])


def verify_inclusion(index, size, leaf_hash, proof, root):
    """True iff `proof` proves `leaf_hash` is the leaf at `index` in a tree of `size` with `root`."""
    try:
        calc = root_from_inclusion_proof(index, size, leaf_hash, proof)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calc, root)


# ---- entry construction (the v2 entry-type guard lives here) -----------------

def assert_v2_entry_type(kind):
    """Refuse anything Rekor v2 cannot store. intoto/rfc3161 were dropped at v2 GA (Oct 2025);
    emitting them is a hard error, never a silent fallback to an unsupported type."""
    if kind in REJECTED_V2_ENTRY_TYPES:
        raise ValueError(
            "Rekor v2 does not support %r entries - it dropped intoto + rfc3161 at GA (Oct 2025). "
            "Use one of: %s" % (kind, ", ".join(ACCEPTED_ENTRY_TYPES)))
    if kind not in ACCEPTED_ENTRY_TYPES:
        raise ValueError("unknown Rekor entry type %r - calma emits only %s"
                         % (kind, ", ".join(ACCEPTED_ENTRY_TYPES)))


def hashedrekord_body(digest_hex, signature_b64="", public_key_b64="", algorithm="sha256"):
    """A Rekor v2 `hashedrekord` body witnessing a content digest + the signature over it. For a
    registry entry, digest_hex is the entry's content address (registry.entry_id) - so the leaf
    Rekor witnesses is exactly the value the hash-chain already commits to."""
    return {
        "apiVersion": "0.0.2",  # hashedrekord under Rekor v2
        "kind": "hashedrekord",
        "spec": {
            "data": {"hash": {"algorithm": algorithm, "value": digest_hex}},
            "signature": {"content": signature_b64,
                          "verifier": {"publicKey": {"content": public_key_b64}}},
        },
    }


def dsse_body(envelope):
    """A Rekor v2 `dsse` body wrapping an EXISTING DSSE envelope (payloadType/payload/signatures,
    exactly what attest.make_bundle emits). Witnesses sha256(payload) + the envelope signatures -
    the same payload bytes the local Ed25519 key, the SSHSIG, and any RFC 3161 token already cover."""
    try:
        payload = base64.b64decode(envelope.get("payload", ""), validate=True)
    except (ValueError, TypeError):
        raise ValueError("dsse entry requires an envelope with a base64 payload")
    return {
        "apiVersion": "0.0.1",  # dsse under Rekor v2
        "kind": "dsse",
        "spec": {
            "payloadHash": {"algorithm": "sha256", "value": hashlib.sha256(payload).hexdigest()},
            "signatures": [{"signature": s.get("sig"), "keyid": s.get("keyid")}
                           for s in (envelope.get("signatures") or [])],
        },
    }


def build_entry(entry_type, *, digest_hex=None, signature_b64="", public_key_b64="", envelope=None):
    """A Rekor entry-creation body of the given (v2-legal) type. Raises for intoto/rfc3161 and any
    unknown type. The returned dict's canonical bytes are the Merkle leaf data the log will hash."""
    assert_v2_entry_type(entry_type)
    if entry_type == "hashedrekord":
        if not digest_hex:
            raise ValueError("hashedrekord requires a digest (the content address to witness)")
        return hashedrekord_body(digest_hex, signature_b64, public_key_b64)
    if not envelope:
        raise ValueError("dsse entry requires a DSSE envelope")
    return dsse_body(envelope)


def witnessed_digest_of(body):
    """The content digest a body commits to: hashedrekord -> data.hash.value, dsse -> payloadHash.
    Used to bind the Rekor leaf to the registry entry's content address on offline verification."""
    spec = (body or {}).get("spec") or {}
    if body.get("kind") == "hashedrekord":
        return ((spec.get("data") or {}).get("hash") or {}).get("value")
    if body.get("kind") == "dsse":
        return (spec.get("payloadHash") or {}).get("value")
    return None


# ---- the network step (the ONLY egress; strictly post-verdict) ----------------

def log_entry(rekor_url, body, version=DEFAULT_VERSION, timeout=30):
    """POST `body` to a Rekor instance and return the created TransparencyLogEntry (parsed JSON).

    THIS IS THE ONLY NETWORK EGRESS in the Rekor path. It runs strictly AFTER the verdict,
    recompute, determinism stamp, hash-chain, and SSHSIG are finalized (see registry.append_entry):
    Rekor availability can never alter a verdict - at worst it blocks the post-verdict log step.
    Raises OSError (network) or ValueError (bad response) - callers map that to fail-closed/open."""
    import urllib.request
    path = "/api/v2/log/entries" if version == "v2" else "/api/v1/log/entries"
    url = rekor_url.rstrip("/") + path
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    try:
        return json.loads(raw)
    except ValueError:
        raise ValueError("Rekor returned a non-JSON response")


def _extract_inclusion(tlog_entry):
    """Pull the inclusion proof out of Rekor's response, defensive across v1/v2 shapes.
    Returns (log_index, tree_size, root_hash_hex, [hash_hex...], checkpoint_text|None)."""
    te = tlog_entry
    # v1 returns {uuid: entry}; unwrap a single-key envelope that isn't itself the entry
    if (isinstance(te, dict) and len(te) == 1
            and not ({"inclusionProof", "inclusion_proof", "verification"} & set(te))):
        te = next(iter(te.values()))
    ip = (te.get("inclusionProof") or te.get("inclusion_proof")
          or (te.get("verification") or {}).get("inclusionProof")
          or (te.get("verification") or {}).get("inclusion_proof") or {})

    def g(*names, default=None):
        for n in names:
            if ip.get(n) is not None:
                return ip[n]
        return default

    cp = g("checkpoint")
    if isinstance(cp, dict):
        cp = cp.get("envelope") or cp.get("body")
    hashes = [h.lower() for h in (g("hashes", default=[]) or [])]
    return (g("logIndex", "log_index"), g("treeSize", "tree_size"),
            (g("rootHash", "root_hash") or "").lower() or None, hashes, cp)


def build_block(entry_type, witnessed_digest, body, tlog_entry, *, log_url=None,
                version=DEFAULT_VERSION):
    """Normalize Rekor's response into the self-contained, offline-verifiable block stored in the
    registry wrapper (wrapper["rekor"]). Stores the canonical body bytes so the leaf hash is
    recomputable locally, and the inclusion proof so the root is recomputable locally. log_url is
    provenance only - it is NEVER consulted (or trusted) during offline verification."""
    log_index, tree_size, root_hash, hashes, checkpoint = _extract_inclusion(tlog_entry)
    body_bytes = _canonical(body)
    block = {
        "schema": REKOR_BLOCK_SCHEMA,
        "entry_type": entry_type,
        "log_url": log_url,
        "log_version": version,
        "log_index": log_index,
        "tree_size": tree_size,
        "root_hash": root_hash,
        "leaf_hash": _hash_leaf(body_bytes).hex(),
        "body_b64": base64.b64encode(body_bytes).decode(),
        "witnessed_digest": witnessed_digest,
        "hashes": hashes,
        "checkpoint": checkpoint,
    }
    return {k: v for k, v in block.items() if v is not None}


# ---- checkpoint (C2SP signed note) parse + verify ----------------------------

def parse_checkpoint(text):
    """Parse a Rekor/C2SP signed-note checkpoint. Returns {origin, size, root_hash, signed_bytes,
    signatures:[(name, key_hint, sig_bytes)]}. signed_bytes is exactly what each signature covers."""
    if not isinstance(text, str):
        raise ValueError("checkpoint is not text")
    parts = text.split("\n\n", 1)
    body = parts[0]
    sig_block = parts[1] if len(parts) > 1 else ""
    lines = body.split("\n")
    if len(lines) < 3:
        raise ValueError("checkpoint body has too few lines")
    origin, size_s, root_b64 = lines[0], lines[1], lines[2]
    try:
        size = int(size_s)
        root = base64.b64decode(root_b64, validate=True)
    except (ValueError, TypeError):
        raise ValueError("checkpoint size/root malformed")
    sigs = []
    for ln in sig_block.split("\n"):
        ln = ln.strip()
        if not ln.startswith("— "):  # the em-dash + space sig prefix
            continue
        try:
            _, name, b64 = ln.split(" ", 2)
            raw = base64.b64decode(b64, validate=True)
        except (ValueError, TypeError):
            continue
        # raw = 4-byte key hint || signature
        if len(raw) >= 4:
            sigs.append((name, raw[:4], raw[4:]))
    return {"origin": origin, "size": size, "root_hash": root.hex(),
            "signed_bytes": (body + "\n").encode(), "signatures": sigs}


def verify_checkpoint(text, log_pub):
    """(ok, detail). True iff the checkpoint note carries a valid Ed25519 signature by `log_pub`
    (32 raw bytes). This is what upgrades the offline proof from 'root self-asserted' to 'root
    anchored by the log's key'. Without a pinned key the caller stays in the lower tier."""
    import ed25519
    try:
        cp = parse_checkpoint(text)
    except ValueError as e:
        return False, str(e)
    for _name, _hint, sig in cp["signatures"]:
        if len(sig) == 64 and ed25519.verify(log_pub, cp["signed_bytes"], sig):
            return True, "checkpoint signature verifies (root anchored by the pinned log key)"
    return False, "no checkpoint signature verifies against the pinned Rekor log key"


# ---- the offline verifier (local, cryptographic, never trusts Rekor) ---------

def verify_inclusion_offline(block, expected_digest=None, log_pub_hex=None):
    """LOCAL cryptographic verification of a stored Rekor inclusion proof. Never contacts Rekor and
    never trusts it. Returns (ok, tier, detail).

    Binds three things, all offline:
      1. body  <-> leaf : leaf_hash == SHA-256(0x00 || stored body bytes)
      2. body  <-> digest: the body commits to witnessed_digest, and (when given) that equals
         expected_digest - the registry entry's content address. Tamper the entry and this fails.
      3. leaf  <-> root : the inclusion proof re-folds the leaf to the stored root (RFC 6962).

    Two honesty tiers (mirrors rfc3161's structural-vs-chain-verified discipline):
      - "anchored": a pinned log key (log_pub_hex) verifies the checkpoint note's signature, so the
        root itself is non-repudiable - full belt-and-suspenders.
      - "merkle": the proof re-folds to the stored root, but no log key was pinned, so the root is
        SELF-ASSERTED (the log could have presented a different tree). Reported honestly, never as a
        proven anchor.
    A present-but-invalid proof returns ok=False; an absent block is the caller's concern (additive).
    """
    if (block or {}).get("schema") != REKOR_BLOCK_SCHEMA:
        return False, "none", "not a %s block" % REKOR_BLOCK_SCHEMA
    try:
        body_bytes = base64.b64decode(block.get("body_b64", ""), validate=True)
        body = json.loads(body_bytes)
    except (ValueError, TypeError):
        return False, "none", "stored Rekor body is not base64 JSON"

    # (1) body <-> leaf
    leaf = _hash_leaf(body_bytes)
    if leaf.hex() != (block.get("leaf_hash") or ""):
        return False, "none", "leaf_hash != SHA-256(0x00 || stored body) - body was altered"

    # (2) body <-> witnessed digest <-> registry entry content address
    wd = witnessed_digest_of(body)
    if wd != block.get("witnessed_digest"):
        return False, "none", "stored witnessed_digest != the digest the Rekor body commits to"
    if expected_digest is not None and wd != expected_digest:
        return False, "none", ("Rekor entry witnesses %s but the registry entry's content address "
                               "is %s - the logged entry is not this entry"
                               % (str(wd)[:16], str(expected_digest)[:16]))

    # (3) leaf <-> root (the Merkle inclusion proof)
    try:
        idx, size = int(block["log_index"]), int(block["tree_size"])
        proof = [bytes.fromhex(h) for h in block.get("hashes", [])]
        root = bytes.fromhex(block.get("root_hash", ""))
    except (KeyError, ValueError, TypeError):
        return False, "none", "inclusion proof fields are malformed"
    if not verify_inclusion(idx, size, leaf, proof, root):
        return False, "none", "inclusion proof does not re-fold the leaf to the stored root"

    # checkpoint: must at least agree with the proven root; a pinned key upgrades the tier
    cp_text = block.get("checkpoint")
    if cp_text:
        try:
            cp = parse_checkpoint(cp_text)
        except ValueError as e:
            return False, "none", "checkpoint malformed: %s" % e
        if cp["root_hash"] != block.get("root_hash") or cp["size"] != size:
            return False, "none", "checkpoint root/size disagrees with the inclusion proof"
    if log_pub_hex:
        if not cp_text:
            return False, "none", "a log key was pinned but the entry carries no checkpoint to anchor"
        try:
            ok_cp, det = verify_checkpoint(cp_text, bytes.fromhex(log_pub_hex))
        except (ValueError, TypeError):
            return False, "none", "pinned Rekor log key is not valid hex"
        if not ok_cp:
            return False, "none", det
        return True, "anchored", ("included in tree size %d at index %d; %s" % (size, idx, det))

    return True, "merkle", ("included in tree size %d at index %d; root SELF-ASSERTED "
                            "(no Rekor log key pinned - pass one to anchor it)" % (size, idx))
