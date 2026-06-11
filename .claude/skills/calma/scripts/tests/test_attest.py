"""Attestation chain: pure-stdlib Ed25519 against the RFC 8032 section 7.1 vectors, the DSSE
pre-auth encoding, SSHSIG (interop with the system ssh-keygen, both directions), the VSA-shaped
predicate, RFC 3161 timestamps (against a locally-built openssl TSA - no network), and the signed
bundle end-to-end - including the adversarial cases: tampered payload, swapped verdict re-signed
under the attacker's OWN key (the ledger re-derivation must catch the forged label), pinned-key
mismatch, SSHSIG namespace confusion, lifted timestamp tokens, and malleated signatures.
Run: python3 test_attest.py
"""
import base64
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
import attest as A  # noqa: E402
import calma as C  # noqa: E402
import ed25519 as E  # noqa: E402
import recompute as RC  # noqa: E402
import rfc3161 as T  # noqa: E402
import sshsig as S  # noqa: E402

BTC = os.path.realpath(os.path.join(SCR, "..", "assets", "btc"))
SSH_KEYGEN = shutil.which("ssh-keygen")
OPENSSL = shutil.which("openssl")
_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def full_resign(t, p_obj, seed):
    """Re-sign a (possibly tampered) statement completely - DSSE + SSHSIG + embedded keys -
    exactly what a capable attacker with their own key would do."""
    payload = A._canonical(p_obj)
    pub = E.secret_to_public(seed)
    principal = "calma-" + A._keyid(pub)[:16]
    t["envelope"]["payload"] = base64.b64encode(payload).decode()
    t["envelope"]["signatures"] = [{
        "keyid": A._keyid(pub),
        "sig": base64.b64encode(E.sign(seed, A._pae(A.PAYLOAD_TYPE, payload))).decode()}]
    t["ssh"] = {"namespace": S.NAMESPACE, "principal": principal,
                "public_key": S.pub_line(pub, principal),
                "allowed_signers": S.allowed_signers_line(pub, principal),
                "signature": S.sign(seed, payload)}
    t["verification"] = {"public_keys": [{"keyid": A._keyid(pub), "scheme": "ed25519",
                                          "public_key_hex": pub.hex()}]}
    return t


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

# explicit sign matches the auto-signed bundle byte-for-byte (deterministic signing given the
# same timeVerified - EdDSA has no nonce; wall-clock time is the only varying input)
auto_tv = json.loads(base64.b64decode(bundle["envelope"]["payload"]))["predicate"]["timeVerified"]
b2, _ = A.sign_run(res["run_dir"], out=os.path.join(tmp_keys, "again.json"), time_verified=auto_tv)
truth(A._canonical(b2) == A._canonical(bundle), "signing is deterministic: same run+time, same bundle")

# --- the VSA shape: verifier/policy/claims are present and bound ---
stmt = json.loads(base64.b64decode(bundle["envelope"]["payload"]))
pred = stmt["predicate"]
truth(stmt["predicateType"] == "https://github.com/rikhinkavuru/calma/verdict/v1",
      "predicateType is the GitHub-rooted verdict/v1 URI")
truth(pred["verifier"]["id"] == "https://github.com/rikhinkavuru/calma/skill",
      "verifier id is GitHub-rooted")
truth("https://calma.dev/verdict/v1" in A.PREDICATE_TYPES_ACCEPTED
      and "https://calma.dev/attestation/verification/v1" in A.PREDICATE_TYPES_ACCEPTED,
      "legacy calma.dev predicate URIs stay accepted (old bundles must keep verifying)")
# a REAL pre-migration bundle (signed under the legacy calma.dev URI) must still verify.
# Mint one here rather than trusting an on-disk fixture: the test_registry fixture is
# untracked local state that other suites regenerate under the NEW URI, which made this
# check order-dependent across full-suite runs.
_orig_pred = A.PREDICATE_TYPE
try:
    A.PREDICATE_TYPE = A.LEGACY_PREDICATE_TYPE
    legacy_bundle, _ = A.sign_run(res["run_dir"], out=os.path.join(tmp_keys, "legacy.json"),
                                  time_verified=auto_tv)
finally:
    A.PREDICATE_TYPE = _orig_pred
legacy_stmt = json.loads(base64.b64decode(legacy_bundle["envelope"]["payload"]))
truth(legacy_stmt["predicateType"] == "https://calma.dev/verdict/v1",
      "minted bundle is genuinely signed under the legacy URI")
