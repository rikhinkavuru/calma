"""B3: the allocator evidence-bundle export. From a REAL verified+signed run, build_evidence projects
the existing artifacts (ledger, signed bundle, manifest) into the allocator/ODD shape: verified result,
input lineage by content hash, runtime digests, scope, assurance flags, and the GIPS-2026/ODD mapping -
plus a human cover sheet and the carried proof. NO new computation; it re-labels what the pipeline made.
On a host that can't isolate, the run is inconclusive but a bundle/ledger still exist, so the structural
asserts hold. Pure stdlib, offline. Run: python3 test_evidence_bundle.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
import attest as A  # noqa: E402
import calma as C  # noqa: E402
import evidence_bundle as EV  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


BTC = os.path.realpath(os.path.join(SCR, "..", "assets", "btc"))
tmp_keys = tempfile.mkdtemp()
os.environ["CALMA_KEY_DIR"] = tmp_keys
A.keygen()                                   # so the run is signed (the evidence needs a bundle)

res = C.verify(BTC, "+14,698%", "total_return", run_id="test_evidence", opts=C.VerifyOptions(force=True))
run_dir = res["run_dir"]

# --- evidence_json: the structured allocator object ---
ev = EV.evidence_json(run_dir)
truth(ev["spec"] == EV.SPEC_VERSION, "evidence carries the spec version")
vr = ev["verified_result"]
truth(vr["metric"] == "total_return" and vr["verdict"] in
      ("REFUTED", "CONFIRMED", "CONFIRMED-WITH-CAVEATS", "INVALIDATED", "INCONCLUSIVE"),
      "verified_result carries the metric + the engine verdict")
truth("recompute" in vr["method"] and "not a model" in vr["method"],
      "verified_result states the method (recompute, deterministic, not a model)")
truth(set(("isolation_tier", "determinism_mode")) <= set(ev["execution"]),
      "execution block carries the isolation tier + determinism mode (ODD)")
truth(isinstance(ev["input_lineage"], list),
      "input_lineage is present (datasets + code pinned by content hash)")
truth("verified" in ev["scope_of_verification"] and "did_not_assess" in ev["scope_of_verification"],
      "scope-of-verification carries the honest verified / did-not-assess boundary")
truth(set(("signed", "trusted_timestamp", "offline_replayable", "independent")) <= set(ev["assurance"]),
      "assurance flags present (signed / timestamp / replayable / independent)")
truth(ev["assurance"]["signed"] is True, "the run is signed -> assurance.signed is True")
truth(set(("GIPS-2026", "ODD")) <= set(ev["standards_mapping"]),
      "standards mapping covers GIPS-2026 + ODD")
truth("ledger_sha256" in ev["integrity"] and ev["integrity"]["signing_keyid"],
      "integrity block carries the content hashes + the signing keyid an LP re-checks")

# --- cover_sheet: the human deliverable in allocator vocabulary ---
md = EV.cover_sheet(ev)
truth(md.startswith("# Independent verification evidence") and "operational due-diligence" in md,
      "cover sheet leads as an ODD-facing evidence doc")
truth("Independently recomputed" in md and "GIPS-2026" in md and "replay" in md.lower(),
      "cover sheet shows the recompute, the GIPS mapping, and the replay path")

# --- W8(c) M-8c.1: the IDD/ODD deliverable fields (pure re-projection, no new computation) ---
truth(ev.get("examination_statement", "").endswith("not a firm-wide GIPS verification."),
      "examination_statement is GIPS-scoped down (a number, not a firm)")
truth(ev["subject"] in ev["examination_statement"]
      and (ev["verified_result"].get("verdict") or "") in ev["examination_statement"],
      "examination_statement names the subject + the verdict")
lim = ev.get("limitations") or []
truth([c["id"] for c in lim] == ["L1", "L2", "L3"], "the three fixed limitation clauses are always present")
truth("reproducible" in lim[0]["title"].lower() and all(c["text"] for c in lim),
      "L1 = reproducible != correct (the load-bearing ceiling)")
tf = ev["input_data_treatment"]["treatment_flags"]
truth(set(tf) == {"net_of_fees", "costs_included", "survivorship_handled", "look_ahead_controlled"},
      "input_data_treatment carries the GIPS #9 treatment flags")
truth(all(v == "declared" or v.startswith("not declared") for v in tf.values()),
      "each treatment flag is declared / not-declared (the honest GIPS #9 row)")
# a present block (even an empty {}) is 'declared'; an absent block is 'not declared' (key presence, not truthiness)
_t = EV._input_data_treatment([], {"frictions": {}, "split": {"train": "a", "test": "b"}})["treatment_flags"]
truth(_t["net_of_fees"] == "declared" and _t["look_ahead_controlled"] == "declared"
      and _t["survivorship_handled"].startswith("not declared"),
      "treatment flags: a present block (even empty) -> declared; an absent one -> not declared")
ddq = ev["ddq_performance_module"]
truth("replay" in ddq["track_record_independently_verifiable"].lower() and "not_independently_assessed" in ddq,
      "ddq_performance_module answers the AIMA performance questions")
truth("Reviewed by" in ev["odd_analyst_checklist"]["sign_off"], "odd_analyst_checklist carries a sign-off line")

# the IDD report renders the 8 sections (markdown) + a styled html page, computing NO new verdict
idd = EV.idd_report(ev)
for sec in ("§1 Verified result", "§2 Input data treatment", "§3 How it was verified",
            "§4 ODD analyst checklist", "§5 DDQ performance", "§6 Scope & limitations",
            "§7 Assurance", "§8 Redaction"):
    truth(sec in idd, "IDD report has %s" % sec)
truth("L1 — reproducible" in idd and "L3 — scope" in idd, "IDD report prints the L1..L3 limitations")
truth((ev["verified_result"].get("verdict") or "—") in idd,
      "the report shows the LEDGER's verdict (re-projection, never a new decision)")
html = EV.idd_report_html(ev)
truth(html.startswith("<!doctype html") and "<table>" in html and "IDD/ODD" in html,
      "idd_report_html is a self-contained styled page")

# the checklist surfaces ✅ checked / 🚩 flag-for-declaration / ⛔ not-assessed from families + inferred-flags
syn_scope = {"families": {"reproducibility": "checked", "leakage": "flagged", "inferred-flags": "flagged"},
             "not_verified": ["data-snooping (no trials block)"]}
syn_find = [{"dimension": "leakage", "validity_class": "inferred-flag", "unblock": "declare the split: block"}]
rows = EV._odd_analyst_checklist(syn_scope, syn_find)["rows"]
marks = {r["family"]: r["status"] for r in rows}
truth(marks.get("reproducibility", "").startswith("✅"), "checklist: a checked family -> ✅")
truth("flag-for-declaration" in marks.get("leakage", ""),
      "checklist: an inferred-flag dimension -> 🚩 flag-for-declaration")
truth(any("not-assessed" in r["status"] for r in rows), "checklist: an undeclared family -> ⛔ not-assessed")

# --- build_evidence: the on-disk pack (structured + human + carried proof) ---
out = tempfile.mkdtemp()
d = EV.build_evidence(run_dir, out)
truth(os.path.isfile(os.path.join(d, "evidence.json")), "build_evidence writes evidence.json")
truth(os.path.isfile(os.path.join(d, "EVIDENCE.md")), "build_evidence writes the EVIDENCE.md cover sheet")
truth(os.path.isfile(os.path.join(d, "attestation.bundle.json")),
      "build_evidence carries the signed attestation bundle (the proof, not just the summary)")
truth(os.path.isfile(os.path.join(d, "ledger.json")), "build_evidence carries the ledger")
truth(os.path.isfile(os.path.join(d, "IDD-REPORT.md")) and os.path.isfile(os.path.join(d, "IDD-REPORT.html")),
      "build_evidence writes the IDD-REPORT.md + .html deliverable")
# the carried evidence.json re-parses and matches the in-memory object (no drift)
truth(json.load(open(os.path.join(d, "evidence.json")))["subject"] == ev["subject"],
      "the written evidence.json round-trips")

# --- guards ---
try:
    EV.evidence_json(tempfile.mkdtemp())     # no ledger -> not a verified run
    truth(False, "evidence_json rejects an unverified run dir")
except ValueError:
    truth(True, "evidence_json rejects an unverified run dir (no ledger)")
try:
    EV.build_evidence(run_dir, run_dir)      # out == run dir would clobber the source
    truth(False, "build_evidence refuses --out == run dir")
except ValueError:
    truth(True, "build_evidence refuses --out == the run dir itself")

print("evidence_bundle: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
