"""calma.merkle - M1: calma as its OWN RFC 6962 transparency log + offline-re-verifiable `.proof` bundles.

The registry (registry.py) is a hash CHAIN; this layers an RFC 6962 Merkle TREE over the same entries so a
published catch carries a self-contained `.proof` bundle - {leaf, inclusion proof, a calma-signed
checkpoint [+ witness cosignatures]} - that re-verifies OFFLINE, with no calma server in the loop, even
years later. The crypto is IDENTICAL to the Rekor path (rekor.py: SHA-256, RFC 6962 leaf/node hashing, C2SP
signed-note checkpoints, Ed25519). rekor.py already has the VERIFIER side (root_from_inclusion_proof /
parse/verify_checkpoint); this adds the TREE + PROOF BUILDERS + the CONSISTENCY proof, REUSING rekor's exact
hash functions so a builder/verifier mismatch is impossible.

Leaf = the registry entry's content address (registry.entry_id = sha256 over the canonical entry, prev
included, so it commits the whole chain). The log stays tiny (32 B/leaf); the evidence lives in the entry.

Library: merkle_root · inclusion_proof · consistency_proof · verify_consistency · build_checkpoint ·
add_witness · build_proof_bundle · verify_proof_bundle.
"""
import base64
import hashlib
import hmac
import json
import os

import ed25519
import rekor as RK

PROOF_SCHEMA = "calma/merkle-proof@1"
DEFAULT_ORIGIN = "calma-registry"


# ---- RFC 6962 tree + proof BUILDERS (the verifier side lives in rekor.py; same _hash_* functions) -----

def _pow2_below(n):
    """Largest power of 2 strictly less than n (n >= 2)."""
    return 1 << ((n - 1).bit_length() - 1)


def merkle_root(leaves):
    """RFC 6962 Merkle Tree Hash over `leaves` (leaf-DATA bytes). MTH({})=SHA256(b''),
    MTH({d})=hash_leaf(d), else hash_children(MTH(left), MTH(right)) split at the largest pow2 < n."""
    n = len(leaves)
    if n == 0:
        return hashlib.sha256(b"").digest()
    if n == 1:
        return RK._hash_leaf(leaves[0])
    k = _pow2_below(n)
    return RK._hash_children(merkle_root(leaves[:k]), merkle_root(leaves[k:]))


def inclusion_proof(leaves, m):
    """RFC 6962 PATH(m, D): sibling hashes (leaf-to-root) proving leaf m is in the tree - the exact format
    rekor.root_from_inclusion_proof consumes."""
    n = len(leaves)
    if not (0 <= m < n):
        raise ValueError("leaf index %d out of range for %d leaves" % (m, n))
    if n == 1:
        return []
    k = _pow2_below(n)
    if m < k:
        return inclusion_proof(leaves[:k], m) + [merkle_root(leaves[k:])]
    return inclusion_proof(leaves[k:], m - k) + [merkle_root(leaves[:k])]


def consistency_proof(leaves, m):
    """RFC 6962 PROOF(m, D[n]) for 0 < m <= n: proves the size-m tree is a prefix of the size-n tree
    (append-only). Returns sibling hashes."""
    n = len(leaves)
    if not (0 < m <= n):
        raise ValueError("consistency m=%d invalid for n=%d" % (m, n))
    return _subproof(m, leaves, True)


def _subproof(m, leaves, b):
    n = len(leaves)
    if m == n:
        return [] if b else [merkle_root(leaves)]
    k = _pow2_below(n)
    if m <= k:
        return _subproof(m, leaves[:k], b) + [merkle_root(leaves[k:])]
    return _subproof(m - k, leaves[k:], False) + [merkle_root(leaves[:k])]


def _chain_inner_right(seed, proof, index):
    """Like rekor._chain_inner but only folds the RIGHT-branch siblings (bit==1) - the old-root half of a
    consistency proof (transparency-dev chainInnerRight)."""
    for i, h in enumerate(proof):
        if (index >> i) & 1 == 1:
            seed = RK._hash_children(h, seed)
    return seed


