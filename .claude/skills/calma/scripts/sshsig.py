"""calma.sshsig - pure-stdlib OpenSSH SSHSIG signatures (openssh PROTOCOL.sshsig, version 1).

The counterparty story: an SSHSIG produced here verifies with stock `ssh-keygen -Y verify`
(OpenSSH >= 8.0 - shipped on every macOS/Linux box), so a counterparty needs ZERO installs and
does not have to trust calma's code to check the signature. The "crypto library" is the OS.
Conversely, this module verifies signatures produced by `ssh-keygen -Y sign` (interop is tested
both directions against the system ssh-keygen in tests/test_attest.py).

Only ssh-ed25519 keys, namespace-bound (default `calma-attest@v1`) to prevent cross-protocol
signature reuse - a signature for another namespace, or a raw SSH auth exchange, can never be
replayed as a calma attestation, and vice versa.

  sign(seed32, msg)                 -> armored SSHSIG text
  verify(armored, msg, ...)         -> (ok, detail)
  pub_line(pub32)                   -> "ssh-ed25519 AAAA... comment" (authorized_keys form)
  allowed_signers_line(pub32, ...)  -> the allowed_signers line for `ssh-keygen -Y verify`
  load_openssh_private_key(text)    -> seed32 from an UNENCRYPTED OpenSSH ed25519 private key
"""
import base64
import hashlib
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ed25519  # noqa: E402

MAGIC = b"SSHSIG"
VERSION = 1
NAMESPACE = "calma-attest@v1"
HASH_ALG = "sha512"  # ssh-keygen's default for -Y sign
KEY_TYPE = b"ssh-ed25519"
PEM_BEGIN = "-----BEGIN SSH SIGNATURE-----"
PEM_END = "-----END SSH SIGNATURE-----"


# ---- SSH wire encoding -----------------------------------------------------

def _s(b):
    """An SSH wire `string`: uint32 length + bytes."""
    if isinstance(b, str):
        b = b.encode()
    return struct.pack(">I", len(b)) + b


class _Reader:
    def __init__(self, buf):
        self.buf, self.off = buf, 0

    def string(self):
        if self.off + 4 > len(self.buf):
            raise ValueError("truncated SSH wire string length")
        n = struct.unpack(">I", self.buf[self.off:self.off + 4])[0]
        self.off += 4
        if self.off + n > len(self.buf):
            raise ValueError("truncated SSH wire string body")
        out = self.buf[self.off:self.off + n]
        self.off += n
        return out

    def uint32(self):
        if self.off + 4 > len(self.buf):
            raise ValueError("truncated SSH wire uint32")
        n = struct.unpack(">I", self.buf[self.off:self.off + 4])[0]
        self.off += 4
        return n

    def raw(self, n):
        out = self.buf[self.off:self.off + n]
        if len(out) != n:
            raise ValueError("truncated SSH wire bytes")
        self.off += n
        return out


# ---- public key forms ------------------------------------------------------

def pub_wire(pub32):
    """SSH wire encoding of an ed25519 public key (what lives base64'd in authorized_keys)."""
    return _s(KEY_TYPE) + _s(pub32)


def pub_line(pub32, comment="calma"):
    """The one-line authorized_keys / .pub form."""
    return "ssh-ed25519 %s %s" % (base64.b64encode(pub_wire(pub32)).decode(), comment)


def parse_pub_line(line):
    """pub32 from an `ssh-ed25519 AAAA... [comment]` line. Raises ValueError on anything else."""
    parts = line.strip().split()
    if len(parts) < 2 or parts[0] != "ssh-ed25519":
        raise ValueError("not an ssh-ed25519 public key line")
    rd = _Reader(base64.b64decode(parts[1]))
    if rd.string() != KEY_TYPE:
        raise ValueError("key blob type is not ssh-ed25519")
    pub = rd.string()
    if len(pub) != 32:
        raise ValueError("ed25519 public key must be 32 bytes")
    return pub


def allowed_signers_line(pub32, principal, namespace=NAMESPACE):
    """The allowed_signers line a counterparty feeds to `ssh-keygen -Y verify -f <file>`.
    The namespaces= option pins the line to calma attestations only."""
    return '%s namespaces="%s" ssh-ed25519 %s' % (
        principal, namespace, base64.b64encode(pub_wire(pub32)).decode())


# ---- SSHSIG construction ---------------------------------------------------

def _signed_data(namespace, hash_alg, msg):
    """The exact bytes the inner ed25519 signature covers (PROTOCOL.sshsig section 3)."""
    h = hashlib.new(hash_alg, msg).digest()
    return MAGIC + _s(namespace) + _s(b"") + _s(hash_alg) + _s(h)


def _armor(blob):
    b64 = base64.b64encode(blob).decode()
    lines = [b64[i:i + 70] for i in range(0, len(b64), 70)]
    return "\n".join([PEM_BEGIN] + lines + [PEM_END]) + "\n"


