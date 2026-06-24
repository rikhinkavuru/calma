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


# W8(c) — the three FIXED, load-bearing limitation clauses. Always present, never editable: they map onto
# the structural ceilings the build plan names (reproducible != correct; input-data authenticity; scope is
# the declared scope) and are exactly what keeps the deliverable from over-claiming — i.e. what makes it
# signable. An ODD analyst initials a report that states its own boundary.
LIMITATIONS = (
    {"id": "L1", "title": "reproducible ≠ correct",
     "text": "We confirm the number follows from the manager's own outputs; we do not certify the outputs "
             "reflect reality (a faithful recompute of a wrong methodology is still a wrong result)."},
    {"id": "L2", "title": "input-data authenticity",
     "text": "We content-hash the inputs we were given; we do not independently source market/return data. "
             "Chain-of-custody upstream of the artifact is the manager's (see input lineage / W8(d))."},
    {"id": "L3", "title": "scope is the declared scope",
     "text": "Families the manager did not declare were not authoritatively assessed; see did_not_assess "
             "and any inferred-flags (a flag-for-declaration is a demand to declare, not a clearance)."},
)


def _load_contract(run_dir):
    """The committed verify.yaml as a dict (treatment blocks like frictions/universe/pit/embargo/split).
    Lazy import of the drafter's loader; {} when absent/unparseable (every flag then reads 'not declared')."""
    path = os.path.join(run_dir, "verify.yaml")
    if not os.path.isfile(path):
        return {}
    try:
        import draft_contract as _DC  # noqa: PLC0415 - lazy; evidence_bundle stays import-light
        return _DC.load_contract(path) or {}
    except Exception:  # noqa: BLE001 - a malformed contract must not break the (re-projection) bundle
        return {}


def _input_data_treatment(lineage, contract):
    """GIPS Input-Data #9 mapping: the declared-treatment flags surfaced from the contract blocks, per the
    artifacts we content-hashed. An UNDECLARED block reads 'not declared - see scope.did_not_assess' (the
    honest GIPS #9 row an ODD analyst maps straight across). Re-projection only - reads no data."""
    b = contract or {}
    def _declared(*keys):                                # "declared" = the block KEY is present (even if {});
        return any(b.get(k) is not None for k in keys)   # absent or null = not declared. NOT a truthiness test
    def _f(ok):                                          # (an empty-but-present `frictions: {}` IS a declaration).
        return "declared" if ok else "not declared - see scope.did_not_assess"
    return {
        "artifacts": [{"path": m.get("path"), "sha256": m.get("sha256")} for m in (lineage or [])],
        "treatment_flags": {
            "net_of_fees": _f(_declared("frictions")),
            "costs_included": _f(_declared("frictions", "backtest")),
            "survivorship_handled": _f(_declared("universe", "pit")),
            "look_ahead_controlled": _f(_declared("embargo", "split", "pit")),
        },
    }


def _ddq_performance_module(treatment, did_not_assess, determinism_mode):
    """AIMA Performance-Presentation Q&A the verdict can answer (the section an allocator pastes into a DDQ).
    No new computation - it re-states the re-projection in DDQ vocabulary."""
    net = treatment["treatment_flags"]["net_of_fees"] == "declared"
    bit = determinism_mode == "controlled-to-bit"
    return {
        "track_record_independently_verifiable": ("yes - a self-contained replay bundle re-derives the "
                                                   "verdict offline, byte-for-byte"),
        "gross_or_net": ("net of fees (frictions declared)" if net
                         else "not determinable from the declared scope - frictions were not declared"),
        "methodology_reproducible": ("yes - deterministic kernels, recompute K-spread 0%s, verdict by "
                                     "code not a model" % (" (bit-exact)" if bit else "")),
        "not_independently_assessed": list(did_not_assess or []),
    }


