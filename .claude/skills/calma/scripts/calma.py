"""calma - the orchestrator. One command chains the whole pipeline and emits the verdict.

  calma.py verify <target> [--claim VALUE] [--metric ID] [--run-id ID]

Steps: draft-or-load contract -> run_hermetic (verified isolation, re-emit raw artifacts) -> recompute
(reference-deterministic) -> compare (calibrated budget + shared verdict()) -> assemble + gate the ledger
-> attest (SBOM manifest) -> strictly-progressive report. The model READS the report; every number and
the verdict label come from the scripts. Writes everything under <target>/.calma/<run-id>/.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attest
import compare as CMP
import draft_contract as DC
import ledger as LED
import recompute as RC
import report as REP
import run_hermetic as H
import verdict as V


def _assemble_ledger(contract, diff, run_res):
    claims, findings = [], []
    for i, m in enumerate(diff["metrics"]):
        cid = "c%d" % (i + 1)
        vi = m["verdict_inputs"]
        label = m["verdict"]
        claim = {
            "id": cid, "headline": m["headline"], "headline_confidence": 0.96 if m["headline"] else 0.5,
            "metric": m["metric_id"], "claimed_value": m["claimed"], "recomputed_value": m["recomputed"],
            "verdict": label, "input_binding_status": vi["binding_status"],
            "verdict_inputs": vi, "verdict_status": "stable", "verdict_history": [], "waivable": False,
            "recipe_authority": "canonical", "set_maturity": "reviewed",
        }
        if label == V.REFUTED:
            claim["driving_dimension"] = "metric-mismatch"
            claim["reproduction_or_reverify"] = {
                "kind": "requires-reexecution",
                "command": "calma replay %s" % run_res.get("run_dir", "./.calma/run"),
                "manifest_ref": run_res.get("manifest_ref", "sha256:PENDING"),
                "expected": "recomputed differs from claimed beyond the calibrated budget",
            }
            findings.append({
                "id": "f-%s-mm" % cid, "claim_id": cid, "dimension": "metric-mismatch",
                "severity": "blocker", "status": "open", "confidence": "deterministic",
                "fixable_by": "author",
                "locator": "claimed %s but the code recomputes %s" % (m["claimed"], m["recomputed"]),
                "reverify": {"kind": "requires-reexecution", "source": m.get("metric_id"),
                             "expected": "recomputed within budget of claimed"},
            })
        claims.append(claim)
    # baseline corroborating finding
    bl = diff.get("baseline")
    if bl and bl.get("finding") and claims:
        findings.append({
            "id": "f-baseline", "claim_id": claims[0]["id"], "dimension": "baseline",
            "severity": "major", "status": "open", "confidence": "deterministic", "fixable_by": "author",
            "locator": bl["finding"],
            "reverify": {"kind": "requires-reexecution", "source": "baseline",
                         "expected": "strategy edge over baseline > 0"},
        })
    led = {
        "schema": "calma/ledger@1", "claims": claims, "findings": findings,
        "scope": {
            "isolation_tier": run_res.get("isolation_tier"),
            "determinism_mode": run_res.get("determinism_mode"),
            "reproducibility_scope": "same-platform",
            "families": {"reproducibility": "checked", "recomputation": "checked",
                         "baseline": "checked" if bl else "not-applicable",
                         "leakage": "not-run (M3)", "overfitting": "flagged-static (DSR is M3)"},
            "not_verified": ["deflated-Sharpe / PBO (M3)", "survivorship-free vendor data (Stage-3)"],
        },
        "repo_verdict": None,
    }
    led["repo_verdict"] = LED.compute_repo_verdict(led)
    return led


def verify(target, claim=None, metric=None, run_id="run"):
    target = os.path.realpath(target)
    run_dir = os.path.join(target, ".calma", run_id)
    os.makedirs(run_dir, exist_ok=True)

    committed = os.path.join(target, "verify.yaml")
    if os.path.exists(committed):
        contract_path = committed
    else:
        contract = DC.draft(target, claim=claim, metric=metric)
        contract_path = os.path.join(run_dir, "verify.yaml")
        json.dump(contract, open(contract_path, "w"), indent=2)
    contract = json.load(open(contract_path))

    run_res = H.run(contract_path, base=target)
    run_res["run_dir"] = run_dir
    if run_res.get("exit_code") in (3, 4):
        # refused (no isolation for untrusted) or killed -> INCONCLUSIVE, never a verdict
        led = {"claims": [{"id": "c1", "headline": True, "headline_confidence": 0.0,
                           "verdict": V.INCONCLUSIVE, "input_binding_status": "author-asserted",
                           "verdict_inputs": {"killed": run_res.get("killed", False),
                                              "exit_codes": [run_res["exit_code"]]}}],
               "findings": [], "scope": {"isolation_tier": run_res.get("isolation_tier")},
               "repo_verdict": V.INCONCLUSIVE}
    else:
        rec = RC.recompute_contract(contract_path, base=target)
        json.dump(rec, open(os.path.join(run_dir, "recompute.json"), "w"), indent=2)
        man = attest.manifest_for(os.path.join(target, "runs")) if os.path.isdir(os.path.join(target, "runs")) else {}
        json.dump(man, open(os.path.join(run_dir, "manifest.json"), "w"), indent=2)
        run_res["manifest_ref"] = "sha256:" + man.get("manifest_sha256", "none")
        diff = CMP.compare(rec, contract, isolation_tier=run_res.get("isolation_tier", "none"),
                           determinism_mode=run_res.get("determinism_mode", "uncontrolled"),
                           untrusted=(contract.get("env", {}).get("trust") == "untrusted-third-party"),
                           killed=run_res.get("killed", False),
                           exit_codes=[run_res.get("exit_code", 0)])
        json.dump(diff, open(os.path.join(run_dir, "diff.json"), "w"), indent=2)
        led = _assemble_ledger(contract, diff, run_res)

    json.dump(led, open(os.path.join(run_dir, "ledger.json"), "w"), indent=2)
    code, summary = LED.validate_obj(led)
    rendered = REP.render(led, led.get("_diff"))
    open(os.path.join(run_dir, "report.txt"), "w").write(rendered)
    return {"gate_exit": code, "gate": summary, "repo_verdict": led["repo_verdict"],
            "report": rendered, "run_dir": run_dir, "ledger": led}


def main():
    ap = argparse.ArgumentParser(prog="calma")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify")
    v.add_argument("target")
    v.add_argument("--claim")
    v.add_argument("--metric")
    v.add_argument("--run-id", default="run")
    a = ap.parse_args()
    if a.cmd == "verify":
        res = verify(a.target, a.claim, a.metric, a.run_id)
        print(res["report"])
        print("\n[gate exit %d - %s]" % (res["gate_exit"], res["repo_verdict"]))
        return res["gate_exit"]
    return 2


if __name__ == "__main__":
    sys.exit(main())
