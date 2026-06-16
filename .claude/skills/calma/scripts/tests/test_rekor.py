"""OPTIONAL Sigstore Rekor transparency-log backing for the catch-history registry.

Unit (no network): DSSE->Rekor + hashedrekord entry construction; the v2 entry-type guard rejects
the dropped intoto/rfc3161 types; RFC 6962 inclusion proofs verify and tamper-fail; the stored
block re-verifies OFFLINE and is bound to the registry entry's content address (tamper the entry,
the proof, the root, or the witnessed digest -> fails); the two honesty tiers (merkle vs anchored).

Integration (gated, default ON - a pure-stdlib in-process Rekor stub over real HTTP, mirroring how
test_attest stands up a local openssl TSA instead of hitting the network): append -> log -> fetch
inclusion proof -> OFFLINE verify passes; tamper -> OFFLINE verify fails; fail-closed leaves nothing
on disk; fail-open writes without a proof; the `calma publish --rekor` + `calma registry verify`
CLI surface drives the real urllib egress end to end.

Pure stdlib. Run: python3 test_rekor.py
"""
import base64
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
import attest as A  # noqa: E402
import ed25519 as E  # noqa: E402
import registry as R  # noqa: E402
import rekor as RK  # noqa: E402

CALMA = os.path.join(SCR, "calma.py")
_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# --- a pure-stdlib RFC 6962 Merkle log, used both as a callable logger and behind the HTTP stub ---

def _lpo2(n):
    """Largest power of two strictly less than n."""
    k = 1
    while k < n:
        k <<= 1
    return k >> 1


class StubRekor:
    """A minimal append-only RFC 6962 Merkle tree that issues real inclusion proofs + a signed
    (C2SP note) checkpoint. Self-contained: no sigstore, no network, no Rekor install."""

    def __init__(self, seed):
        self.leaves = []
        self.seed = seed
        self.pub = E.secret_to_public(seed)

    def _mth(self, leaves):
        if len(leaves) == 1:
            return leaves[0]
        k = _lpo2(len(leaves))
        return RK._hash_children(self._mth(leaves[:k]), self._mth(leaves[k:]))

    def _path(self, m, leaves):
        n = len(leaves)
        if n == 1:
            return []
        k = _lpo2(n)
        if m < k:
            return self._path(m, leaves[:k]) + [self._mth(leaves[k:])]
        return self._path(m - k, leaves[k:]) + [self._mth(leaves[:k])]

    def checkpoint(self, size, root):
        body = "stub-rekor\n%d\n%s\n" % (size, base64.b64encode(root).decode())
        sig = E.sign(self.seed, body.encode())
        return body + "\n— stub " + base64.b64encode(b"\x00\x00\x00\x00" + sig).decode() + "\n"

    def add(self, body):
        """Append a Rekor entry body; return the inclusion-proof response Rekor would return."""
        leaf = RK._hash_leaf(RK._canonical(body))
        idx = len(self.leaves)
        self.leaves.append(leaf)
        root = self._mth(self.leaves)
        return {"inclusionProof": {
            "logIndex": idx, "treeSize": len(self.leaves), "rootHash": root.hex(),
            "hashes": [h.hex() for h in self._path(idx, self.leaves)],
            "checkpoint": self.checkpoint(len(self.leaves), root)}}

    def __call__(self, body, version):  # the registry.append_entry logger hook
        return self.add(body)


def _keys():
    kd = tempfile.mkdtemp()
    os.environ["CALMA_KEY_DIR"] = kd
    info = A.keygen()
    seed = bytes.fromhex(open(info["key_path"]).read().strip())
    return kd, info, seed


# =============================== UNIT (no network) =================================================

# (1) DSSE -> Rekor entry construction, and hashedrekord construction
env = {"payloadType": A.PAYLOAD_TYPE, "payload": base64.b64encode(b'{"_type":"x"}').decode(),
       "signatures": [{"keyid": "abc", "sig": base64.b64encode(b"sig").decode()}]}