okL, checksL = A.verify_bundle(legacy_bundle)
truth(okL, "legacy-URI bundle still verifies end-to-end: %s" % [c for c in checksL if not c[1]])
truth(any(n == "claims-binding" for n, _, _ in checksL),
      "claims-binding is still enforced on legacy verdict/v1 bundles")
truth(pred["verifier"]["engine"] == "calma" and pred["verifier"]["version"] == C.__version__,
      "VSA verifier carries the engine + version")
truth(isinstance(pred["timeVerified"], str) and pred["timeVerified"].endswith("Z"),
      "VSA timeVerified is ISO 8601 UTC")
truth(pred["policy"]["contract_sha256"] is not None, "VSA policy pins the contract hash")
truth(pred["policy"]["reference_vectors_sha256"] is not None, "VSA policy pins the calibration corpus")
truth(pred["claims"] and pred["claims"][0]["verdict"] == "REFUTED"
      and pred["claims"][0]["claimed"] is not None,
      "VSA claims summary carries claimed vs recomputed + verdict")
truth(len(stmt["subject"]) >= 2 and stmt["subject"][1]["name"].endswith("/manifest"),
      "manifest root hash is a first-class subject")

# --- SSHSIG: in-bundle + sidecars + system ssh-keygen interop ---
truth(bundle.get("ssh", {}).get("namespace") == "calma-attest@v1",
      "bundle carries an SSHSIG in the calma-attest@v1 namespace")
payload_bytes = base64.b64decode(bundle["envelope"]["payload"])
okS, detS = S.verify(bundle["ssh"]["signature"], payload_bytes)
truth(okS, "in-bundle SSHSIG verifies pure-stdlib: %s" % detS)
okS2, _ = S.verify(bundle["ssh"]["signature"], payload_bytes + b"x")
truth(not okS2, "SSHSIG rejects an altered payload")
okS3, detS3 = S.verify(bundle["ssh"]["signature"], payload_bytes, namespace="file")
truth(not okS3 and "namespace" in detS3, "SSHSIG namespace confusion is rejected (anti cross-protocol)")
for name in (A.PAYLOAD_SIDECAR, A.SSHSIG_SIDECAR, A.SIGNERS_SIDECAR):
    truth(os.path.exists(os.path.join(res["run_dir"], name)), "sidecar %s is written" % name)
if SSH_KEYGEN:
    r = subprocess.run([SSH_KEYGEN, "-Y", "verify",
                        "-f", os.path.join(res["run_dir"], A.SIGNERS_SIDECAR),
                        "-I", bundle["ssh"]["principal"], "-n", S.NAMESPACE,
                        "-s", os.path.join(res["run_dir"], A.SSHSIG_SIDECAR)],
                       input=open(os.path.join(res["run_dir"], A.PAYLOAD_SIDECAR), "rb").read(),
                       capture_output=True)
    truth(r.returncode == 0, "stock ssh-keygen -Y verify accepts the sidecars: %s"
          % r.stderr.decode().strip()[:120])
    # reverse interop: a signature made BY ssh-keygen verifies in our parser
    sshd = tempfile.mkdtemp()
    subprocess.run([SSH_KEYGEN, "-t", "ed25519", "-N", "", "-q",
                    "-f", os.path.join(sshd, "k")], check=True)
    msgp = os.path.join(sshd, "m")
    open(msgp, "wb").write(b"reverse interop")
    subprocess.run([SSH_KEYGEN, "-Y", "sign", "-f", os.path.join(sshd, "k"),
                    "-n", S.NAMESPACE, msgp], check=True, capture_output=True)
    okR, detR = S.verify(open(msgp + ".sig").read(), b"reverse interop")
    truth(okR, "a signature made by ssh-keygen verifies pure-stdlib: %s" % detR)
    # OpenSSH private key import round-trips
    seed_os = S.load_openssh_private_key(open(os.path.join(sshd, "k")).read())
    truth(E.secret_to_public(seed_os) == S.parse_pub_line(open(os.path.join(sshd, "k.pub")).read()),
          "OpenSSH ed25519 private key import derives the matching public key")
    shutil.rmtree(sshd, ignore_errors=True)

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

# (3) statement verdict diverges from the (untouched) embedded ledger -> verdict-binding fails.
# The attacker fully re-signs (DSSE + SSHSIG) under their own key, so every signature check
# passes - the cross-binding checks are what must catch it.
led_real = payload["predicate"]["ledger"]
t3 = A.make_bundle(led_real, payload["predicate"]["manifest"], attacker_seed)
p3 = json.loads(base64.b64decode(t3["envelope"]["payload"]))
p3["predicate"]["verdict"] = "CONFIRMED"
p3["predicate"]["claims"] = A.claims_summary(led_real)
full_resign(t3, p3, attacker_seed)
ok3, checks3 = A.verify_bundle(t3)
truth(not ok3 and any(n == "verdict-binding" and not o for n, o, _ in checks3),
      "statement verdict != embedded ledger verdict fails verdict-binding")

