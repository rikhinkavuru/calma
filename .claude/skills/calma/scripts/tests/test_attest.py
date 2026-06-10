"""Attestation chain: pure-stdlib Ed25519 against the RFC 8032 section 7.1 vectors, the DSSE
pre-auth encoding, and the signed bundle end-to-end - including the adversarial cases: tampered
payload, swapped verdict re-signed under the attacker's OWN key (the ledger re-derivation must
catch the forged label), pinned-key mismatch, and malleated signatures. Pure stdlib.
Run: python3 test_attest.py
"""
import base64
import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
import attest as A  # noqa: E402
import calma as C  # noqa: E402
import ed25519 as E  # noqa: E402
import recompute as RC  # noqa: E402

BTC = os.path.realpath(os.path.join(SCR, "..", "assets", "btc"))
_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# --- Ed25519: RFC 8032 section 7.1 test vectors (secret -> public, sign, verify) ---
RFC_VECTORS = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
     "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
     "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
     "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
     "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
     "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
     "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
     "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
]
for i, (sk_h, pk_h, msg_h, sig_h) in enumerate(RFC_VECTORS, 1):
    sk, pk = bytes.fromhex(sk_h), bytes.fromhex(pk_h)
    msg, sig = bytes.fromhex(msg_h), bytes.fromhex(sig_h)
    truth(E.secret_to_public(sk) == pk, "RFC vector %d: public key derivation" % i)
    truth(E.sign(sk, msg) == sig, "RFC vector %d: deterministic signature bytes" % i)
    truth(E.verify(pk, msg, sig), "RFC vector %d: verify accepts" % i)
    truth(not E.verify(pk, msg + b"x", sig), "RFC vector %d: verify rejects altered message" % i)
    flipped = bytearray(sig)
    flipped[0] ^= 1
    truth(not E.verify(pk, msg, bytes(flipped)), "RFC vector %d: verify rejects flipped sig bit" % i)

# malleability: s' = s + L is the classic malleated form - strict verify must reject it
sk, msg = bytes.fromhex(RFC_VECTORS[0][0]), b""
pk, sig = bytes.fromhex(RFC_VECTORS[0][1]), bytes.fromhex(RFC_VECTORS[0][3])
s_mall = (int.from_bytes(sig[32:], "little") + E.L).to_bytes(32, "little")
truth(not E.verify(pk, msg, sig[:32] + s_mall), "verify rejects malleated s + L signature")
truth(not E.verify(pk, msg, sig[:63]), "verify rejects truncated signature")
truth(not E.verify(pk[:31], msg, sig), "verify rejects truncated public key")
wrong_pk = bytes.fromhex(RFC_VECTORS[1][1])
truth(not E.verify(wrong_pk, msg, sig), "verify rejects the wrong public key")

# --- DSSE pre-auth encoding: exact bytes per the DSSE v1 spec ---
truth(A._pae("application/vnd.in-toto+json", b'{"a":1}')
      == b'DSSEv1 28 application/vnd.in-toto+json 7 {"a":1}',
      "DSSE PAE encodes type/payload lengths exactly")

# --- keygen + sign + verify end-to-end on a real verification run ---
tmp_keys = tempfile.mkdtemp()
os.environ["CALMA_KEY_DIR"] = tmp_keys
info = A.keygen()
truth(os.path.exists(info["key_path"]), "keygen writes the seed file")
truth((os.stat(info["key_path"]).st_mode & 0o777) == 0o600, "seed file is 0600")
truth(info["keyid"] == hashlib.sha256(bytes.fromhex(info["public_key"])).hexdigest(),
      "keyid is sha256 of the raw public key")
try:
    A.keygen()
    truth(False, "keygen refuses to overwrite without --force")
except ValueError:
    truth(True, "keygen refuses to overwrite without --force")