dsse = RK.build_entry("dsse", envelope=env)
import hashlib  # noqa: E402
truth(dsse["kind"] == "dsse" and dsse["spec"]["payloadHash"]["value"]
      == hashlib.sha256(b'{"_type":"x"}').hexdigest(),
      "DSSE->Rekor: dsse body wraps the envelope and witnesses sha256(payload)")
truth(dsse["spec"]["signatures"][0]["keyid"] == "abc", "dsse body carries the envelope signatures")
hr = RK.build_entry("hashedrekord", digest_hex="de" * 32, signature_b64="c2ln", public_key_b64="cHVi")
truth(hr["kind"] == "hashedrekord" and hr["spec"]["data"]["hash"]["value"] == "de" * 32,
      "hashedrekord body witnesses the content digest")
truth(RK.witnessed_digest_of(hr) == "de" * 32 and RK.witnessed_digest_of(dsse)
      == dsse["spec"]["payloadHash"]["value"], "witnessed_digest_of reads both entry shapes")

# (2) the v2 entry-type guard: intoto + rfc3161 were DROPPED in v2 and must be hard-rejected
for bad in ("intoto", "rfc3161"):
    try:
        RK.build_entry(bad, digest_hex="00" * 32)
        truth(False, "build_entry(%r) must raise (dropped in Rekor v2)" % bad)
    except ValueError as e:
        truth("v2" in str(e) and bad in str(e), "build_entry rejects %r naming the v2 constraint" % bad)
try:
    RK.assert_v2_entry_type("rfc3161")
    truth(False, "assert_v2_entry_type(rfc3161) must raise")
except ValueError:
    truth(True, "assert_v2_entry_type rejects rfc3161")
try:
    RK.build_entry("bogus", digest_hex="00" * 32)
    truth(False, "unknown entry type must raise")
except ValueError:
    truth(True, "unknown entry type is rejected (only hashedrekord + dsse are emitted)")

# (3) RFC 6962 inclusion proof: verifies, and a tampered proof fails (full sweep is below in the
# cross-check; here a focused case binds the API)
_kd, _info, _seed = _keys()
_logseed = os.urandom(32)
stub = StubRekor(_logseed)
bodies = [RK.build_entry("hashedrekord", digest_hex=("%02x" % i) * 32) for i in range(5)]
resps = [stub.add(b) for b in bodies]
for i, (b, resp) in enumerate(zip(bodies, resps)):
    ip = resp["inclusionProof"]
    leaf = RK._hash_leaf(RK._canonical(b))
    proof = [bytes.fromhex(h) for h in ip["hashes"]]
    # NOTE: re-folds against the root AS OF that append; the stub returns the contemporaneous root
    truth(RK.verify_inclusion(ip["logIndex"], ip["treeSize"], leaf, proof, bytes.fromhex(ip["rootHash"])),
          "RFC6962 inclusion proof verifies for leaf %d" % i)

# (4) the stored block re-verifies OFFLINE, is bound to the entry content address, and tampers fail
digest = "ab" * 32
body = RK.build_entry("hashedrekord", digest_hex=digest)
resp = stub.add(body)
block = RK.build_block("hashedrekord", digest, body, resp, log_url="https://stub.local")
ok, tier, det = RK.verify_inclusion_offline(block, expected_digest=digest)
truth(ok and tier == "merkle", "stored block verifies offline (merkle tier, root self-asserted): %s" % det)
ok_a, tier_a, det_a = RK.verify_inclusion_offline(block, expected_digest=digest, log_pub_hex=stub.pub.hex())
truth(ok_a and tier_a == "anchored", "a pinned log key upgrades to the anchored tier: %s" % det_a)
# wrong log key -> the checkpoint signature fails, so anchoring fails (never falls back to trusting)
ok_w, _, _ = RK.verify_inclusion_offline(block, expected_digest=digest,
                                         log_pub_hex=E.secret_to_public(os.urandom(32)).hex())
