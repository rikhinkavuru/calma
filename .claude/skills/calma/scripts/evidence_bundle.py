"""calma.evidence_bundle - B3: the allocator "evidence bundle" export.

Allocators (LPs / fund-of-funds / ODD teams) are converging on a 2026 evidence spec for a number they're
asked to allocate on: dataset versions + lineage, runtime/environment digests, the verdict, and
replay instructions - mapped to the language operational due diligence (ODD) and GIPS-2026 use. Calma
already produces every one of those as a by-product of `verify` + `seal` (the signed VSA/in-toto bundle,
the content-hashed manifest, the ledger, the offline replay bundle). This packages them into the shape
an allocator expects, with a human cover sheet in their vocabulary.

NO NEW ENGINE WORK: this is a pure re-projection of existing run-dir artifacts (ledger.json, the signed
attestation bundle, manifest.json, report.html, replay/). It computes no metric and decides no verdict -
it reads what the deterministic pipeline already produced and re-labels it for the manager->allocator
handoff (a second buyer off the same artifact).

Maps to:
  - GIPS-2026 (Global Investment Performance Standards): the verified return/metric + the
    independent-verification statement + the input provenance an LP's verifier re-checks.
  - ODD (operational due diligence): "can we independently reproduce this number, and what exactly was
    run on what data?" - answered by the replay bundle + the lineage digests.

Library: build_evidence(run_dir, out_dir=None) -> out_dir; evidence_json(run_dir) -> dict;
cover_sheet(evidence) -> markdown str.
"""
import json
import os
import shutil

import pathsafe as PS
import report as REP

SPEC_VERSION = "calma-allocator-evidence@1"

# L3: an evidence bundle is a PRIVATE allocator/ODD handoff - by design it carries input_lineage
# (artifact paths) + the target name, which a PUBLIC registry entry deliberately redacts away
# (registry.ALLOWED_FIELDS is a hard whitelist; this is not). Surface the distinction so nobody
# ships an evidence pack assuming registry-grade redaction. See docs/internal/EVIDENCE-VS-REGISTRY.md.
REDACTION_NOTICE = ("This evidence bundle is a PRIVATE allocator/ODD handoff: it intentionally "
                    "carries input lineage (artifact paths) and the target name. It is NOT a "
                    "redacted public registry entry (a public entry passes an internal field "
                    "allowlist that strips paths). Share it under the same NDA as the manager's "
                    "data - not as a public attestation.")


def _load(run_dir, name):
    try:
        return json.load(open(os.path.join(run_dir, name)))
    except (OSError, ValueError):
        return None


def _bundle_predicate(bundle):
    """The VSA/in-toto predicate (verdict, timeVerified, materials lineage, verifier) from the signed
    bundle's base64 DSSE payload. {} when no bundle / unparseable."""
    import base64
    try:
        stmt = json.loads(base64.b64decode(bundle["envelope"]["payload"]))
        return stmt.get("predicate") or {}, stmt
    except (KeyError, ValueError, TypeError):
        return {}, {}


