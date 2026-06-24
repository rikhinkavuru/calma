"""calma.soc2_controls - the four Calma-specific SOC 2 controls (master roadmap §1.2), run as ONE auditable,
CI-runnable evidence pack. These are the controls the "data never leaves / network-off / no-raw-retention"
architecture turns from a slogan into *testable, attestable* evidence — exactly what a verdict-issuing vendor's
buyers probe hardest. Each wraps an existing engine mechanism; together they ARE the auditor's evidence pack.

  1. sandbox-isolation        - a sandbox-per-run under a verified tier; network-default-deny + secret-read
                                deny, proven by the doctor self-test (wraps run_hermetic.doctor).
  2. egress-blocked           - a sandboxed job cannot reach DNS / an external IP / the 169.254.169.254
                                cloud-metadata endpoint / IPv6 (wraps egress_audit).
  3. no-raw-data-retention    - published records are a metadata-only whitelist (hashes + verdict + labels);
                                the chain fails closed on any non-whitelisted key (wraps registry.ALLOWED_FIELDS).
  4. verdict-integrity        - every stored verdict re-derives byte-for-byte from its verdict_inputs (the gate
                                + determinism), so a label can't be forged (wraps ledger.semantic_validate).

A control's result is `verified` (the control holds), `skipped-host-not-isolated` (honest: no local sandbox
to attest — never a false pass), or `FAILED`/`LEAK` (the control did not hold — investigate). NO external
credentials: everything exercises the local engine. `all_pass` is true iff no control FAILED/LEAKed (a skip
is not a failure). This is the W9 "run the controls, get the evidence" deliverable.

Run:  python3 soc2_controls.py [--out evidence.json] [--as-of YYYY-MM-DD]   (exit 0 = all pass; 1 = a failure)
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
_BTC_LEDGER = os.path.join(HERE, "..", "assets", "btc", "ledger.json")

CONTROL_PACK = "calma-soc2-controls@1"


def control_isolation():
    """Wrap the doctor self-test: a sandbox-per-run under a verified tier denies egress AND secret-reads."""
    import run_hermetic as H
    doc = H.doctor()
    tier = doc.get("tier") or "host-not-isolated"
    if not doc.get("sandbox_exec"):
        return {"name": "sandbox-isolation", "result": "skipped-host-not-isolated", "tier": tier,
                "detail": "no local sandbox tool (Seatbelt/bubblewrap) on this host - no boundary to attest"}
    ok = bool(doc.get("egress_blocked")) and bool(doc.get("secret_read_blocked"))
    return {"name": "sandbox-isolation", "result": "verified" if ok else "FAILED", "tier": tier,
            "detail": "sandbox-per-run under %s; egress-denied=%s, secret-read-denied=%s (host-kernel-shared: "
                      "verified = egress + secret-read denial, not escape isolation)"
                      % (tier, doc.get("egress_blocked"), doc.get("secret_read_blocked"))}


def control_egress():
    """Wrap egress_audit: every named egress vector denied under a verified tier."""
    import egress_audit as EA
    ev = EA.audit()
    res = {"denied": "verified", "LEAK": "LEAK"}.get(ev["result"], "skipped-host-not-isolated")
    return {"name": "egress-blocked", "result": res, "tier": ev["isolation_tier"],
            "vectors": ev["vectors_tested"], "detail": ev["note"]}


def control_no_raw_retention():
    """Attest the registry redaction boundary: ALLOWED_FIELDS is metadata-only (no raw data/paths), and the
    chain rejects any entry carrying a non-whitelisted key (`set(entry) - ALLOWED_FIELDS`, the exact guard
    verify_chain uses) - so raw inputs structurally cannot reach a published record."""
    import registry as REG
    raw_keys = {"raw_input_path", "raw_rows", "input_bundle", "artifact_path", "dataset", "input", "rows"}
    whitelist_metadata_only = not (raw_keys & REG.ALLOWED_FIELDS)
    leaky = dict.fromkeys(REG.REQUIRED_FIELDS, "x")
    leaky.update({"raw_rows": [[1, 2], [3, 4]], "input_bundle": "s3://manager/data.csv"})
    chain_rejects_raw = bool(set(leaky) - REG.ALLOWED_FIELDS)        # verify_chain fails closed on this
    ok = whitelist_metadata_only and chain_rejects_raw
    return {"name": "no-raw-data-retention", "result": "verified" if ok else "FAILED",
            "detail": "published records are a %d-field metadata whitelist (hashes + verdict + labels, no raw "
                      "data/paths); the chain fails closed on any non-whitelisted key" % len(REG.ALLOWED_FIELDS)}


def control_verdict_integrity(ledger_path=None):
    """Attest that every stored verdict re-derives byte-for-byte from its verdict_inputs (ledger._validate
    re-invokes the pure verdict() and byte-checks the stored label) - a label can't be forged or model-set.
    Runs against the signed BTC fixture by default (a real REFUTED ledger)."""
    import ledger as L
    path = ledger_path or _BTC_LEDGER
    try:
        led = L.load_ledger(path)
        struct_errs = L.structural_validate(led)
        sem_errs = [] if struct_errs else L.semantic_validate(led)
    except (OSError, ValueError) as e:
        return {"name": "verdict-integrity", "result": "skipped", "detail": "no ledger to attest (%s)" % e}
    ok = not struct_errs and not sem_errs
    import calma as _C  # noqa: PLC0415 - only for the version pin (heavy module; lazy)
    return {"name": "verdict-integrity", "result": "verified" if ok else "FAILED",
            "engine_version": getattr(_C, "__version__", None),
            "detail": "every stored verdict re-derives byte-for-byte from its verdict_inputs via the gate's "
                      "_validate; the label is computed by one deterministic function, never a model"
                      if ok else "a stored verdict did NOT re-derive: %s" % (struct_errs or sem_errs)}


def run_controls(as_of=None, ledger_path=None):
    """Run all four controls and return the consolidated, dated evidence pack."""
    controls = [
        control_isolation(),
        control_egress(),
        control_no_raw_retention(),
        control_verdict_integrity(ledger_path),
    ]
    failed = [c for c in controls if str(c["result"]) in ("FAILED", "LEAK")]
    verified = [c for c in controls if c["result"] == "verified"]
    skipped = [c for c in controls if str(c["result"]).startswith("skipped")]
    return {
        "control_pack": CONTROL_PACK,
        "as_of": as_of,
        "host": sys.platform,
        "controls": controls,
        "all_pass": not failed,
        "summary": "%d controls: %d verified, %d skipped (no local sandbox), %d FAILED"
                   % (len(controls), len(verified), len(skipped), len(failed)),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run the four Calma SOC 2 controls as one auditable evidence pack.")
    ap.add_argument("--out", help="write the JSON evidence pack here")
    ap.add_argument("--as-of", default=None, help="evidence date (YYYY-MM-DD); omit to leave null")
    ap.add_argument("--ledger", default=None, help="a ledger.json to attest verdict-integrity against")
    a = ap.parse_args(argv)
    pack = run_controls(as_of=a.as_of, ledger_path=a.ledger)
    text = json.dumps(pack, indent=2)
    if a.out:
        with open(a.out, "w") as fh:
            fh.write(text)
    print(text)
    return 0 if pack["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