def _dearmor(text):
    lines = [ln.strip() for ln in text.strip().splitlines()]
    if not lines or lines[0] != PEM_BEGIN or lines[-1] != PEM_END:
        raise ValueError("not an armored SSH signature")
    return base64.b64decode("".join(lines[1:-1]))


def sign(seed, msg, namespace=NAMESPACE):
    """Armored SSHSIG over msg. Deterministic (EdDSA): same key + same msg -> same signature."""
    pub = ed25519.secret_to_public(seed)
    raw = ed25519.sign(seed, _signed_data(namespace, HASH_ALG, msg))
    blob = (MAGIC + struct.pack(">I", VERSION) + _s(pub_wire(pub)) + _s(namespace)
            + _s(b"") + _s(HASH_ALG) + _s(_s(KEY_TYPE) + _s(raw)))
    return _armor(blob)


def parse(armored):
    """Decode an armored SSHSIG -> {pub32, namespace, hash_alg, sig64}. Strict on every field."""
    rd = _Reader(_dearmor(armored))
    if rd.raw(6) != MAGIC:
        raise ValueError("bad SSHSIG magic")
    ver = rd.uint32()
    if ver != VERSION:
        raise ValueError("unsupported SSHSIG version %d" % ver)
    krd = _Reader(rd.string())
    if krd.string() != KEY_TYPE:
        raise ValueError("SSHSIG key type is not ssh-ed25519")
    pub = krd.string()
    if len(pub) != 32:
        raise ValueError("SSHSIG ed25519 public key must be 32 bytes")
    namespace = rd.string().decode()
    rd.string()  # reserved
    hash_alg = rd.string().decode()
    if hash_alg not in ("sha256", "sha512"):
        raise ValueError("SSHSIG hash algorithm %r not allowed" % hash_alg)
    srd = _Reader(rd.string())
    if srd.string() != KEY_TYPE:
        raise ValueError("SSHSIG signature algorithm is not ssh-ed25519")
    sig = srd.string()
    if len(sig) != 64:
        raise ValueError("ed25519 signature must be 64 bytes")
    return {"pub": pub, "namespace": namespace, "hash_alg": hash_alg, "sig": sig}


def verify(armored, msg, namespace=NAMESPACE, expect_pub=None):
    """(ok, detail). Enforces the namespace (anti cross-protocol reuse) and, when expect_pub
    is given, that the embedded key IS that key - an attacker re-signing under their own key
    fails here even though their signature is internally valid."""
    try:
        p = parse(armored)
    except (ValueError, TypeError) as e:
        return False, "malformed SSHSIG: %s" % e
    if p["namespace"] != namespace:
        return False, "namespace %r != required %r" % (p["namespace"], namespace)
    if expect_pub is not None and p["pub"] != expect_pub:
        return False, "signed by a different key than expected"
    if not ed25519.verify(p["pub"], _signed_data(p["namespace"], p["hash_alg"], msg), p["sig"]):
        return False, "ed25519 signature does not verify"
    return True, "ssh-ed25519, namespace %s" % p["namespace"]


# ---- OpenSSH private key import (unencrypted ed25519 only) ------------------

_OPENSSH_MAGIC = b"openssh-key-v1\x00"


def load_openssh_private_key(text):
    """The 32-byte seed from an UNENCRYPTED `-----BEGIN OPENSSH PRIVATE KEY-----` ed25519 key,
    so an existing `ssh-keygen -t ed25519` identity can sign calma attestations directly.
    Raises ValueError on encrypted keys (decrypt-by-hand is out of scope) or other key types."""
    lines = [ln.strip() for ln in text.strip().splitlines()]
    if (not lines or lines[0] != "-----BEGIN OPENSSH PRIVATE KEY-----"
            or lines[-1] != "-----END OPENSSH PRIVATE KEY-----"):
        raise ValueError("not an OpenSSH private key")
    rd = _Reader(base64.b64decode("".join(lines[1:-1])))
    if rd.raw(len(_OPENSSH_MAGIC)) != _OPENSSH_MAGIC:
        raise ValueError("bad openssh-key-v1 magic")
    cipher, kdf = rd.string(), rd.string()
    rd.string()  # kdf options
    if cipher != b"none" or kdf != b"none":
        raise ValueError("key is passphrase-encrypted - decrypt it first "
                         "(ssh-keygen -p -N '' -f <key>) or use the calma key")
    if rd.uint32() != 1:
        raise ValueError("expected exactly one key in the file")
    rd.string()  # public key blob
    prd = _Reader(rd.string())
    prd.uint32(), prd.uint32()  # checkints (equal iff decrypted; always equal when unencrypted)
    if prd.string() != KEY_TYPE:
        raise ValueError("not an ed25519 private key")
    prd.string()  # pub32
    priv = prd.string()  # 64 bytes: seed || pub
    if len(priv) != 64:
        raise ValueError("malformed ed25519 private half")
    return priv[:32]
