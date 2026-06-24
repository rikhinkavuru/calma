"""Tests for egress_audit.py - the auditable "data never leaves" egress control (master roadmap §1.2 / P2-M1
/ K1). Pure stdlib. Run: python3 test_egress_audit.py

It runs the real probe under this host's isolation tier (a few seconds, like test_hermetic), asserting the
evidence record shape + that a verified tier denies EVERY named egress vector (DNS / external IP / the
169.254.169.254 cloud-metadata endpoint / IPv6); host-not-isolated -> skipped (no boundary to attest)."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import egress_audit as EA  # noqa: E402

_n = _fail = 0


def expect(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# the control probes exactly the threats the SOC2 / SIG-CAIQ network-security domain names
expect(set(EA.VECTORS) == {"dns", "external-ip", "cloud-metadata-169.254.169.254", "ipv6"},
       "probes DNS + external IP + the 169.254.169.254 metadata endpoint + IPv6")

# --- the real audit on this host ---
ev = EA.audit(as_of="2026-06-24")
expect(ev["control"].startswith("egress-blocked") and ev["spec"] == EA.SPEC, "evidence record carries the control + spec")
expect(set(ev["vectors_tested"]) == set(EA.VECTORS) and ev["as_of"] == "2026-06-24", "all vectors + the as-of date recorded")
expect(ev["result"] in ("denied", "skipped-host-not-isolated", "LEAK"), "result is one of the three honest outcomes")
json.dumps(ev)
expect(True, "the evidence record is JSON-serialisable")

if ev["result"] == "denied":
    expect(ev["all_blocked"] is True and ev["vectors_reached"] == [],
           "a VERIFIED tier denies all egress: nothing reached the network")
    expect(ev["isolation_tier"] not in ("host-not-isolated", None) and "169.254.169.254" in ev["note"],
           "denied under a named verified tier; the note cites the metadata endpoint")
elif ev["result"].startswith("skipped"):
    expect(ev["all_blocked"] is None and ev["isolation_tier"] == "host-not-isolated",
           "no verified tier -> skipped (makes no claim — never a false pass)")
else:  # LEAK
    expect(False, "egress LEAKED under a verified tier (%s) — the boundary FAILED: %s"
           % (ev["isolation_tier"], ev["vectors_reached"]))

# --- _parse_reached: the probe's EGRESS_REACHED line ---
expect(EA._parse_reached("noise\nEGRESS_REACHED:dns,ipv6\nmore") == ["dns", "ipv6"], "parses the reached vectors")
expect(EA._parse_reached("EGRESS_REACHED:") == [], "empty marker -> nothing reached")
expect(EA._parse_reached("no marker here") is None, "no marker -> None (probe didn't report; treated as denied)")

# --- exit-code semantics: denied/skipped -> 0; only a real LEAK -> 1 ---
expect(EA.main(["--as-of", "2026-06-24"]) == 0, "main exits 0 when egress is denied (or skipped)")

print("egress_audit: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
