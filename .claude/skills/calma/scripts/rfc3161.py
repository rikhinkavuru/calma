"""calma.rfc3161 - Layer 1 of the attestation chain: a trusted timestamp over the signature.

An RFC 3161 TimeStampReq is built pure-stdlib (DER is ~30 lines for this shape), POSTed to a
public TSA (default freetsa.org - free, CA cert published, tokens verifiable through 2040), and
the DER TimeStampResp token is embedded in the bundle under "timestamps", together with the TSA's
CA certificate so verification stays fully OFFLINE afterwards. Network is needed only at
timestamping time.

What it proves: the DSSE signature bytes (and therefore the signed verdict payload) existed
before the TSA's genTime - "we verified this before the fund blew up" becomes provable, not
asserted. Anti-backdating: the signer cannot mint a token for a past date.

Verification is two-tier and honest about which tier ran:
  - structural (pure stdlib, always): parse the token's TSTInfo, require the messageImprint to
    be sha256(DSSE signature bytes) and extract genTime. This binds the token to THIS bundle -
    a token lifted from another bundle fails here.
  - cryptographic (openssl ts -verify, when openssl is on PATH - it ships on macOS/Linux): full
    PKCS#7 chain verification against the embedded TSA CA cert. When openssl is absent the
    report says "structural only", never pretends.

Library: request_der(data), timestamp_bundle(bundle, tsa_url), verify_bundle_timestamps(bundle).
"""
import base64
import hashlib
import os
import shutil
import subprocess
import tempfile

DEFAULT_TSA = "https://freetsa.org/tsr"
DEFAULT_TSA_CA = "https://freetsa.org/files/cacert.pem"
SHA256_OID = (2, 16, 840, 1, 101, 3, 4, 2, 1)
TSTINFO_OID = (1, 2, 840, 113549, 1, 9, 16, 1, 4)  # id-ct-TSTInfo


# ---- minimal DER encode ------------------------------------------------------

def _len(n):
    if n < 0x80:
        return bytes([n])
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(body)]) + body


def _tlv(tag, body):
    return bytes([tag]) + _len(len(body)) + body


def _oid(arcs):
    body = bytes([arcs[0] * 40 + arcs[1]])
    for a in arcs[2:]:
        chunk = [a & 0x7F]
        a >>= 7
        while a:
            chunk.append(0x80 | (a & 0x7F))
            a >>= 7
        body += bytes(reversed(chunk))
    return _tlv(0x06, body)


