"""calma.ed25519 - pure-stdlib Ed25519 (RFC 8032, section 5.1). No third-party crypto: the same
no-deps rule as the numeric kernels, and EdDSA signing is fully deterministic (same seed + same
message => same signature bytes), which keeps attestation byte-reproducible.

This is the RFC's reference algorithm over Python big ints - small messages only (the bundle
signs a 32-byte digest's worth of canonical JSON, so the O(ms) point arithmetic is irrelevant).
Validated against the RFC 8032 section 7.1 test vectors in tests/test_attest.py.

  secret_to_public(seed32) -> pub32
  sign(seed32, msg)        -> sig64
  verify(pub32, msg, sig64) -> bool   (strict: rejects s >= L malleated signatures)
"""
import hashlib

P = 2 ** 255 - 19                                   # field prime
L = 2 ** 252 + 27742317777372353535851937790883648493  # group order


def _sha512(s):
    return hashlib.sha512(s).digest()


def _inv(x):
    return pow(x, P - 2, P)


D = (-121665 * _inv(121666)) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


def _point_add(p, q):
    # extended homogeneous coordinates (RFC 8032 5.1.4)
    a = (p[1] - p[0]) * (q[1] - q[0]) % P
    b = (p[1] + p[0]) * (q[1] + q[0]) % P
    c = 2 * p[3] * q[3] * D % P
    d = 2 * p[2] * q[2] % P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _point_mul(s, p):
    q = (0, 1, 1, 0)  # neutral element
    while s > 0:
        if s & 1:
            q = _point_add(q, p)
        p = _point_add(p, p)
        s >>= 1
    return q


def _point_equal(p, q):
    if (p[0] * q[2] - q[0] * p[2]) % P != 0:
        return False
    if (p[1] * q[2] - q[1] * p[2]) % P != 0:
        return False
    return True


def _recover_x(y, sign):
    if y >= P:
        return None
    x2 = (y * y - 1) * _inv(D * y * y + 1) % P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P != 0:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


_G_Y = 4 * _inv(5) % P
_G_X = _recover_x(_G_Y, 0)
G = (_G_X, _G_Y, 1, _G_X * _G_Y % P)


def _compress(p):
    zinv = _inv(p[2])
    x, y = p[0] * zinv % P, p[1] * zinv % P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(s):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % P)


def _expand(seed):
    if len(seed) != 32:
        raise ValueError("ed25519 seed must be exactly 32 bytes")
    h = _sha512(seed)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def _sha512_mod_l(s):
    return int.from_bytes(_sha512(s), "little") % L


def secret_to_public(seed):
    a, _ = _expand(seed)
    return _compress(_point_mul(a, G))


def sign(seed, msg):
    a, prefix = _expand(seed)
    pub = _compress(_point_mul(a, G))
    r = _sha512_mod_l(prefix + msg)
    r_enc = _compress(_point_mul(r, G))
    h = _sha512_mod_l(r_enc + pub + msg)
    s = (r + h * a) % L
    return r_enc + int.to_bytes(s, 32, "little")


def verify(pub, msg, sig):
    if len(pub) != 32 or len(sig) != 64:
        return False
    a = _decompress(pub)
    if a is None:
        return False
    r = _decompress(sig[:32])
    if r is None:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= L:  # strict: reject the malleated (s + L) form
        return False
    h = _sha512_mod_l(sig[:32] + pub + msg)
    return _point_equal(_point_mul(s, G), _point_add(r, _point_mul(h, a)))