def verify_consistency(m, n, root1, root2, proof):
    """True iff `proof` proves the size-m tree (root1) is a prefix of the size-n tree (root2). RFC 6962
    sec 2.1.2 verification (ported from transparency-dev/merkle), reusing rekor's node hash."""
    try:
        if m > n:
            return False
        if m == n:
            return not proof and hmac.compare_digest(root1, root2)
        if m == 0:
            return not proof
        if not proof:
            return False
        inner = RK._inner_proof_size(m - 1, n)
        border = bin((m - 1) >> inner).count("1")
        shift = (m & -m).bit_length() - 1  # trailing zeros of m
        inner -= shift
        if m == (1 << shift):
            seed, start = root1, 0
        else:
            seed, start = proof[0], 1
        if len(proof) != start + inner + border:
            return False
        p = proof[start:]
        mask = (m - 1) >> shift
        h1 = RK._chain_border_right(_chain_inner_right(seed, p[:inner], mask), p[inner:])
        if not hmac.compare_digest(h1, root1):
            return False
        h2 = RK._chain_border_right(RK._chain_inner(seed, p[:inner], mask), p[inner:])
        return hmac.compare_digest(h2, root2)
    except (ValueError, TypeError, IndexError):
        return False


# ---- C2SP signed-note checkpoint (BUILD side; rekor.parse/verify_checkpoint is the verify side) --------

def _keyhint(name, pub):
    """C2SP/Sigsum 4-byte key hint = first 4 bytes of SHA-256(name || '\\n' || 0x01 || pub)."""
    return hashlib.sha256(name.encode() + b"\n" + b"\x01" + pub).digest()[:4]


def build_checkpoint(origin, size, root, seed, name="calma"):
    """A C2SP signed-note checkpoint over (origin, size, root): the 3-line body, then an Ed25519 signature
    line `— <name> base64(keyhint||sig)`. Verifiable by rekor.verify_checkpoint(text, pub)."""
    body = "%s\n%d\n%s" % (origin, size, base64.b64encode(root).decode())
    signed = (body + "\n").encode()
    pub = ed25519.secret_to_public(seed)
    sig = ed25519.sign(seed, signed)
    line = "— %s %s" % (name, base64.b64encode(_keyhint(name, pub) + sig).decode())
    return body + "\n\n" + line + "\n"


def add_witness(checkpoint, seed, name):
    """Append a WITNESS cosignature line to an existing checkpoint (the same signed body). A diverse-operator
    witness countersigning the tree head converts 'trust calma's key' into 'trust a quorum' (CT's model)."""
    cp = RK.parse_checkpoint(checkpoint)
    pub = ed25519.secret_to_public(seed)
    sig = ed25519.sign(seed, cp["signed_bytes"])
    line = "— %s %s" % (name, base64.b64encode(_keyhint(name, pub) + sig).decode())
    return checkpoint.rstrip("\n") + "\n" + line + "\n"


# ---- registry -> leaves -------------------------------------------------------------------------------

def _load_leaves(reg_dir):
    """The registry entries in seq order -> (list of leaf-data bytes, list of wrappers). Leaf-data = the
    entry's content address (registry.entry_id, a 32-byte sha256) so the tree binds to the chain."""
    edir = os.path.join(reg_dir, "entries")
    wraps = []
    if os.path.isdir(edir):
        for fn in os.listdir(edir):
            if fn.endswith(".json"):
                try:
                    wraps.append(json.load(open(os.path.join(edir, fn))))
                except (OSError, ValueError):
                    continue
    wraps.sort(key=lambda w: (w.get("entry") or {}).get("seq", 0))
    leaves = [bytes.fromhex(w["id"]) for w in wraps if isinstance(w.get("id"), str)]
    return leaves, wraps