truth(not ok_w, "a wrong pinned log key fails the checkpoint anchor")
# cross-check binding: the entry's content address must match what Rekor witnessed
truth(not RK.verify_inclusion_offline(block, expected_digest="cd" * 32)[0],
      "a block whose witnessed digest != the registry entry content address fails (the coupling)")
# tamper the proof
b_proof = copy.deepcopy(block)
b_proof["hashes"][0] = "%064x" % (int(b_proof["hashes"][0], 16) ^ 1) if b_proof["hashes"] else "11" * 32
truth(not RK.verify_inclusion_offline(b_proof, expected_digest=digest)[0],
      "tampering an inclusion-proof hash fails the offline re-fold")
# tamper the root
b_root = copy.deepcopy(block)
b_root["root_hash"] = "%064x" % (int(b_root["root_hash"], 16) ^ 1)
truth(not RK.verify_inclusion_offline(b_root, expected_digest=digest)[0],
      "tampering the stored root fails (proof no longer folds to it)")
# tamper the body (so witnessed digest changes) -> leaf_hash recompute mismatch
b_body = copy.deepcopy(block)
tampered = copy.deepcopy(body)
tampered["spec"]["data"]["hash"]["value"] = "ff" * 32
b_body["body_b64"] = base64.b64encode(RK._canonical(tampered)).decode()
truth(not RK.verify_inclusion_offline(b_body, expected_digest=digest)[0],
      "tampering the stored Rekor body fails (leaf_hash no longer matches)")
# checkpoint that disagrees with the proven root
b_cp = copy.deepcopy(block)
b_cp["checkpoint"] = stub.checkpoint(block["tree_size"], bytes.fromhex("22" * 32))
truth(not RK.verify_inclusion_offline(b_cp, expected_digest=digest)[0],
      "a checkpoint whose root disagrees with the inclusion proof fails")
# pinned key but no checkpoint -> cannot anchor
b_nocp = copy.deepcopy(block)
b_nocp.pop("checkpoint", None)
truth(not RK.verify_inclusion_offline(b_nocp, expected_digest=digest, log_pub_hex=stub.pub.hex())[0],
      "a pinned log key with no checkpoint to anchor fails (never silently downgrades)")

# (5) byte-identical property: the rekor block is wrapper-level; the signed entry bytes are untouched
reg_plain, reg_rek = tempfile.mkdtemp(), tempfile.mkdtemp()
e_open = R.opened_entry("ENG-IDENT")
f_p, w_p = R.append_entry(reg_plain, copy.deepcopy(e_open), _seed)
f_r, w_r = R.append_entry(reg_rek, copy.deepcopy(e_open), _seed,
                          rekor={"url": "https://stub.local", "logger": stub})
truth(w_p["id"] == w_r["id"] and w_p["ssh"]["signature"] == w_r["ssh"]["signature"]
      and "rekor" not in w_p and "rekor" in w_r,
      "the rekor block is additive: entry id + SSHSIG are byte-identical with and without it")


# ======================== INTEGRATION: stub Rekor over real HTTP ==================================
# Gated by CALMA_SKIP_REKOR_HTTP=1 (e.g. sandboxes with no loopback sockets). Default: ON, hermetic.

