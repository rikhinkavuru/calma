"""calma.registry - the catch history: a public, append-only, hash-chained log of verification
outcomes ("clinical-trial registration for backtests").

v1 is deliberately a static transparency log with zero infrastructure: entries are JSON files in
a `registry/` directory of a public git repo, each entry embeds the sha256 of the previous entry
(a hash chain), every entry AND the HEAD pointer are SSHSIG-signed with the lab key, and the site
renders the directory statically. Tamper evidence on day one = the signed chain + git history;
each Layer-2 Sigstore verdict additionally lands in Rekor's public log, which independently
witnesses the registry's contents. v2 (additive, entries are already hash-addressed) is a Merkle
tree per C2SP tlog-tiles + checkpoints cosigned by the public witness network.

REDACTION IS STRUCTURAL: an entry is built ONLY from a whitelist of fields derived from the
attestation bundle - claim, metric, claimed vs recomputed, verdict, dates, content hashes. Code
and data never enter the entry, and verify_chain rejects any entry carrying non-whitelisted keys.

The clinical-trial property is enforced by entry kinds: an `engagement-opened` entry is published
at contract signing; a missing `engagement-outcome` for an opened engagement is itself visible.

publish requires attest: an entry is derived from a VERIFIED attestation bundle, never from a
bare run dir.

Library: derive_entry(bundle), append_entry(reg_dir, entry, seed), verify_chain(reg_dir).
CLI lives in calma.py: `calma publish <run_dir>`, `calma publish --open <id>`,
`calma registry verify [DIR]`.
"""
import base64
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attest as A  # noqa: E402
import ed25519  # noqa: E402
import sshsig  # noqa: E402

ENTRY_SCHEMA = "calma/registry-entry@1"
HEAD_SCHEMA = "calma/registry-head@1"
ENTRY_KINDS = {"verification", "engagement-opened", "engagement-outcome"}
# THE redaction boundary. Nothing outside this set ever reaches a published entry, and
# verify_chain rejects entries with unknown keys - leaks fail closed.
ALLOWED_FIELDS = {
    "schema", "seq", "prev", "kind", "date", "target", "claim", "metric",
    "claimed", "recomputed", "verdict", "engagement", "note",
    "manifest_sha256", "ledger_sha256", "contract_sha256", "keyid", "time_verified",
}
REQUIRED_FIELDS = {"schema", "seq", "prev", "kind", "date", "verdict"}


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def entry_id(entry):
    """The content address of an entry: sha256 over its canonical bytes (prev included, so the
    id commits to the whole chain behind it - Crosby-Wallach style, degenerate-tree case)."""
    return hashlib.sha256(_canonical(entry)).hexdigest()


def _entries_dir(reg_dir):
    return os.path.join(reg_dir, "entries")


def _head_path(reg_dir):
    return os.path.join(reg_dir, "HEAD.json")


def read_head(reg_dir):
    try:
        return json.load(open(_head_path(reg_dir)))
    except (OSError, ValueError):
        return None


def list_entry_files(reg_dir):
    d = _entries_dir(reg_dir)
    if not os.path.isdir(d):
        return []
    return sorted(n for n in os.listdir(d) if n.endswith(".json"))


def load_entries(reg_dir):
    """[(filename, wrapper)] in sequence order."""
    out = []
    for n in list_entry_files(reg_dir):
        out.append((n, json.load(open(os.path.join(_entries_dir(reg_dir), n)))))
    return out


# ---- entry derivation (the redaction boundary) -------------------------------

def derive_entry(bundle, engagement=None, note=None, date=None):
    """A redacted registry entry from a VERIFIED attestation bundle. Pulls ONLY whitelisted
    scalars: the claim line, metric, claimed vs recomputed, verdict, content hashes. The caller
    must have run attest.verify_bundle first (calma.py enforces it)."""
    statement = json.loads(base64.b64decode(bundle["envelope"]["payload"]))
    pred = statement.get("predicate") or {}
    led = pred.get("ledger") or {}
    claims = pred.get("claims") or A.claims_summary(led)
    head = next((c for c in claims if c.get("headline")), claims[0] if claims else {})
    keyid = ((bundle.get("envelope") or {}).get("signatures") or [{}])[0].get("keyid")
    tv = pred.get("timeVerified")
    if date is None:
        date = (tv or "")[:10] or None
    if date is None:
        import datetime
        date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    metric = head.get("metric")
    claim_line = None
    if metric is not None and head.get("claimed") is not None:
        claim_line = "claimed %s %s" % (metric, head.get("claimed"))
    entry = {
        "schema": ENTRY_SCHEMA,
        "kind": "engagement-outcome" if engagement else "verification",
        "date": date,
        "target": os.path.basename(str(led.get("target", "run"))),
        "claim": claim_line,
        "metric": metric,
        "claimed": head.get("claimed"),
        "recomputed": head.get("recomputed"),
        "verdict": led.get("repo_verdict"),
        "engagement": engagement,
        "note": note,
        "manifest_sha256": (pred.get("manifest") or {}).get("manifest_sha256"),
        "ledger_sha256": ((statement.get("subject") or [{}])[0].get("digest") or {}).get("sha256"),
        "contract_sha256": (pred.get("policy") or {}).get("contract_sha256"),
        "keyid": keyid,
        "time_verified": tv,
    }
    return {k: v for k, v in entry.items() if v is not None}


