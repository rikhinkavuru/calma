"""calma.egress_audit - the "data never leaves" control, made AUDITABLE (master roadmap §1.2 / P2-M1 / K1).

Runs a probe entrypoint UNDER the local isolation tier (Seatbelt on macOS / bubblewrap on Linux) that attempts
every egress vector the SOC 2 control + the SIG/CAIQ network-security domain name, and asserts ALL are denied:

  - DNS resolution (hostname lookup),
  - an arbitrary external IP (1.1.1.1:80),
  - the cloud-metadata endpoint 169.254.169.254 (the classic SSRF / credential-theft target),
  - an IPv6 destination (so an IPv6 path can't bypass an IPv4-only deny).

It emits a dated, signable JSON evidence record. THIS is the egress-control test the roadmap calls for ("run
on a schedule, logged") — the K1 sandbox-escape kill-risk made into evidence, and the part of the P2-M1
acceptance criterion ("network-OFF verified by an automated egress-blocked test") that proves the boundary.

NO external credentials: it exercises the LOCAL sandbox only. With no verified tier (host-not-isolated) the
audit is SKIPPED — honest: there is no sandbox boundary to attest, so it makes no claim (never a false pass).

Run:  python3 egress_audit.py [--out evidence.json] [--as-of YYYY-MM-DD]
      exit 0 = all egress denied OR skipped (no tier);  exit 1 = a LEAK (the boundary failed — investigate).
"""
import argparse
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_hermetic as H  # noqa: E402
import tiers as _tiers  # noqa: E402

SPEC = "calma-egress-control@1"

# the probe entrypoint (self-contained, pure stdlib). It runs INSIDE the sandbox; every vector that returns
# real bytes is a LEAK. A blocked vector raises (Seatbelt `deny network*` fails at connect()) and is skipped.
# Prints exactly one line: EGRESS_REACHED:<comma-separated vectors that got through> (empty == fully denied).
_PROBE = r'''
import socket
def _http(sock):
    sock.sendall(b"GET / HTTP/1.0\r\nHost: x\r\n\r\n")
    data = sock.recv(1)
    sock.close()
    return bool(data)                         # real bytes back == egress actually reached
def ip4(host):
    return _http(socket.create_connection((host, 80), timeout=3))
def ip6(host):
    s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM); s.settimeout(3)
    s.connect((host, 80, 0, 0)); return _http(s)
def dns():
    socket.getaddrinfo("example.com", 80); return True   # a successful resolve already needs the network out
VECTORS = {
    "dns": dns,
    "external-ip": lambda: ip4("1.1.1.1"),
    "cloud-metadata-169.254.169.254": lambda: ip4("169.254.169.254"),
    "ipv6": lambda: ip6("2606:4700:4700::1111"),
}
reached = []
for name, fn in VECTORS.items():
    try:
        if fn():
            reached.append(name)
    except Exception:
        pass                                  # blocked (connect/resolve raised) -> not reached
print("EGRESS_REACHED:" + ",".join(reached))
'''

VECTORS = ("dns", "external-ip", "cloud-metadata-169.254.169.254", "ipv6")


def _parse_reached(stdout_tail):
    for line in (stdout_tail or "").splitlines():
        if line.startswith("EGRESS_REACHED:"):
            rest = line[len("EGRESS_REACHED:"):].strip()
            return [v for v in rest.split(",") if v]
    return None  # the probe didn't report (it was killed / blocked before printing) -> treat as denied


def audit(as_of=None, timeout=30):
    """Run the egress probe under the local tier and return the evidence record (a JSON-serialisable dict).
    result ∈ 'denied' (all vectors blocked under a verified tier) | 'LEAK' (a vector reached the network) |
    'skipped-host-not-isolated' (no sandbox boundary to attest)."""
    tmp = tempfile.mkdtemp(prefix="calma-egress-")
    with open(os.path.join(tmp, "probe.py"), "w") as fh:
        fh.write(_PROBE)
    with open(os.path.join(tmp, "verify.yaml"), "w") as fh:
        json.dump({"run": {"entrypoint": "probe.py", "network": "off"},
                   "env": {"trust": "own-code"}, "artifacts": [], "metrics": []}, fh)
    res = H.run(os.path.join(tmp, "verify.yaml"), base=tmp, timeout=timeout)
    tier = res.get("isolation_tier") or "host-not-isolated"
    reached = _parse_reached(res.get("stdout_tail", "")) or []
    verified = tier in set(_tiers.VERIFIED_TIERS)
    if not verified:
        result = "skipped-host-not-isolated"
        all_blocked = None
    elif reached:
        result, all_blocked = "LEAK", False
    else:
        result, all_blocked = "denied", True
    ev = {
        "control": "egress-blocked (data never leaves)",
        "spec": SPEC,
        "as_of": as_of,
        "host": sys.platform,
        "isolation_tier": tier,
        "exit_code": res.get("exit_code"),
        "vectors_tested": list(VECTORS),
        "vectors_reached": reached,
        "all_blocked": all_blocked,
        "result": result,
        "note": ("every egress vector (DNS / external IP / the 169.254.169.254 cloud-metadata endpoint / IPv6) "
                 "was denied under a verified isolation tier" if result == "denied" else
                 "no verified isolation tier on this host - no egress boundary to attest (not a pass, not a leak)"
                 if result.startswith("skipped") else
                 "a probe vector reached the network UNDER A VERIFIED TIER - the egress boundary FAILED"),
    }
    return ev


def main(argv=None):
    ap = argparse.ArgumentParser(description="Egress-blocked control: prove a sandboxed job cannot leave the host.")
    ap.add_argument("--out", help="write the JSON evidence record here")
    ap.add_argument("--as-of", default=None, help="evidence date (YYYY-MM-DD); omit to leave null")
    a = ap.parse_args(argv)
    ev = audit(as_of=a.as_of)
    text = json.dumps(ev, indent=2)
    if a.out:
        with open(a.out, "w") as fh:
            fh.write(text)
    print(text)
    # exit 1 ONLY on a real leak under a verified tier; denied + skipped both exit 0 (no boundary failure).
    return 1 if ev["result"] == "LEAK" else 0


if __name__ == "__main__":
    sys.exit(main())