def _run_http_integration():
    httpseed = os.urandom(32)
    httptree = StubRekor(httpseed)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silence
            pass

        def do_POST(self):
            if not self.path.startswith("/api/v2/log/entries"):
                self.send_response(404)
                self.end_headers()
                return
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n))
            resp = json.dumps(httptree.add(body)).encode()
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(resp)

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    url = "http://127.0.0.1:%d" % port
    try:
        # library path: append -> log over HTTP -> store proof -> OFFLINE verify
        regH = tempfile.mkdtemp()
        fH, wH = R.append_entry(regH, R.opened_entry("ENG-HTTP"), _seed,
                                rekor={"url": url, "version": "v2", "optional": False})
        okH, tierH, _ = RK.verify_inclusion_offline(wH["rekor"], expected_digest=wH["id"],
                                                    log_pub_hex=httptree.pub.hex())
        truth("rekor" in wH and okH and tierH == "anchored",
              "[http] append -> log -> fetch proof -> OFFLINE anchored verify passes")
        # tamper -> offline verify fails
        bad = copy.deepcopy(wH["rekor"])
        bad["root_hash"] = "%064x" % (int(bad["root_hash"], 16) ^ 1)
        truth(not RK.verify_inclusion_offline(bad, expected_digest=wH["id"])[0],
              "[http] tampering the logged root fails offline verification")

        # CLI path: calma publish --rekor (real urllib egress) then calma registry verify
        cli_reg = tempfile.mkdtemp()
        env = dict(os.environ)
        r = subprocess.run([sys.executable, CALMA, "publish", "--open", "ENG-CLI",
                            "--registry", cli_reg, "--rekor", url],
                           capture_output=True, text=True, env=env)
        truth(r.returncode == 0 and "rekor" in r.stdout and "VERIFIES" in r.stdout,
              "[http] `calma publish --rekor` logs + reports an offline-verified proof: %s"
              % (r.stdout + r.stderr).strip().splitlines()[-1:])
        r2 = subprocess.run([sys.executable, CALMA, "registry", "verify", cli_reg,
                             "--rekor-log-key", httptree.pub.hex()],
                            capture_output=True, text=True, env=env)
        truth(r2.returncode == 0 and "inclusion proof" in r2.stdout and "anchored" in r2.stdout,
              "[http] `calma registry verify --rekor-log-key` anchors the inclusion proof: %s"
              % r2.stdout.strip().splitlines())
    finally:
        srv.shutdown()


if os.environ.get("CALMA_SKIP_REKOR_HTTP") != "1":
    try:
        _run_http_integration()
    except OSError as e:
        print("  (skipped HTTP integration: %s)" % e)


# ======================== fail-closed / fail-open (the logging policy) ============================

def _boom(body, version):
    raise OSError("simulated Rekor outage")


# fail-closed (default): a requested log that fails writes NOTHING - no silently un-logged entry
reg_fc = tempfile.mkdtemp()
try:
    R.append_entry(reg_fc, R.opened_entry("ENG-FC"), _seed,
                   rekor={"url": "https://down.local", "logger": _boom, "optional": False})
    truth(False, "fail-closed must raise when Rekor logging fails")
except ValueError as e:
    truth("fail-closed" in str(e) and "no entry was written" in str(e),
          "fail-closed: append raises and names the policy")
truth(R.list_entry_files(reg_fc) == [] and R.read_head(reg_fc) is None,
      "fail-closed leaves NOTHING on disk (no entry, no HEAD) - the entry is not silently un-logged")

# fail-open (--rekor-optional): the entry is written WITHOUT a proof, marked, and still chains
reg_fo = tempfile.mkdtemp()
ffo, wfo = R.append_entry(reg_fo, R.opened_entry("ENG-FO"), _seed,
                          rekor={"url": "https://down.local", "logger": _boom, "optional": True})
truth("rekor" not in wfo and wfo.get("rekor_error"),
      "fail-open: the entry is written without a proof and records the error")
okfo, _, sumfo = R.verify_chain(reg_fo)
truth(okfo and sumfo["rekor"]["pending"] == 1 and sumfo["rekor"]["logged"] == 0,
      "fail-open: the chain still verifies and the audit counts 1 entry pending a proof")

# backward compatibility: append_entry with rekor=None (the default) is unchanged
reg_bc = tempfile.mkdtemp()
_, wbc = R.append_entry(reg_bc, R.opened_entry("ENG-BC"), _seed)
okbc, _, sumbc = R.verify_chain(reg_bc)
truth(okbc and "rekor" not in wbc and sumbc["rekor"]["logged"] == 0,
      "no Rekor configured: entries and audit are exactly as before (additive, default off)")

del os.environ["CALMA_KEY_DIR"]
shutil.rmtree(_kd, ignore_errors=True)

print("rekor: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