# (3b) forged claims SUMMARY over an untouched ledger -> claims-binding fails
t3b = A.make_bundle(led_real, payload["predicate"]["manifest"], attacker_seed)
p3b = json.loads(base64.b64decode(t3b["envelope"]["payload"]))
p3b["predicate"]["claims"] = [dict(c, verdict="CONFIRMED") for c in p3b["predicate"]["claims"]]
full_resign(t3b, p3b, attacker_seed)
ok3b, checks3b = A.verify_bundle(t3b)
truth(not ok3b and any(n == "claims-binding" and not o for n, o, _ in checks3b),
      "forged predicate claims summary fails claims-binding")

# (3c) SSHSIG stripped from a @2 bundle -> fails (no silent downgrade)
t3c = copy.deepcopy(bundle)
del t3c["ssh"]
ok3c, checks3c = A.verify_bundle(t3c)
truth(not ok3c and any(n == "ssh-signature" and not o for n, o, _ in checks3c),
      "stripping the SSHSIG from a @2 bundle fails (no downgrade)")

# (3d) mix-and-match: DSSE signed by the real key, SSHSIG swapped for the attacker's -> fails
t3d = copy.deepcopy(bundle)
t3d["ssh"]["signature"] = S.sign(attacker_seed, base64.b64decode(bundle["envelope"]["payload"]))
ok3d, checks3d = A.verify_bundle(t3d)
truth(not ok3d and any(n == "ssh-signature" and not o for n, o, _ in checks3d),
      "SSHSIG from a different key than the DSSE signer fails (no mix-and-match)")

# (4) tampered subject digest -> fails before the ledger is even trusted
seed_real = bytes.fromhex(open(info["key_path"]).read().strip())
t4 = copy.deepcopy(bundle)
p4 = copy.deepcopy(payload)
p4["subject"][0]["digest"]["sha256"] = "0" * 64
full_resign(t4, p4, seed_real)
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

# --- calma seal: the one-command proof chain (no network: --no-timestamp) ---
CALMA_CLI = os.path.join(SCR, "calma.py")
seal_reg = tempfile.mkdtemp()
r = subprocess.run([sys.executable, CALMA_CLI, "seal", res["run_dir"], "--no-timestamp",
                    "--publish", seal_reg, "--note", "seal regression"],
                   capture_output=True, text=True, env=dict(os.environ))
truth(r.returncode == 0 and "signed" in r.stdout and "self-check  VERIFIED" in r.stdout
      and "published" in r.stdout and "sealed" in r.stdout,
      "calma seal signs + self-checks + publishes in one command: %s" % r.stdout[:120])
vt = os.path.join(res["run_dir"], "VERIFY-THIS.txt")
truth(os.path.exists(vt), "seal writes VERIFY-THIS.txt")
vt_text = open(vt).read()
truth("ssh-keygen -Y verify" in vt_text and "calma attest verify" in vt_text
      and bundle["ssh"]["principal"] in vt_text,
      "VERIFY-THIS.txt carries both verification paths with the real principal filled in")
if SSH_KEYGEN:
    # the instructions must be literally runnable: execute the Path B command they describe
    r2 = subprocess.run([SSH_KEYGEN, "-Y", "verify",
                         "-f", os.path.join(res["run_dir"], A.SIGNERS_SIDECAR),
                         "-I", bundle["ssh"]["principal"], "-n", S.NAMESPACE,
                         "-s", os.path.join(res["run_dir"], A.SSHSIG_SIDECAR)],
                        input=open(os.path.join(res["run_dir"], A.PAYLOAD_SIDECAR), "rb").read(),
                        capture_output=True)
    truth(r2.returncode == 0, "the VERIFY-THIS.txt instructions actually verify")
shutil.rmtree(seal_reg, ignore_errors=True)