# ---- the .proof bundle: build (online, has the key) / verify (offline, pure) --------------------------

def build_proof_bundle(reg_dir, ref, seed, origin=DEFAULT_ORIGIN, name="calma"):
    """A self-contained inclusion `.proof` bundle for the registry entry named by `ref` (its seq int or its
    content-address id / a prefix). {leaf, index, size, inclusion_proof, a calma-signed checkpoint, the
    redacted entry}. Re-verifies OFFLINE via verify_proof_bundle."""
    leaves, wraps = _load_leaves(reg_dir)
    if not leaves:
        raise ValueError("registry has no entries to prove")
    idx = None
    for i, w in enumerate(wraps):
        e = w.get("entry") or {}
        if str(ref) == str(e.get("seq")) or w.get("id") == ref or (isinstance(ref, str) and w.get("id", "").startswith(ref)):
            idx = i
            break
    if idx is None:
        raise ValueError("no registry entry matches %r" % (ref,))
    size = len(leaves)
    root = merkle_root(leaves)
    proof = inclusion_proof(leaves, idx)
    return {
        "schema": PROOF_SCHEMA, "origin": origin,
        "leaf": leaves[idx].hex(), "index": idx, "size": size,
        "inclusion_proof": [h.hex() for h in proof],
        "checkpoint": build_checkpoint(origin, size, root, seed, name=name),
        "entry": wraps[idx].get("entry"),
    }


def verify_proof_bundle(bundle, log_pub_hex=None, witness_pub_hexes=None):
    """OFFLINE verification of a `.proof` bundle. Returns (ok, tier, detail) with tier in:
      self-asserted - the inclusion proof refolds to the checkpoint's root (no key pinned);
      anchored      - PLUS the checkpoint signature verifies against the pinned calma log key;
      witnessed     - PLUS >=1 pinned external witness cosigned the same tree head.
    No network, no calma server; the verifier is rekor.py's RFC 6962 math + ed25519.py."""
    try:
        if bundle.get("schema") != PROOF_SCHEMA:
            return False, "none", "unexpected schema %r" % bundle.get("schema")
        leaf = bytes.fromhex(bundle["leaf"])
        index, size = int(bundle["index"]), int(bundle["size"])
        proof = [bytes.fromhex(h) for h in bundle["inclusion_proof"]]
        root = RK.root_from_inclusion_proof(index, size, RK._hash_leaf(leaf), proof)
    except (ValueError, TypeError, KeyError) as e:
        return False, "none", "malformed proof bundle: %s" % e
    try:
        cp = RK.parse_checkpoint(bundle["checkpoint"])
    except (ValueError, KeyError) as e:
        return False, "none", "checkpoint unparseable: %s" % e
    if cp["size"] != size or not hmac.compare_digest(bytes.fromhex(cp["root_hash"]), root):
        return False, "none", "checkpoint (size %d, root %s...) does not match the inclusion proof (size %d, root %s...)" \
            % (cp["size"], cp["root_hash"][:12], size, root.hex()[:12])
    tier, detail = "self-asserted", "the inclusion proof refolds to the checkpoint root (root self-asserted)"
    if log_pub_hex:
        ok, d = RK.verify_checkpoint(bundle["checkpoint"], bytes.fromhex(log_pub_hex))
        if not ok:
            return False, "none", "checkpoint signature does not verify against the pinned log key: %s" % d
        tier, detail = "anchored", "root anchored by the pinned calma log key"
    if witness_pub_hexes:
        signed = cp["signed_bytes"]
        n_w = sum(1 for wp in witness_pub_hexes
                  for _n, _h, s in cp["signatures"]
                  if len(s) == 64 and ed25519.verify(bytes.fromhex(wp), signed, s))
        if n_w >= 1:
            tier, detail = "witnessed", "%s + %d external witness cosignature(s) on the same tree head" % (detail, n_w)
        elif log_pub_hex:
            detail += " (no pinned witness cosignature found)"
    return True, tier, detail