def _int(v):
    body = v.to_bytes(max(1, (v.bit_length() + 8) // 8), "big")
    return _tlv(0x02, body)


def request_der(data, nonce=None):
    """A DER TimeStampReq: version 1, sha256 messageImprint over `data`, certReq TRUE (the TSA
    must return its signing cert so verification is self-contained)."""
    imprint = _tlv(0x30, _tlv(0x30, _oid(SHA256_OID) + _tlv(0x05, b""))
                   + _tlv(0x04, hashlib.sha256(data).digest()))
    body = _int(1) + imprint
    if nonce is not None:
        body += _int(nonce)
    body += _tlv(0x01, b"\xff")  # certReq TRUE
    return _tlv(0x30, body)


# ---- minimal DER parse (just enough to walk to TSTInfo) ----------------------

class _Der:
    def __init__(self, buf, off=0, end=None):
        self.buf, self.off = buf, off
        self.end = len(buf) if end is None else end

    def tlv(self):
        """(tag, value_start, value_end); advances past the element."""
        if self.off >= self.end:
            raise ValueError("DER: truncated")
        tag = self.buf[self.off]
        i = self.off + 1
        first = self.buf[i]
        i += 1
        if first < 0x80:
            n = first
        else:
            nb = first & 0x7F
            if nb == 0 or nb > 4:
                raise ValueError("DER: bad length")
            n = int.from_bytes(self.buf[i:i + nb], "big")
            i += nb
        if i + n > self.end:
            raise ValueError("DER: element overruns buffer")
        self.off = i + n
        return tag, i, i + n


def _walk_to_tstinfo(token):
    """The DER TSTInfo bytes from a TimeStampResp or a bare TimeStampToken (ContentInfo)."""
    d = _Der(token)
    tag, s, e = d.tlv()
    if tag != 0x30:
        raise ValueError("not a DER SEQUENCE")
    inner = _Der(token, s, e)
    tag, s2, e2 = inner.tlv()
    if tag == 0x30:  # TimeStampResp: SEQUENCE { status SEQUENCE, token ContentInfo }
        # status PKIStatusInfo: first INTEGER must be 0 (granted) or 1 (grantedWithMods)
        st = _Der(token, s2, e2)
        st_tag, ss, se = st.tlv()
        if st_tag != 0x02 or int.from_bytes(token[ss:se], "big") not in (0, 1):
            raise ValueError("TSA did not grant the timestamp (status != granted)")
        tag, s2, e2 = inner.tlv()  # the TimeStampToken ContentInfo
        inner = _Der(token, s2, e2)
        tag, s2, e2 = inner.tlv()  # contentType OID
    if tag != 0x06:
        raise ValueError("expected ContentInfo contentType OID")
    # [0] EXPLICIT content -> SignedData
    tag, s3, e3 = inner.tlv()
    if tag != 0xA0:
        raise ValueError("expected [0] EXPLICIT content")
    sd = _Der(token, s3, e3)
    tag, s4, e4 = sd.tlv()  # SignedData SEQUENCE
    if tag != 0x30:
        raise ValueError("expected SignedData SEQUENCE")
    sdi = _Der(token, s4, e4)
    sdi.tlv()  # version
    sdi.tlv()  # digestAlgorithms SET
    tag, s5, e5 = sdi.tlv()  # encapContentInfo SEQUENCE
    eci = _Der(token, s5, e5)
    tag, s6, e6 = eci.tlv()  # eContentType OID
    if tag != 0x06 or token[s6:e6] != _oid(TSTINFO_OID)[2:]:
        raise ValueError("encapsulated content is not TSTInfo")
    tag, s7, e7 = eci.tlv()  # [0] EXPLICIT eContent
    if tag != 0xA0:
        raise ValueError("expected [0] EXPLICIT eContent")
    ec = _Der(token, s7, e7)
    tag, s8, e8 = ec.tlv()  # OCTET STRING holding the DER TSTInfo
    if tag != 0x04:
        raise ValueError("expected OCTET STRING eContent")
    return token[s8:e8]


def parse_tstinfo(token):
    """{gen_time, imprint_sha256_hex, serial} from a DER TimeStampResp/TimeStampToken."""
    tst = _walk_to_tstinfo(token)
    d = _Der(tst)
    tag, s, e = d.tlv()
    if tag != 0x30:
        raise ValueError("TSTInfo is not a SEQUENCE")
    f = _Der(tst, s, e)
    f.tlv()  # version
    f.tlv()  # policy OID
    tag, s2, e2 = f.tlv()  # messageImprint SEQUENCE
    mi = _Der(tst, s2, e2)
    tag, s3, e3 = mi.tlv()  # AlgorithmIdentifier
    alg = _Der(tst, s3, e3)
    a_tag, as_, ae = alg.tlv()
    if a_tag != 0x06 or tst[as_:ae] != _oid(SHA256_OID)[2:]:
        raise ValueError("messageImprint hash is not sha256")
    tag, s4, e4 = mi.tlv()  # OCTET STRING digest
    imprint = tst[s4:e4]
    tag, s5, e5 = f.tlv()  # serialNumber INTEGER
    serial = int.from_bytes(tst[s5:e5], "big")
    tag, s6, e6 = f.tlv()  # genTime GeneralizedTime
    if tag != 0x18:
        raise ValueError("expected GeneralizedTime genTime")
    return {"gen_time": tst[s6:e6].decode("ascii"),
            "imprint_sha256_hex": imprint.hex(), "serial": serial}


# ---- timestamping + verification --------------------------------------------

def _bundle_message(bundle):
    """The bytes the timestamp covers: the FIRST DSSE signature (raw bytes). Timestamping the
    signature (not the payload) proves both existed - the signature commits to the payload."""
    sigs = (bundle.get("envelope") or {}).get("signatures") or []
    if not sigs:
        raise ValueError("bundle has no envelope signatures to timestamp")
    return base64.b64decode(sigs[0]["sig"])


def timestamp_bundle(bundle, tsa_url=DEFAULT_TSA, ca_url=DEFAULT_TSA_CA, timeout=30):
    """POST a TimeStampReq for the bundle's DSSE signature; embed the token + the TSA CA cert.
    The ONLY networked step in the whole attestation chain. Returns the timestamps entry."""
    import urllib.request
    msg = _bundle_message(bundle)
    nonce = int.from_bytes(os.urandom(8), "big")
    req = urllib.request.Request(tsa_url, data=request_der(msg, nonce),
                                 headers={"Content-Type": "application/timestamp-query"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        token = resp.read()
    info = parse_tstinfo(token)  # raises if the TSA refused or the token is malformed
    if info["imprint_sha256_hex"] != hashlib.sha256(msg).hexdigest():
        raise ValueError("TSA returned a token for different bytes (imprint mismatch)")
    ca_pem = None
    if ca_url:
        try:
            with urllib.request.urlopen(ca_url, timeout=timeout) as resp:
                ca_pem = resp.read().decode("ascii", "replace")
        except OSError:
            ca_pem = None  # token still embeds the signing cert (certReq); chain check degrades
    entry = {"format": "rfc3161", "tsa_url": tsa_url, "gen_time": info["gen_time"],
             "serial": str(info["serial"]), "token_b64": base64.b64encode(token).decode(),
             "tsa_ca_pem": ca_pem, "covers": "envelope.signatures[0].sig"}
    bundle.setdefault("timestamps", []).append(entry)
    return entry


def _openssl_verify(token, msg, ca_pem):
    """Full PKCS#7 verification via `openssl ts -verify`. (ok, detail); (None, why) if openssl
    or the CA cert is unavailable - the caller reports the degraded tier honestly."""
    exe = shutil.which("openssl")
    if exe is None:
        return None, "openssl not on PATH"
    if not ca_pem:
        return None, "no TSA CA certificate embedded"
    with tempfile.TemporaryDirectory() as td:
        tok_p, msg_p, ca_p = (os.path.join(td, n) for n in ("tok.tsr", "msg.bin", "ca.pem"))
        open(tok_p, "wb").write(token)
        open(msg_p, "wb").write(msg)
        open(ca_p, "w").write(ca_pem)
        r = subprocess.run([exe, "ts", "-verify", "-data", msg_p, "-in", tok_p,
                            "-CAfile", ca_p], capture_output=True, text=True, timeout=60)
        # `openssl ts -verify` wants a TimeStampResp by default; a bare token needs -token_in
        if r.returncode != 0 and "wrong tag" in (r.stderr or "").lower():
            r = subprocess.run([exe, "ts", "-verify", "-data", msg_p, "-in", tok_p, "-token_in",
                                "-CAfile", ca_p], capture_output=True, text=True, timeout=60)
        ok = r.returncode == 0 and "Verification: OK" in (r.stdout or "")
        return ok, ("chain verified (openssl ts)" if ok
                    else (r.stderr or r.stdout or "openssl ts failed").strip()[:200])


def verify_bundle_timestamps(bundle):
    """(ok, detail) over every embedded timestamp. Structural binding (imprint == sha256 of the
    DSSE signature) is mandatory; the openssl chain check upgrades the tier when available."""
    entries = bundle.get("timestamps") or []
    if not entries:
        return True, "no timestamps"
    try:
        msg = _bundle_message(bundle)
    except (ValueError, KeyError) as e:
        return False, str(e)
    details = []
    for i, t in enumerate(entries):
        try:
            token = base64.b64decode(t.get("token_b64", ""), validate=True)
            info = parse_tstinfo(token)
        except (ValueError, TypeError) as e:
            return False, "timestamp[%d] malformed: %s" % (i, e)
        if info["imprint_sha256_hex"] != hashlib.sha256(msg).hexdigest():
            return False, ("timestamp[%d] does not cover this bundle's signature "
                           "(imprint mismatch)" % i)
        crypto_ok, crypto_detail = _openssl_verify(token, msg, t.get("tsa_ca_pem"))
        if crypto_ok is False:
            return False, "timestamp[%d] chain verification failed: %s" % (i, crypto_detail)
        tier = "chain verified" if crypto_ok else ("structural only: %s" % crypto_detail)
        details.append("%s (%s)" % (info["gen_time"], tier))
    return True, "; ".join(details)
