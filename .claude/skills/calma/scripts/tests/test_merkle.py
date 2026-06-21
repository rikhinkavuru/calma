"""M1: calma as its own RFC 6962 transparency log + offline-re-verifiable .proof bundles. The tree/proof
BUILDERS (merkle.py) are validated against (a) RFC 6962 hand-computed roots and (b) rekor.py's INDEPENDENT
verifier (root_from_inclusion_proof / verify_checkpoint), so a builder/verifier drift is impossible. The
.proof bundle re-verifies OFFLINE (self-asserted -> anchored by the log key -> witnessed by a quorum), and
any tamper fails. Pure stdlib. Run: python3 test_merkle.py
"""
import hashlib
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import ed25519  # noqa: E402
import merkle as M  # noqa: E402
import rekor as RK  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def _hl(d):
    return hashlib.sha256(b"\x00" + d).digest()


def _hc(left, right):
    return hashlib.sha256(b"\x01" + left + right).digest()


# ---- RFC 6962 roots, hand-computed from the definition (independent of merkle.py's recursion) ----------
L = [bytes([i]) for i in range(4)]
truth(M.merkle_root([]) == hashlib.sha256(b"").digest(), "MTH({}) = SHA256('')")
truth(M.merkle_root(L[:1]) == _hl(L[0]), "MTH({d0}) = hash_leaf(d0)")
truth(M.merkle_root(L[:2]) == _hc(_hl(L[0]), _hl(L[1])), "MTH(2) = hash_children(hl0, hl1)")
truth(M.merkle_root(L[:3]) == _hc(_hc(_hl(L[0]), _hl(L[1])), _hl(L[2])), "MTH(3) splits at k=2")
truth(M.merkle_root(L[:4]) == _hc(_hc(_hl(L[0]), _hl(L[1])), _hc(_hl(L[2]), _hl(L[3]))), "MTH(4) balanced")

# ---- inclusion proofs: builder <-> rekor's INDEPENDENT verifier, every leaf, n = 1..24 ----------------
ok_incl = True
for n in range(1, 25):
    leaves = [hashlib.sha256(bytes([n, i])).digest() for i in range(n)]
    root = M.merkle_root(leaves)
    for m in range(n):
        if not RK.verify_inclusion(m, n, RK._hash_leaf(leaves[m]), M.inclusion_proof(leaves, m), root):
            ok_incl = False
truth(ok_incl, "inclusion_proof refolds to the root via rekor's verifier (all leaves, n=1..24)")
# a tampered leaf must NOT verify
_lv = [hashlib.sha256(bytes([7, i])).digest() for i in range(7)]
truth(not RK.verify_inclusion(3, 7, RK._hash_leaf(b"forged"), M.inclusion_proof(_lv, 3), M.merkle_root(_lv)),
      "inclusion: a forged leaf does NOT verify")

# ---- consistency proofs: append-only (size-m prefix of size-n), build <-> verify + tamper -------------
ok_cons = True
for n in range(2, 22):
    leaves = [hashlib.sha256(bytes([55, i])).digest() for i in range(n)]
    for m in range(1, n):
        cp = M.consistency_proof(leaves, m)
        if not M.verify_consistency(m, n, M.merkle_root(leaves[:m]), M.merkle_root(leaves), cp):
            ok_cons = False
truth(ok_cons, "consistency_proof proves the size-m tree is a prefix of size-n (n=2..21)")
_cv = [hashlib.sha256(bytes([9, i])).digest() for i in range(9)]
truth(not M.verify_consistency(4, 9, RK._hash_leaf(b"forked-history"), M.merkle_root(_cv),
                               M.consistency_proof(_cv, 4)), "consistency: a forked old-root is rejected")

# ---- signed checkpoint: build -> rekor.verify_checkpoint (+ wrong-key reject) -------------------------
seed = hashlib.sha256(b"log-key").digest()
pub_hex = ed25519.secret_to_public(seed).hex()
ck = M.build_checkpoint("calma-registry", 4, M.merkle_root(L), seed)
truth(RK.verify_checkpoint(ck, bytes.fromhex(pub_hex))[0], "checkpoint signature verifies under the log key")
truth(not RK.verify_checkpoint(ck, ed25519.secret_to_public(hashlib.sha256(b"x").digest()))[0],
      "checkpoint: a wrong key does NOT verify")

# ---- the .proof bundle: build on a registry, re-verify OFFLINE, tier by tier --------------------------
_dir = tempfile.mkdtemp(prefix="calma_mk_")
edir = os.path.join(_dir, "entries")
os.makedirs(edir)
ids = []
for i in range(6):
    cid = hashlib.sha256(("entry-%d" % i).encode()).hexdigest()  # stand-in for registry.entry_id
    ids.append(cid)
    json.dump({"entry": {"seq": i, "verdict": "REFUTED"}, "id": cid},
              open(os.path.join(edir, "%d-%s.json" % (i, cid[:12])), "w"))

bundle = M.build_proof_bundle(_dir, 3, seed)  # prove entry seq=3
truth(bundle["schema"] == M.PROOF_SCHEMA and bundle["size"] == 6 and bundle["index"] == 3,
      "build_proof_bundle: index/size for the requested entry")
truth(verify := M.verify_proof_bundle(bundle)[0], "proof bundle re-verifies OFFLINE (self-asserted tier)")
truth(M.verify_proof_bundle(bundle)[1] == "self-asserted", "tier = self-asserted with no pinned key")
truth(M.verify_proof_bundle(bundle, log_pub_hex=pub_hex)[1] == "anchored",
      "tier = anchored when the calma log key is pinned")
truth(M.verify_proof_bundle(bundle, log_pub_hex="00" * 32)[0] is False,
      "proof bundle: a wrong pinned log key FAILS (no false anchor)")

# a tampered leaf in the bundle breaks the root match -> fails (the whole point: offline tamper-evidence)
tampered = dict(bundle, leaf=hashlib.sha256(b"swapped").hexdigest())
truth(M.verify_proof_bundle(tampered)[0] is False, "proof bundle: a swapped leaf FAILS the root check")
tampered2 = dict(bundle, size=7)
truth(M.verify_proof_bundle(tampered2)[0] is False, "proof bundle: a forged tree size FAILS")

# ---- witness cosignature: a diverse-operator quorum on the SAME tree head -----------------------------
wseed = hashlib.sha256(b"witness-operator").digest()
wpub_hex = ed25519.secret_to_public(wseed).hex()
bundle["checkpoint"] = M.add_witness(bundle["checkpoint"], wseed, "witness-1")
ok_w, tier_w, _ = M.verify_proof_bundle(bundle, log_pub_hex=pub_hex, witness_pub_hexes=[wpub_hex])
truth(ok_w and tier_w == "witnessed", "tier = witnessed when >=1 pinned external witness cosigned the head")
truth(M.verify_proof_bundle(bundle, log_pub_hex=pub_hex, witness_pub_hexes=["11" * 32])[1] == "anchored",
      "witness: an unknown witness key does not upgrade the tier")

print("merkle: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