def opened_entry(engagement, note=None, date=None):
    """An `engagement-opened` entry, published at contract signing - so a later missing outcome
    is structurally visible (the clinical-trial property)."""
    if not engagement:
        raise ValueError("--open requires an engagement id")
    if date is None:
        import datetime
        date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    e = {"schema": ENTRY_SCHEMA, "kind": "engagement-opened", "date": date,
         "engagement": engagement, "verdict": "PENDING", "note": note}
    return {k: v for k, v in e.items() if v is not None}


# ---- append + verify ----------------------------------------------------------

def append_entry(reg_dir, entry, seed):
    """Chain + sign + write. The entry gets seq/prev from the current HEAD; the wrapper stores
    the SSHSIG over the canonical entry bytes; HEAD.json is re-signed to make tail-truncation
    detectable. Returns (filename, wrapper)."""
    if entry.get("kind") not in ENTRY_KINDS:
        raise ValueError("entry kind %r invalid" % entry.get("kind"))
    os.makedirs(_entries_dir(reg_dir), exist_ok=True)
    head = read_head(reg_dir)
    entry = dict(entry)
    entry["seq"] = (head["seq"] + 1) if head else 1
    entry["prev"] = head["id"] if head else None
    bad = set(entry) - ALLOWED_FIELDS
    if bad:
        raise ValueError("entry carries non-whitelisted fields (redaction guard): %s"
                         % ", ".join(sorted(bad)))
    eid = entry_id(entry)
    pub = ed25519.secret_to_public(seed)
    principal = "calma-" + hashlib.sha256(pub).hexdigest()[:16]
    wrapper = {
        "entry": entry,
        "id": eid,
        "ssh": {"namespace": sshsig.NAMESPACE, "principal": principal,
                "public_key": sshsig.pub_line(pub, principal),
                "allowed_signers": sshsig.allowed_signers_line(pub, principal),
                "signature": sshsig.sign(seed, _canonical(entry))},
    }
    fname = "%05d-%s.json" % (entry["seq"], eid[:12])
    # atomic writes (write-temp + os.replace): a crash mid-append must never leave a truncated
    # entry or a HEAD that doesn't match the chain on disk
    entry_path = os.path.join(_entries_dir(reg_dir), fname)
    with open(entry_path + ".tmp", "w") as fh:
        json.dump(wrapper, fh, indent=2)
    os.replace(entry_path + ".tmp", entry_path)
    # HEAD is itself signed, so silently dropping the newest entries (tail truncation) breaks it
    new_head = {"schema": HEAD_SCHEMA, "seq": entry["seq"], "id": eid, "count": entry["seq"]}
    flat = dict(new_head)
    flat["ssh"] = {"namespace": sshsig.NAMESPACE, "principal": principal,
                   "public_key": sshsig.pub_line(pub, principal),
                   "signature": sshsig.sign(seed, _canonical(new_head))}
    head_path = _head_path(reg_dir)
    with open(head_path + ".tmp", "w") as fh:
        json.dump(flat, fh, indent=2)
    os.replace(head_path + ".tmp", head_path)
    return fname, wrapper