# a real REFUTED run on the BTC fixture; auto-sign should fire because a key now exists
res = C.verify(BTC, run_id="test_attest", force=True)
bundle_path = os.path.join(res["run_dir"], A.BUNDLE_NAME)
truth(os.path.exists(bundle_path), "verify auto-signs when a local key exists")
bundle = json.load(open(bundle_path))
ok, checks = A.verify_bundle(bundle)
truth(ok, "auto-signed bundle verifies offline: %s" % [c for c in checks if not c[1]])
truth(res["repo_verdict"] == "REFUTED", "fixture run is REFUTED (the bundle still verifies)")

# explicit sign matches the auto-signed bundle byte-for-byte (deterministic signing)
b2, _ = A.sign_run(res["run_dir"], out=os.path.join(tmp_keys, "again.json"))
truth(A._canonical(b2) == A._canonical(bundle), "signing is deterministic: same run, same bundle")

# pinning: the right key passes, a different key fails
ok_pin, _ = A.verify_bundle(bundle, pinned_pub_hex=info["public_key"])
truth(ok_pin, "verify with the correct pinned key passes")
attacker_seed = bytes.fromhex(RFC_VECTORS[2][0])
ok_wrongpin, checks_wp = A.verify_bundle(bundle, pinned_pub_hex=E.secret_to_public(attacker_seed).hex())
truth(not ok_wrongpin and any(n == "signature" and not o for n, o, _ in checks_wp),
      "verify with a different pinned key fails at the signature check")

# --- tamper cases ---
payload = json.loads(base64.b64decode(bundle["envelope"]["payload"]))

# (1) edit the payload in place (flip the verdict) without re-signing -> signature fails
t1 = copy.deepcopy(bundle)
p1 = copy.deepcopy(payload)
p1["predicate"]["verdict"] = "CONFIRMED"
p1["predicate"]["ledger"]["repo_verdict"] = "CONFIRMED"
t1["envelope"]["payload"] = base64.b64encode(A._canonical(p1)).decode()
ok1, checks1 = A.verify_bundle(t1)
truth(not ok1 and any(n == "signature" and not o for n, o, _ in checks1),
      "tampered payload (REFUTED -> CONFIRMED) fails the signature check")

# (2) the strong attack: attacker forges the labels AND re-signs with their OWN key, embedding it.
# The signature is then valid - the ledger re-derivation is what must catch the forged label.
led_forged = copy.deepcopy(payload["predicate"]["ledger"])
led_forged["repo_verdict"] = "CONFIRMED"
for c in led_forged["claims"]:
    c["verdict"] = "CONFIRMED"  # labels forged; verdict_inputs still say otherwise
t2 = A.make_bundle(led_forged, payload["predicate"]["manifest"], attacker_seed)
ok2, checks2 = A.verify_bundle(t2)
truth(any(n == "signature" and o for n, o, _ in checks2),
      "re-signed forged bundle: attacker's signature itself is valid (by construction)")
truth(not ok2 and any(n == "ledger-rederive" and not o for n, o, _ in checks2),
      "re-signed forged bundle: verdict labels fail byte-for-byte re-derivation")

# (3) statement verdict diverges from the (untouched) embedded ledger -> verdict-binding fails
led_real = payload["predicate"]["ledger"]
t3 = A.make_bundle(led_real, payload["predicate"]["manifest"], attacker_seed)
p3 = json.loads(base64.b64decode(t3["envelope"]["payload"]))
p3["predicate"]["verdict"] = "CONFIRMED"
p3["subject"][0]["digest"]["sha256"] = hashlib.sha256(A._canonical(led_real)).hexdigest()
sig3 = E.sign(attacker_seed, A._pae(A.PAYLOAD_TYPE, A._canonical(p3)))
t3["envelope"]["payload"] = base64.b64encode(A._canonical(p3)).decode()
t3["envelope"]["signatures"][0]["sig"] = base64.b64encode(sig3).decode()
ok3, checks3 = A.verify_bundle(t3)
truth(not ok3 and any(n == "verdict-binding" and not o for n, o, _ in checks3),
      "statement verdict != embedded ledger verdict fails verdict-binding")