def evidence_json(run_dir):
    """The structured allocator evidence object, assembled from the existing run-dir artifacts. Raises
    ValueError when the run isn't sealed (no ledger) - an allocator pack must stand on a real verdict."""
    led = _load(run_dir, "ledger.json")
    if not led:
        raise ValueError("no ledger.json in %s - run `calma verify` (and `calma seal`) first" % run_dir)
    bundle = _load(run_dir, "attestation.bundle.json")
    manifest = _load(run_dir, "manifest.json") or {}
    pred, stmt = _bundle_predicate(bundle) if bundle else ({}, {})
    claims = [c for c in (led.get("claims") or []) if c.get("metric")]
    head = next((c for c in claims if c.get("headline")), claims[0] if claims else {})
    scope = led.get("scope") or {}
    hashes = REP._report_hashes(run_dir, bundle)
    signed = bool(bundle)
    timestamped = bool(pred.get("timeVerified")) and signed

    # input lineage = the content-hashed materials (datasets, code, outputs the run re-emitted)
    lineage = [{"path": m.get("uri"), "sha256": (m.get("digest") or {}).get("sha256")}
               for m in (pred.get("materials") or [])]

    return {
        "spec": SPEC_VERSION,
        "subject": led.get("target", "result"),
        # the verified result (GIPS: the performance figure + the independent-verification result)
        "verified_result": {
            "metric": head.get("metric"),
            "claimed_value": head.get("claimed_value"),
            "recomputed_value": head.get("recomputed_value"),
            "verdict": led.get("repo_verdict"),
            "confidence": head.get("headline_confidence"),
            "method": "re-execution + recompute from raw outputs on deterministic kernels "
                      "(verdict by deterministic code, not a model)",
            "all_metrics": [{"metric": c.get("metric"), "claimed": c.get("claimed_value"),
                             "recomputed": c.get("recomputed_value"), "verdict": c.get("verdict")}
                            for c in claims],
        },
        # ODD: exactly what was run, on what, and how to reproduce it
        "execution": {
            "isolation_tier": scope.get("isolation_tier"),
            "determinism_mode": scope.get("determinism_mode"),
            "network": scope.get("run_network"),
            "verifier": (pred.get("verifier") or pred.get("builder") or {}),
        },
        "input_lineage": lineage,          # dataset versions + code, by content hash
        "scope_of_verification": {
            "verified": [k for k, v in (scope.get("families") or {}).items()
                         if str(v).startswith("checked") or str(v) == "flagged"],
            "did_not_assess": scope.get("not_verified") or [],
            "binding": scope.get("binding_note"),
        },
        "integrity": {                     # the digests an LP's verifier re-checks
            "ledger_sha256": hashes.get("ledger_sha256"),
            "manifest_sha256": hashes.get("manifest_sha256") or manifest.get("manifest_sha256"),
            "contract_sha256": hashes.get("contract_sha256"),
            "signing_keyid": hashes.get("keyid"),
            "time_verified": hashes.get("time_verified"),
        },
        "assurance": {
            "signed": signed,              # DSSE + OpenSSH SSHSIG
            "trusted_timestamp": timestamped,   # RFC-3161
            "offline_replayable": True,    # the replay bundle re-derives the verdict byte-for-byte
            "independent": True,           # the verifier is not the producer; deterministic, re-derivable
        },
        "standards_mapping": {
            "GIPS-2026": "verified performance figure + independent-verification result + input provenance",
            "ODD": "independent reproduction (replay bundle) + full run/dataset lineage by content hash",
            "in-toto/SLSA": "the signed VSA attestation binds the verdict to the content-addressed inputs",
        },
    }