def verify_chain(reg_dir, pinned_pub_hex=None, min_seq=None):
    """Full offline audit of the registry. Returns (ok, checks, summary) where checks is an
    ordered list of (name, ok, detail). Catches: edited entries (id + signature), reordered or
    dropped MIDDLE entries (prev/seq links), non-whitelisted fields (redaction guard), and any
    entry signed by a key other than the pinned one.

    LIMITATION: a tail truncation in which the attacker ALSO rolls the signed HEAD back to a
    consistent earlier state (deleting the newest entries AND restoring the older, genuinely-signed
    HEAD that matched the log then) is internally consistent and CANNOT be detected from the files
    alone - a signed append-only log needs an EXTERNAL monotonic anchor. Pass `min_seq` (the lowest
    sequence number you know the log must have reached, e.g. from a prior audit or the git history)
    to turn that out-of-band knowledge into a hard rollback check."""
    checks = []

    def chk(name, ok, detail=""):
        checks.append((name, bool(ok), detail))
        return bool(ok)

    expect_pub = bytes.fromhex(pinned_pub_hex) if pinned_pub_hex else None
    entries = []
    try:
        entries = load_entries(reg_dir)
    except (OSError, ValueError) as e:
        chk("read", False, str(e))
        return False, checks, {}
    chk("read", True, "%d entries" % len(entries))

    prev_id, prev_seq = None, 0
    verdict_counts, opened, outcomes = {}, set(), set()
    for fname, w in entries:
        entry, eid, ssh = w.get("entry") or {}, w.get("id"), w.get("ssh") or {}
        label = fname
        if not chk("%s schema" % label, entry.get("schema") == ENTRY_SCHEMA
                   and entry.get("kind") in ENTRY_KINDS
                   and REQUIRED_FIELDS <= set(entry), "bad schema/kind/required fields"):
            return False, checks, {}
        bad = set(entry) - ALLOWED_FIELDS
        if not chk("%s redaction" % label, not bad,
                   "non-whitelisted fields: %s" % ", ".join(sorted(bad))):
            return False, checks, {}
        if not chk("%s id" % label, entry_id(entry) == eid, "stored id != canonical hash"):
            return False, checks, {}
        if not chk("%s chain" % label, entry.get("prev") == prev_id
                   and entry.get("seq") == prev_seq + 1,
                   "prev/seq does not extend the chain (reorder, edit, or a dropped entry)"):
            return False, checks, {}
        ok_sig, det = sshsig.verify(ssh.get("signature", ""), _canonical(entry),
                                    expect_pub=expect_pub)
        if not chk("%s signature" % label, ok_sig, det):
            return False, checks, {}
        prev_id, prev_seq = eid, entry["seq"]
        verdict_counts[entry.get("verdict")] = verdict_counts.get(entry.get("verdict"), 0) + 1
        if entry["kind"] == "engagement-opened":
            opened.add(entry.get("engagement"))
        if entry["kind"] == "engagement-outcome":
            outcomes.add(entry.get("engagement"))

    head = read_head(reg_dir)
    if entries or head:
        head_ok = bool(head) and head.get("id") == prev_id and head.get("seq") == prev_seq
        if head_ok:
            flat = {k: v for k, v in head.items() if k != "ssh"}
            ok_sig, det = sshsig.verify((head.get("ssh") or {}).get("signature", ""),
                                        _canonical(flat), expect_pub=expect_pub)
            head_ok, head_det = ok_sig, det
        else:
            head_det = "HEAD does not match the last entry (inconsistent truncation or missing HEAD)"
        if not chk("HEAD", head_ok, head_det):
            return False, checks, {}

    # external rollback anchor: a consistent tail-truncation (entries + HEAD both rolled back to an
    # earlier genuinely-signed state) is internally valid and undetectable from the files alone. If
    # the caller supplies the lowest sequence the log is KNOWN to have reached, enforce it.
    if min_seq is not None:
        if not chk("rollback", prev_seq >= min_seq,
                   "registry is at seq %d but a floor of %d was pinned - newer entries were dropped "
                   "(rollback / tail truncation)" % (prev_seq, min_seq),
                   ):
            return False, checks, {}

    summary = {"entries": len(entries), "verdicts": verdict_counts,
               "open_engagements": sorted(x for x in (opened - outcomes) if x)}
    return True, checks, summary


def render_verify(ok, checks, summary):
    _ne = summary.get("entries", 0)
    lines = ["REGISTRY %s  -  %d entr%s" % ("VERIFIED" if ok else "BROKEN",
                                            _ne, "y" if _ne == 1 else "ies")]
    for name, cok, detail in checks:
        if not cok:
            lines.append("  %-28s FAIL  (%s)" % (name, detail))
    if ok:
        for v, n in sorted((summary.get("verdicts") or {}).items()):
            lines.append("  %-12s %d" % (v, n))
        if summary.get("open_engagements"):
            lines.append("  open engagements (no outcome yet): %s"
                         % ", ".join(summary["open_engagements"]))
        lines.append("  every entry re-hashes, the chain links, and every signature verifies")
    return "\n".join(lines)