# (4) tampered subject digest -> fails before the ledger is even trusted
t4 = copy.deepcopy(bundle)
p4 = copy.deepcopy(payload)
p4["subject"][0]["digest"]["sha256"] = "0" * 64
sig4 = E.sign(bytes.fromhex(open(info["key_path"]).read().strip()),
              A._pae(A.PAYLOAD_TYPE, A._canonical(p4)))
t4["envelope"]["payload"] = base64.b64encode(A._canonical(p4)).decode()
t4["envelope"]["signatures"][0]["sig"] = base64.b64encode(sig4).decode()
ok4, checks4 = A.verify_bundle(t4)
truth(not ok4 and any(n == "subject-digest" and not o for n, o, _ in checks4),
      "tampered subject digest fails even under a valid signature")

# (5) tampered manifest file hash -> manifest root-hash cross-check fails
if payload["predicate"]["manifest"].get("files"):
    man5 = copy.deepcopy(payload["predicate"]["manifest"])
    man5["files"][0]["sha256"] = "f" * 64
    t5 = A.make_bundle(led_real, man5, attacker_seed)
    ok5, checks5 = A.verify_bundle(t5)
    truth(not ok5 and any(n == "manifest" and not o for n, o, _ in checks5),
          "tampered manifest file hash fails the root-hash cross-check")

# (6) garbage / wrong-schema bundles degrade cleanly
ok6, _ = A.verify_bundle({"schema": "something-else"})
truth(not ok6, "wrong schema fails cleanly")
t7 = copy.deepcopy(bundle)
t7["envelope"]["payload"] = "!!!not-base64!!!"
ok7, _ = A.verify_bundle(t7)
truth(not ok7, "non-base64 payload fails cleanly")

# --- a CONFIRMED (clean) run also signs and verifies ---
tmp = tempfile.mkdtemp()
os.makedirs(os.path.join(tmp, "runs", "oos"))
shutil.copy(os.path.join(BTC, "runs", "oos", "returns.csv"),
            os.path.join(tmp, "runs", "oos", "returns.csv"))
rec = RC.recompute_contract(os.path.join(BTC, "verify.yaml"), base=BTC, k=1)
true_val = rec["metrics"][0]["value"]
with open(os.path.join(tmp, "noop.py"), "w") as fh:
    fh.write("pass\n")
with open(os.path.join(tmp, "verify.yaml"), "w") as fh:
    json.dump({"run": {"entrypoint": "noop.py", "network": "off"},
               "env": {"ecosystem": "python-stdlib", "trust": "own-code"},
               "artifacts": [{"path": "runs/oos/returns.csv", "re_emit": False,
                              "columns": {"strat_return": {"tag": "return", "na_policy": "error"}}}],
               "metrics": [{"metric_id": "total_return", "artifact": "runs/oos/returns.csv",
                            "binding": {"return": "strat_return"}, "claimed_value": true_val,
                            "headline": True, "binding_status": "independently-bound",
                            "claim_confirmed": True}],
               "baselines": []}, fh)
res2 = C.verify(tmp, run_id="attest_clean")
b_clean = os.path.join(res2["run_dir"], A.BUNDLE_NAME)
truth(os.path.exists(b_clean), "clean run auto-signs too")
okc, checksc = A.verify_bundle(json.load(open(b_clean)))
truth(okc, "clean-run bundle verifies: %s" % [c for c in checksc if not c[1]])
rendered = A.render_verify(json.load(open(b_clean)), okc, checksc)
truth(rendered.startswith("ATTESTATION VERIFIED"), "render leads with the outcome")

# missing-key / missing-ledger error paths
try:
    A.sign_run(tempfile.mkdtemp())
    truth(False, "sign_run without a ledger raises")
except ValueError:
    truth(True, "sign_run without a ledger raises")
truth(A.load_signing_key("/nonexistent/key") is None, "load_signing_key absent -> None")

del os.environ["CALMA_KEY_DIR"]
shutil.rmtree(tmp_keys, ignore_errors=True)
shutil.rmtree(tmp, ignore_errors=True)

print("attest: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