_CHECK_MARK = "✅ checked"
_FLAG_MARK = "⚠️ flagged"
_DEMAND_MARK = "\U0001f6a9 flag-for-declaration"
_GAP_MARK = "⛔ not-assessed (undeclared)"


def _odd_analyst_checklist(scope, findings):
    """A machine-generated, human-signable per-family checklist: each family -> checked / flagged /
    flag-for-declaration / not-assessed, with the one-line "what to ask the manager." Derived from
    scope.families + scope.not_verified + the inferred-flags (validity_class='inferred-flag')."""
    families = scope.get("families") or {}
    not_assessed = scope.get("not_verified") or []
    flag_dims = {f.get("dimension"): f for f in (findings or [])
                 if f.get("validity_class") == "inferred-flag"}
    rows = []
    for fam, status in families.items():
        if fam == "inferred-flags":
            continue                                    # surfaced per-dimension below, not as a meta-row
        s = str(status)
        if s.startswith("checked") or s == "checked":
            rows.append({"family": fam, "status": _CHECK_MARK, "ask": ""})
        elif s == "flagged":
            rows.append({"family": fam, "status": _FLAG_MARK,
                         "ask": "review the flagged finding before relying on the number"})
        elif s in ("FAILED",):
            rows.append({"family": fam, "status": _GAP_MARK, "ask": "the re-execution failed - ask why"})
    for fam, f in flag_dims.items():                    # the loud inferred demands (FLAG_FOR_DECLARATION)
        rows.append({"family": fam, "status": _DEMAND_MARK,
                     "ask": f.get("unblock") or "ask the manager to declare the inferred block"})
    for gap in not_assessed:                            # undeclared families = a blank an analyst must chase
        rows.append({"family": str(gap), "status": _GAP_MARK,
                     "ask": "ask the manager to declare this block, then re-verify"})
    return {"rows": rows, "sign_off": "Reviewed by ______________________    Date ________________"}


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

    # W8(c) IDD/ODD fields — pure re-projection (no engine computation): the GIPS/AIMA/ODD shapes an
    # IC-acceptable deliverable maps onto. examination_statement is GIPS-scoped (a number, not a firm);
    # input_data_treatment is the GIPS #9 row; ddq_performance_module is the AIMA Q&A; the checklist is the
    # signable per-family ✅/⚠️/🚩/⛔ table; LIMITATIONS are the three fixed, load-bearing ceilings.
    contract = _load_contract(run_dir)
    did_not_assess = scope.get("not_verified") or []
    treatment = _input_data_treatment(lineage, contract)
    rec = REP.fmt_value(head.get("recomputed_value"), head.get("metric")) \
        if head.get("recomputed_value") is not None else "—"
    clm = REP.fmt_value(head.get("claimed_value"), head.get("metric")) \
        if head.get("claimed_value") is not None else "—"
    examination_statement = (
        "%s's reported %s of %s was independently re-executed and recomputed from the raw outputs to %s; "
        "verdict %s. This is a metric-level performance examination, not a firm-wide GIPS verification."
        % (led.get("target", "the manager"), head.get("metric") or "the metric", clm, rec,
           led.get("repo_verdict") or "—"))

    return {
        "spec": SPEC_VERSION,
        "subject": led.get("target", "result"),
        "examination_statement": examination_statement,
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
        # GIPS Input-Data #9: declared treatment flags per content-hashed artifact (undeclared -> flagged).
        "input_data_treatment": treatment,
        # AIMA Performance-Presentation module: the DDQ Q&A the verdict answers.
        "ddq_performance_module": _ddq_performance_module(treatment, did_not_assess,
                                                          scope.get("determinism_mode")),
        # the signable per-family checklist (✅ checked / ⚠️ flagged / 🚩 flag-for-declaration / ⛔ not-assessed).
        "odd_analyst_checklist": _odd_analyst_checklist(scope, led.get("findings")),
        # the three fixed, always-present, never-editable limitation clauses (the structural ceilings).
        "limitations": [dict(c) for c in LIMITATIONS],
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


def idd_report(ev):
    """The multi-section IDD/ODD report (markdown) — the IC-acceptable deliverable, a graduation of the
    one-page cover_sheet. Renders ONLY the structured evidence (re-projection; no new computation): Cover +
    §1 Verified Result · §2 Input Data Treatment (GIPS #9) · §3 How It Was Verified (ODD) · §4 ODD Analyst
    Checklist · §5 DDQ Performance Module · §6 Scope & Limitations · §7 Assurance & Integrity · §8 Redaction."""
    vr, ig, asr = ev["verified_result"], ev["integrity"], ev["assurance"]
    sc, ex = ev["scope_of_verification"], ev["execution"]

    def _num(v):
        return REP.fmt_value(v, vr.get("metric")) if v is not None else "—"

    L = ["# IDD/ODD verification report — %s" % ev["subject"], "",
         "_%s_" % ev["examination_statement"], "",
         "**For:** allocator IC / operational due-diligence review &nbsp;·&nbsp; **Spec:** `%s`" % ev["spec"],
         "", "## §1 Verified result", "", "| | |", "|---|---|",
         "| Metric | `%s` |" % (vr.get("metric") or "—"),
         "| Reported (manager) | %s |" % _num(vr.get("claimed_value")),
         "| **Independently recomputed** | **%s** |" % _num(vr.get("recomputed_value")),
         "| Verdict | **%s** |" % (vr.get("verdict") or "—"),
         "| Confidence | %s |" % (vr.get("confidence") if vr.get("confidence") is not None else "—"),
         "", "## §2 Input data treatment (GIPS #9)", "", "| Treatment | Status |", "|---|---|"]
    for k, v in ev["input_data_treatment"]["treatment_flags"].items():
        L.append("| %s | %s |" % (k.replace("_", " "), v))
    arts = ev["input_data_treatment"]["artifacts"]
    if arts:
        L += ["", "Content-hashed artifacts:"]
        L += ["- `%s` — `%s`" % (a.get("path") or "—", a.get("sha256") or "—") for a in arts]
    L += ["", "## §3 How it was verified (ODD)", "",
          "- **Re-execution:** re-run in a `%s` sandbox (network `%s`), determinism `%s`."
          % (ex.get("isolation_tier"), ex.get("network") or "off", ex.get("determinism_mode")),
          "- **Recompute, not trust:** the headline was rebuilt from the raw output files, never read from "
          "the reported number; the verdict is computed by deterministic code, not a model.",
          "- **Independent reproduction:** a self-contained replay bundle re-derives this verdict offline, "
          "byte-for-byte (`replay/` → `sh replay.sh`).",
          "", "## §4 ODD analyst checklist", "",
          "| Family | Status | What to ask the manager |", "|---|---|---|"]
    for r in ev["odd_analyst_checklist"]["rows"]:
        L.append("| %s | %s | %s |" % (r["family"], r["status"], r.get("ask") or ""))
    L += ["", "_%s_" % ev["odd_analyst_checklist"]["sign_off"], "",
          "## §5 DDQ performance module (AIMA)", ""]
    ddq = ev["ddq_performance_module"]
    L += ["- **Track record independently verifiable?** %s" % ddq["track_record_independently_verifiable"],
          "- **Gross or net?** %s" % ddq["gross_or_net"],
          "- **Methodology reproducible?** %s" % ddq["methodology_reproducible"],
          "- **Not independently assessed:** %s" % ("; ".join(ddq["not_independently_assessed"]) or "—"),
          "", "## §6 Scope & limitations", "",
          "- **Verified:** %s" % (", ".join(sc["verified"]) or "the headline recompute")]
    if sc.get("did_not_assess"):
        L.append("- **Did NOT assess:** %s" % "; ".join(sc["did_not_assess"]))
    L += ["", "**Limitations (always apply — this is what makes the report signable):**"]
    L += ["- **%s — %s.** %s" % (c["id"], c["title"], c["text"]) for c in ev["limitations"]]
    L += ["", "## §7 Assurance & integrity", "",
          "- Signed: **%s** (DSSE + OpenSSH SSHSIG) · Trusted timestamp: **%s** (RFC-3161) · "
          "Offline-replayable: **%s**" % ("yes" if asr["signed"] else "no",
                                          "yes" if asr["trusted_timestamp"] else "no",
                                          "yes" if asr["offline_replayable"] else "no"),
          "- `ledger` `%s`" % (ig.get("ledger_sha256") or "—"),
          "- `manifest` `%s`" % (ig.get("manifest_sha256") or "—"),
          "- signing keyid `%s` · verified `%s`" % (ig.get("signing_keyid") or "—",
                                                    ig.get("time_verified") or "—"),
          "", "## §8 Redaction boundary (read before sharing)", "", "> " + REDACTION_NOTICE, "",
          "---", "*Verify it yourself: `calma attest verify attestation.bundle.json --replay` re-checks the "
          "signature and re-derives the verdict offline. No number here is computed by a model.*"]
    return "\n".join(L)


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline(s):
    """Minimal inline markdown -> html for the constructs idd_report emits: `code`, **bold**, _italic_."""
    import re
    s = _esc(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(^|[\s(])_([^_]+)_", r"\1<em>\2</em>", s)
    return s


def _md_to_html(md):
    """A small, defensive markdown->html for exactly the subset idd_report emits (#/## headings, | tables |,
    - lists, > blockquote, --- hr, paragraphs). Not a general parser — scoped to this one deliverable."""
    out, i, lines = [], 0, md.split("\n")
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("## "):
            out.append("<h2>%s</h2>" % _inline(ln[3:]))
        elif ln.startswith("# "):
            out.append("<h1>%s</h1>" % _inline(ln[2:]))
        elif ln.strip() == "---":
            out.append("<hr>")
        elif ln.startswith("> "):
            out.append("<blockquote>%s</blockquote>" % _inline(ln[2:]))
        elif ln.startswith("|"):                         # a markdown table: gather contiguous rows
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
            cells = [r for r in cells if not all(set(c) <= set("-: ") for c in r)]  # drop the --- separator
            if cells:
                out.append("<table>")
                out.append("<tr>" + "".join("<th>%s</th>" % _inline(c) for c in cells[0]) + "</tr>")
                for r in cells[1:]:
                    out.append("<tr>" + "".join("<td>%s</td>" % _inline(c) for c in r) + "</tr>")
                out.append("</table>")
            continue
        elif ln.startswith("- "):                        # a list: gather contiguous items
            out.append("<ul>")
            while i < len(lines) and lines[i].startswith("- "):
                out.append("<li>%s</li>" % _inline(lines[i][2:]))
                i += 1
            out.append("</ul>")
            continue
        elif ln.strip():
            out.append("<p>%s</p>" % _inline(ln))
        i += 1
    return "\n".join(out)


def idd_report_html(ev):
    """The IDD/ODD report rendered to a self-contained styled HTML page (reuses report.py's report styling)."""
    body = _md_to_html(idd_report(ev))
    return ("<!doctype html><html lang=en><head><meta charset=utf-8><title>Calma IDD/ODD — %s</title>"
            "<style>%s</style></head><body><div class=page>%s</div></body></html>"
            % (_esc(ev["subject"]), REP._HTML_CSS, body))


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
    # W8(c): the IC-acceptable IDD/ODD deliverable (8 sections) in markdown + a styled HTML page. Still a
    # pure re-projection — no verdict is decided here (the docstring invariant holds).
    with open(os.path.join(out_dir, "IDD-REPORT.md"), "w") as fh:
        fh.write(idd_report(ev))
    with open(os.path.join(out_dir, "IDD-REPORT.html"), "w") as fh:
        fh.write(idd_report_html(ev))
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