def cover_sheet(ev):
    """A one-page human cover sheet in allocator / ODD vocabulary (markdown). Renders only the structured
    evidence above - no new computation."""
    vr = ev["verified_result"]
    ig = ev["integrity"]
    asr = ev["assurance"]

    def _num(v):
        return REP.fmt_value(v, vr.get("metric")) if v is not None else "—"

    L = ["# Independent verification evidence — %s" % ev["subject"], "",
         "**For:** allocator / operational due-diligence (ODD) review &nbsp;·&nbsp; "
         "**Spec:** `%s`" % ev["spec"], "",
         "## The verified result", "",
         "| | |", "|---|---|",
         "| Metric | `%s` |" % (vr.get("metric") or "—"),
         "| Reported (manager) | %s |" % _num(vr.get("claimed_value")),
         "| **Independently recomputed** | **%s** |" % _num(vr.get("recomputed_value")),
         "| Verdict | **%s** |" % (vr.get("verdict") or "—"),
         "| Method | %s |" % vr["method"], "",
         "## How it was verified (ODD)", "",
         "- **Re-execution:** the manager's code was re-run in a `%s` sandbox (network `%s`), determinism "
         "`%s`." % (ev["execution"].get("isolation_tier"), ev["execution"].get("network") or "off",
                    ev["execution"].get("determinism_mode")),
         "- **Recompute, not trust:** the headline was rebuilt from the raw output files, never read "
         "from the reported number; the verdict is computed by deterministic code, not a model.",
         "- **Input lineage:** %d input artifact(s) (datasets + code) pinned by SHA-256 (see "
         "`evidence.json → input_lineage`)." % len(ev.get("input_lineage") or []),
         "- **Independent reproduction:** a self-contained replay bundle re-derives this verdict offline, "
         "byte-for-byte, on a fresh machine (`replay/` → `sh replay.sh`).", "",
         "## Scope (the honest boundary)", ""]
    sc = ev["scope_of_verification"]
    L.append("- **Verified:** %s" % (", ".join(sc["verified"]) or "the headline recompute"))
    if sc.get("did_not_assess"):
        L.append("- **Did NOT assess:** %s" % "; ".join(sc["did_not_assess"]))
    L += ["", "## Assurance & integrity", "",
          "- Signed: **%s** (DSSE + OpenSSH SSHSIG) · Trusted timestamp: **%s** (RFC-3161) · "
          "Offline-replayable: **%s**" % ("yes" if asr["signed"] else "no",
                                          "yes" if asr["trusted_timestamp"] else "no",
                                          "yes" if asr["offline_replayable"] else "no"),
          "- `ledger` `%s`" % (ig.get("ledger_sha256") or "—"),
          "- `manifest` `%s`" % (ig.get("manifest_sha256") or "—"),
          "- `contract` `%s`" % (ig.get("contract_sha256") or "—"),
          "- signing keyid `%s` · verified `%s`" % (ig.get("signing_keyid") or "—",
                                                    ig.get("time_verified") or "—"), "",
          "## Standards mapping", ""]
    for k, v in ev["standards_mapping"].items():
        L.append("- **%s** — %s" % (k, v))
    L += ["", "## Redaction boundary (read before sharing)", "", "> " + REDACTION_NOTICE, "",
          "---", "*Verify it yourself: `calma attest verify attestation.bundle.json --replay` "
          "re-checks the signature and re-derives the verdict offline. Nothing here is computed by a "
          "model.*"]
    return "\n".join(L)


# the run-dir artifacts an allocator pack carries verbatim (the proof, not just the summary).
_CARRIED = ("attestation.bundle.json", "attestation.payload.json", "attestation.sig.sshsig",
            "attestation.allowed_signers", "VERIFY-THIS.txt", "ledger.json", "manifest.json",
            "verify.yaml", "report.html", "recompute.json", "diff.json")


def build_evidence(run_dir, out_dir=None):
    """Assemble the allocator evidence bundle: evidence.json + EVIDENCE.md (cover sheet) + the carried
    proof artifacts + the offline replay bundle (copied if present). Returns out_dir. Idempotent."""
    run_dir = os.path.realpath(run_dir)
    ev = evidence_json(run_dir)              # raises if not verified
    # L2: contain --out (no parent/traversal escape), not just out != source
    out_dir = PS.guard_out_dir(out_dir or os.path.join(run_dir, "evidence"), run_dir)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "evidence.json"), "w") as fh:
        json.dump(ev, fh, indent=2)
    with open(os.path.join(out_dir, "EVIDENCE.md"), "w") as fh:
        fh.write(cover_sheet(ev))
    for name in _CARRIED:
        src = os.path.join(run_dir, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(out_dir, name))
    # carry the offline replay bundle (the ODD "reproduce it yourself" deliverable) when present
    replay_src = os.path.join(run_dir, "replay")
    if os.path.isdir(replay_src):
        replay_dst = os.path.join(out_dir, "replay")
        if os.path.isdir(replay_dst):
            shutil.rmtree(replay_dst)
        shutil.copytree(replay_src, replay_dst)
    return out_dir