# --- RFC 3161 (Layer 1) against a locally-built openssl TSA - zero network ---
if OPENSSL:
    tsd = tempfile.mkdtemp()

    def _ossl(*args, **kw):
        return subprocess.run([OPENSSL] + list(args), capture_output=True, text=True,
                              cwd=tsd, **kw)

    open(os.path.join(tsd, "ext.cnf"), "w").write(
        "[tsa_ext]\nextendedKeyUsage=critical,timeStamping\n")
    open(os.path.join(tsd, "tsa.cnf"), "w").write(
        "[ tsa ]\ndefault_tsa = tsa_config1\n[ tsa_config1 ]\nserial = ./serial\n"
        "default_policy = 1.2.3.4\ndigests = sha256\naccuracy = secs:1\nordering = no\n"
        "tsa_name = no\ness_cert_id_chain = no\nsigner_digest = sha256\n")
    open(os.path.join(tsd, "serial"), "w").write("01\n")
    _ossl("req", "-x509", "-newkey", "rsa:2048", "-keyout", "cakey.pem", "-out", "cacert.pem",
          "-nodes", "-days", "3", "-subj", "/CN=Calma Test CA")
    _ossl("req", "-newkey", "rsa:2048", "-keyout", "tsakey.pem", "-out", "tsa.csr",
          "-nodes", "-subj", "/CN=Calma Test TSA")
    _ossl("x509", "-req", "-in", "tsa.csr", "-CA", "cacert.pem", "-CAkey", "cakey.pem",
          "-CAcreateserial", "-out", "tsacert.pem", "-days", "2",
          "-extfile", "ext.cnf", "-extensions", "tsa_ext")
    tsig = base64.b64decode(bundle["envelope"]["signatures"][0]["sig"])
    open(os.path.join(tsd, "req.tsq"), "wb").write(T.request_der(tsig, nonce=7))
    rts = _ossl("ts", "-reply", "-queryfile", "req.tsq", "-signer", "tsacert.pem",
                "-inkey", "tsakey.pem", "-out", "resp.tsr", "-config", "tsa.cnf")
    truth(rts.returncode == 0, "local openssl TSA issues a token: %s" % rts.stderr.strip()[:120])
    token = open(os.path.join(tsd, "resp.tsr"), "rb").read()
    tinfo = T.parse_tstinfo(token)
    truth(tinfo["imprint_sha256_hex"] == hashlib.sha256(tsig).hexdigest(),
          "TSTInfo messageImprint is sha256 of the DSSE signature")
    tb = copy.deepcopy(bundle)
    tb["timestamps"] = [{"format": "rfc3161", "tsa_url": "local-test",
                         "gen_time": tinfo["gen_time"], "serial": str(tinfo["serial"]),
                         "token_b64": base64.b64encode(token).decode(),
                         "tsa_ca_pem": open(os.path.join(tsd, "cacert.pem")).read(),
                         "covers": "envelope.signatures[0].sig"}]
    okT, checksT = A.verify_bundle(tb)
    ts_check = [c for c in checksT if c[0] == "timestamp"]
    truth(okT and ts_check and ts_check[0][1] and "chain verified" in ts_check[0][2],
          "timestamped bundle verifies with full chain verification: %s"
          % (ts_check[0][2] if ts_check else "no timestamp check ran"))
    # lifted token: the same token on a DIFFERENT bundle (other signature bytes) must fail
    tb2 = copy.deepcopy(t2)  # the attacker's forged-label bundle from case (2)
    tb2["timestamps"] = copy.deepcopy(tb["timestamps"])
    okT2, checksT2 = A.verify_bundle(tb2)
    truth(any(n == "timestamp" and not o and "imprint" in d for n, o, d in checksT2),
          "a timestamp token lifted from another bundle fails the imprint binding")
    # degraded tier: no CA cert embedded -> verifies structurally and SAYS so
    tb3 = copy.deepcopy(tb)
    tb3["timestamps"][0]["tsa_ca_pem"] = None
    okT3, checksT3 = A.verify_bundle(tb3)
    ts3 = [c for c in checksT3 if c[0] == "timestamp"][0]
    truth(okT3 and "structural only" in ts3[2],
          "timestamp without a CA cert verifies structurally and reports the degraded tier")
    # garbage token fails cleanly
    tb4 = copy.deepcopy(tb)
    tb4["timestamps"][0]["token_b64"] = base64.b64encode(b"garbage").decode()
    okT4, checksT4 = A.verify_bundle(tb4)
    truth(not okT4 and any(n == "timestamp" and not o for n, o, _ in checksT4),
          "a malformed timestamp token fails cleanly")
    shutil.rmtree(tsd, ignore_errors=True)

del os.environ["CALMA_KEY_DIR"]
shutil.rmtree(tmp_keys, ignore_errors=True)
shutil.rmtree(tmp, ignore_errors=True)

print("attest: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
