"""calma - the orchestrator. One command chains the whole pipeline and emits the verdict.

  calma.py verify <target> ["<claim>"] [--claim VALUE] [--metric ID] [--run-id ID] [--fail-on MODE]
  calma.py teardown <target> ["<claim>"] [--metric ID]
  calma.py replay <run_dir>
  calma.py attest keygen|sign <run_dir>|verify <bundle> [--key PATH] [--replay]

Steps: draft-or-load contract -> run_hermetic (verified isolation, re-emit raw artifacts) -> recompute
(reference-deterministic) -> compare (calibrated budget + shared verdict()) -> assemble + gate the ledger
-> attest (SBOM manifest + Ed25519-signed DSSE bundle when a key exists) -> strictly-progressive report.
The model READS the report; every number and the verdict label come from the scripts. Writes everything
under <target>/.calma/<run-id>/.
"""
import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import attest
import compare as CMP
import draft_contract as DC
import ledger as LED
import recipes as RCP
import recompute as RC
import report as REP
import run_hermetic as H
import verdict as V

__version__ = "0.4.0"

QUANT_METRICS = {"total_return", "sharpe", "max_drawdown"}


def _not_verified(metric_ids):
    """Honest 'what we did NOT check' list, phrased for the family actually verified."""
    if any(m in QUANT_METRICS for m in metric_ids):
        return ["deflated-Sharpe / PBO overfitting stats (CLI roadmap)",
                "survivorship-free vendor data (managed roadmap)"]
    return ["leakage re-run (roadmap)", "overfitting statistics (roadmap)"]


def _inconclusive_ledger(run_res, finding=None, target_name=None):
    """A valid INCONCLUSIVE ledger for paths where re-execution could not produce a verdict.
    The finding carries the actionable unblock (the 'here's the fix' line)."""
    vi = {"killed": run_res.get("killed", False),
          "exit_codes": [run_res.get("exit_code", 0)]}
    led = {
        "schema": "calma/ledger@1",
        "claims": [{"id": "c1", "headline": True, "headline_confidence": 0.0,
                    "verdict": V.INCONCLUSIVE, "input_binding_status": "author-asserted",
                    "verdict_inputs": vi, "verdict_status": "stable", "verdict_history": [],
                    "waivable": False}],
        "findings": [finding] if finding else [],
        "scope": {"isolation_tier": run_res.get("isolation_tier"),
                  "determinism_mode": run_res.get("determinism_mode")},
        "repo_verdict": V.INCONCLUSIVE,
    }
    if target_name:
        led["target"] = target_name
    return led


def _assemble_ledger(contract, diff, run_res):
    claims, findings = [], []
    for i, m in enumerate(diff["metrics"]):
        cid = "c%d" % (i + 1)
        vi = m["verdict_inputs"]
        label = m["verdict"]
        claim = {
            "id": cid, "headline": m["headline"],
            "headline_confidence": V.confidence(vi, label),
            "metric": m["metric_id"], "claimed_value": m["claimed"], "recomputed_value": m["recomputed"],
            "verdict": label, "input_binding_status": vi["binding_status"],
            "verdict_inputs": vi, "verdict_status": "stable", "verdict_history": [], "waivable": False,
            "recipe_authority": "canonical", "set_maturity": "reviewed",
            "reason": m.get("reason"),
        }
        if label == V.REFUTED:
            claim["driving_dimension"] = "metric-mismatch"
            claim["reproduction_or_reverify"] = {
                "kind": "requires-reexecution",
                "command": "calma replay %s" % run_res.get("run_dir", "./.calma/run"),
                "manifest_ref": run_res.get("manifest_ref", "sha256:unavailable"),
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
    # FLAKY: two identical re-executions disagreed -> blocking finding with the seed fix
    recheck = run_res.get("determinism_recheck")
    if recheck and not recheck.get("stable", True):
        findings.append({
            "id": "f-flaky", "claim_id": claims[0]["id"] if claims else None,
            "dimension": "reproducibility", "severity": "blocker", "status": "open",
            "confidence": "deterministic", "fixable_by": "author",
            "locator": "outputs differ across identical re-runs (FLAKY): %s"
                       % ", ".join(recheck.get("differing_artifacts", [])[:4]),
            "unblock": "set a fixed seed (and write outputs deterministically), then re-run calma verify",
            "reverify": {"kind": "requires-reexecution", "source": "run",
                         "expected": "identical artifacts across re-runs"},
        })
    # a failed re-execution is itself a blocking finding (the verdict guard already forced INCONCLUSIVE)
    rc = run_res.get("exit_code", 0)
    if rc not in (0, 3, 4):
        findings.append({
            "id": "f-run-fail", "claim_id": claims[0]["id"] if claims else None,
            "dimension": "reproducibility", "severity": "blocker", "status": "open",
            "confidence": "deterministic", "fixable_by": "author",
            "locator": "the entrypoint exited non-zero - the result was NOT reproduced"
                       + ((" | stderr: " + run_res["stderr_tail"].strip()[-200:])
                          if run_res.get("stderr_tail") else ""),
            "unblock": "make the entrypoint run to completion (exit 0), then re-run calma verify",
            "reverify": {"kind": "requires-reexecution", "source": "run",
                         "expected": "entrypoint exits 0"},
        })
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
    metric_ids = [m["metric_id"] for m in diff["metrics"]]
    # surface which binding was auto-picked (the one surface the producer influences)
    binding_note = None
    for m in contract.get("metrics", []):
        if m.get("binding_source") == "auto-detected" and m.get("claimed_value") is not None:
            binding_note = ("%s over %s (auto-detected binding %s) - pass --metric to override"
                            % (m["metric_id"], m.get("artifact"), m.get("binding")))
    led = {
        "schema": "calma/ledger@1", "claims": claims, "findings": findings,
        "scope": {
            "isolation_tier": run_res.get("isolation_tier"),
            "determinism_mode": run_res.get("determinism_mode"),
            "run_network": run_res.get("run_network"),
            "reproducibility_scope": "same-platform",
            "determinism_recheck": (
                "stable across %d re-runs" % run_res["determinism_recheck"]["reruns"]
                if run_res.get("determinism_recheck", {}).get("stable")
                else ("FLAKY across re-runs" if run_res.get("determinism_recheck") else None)),
            "binding_note": binding_note,
            "families": {"reproducibility": "checked" if run_res.get("exit_code", 0) == 0 else "FAILED",
                         "recomputation": "checked",
                         "baseline": "checked" if bl else "not-applicable"},
            "not_verified": _not_verified(metric_ids),
        },
        "repo_verdict": None,
    }
    led["repo_verdict"] = LED.compute_repo_verdict(led)
    return led


def _input_fingerprint(target, contract):
    """Content-address everything the verdict depends on: the contract (minus draft notes), the
    entrypoint bytes, and every bound artifact's bytes. Same fingerprint => the prior verdict is the
    verdict (re-verification would re-derive it from identical inputs)."""
    h = hashlib.sha256()
    # the verifier's own version and the interpreter line are part of the key: upgrading either
    # invalidates the cache (a different verifier run is a different computation)
    h.update(("calma-cache@1|calma=%s|py=%d.%d\n"
              % (__version__, sys.version_info[0], sys.version_info[1])).encode())
    h.update(json.dumps({k: v for k, v in contract.items() if not str(k).startswith("_")},
                        sort_keys=True).encode())
    rt = os.path.realpath(target)
    paths = []
    entry = (contract.get("run") or {}).get("entrypoint")
    if entry and entry != "MANUAL":
        paths.append(entry)
    for a in contract.get("artifacts", []):
        if isinstance(a, dict) and a.get("path"):
            paths.append(a["path"])
    for rel in sorted(set(paths)):
        full = os.path.realpath(os.path.join(rt, rel))
        if full != rt and not full.startswith(rt + os.sep):
            continue
        h.update(rel.encode() + b"\x00")
        try:
            with open(full, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
        except OSError:
            h.update(b"<missing>")
    return h.hexdigest()


def _cached_result(target, fingerprint):
    """Return the prior result for this fingerprint, or None. Only definite verdicts are served from
    cache (an INCONCLUSIVE may have been environmental - it always re-runs)."""
    cache_path = os.path.join(target, ".calma", "cache.json")
    try:
        cache = json.load(open(cache_path))
    except (OSError, ValueError):
        return None
    ent = cache.get(fingerprint)
    if not ent:
        return None
    run_dir = os.path.join(target, ".calma", ent.get("run_id", ""))
    led_path = os.path.join(run_dir, "ledger.json")
    try:
        led = json.load(open(led_path))
    except (OSError, ValueError):
        return None
    code, summary = LED.validate_obj(led)
    if led.get("repo_verdict") not in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS", "REFUTED", "MIXED"):
        return None
    rendered = ("(cached: code, data, and claim unchanged since the last verification - "
                "pass --force to re-execute)\n") + REP.render(led)
    return {"gate_exit": code, "gate": summary, "repo_verdict": led["repo_verdict"],
            "report": rendered, "teardown": REP.teardown_card(led), "run_dir": run_dir,
            "ledger": led, "cached": True}


def _store_cache(target, fingerprint, run_id, repo_verdict):
    if repo_verdict not in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS", "REFUTED", "MIXED"):
        return
    cache_path = os.path.join(target, ".calma", "cache.json")
    try:
        cache = json.load(open(cache_path))
    except (OSError, ValueError):
        cache = {}
    cache[fingerprint] = {"run_id": run_id, "repo_verdict": repo_verdict}
    json.dump(cache, open(cache_path, "w"), indent=2)


def _artifact_hashes(target, contract):
    """Hash every bound artifact (not the entrypoint): the re-run comparison set for FLAKY detection."""
    out = {}
    rt = os.path.realpath(target)
    for a in contract.get("artifacts", []):
        if not (isinstance(a, dict) and a.get("path")):
            continue
        full = os.path.realpath(os.path.join(rt, a["path"]))
        if full != rt and not full.startswith(rt + os.sep):
            continue
        h = hashlib.sha256()
        try:
            with open(full, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
            out[a["path"]] = h.hexdigest()
        except OSError:
            out[a["path"]] = "<missing>"
    return out


def verify(target, claim=None, metric=None, run_id="run", force=False, check_determinism=False):
    target = os.path.realpath(target)
    if not os.path.isdir(target):
        raise ValueError("target directory does not exist: %s" % target)
    if not any(n for n in os.listdir(target) if n not in (".calma", ".DS_Store")):
        raise ValueError("nothing to verify: %s is empty (expected code + machine-readable outputs)" % target)
    run_dir = os.path.join(target, ".calma", run_id)
    os.makedirs(run_dir, exist_ok=True)

    committed = os.path.join(target, "verify.yaml")
    if os.path.exists(committed):
        contract_path = committed
        contract = DC.load_contract(contract_path)
        errs = DC.validate_contract(contract)
        if errs:
            raise ValueError("verify.yaml is invalid: " + "; ".join(errs))
        # an explicitly passed claim that differs from the committed one must never be silently ignored
        if claim is not None:
            cv, _hint = DC.parse_claim(claim)
            committed_vals = [m.get("claimed_value") for m in contract.get("metrics", [])]
            if cv is not None and committed_vals and all(
                    v is None or abs(v - cv) > 1e-12 for v in committed_vals):
                print("note: using the committed verify.yaml (claimed %s); your claim %r differs - "
                      "edit verify.yaml to change the claim under test" % (committed_vals[0], claim),
                      file=sys.stderr)
    else:
        contract = DC.draft(target, claim=claim, metric=metric)
        contract_path = os.path.join(run_dir, "verify.yaml")
        json.dump(contract, open(contract_path, "w"), indent=2)

    # the cache: same contract + same entrypoint bytes + same artifact bytes => same verdict.
    # Inline/agent-loop use re-verifies only what changed; --force always re-executes, and a
    # determinism check is new evidence, so it never reads the cache (it still stores).
    if not force and not check_determinism:
        hit = _cached_result(target, _input_fingerprint(target, contract))
        if hit:
            return hit

    diff = None
    entry = contract.get("run", {}).get("entrypoint")
    if entry == "MANUAL":
        run_res = {"exit_code": 3, "isolation_tier": "n/a", "killed": False, "run_dir": run_dir}
        led = _inconclusive_ledger(run_res, finding={
            "id": "f-entrypoint", "claim_id": "c1", "dimension": "contract-grounding",
            "severity": "major", "status": "open", "confidence": "deterministic", "fixable_by": "author",
            "locator": "no entrypoint detected (looked for %s, then a single script in the root)"
                       % ", ".join(DC.ENTRYPOINT_CANDIDATES),
            "unblock": "name your script main.py/run.py, or set run.entrypoint in verify.yaml",
            "reverify": {"kind": "static-reread", "source": "contract", "expected": "an entrypoint exists"},
        }, target_name=os.path.basename(target))
        run_res["run_dir"] = run_dir
    else:
        run_res = H.run(contract_path, base=target)
        run_res["run_dir"] = run_dir
        if run_res.get("exit_code") in (3, 4):
            # refused (no isolation for untrusted) or killed -> INCONCLUSIVE, never a verdict
            if run_res.get("exit_code") == 4:
                unblock = "the run timed out - raise the timeout or make the entrypoint faster"
            else:
                unblock = run_res.get("reason", "isolation was refused") + \
                    " - run on a host with a verified sandbox, or mark trust: own-code if this is your code"
            led = _inconclusive_ledger(run_res, finding={
                "id": "f-run-blocked", "claim_id": "c1",
                "dimension": "reproducibility" if run_res.get("exit_code") == 4 else "isolation-security",
                "severity": "major", "status": "open", "confidence": "deterministic",
                "fixable_by": "operator",
                "locator": run_res.get("reason", "execution did not complete"),
                "unblock": unblock,
                "reverify": {"kind": "requires-reexecution", "source": "run",
                             "expected": "the entrypoint completes under a verified tier"},
            }, target_name=os.path.basename(target))
        else:
            # chicken-and-egg: on a fresh project the outputs only exist AFTER the first run, so a
            # pre-run draft finds no metrics. Re-draft from the artifacts the run just produced.
            if not contract.get("metrics") and contract_path != committed \
                    and run_res.get("exit_code") == 0:
                redrafted = DC.draft(target, claim=claim, metric=metric)
                if redrafted.get("metrics"):
                    contract = redrafted
                    json.dump(contract, open(contract_path, "w"), indent=2)
            # optional FLAKY check: re-execute a second time and diff the artifact bytes. Identical
            # inputs producing different outputs is itself a verdict-blocking finding (G1c).
            outputs_unstable = False
            if check_determinism and run_res.get("exit_code") == 0:
                h1 = _artifact_hashes(target, contract)
                run2 = H.run(contract_path, base=target)
                if run2.get("exit_code") == 0:
                    h2 = _artifact_hashes(target, contract)
                    unstable_paths = sorted(p for p in set(h1) | set(h2) if h1.get(p) != h2.get(p))
                else:
                    unstable_paths = ["<second run exited %s>" % run2.get("exit_code")]
                outputs_unstable = bool(unstable_paths)
                run_res["determinism_recheck"] = {
                    "reruns": 2, "stable": not outputs_unstable,
                    "differing_artifacts": unstable_paths,
                }
            rec = RC.recompute_contract(contract_path, base=target)
            json.dump(rec, open(os.path.join(run_dir, "recompute.json"), "w"), indent=2)
            man = attest.manifest_for(os.path.join(target, "runs")) if os.path.isdir(os.path.join(target, "runs")) else {}
            json.dump(man, open(os.path.join(run_dir, "manifest.json"), "w"), indent=2)
            run_res["manifest_ref"] = "sha256:" + man.get("manifest_sha256", "none")
            run_res["_manifest"] = man
            diff = CMP.compare(rec, contract, isolation_tier=run_res.get("isolation_tier", "none"),
                               determinism_mode=run_res.get("determinism_mode", "uncontrolled"),
                               untrusted=(contract.get("env", {}).get("trust") == "untrusted-third-party"),
                               killed=run_res.get("killed", False),
                               exit_codes=[run_res.get("exit_code", 0)],
                               outputs_unstable=outputs_unstable)
            json.dump(diff, open(os.path.join(run_dir, "diff.json"), "w"), indent=2)
            led = _assemble_ledger(contract, diff, run_res)
            if not diff["metrics"]:
                led["findings"].append({
                    "id": "f-no-metric", "claim_id": None, "dimension": "contract-grounding",
                    "severity": "major", "status": "open", "confidence": "deterministic",
                    "fixable_by": "author",
                    "locator": "no machine-readable output with a recognizable metric column was found",
                    "unblock": "write the result to a CSV the recompute can read "
                               "(e.g. predictions.csv with y_true,y_pred / returns.csv with strat_return)",
                    "reverify": {"kind": "artifact-recheck", "source": "artifacts",
                                 "expected": "a bindable metric column exists"},
                })

    led.setdefault("target", os.path.basename(target))
    _man = run_res.get("_manifest")
    if _man:
        json.dump(attest.intoto_statement(_man, led["target"], led["repo_verdict"], led.get("scope")),
                  open(os.path.join(run_dir, "attestation.json"), "w"), indent=2)
        json.dump(attest.ml_bom(_man, led["target"], led.get("scope")),
                  open(os.path.join(run_dir, "mlbom.json"), "w"), indent=2)
    json.dump(led, open(os.path.join(run_dir, "ledger.json"), "w"), indent=2)
    # auto-sign when a local key exists: the bundle is the counterparty artifact, never load-bearing
    # for the verdict itself, so a signing failure must not fail the verification
    if attest.load_signing_key() is not None:
        try:
            attest.sign_run(run_dir)
        except (OSError, ValueError):
            pass
    code, summary = LED.validate_obj(led)
    rendered = REP.render(led, diff)
    open(os.path.join(run_dir, "report.txt"), "w").write(rendered)
    card = REP.teardown_card(led)
    if card:
        open(os.path.join(run_dir, "teardown.txt"), "w").write(card)
    _store_cache(target, _input_fingerprint(target, contract), run_id, led["repo_verdict"])
    # append-only, human-readable history: one JSON line per verification (the audit trail is a feature)
    c0 = (led.get("claims") or [{}])[0]
    try:
        import time
        with open(os.path.join(target, ".calma", "history.jsonl"), "a") as fh:
            fh.write(json.dumps({
                "ts": int(time.time()), "run_id": run_id, "verdict": led["repo_verdict"],
                "metric": c0.get("metric"), "claimed": c0.get("claimed_value"),
                "recomputed": c0.get("recomputed_value"),
                "isolation": led.get("scope", {}).get("isolation_tier"),
                "calma": __version__,
            }) + "\n")
    except OSError:
        pass
    return {"gate_exit": code, "gate": summary, "repo_verdict": led["repo_verdict"],
            "report": rendered, "teardown": card, "run_dir": run_dir, "ledger": led,
            "cached": False}


def replay(run_dir):
    """Re-run a prior verification from its saved run dir and check the verdict reproduces.
    Accepts the path printed on a REFUTED card (<target>/.calma/<id>). Exit 0 iff reproduced."""
    run_dir = os.path.realpath(run_dir)
    prior_path = os.path.join(run_dir, "ledger.json")
    if not os.path.exists(prior_path):
        raise ValueError("no ledger.json under %s - pass the .calma/<run-id> dir from a previous verify" % run_dir)
    prior = json.load(open(prior_path))
    target = os.path.dirname(os.path.dirname(run_dir))
    # replay under the SAME contract terms: reuse the prior run's claim + metric
    claim = metric = None
    prior_contract = os.path.join(run_dir, "verify.yaml")
    if os.path.exists(prior_contract):
        pc_obj = DC.load_contract(prior_contract)
        mets = pc_obj.get("metrics") or [{}]
        claim, metric = mets[0].get("claimed_value"), mets[0].get("metric_id")
    res = verify(target, claim=claim, metric=metric,
                 run_id=os.path.basename(run_dir) + "-replay", force=True)
    same_verdict = res["repo_verdict"] == prior.get("repo_verdict")
    pc = (prior.get("claims") or [{}])[0]
    nc = (res["ledger"].get("claims") or [{}])[0]
    pv, nv = pc.get("recomputed_value"), nc.get("recomputed_value")
    same_value = (pv is None and nv is None) or \
        (isinstance(pv, float) and isinstance(nv, float) and abs(pv - nv) <= 1e-9 + 1e-6 * abs(pv))
    ok = same_verdict and same_value
    lines = ["CALMA REPLAY  -  %s" % prior.get("target", os.path.basename(target)),
             "  prior:    %s  (recomputed %s)" % (prior.get("repo_verdict"), pv),
             "  replayed: %s  (recomputed %s)" % (res["repo_verdict"], nv),
             "  %s" % ("REPRODUCED - the verdict holds under re-execution" if ok
                       else "DID NOT REPRODUCE - the prior verdict no longer holds")]
    return ok, "\n".join(lines)


def stats(target):
    """Summarize the append-only verification history for a target. Returns (data, rendered)."""
    target = os.path.realpath(target)
    path = os.path.join(target, ".calma", "history.jsonl")
    if not os.path.exists(path):
        raise ValueError("no verification history at %s - run `calma verify` first" % path)
    rows = []
    for line in open(path):
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    counts = {}
    for r in rows:
        v = r.get("verdict", "?")
        counts[v] = counts.get(v, 0) + 1
    lines = ["CALMA STATS  -  %s" % os.path.basename(target),
             "  verifications: %d" % len(rows)]
    for v in ("CONFIRMED", "CONFIRMED-WITH-CAVEATS", "REFUTED", "MIXED", "INCONCLUSIVE"):
        if counts.get(v):
            lines.append("  %-24s %d" % (v, counts[v]))
    catches = [r for r in rows if r.get("verdict") in ("REFUTED", "MIXED")]
    for c in catches[-3:]:
        lines.append("  catch: claimed %s -> recomputed %s (%s)"
                     % (REP.fmt_value(c.get("claimed"), c.get("metric")),
                        REP.fmt_value(c.get("recomputed"), c.get("metric")), c.get("metric")))
    return {"total": len(rows), "counts": counts}, "\n".join(lines)


def _json_result(res):
    """The agent-consumable structured verdict (stable shape; no prose parsing needed)."""
    led = res["ledger"]
    c0 = (led.get("claims") or [{}])[0]
    return {
        "verdict": res["repo_verdict"],
        "clean": res["gate_exit"] == 0,
        "gate_exit": res["gate_exit"],
        "cached": bool(res.get("cached")),
        "confidence": c0.get("headline_confidence"),
        "metric": c0.get("metric"),
        "claimed": c0.get("claimed_value"),
        "recomputed": c0.get("recomputed_value"),
        "reason": c0.get("reason"),
        "fix": REP.fix_line(led) if res["repo_verdict"] != "CONFIRMED" else None,
        "isolation_tier": led.get("scope", {}).get("isolation_tier"),
        "determinism_mode": led.get("scope", {}).get("determinism_mode"),
        "run_dir": res["run_dir"],
    }


def main():
    ap = argparse.ArgumentParser(
        prog="calma",
        description="Verify a computational result by re-executing it and recomputing the headline "
                    "number from the raw outputs. The verdict comes from deterministic scripts.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="re-run + recompute + diff against the claim")
    v.add_argument("target", help="folder containing the code and its outputs")
    v.add_argument("claim_text", nargs="?", default=None,
                   help="the claim to check, e.g. \"accuracy 0.87\" or \"+14,698%%\" (optional)")
    v.add_argument("--claim", help="same as the positional claim")
    v.add_argument("--metric", help="force a metric id (see recipes: %s)" % ", ".join(RCP.ids()))
    v.add_argument("--run-id", default="run")
    v.add_argument("--fail-on", choices=["not-clean", "refuted"], default="not-clean",
                   help="process exit policy: not-clean (default; INCONCLUSIVE also fails) or refuted")
    v.add_argument("--force", action="store_true",
                   help="re-execute even if code, data, and claim are unchanged since the last verification")
    v.add_argument("--check-determinism", action="store_true",
                   help="re-execute TWICE and require identical artifacts (catches FLAKY results)")
    v.add_argument("--json", action="store_true", dest="as_json",
                   help="print a machine-readable verdict object instead of the report")
    t = sub.add_parser("teardown", help="print a shareable card when a claim breaks")
    t.add_argument("target")
    t.add_argument("claim_text", nargs="?", default=None)
    t.add_argument("--claim")
    t.add_argument("--metric")
    t.add_argument("--force", action="store_true")
    t.add_argument("--svg", help="also write the share card as a dark SVG image to this path")
    r = sub.add_parser("replay", help="re-run a saved verification and check it reproduces")
    r.add_argument("run_dir", help="the .calma/<run-id> dir printed on the original verdict")
    s = sub.add_parser("stats", help="summarize this target's verification history")
    s.add_argument("target")
    s.add_argument("--json", action="store_true", dest="as_json")
    at = sub.add_parser("attest", help="sign a run into a portable bundle, or verify one offline")
    atsub = at.add_subparsers(dest="attest_cmd", required=True)
    kg = atsub.add_parser("keygen", help="generate a local Ed25519 signing key (~/.calma/keys)")
    kg.add_argument("--force", action="store_true", help="overwrite an existing key")
    sg = atsub.add_parser("sign", help="sign a run dir's ledger+manifest into attestation.bundle.json")
    sg.add_argument("run_dir", help="the .calma/<run-id> dir from a previous verify")
    sg.add_argument("--key", help="signing key file (default: ~/.calma/keys/ed25519.key)")
    sg.add_argument("--out", help="bundle output path (default: <run_dir>/attestation.bundle.json)")
    av = atsub.add_parser("verify", help="verify a bundle offline: signature + verdict re-derivation")
    av.add_argument("bundle", help="path to attestation.bundle.json")
    av.add_argument("--key", help="pin the signer: hex public key, or a path to the .pub file")
    av.add_argument("--replay", action="store_true",
                    help="also re-execute the run next to the bundle and check the verdict reproduces")
    a = ap.parse_args()
    try:
        if a.cmd == "verify":
            res = verify(a.target, a.claim_text or a.claim, a.metric, a.run_id,
                         force=a.force, check_determinism=a.check_determinism)
            if a.as_json:
                print(json.dumps(_json_result(res), indent=2))
            else:
                print(res["report"])
                print("\n[gate exit %d - %s]" % (res["gate_exit"], res["repo_verdict"]))
            if a.fail_on == "refuted":
                return 1 if res["repo_verdict"] in ("REFUTED", "MIXED") else 0
            return res["gate_exit"]
        if a.cmd == "teardown":
            res = verify(a.target, a.claim_text or a.claim, a.metric, "teardown", force=a.force)
            print(res.get("teardown") or "(no teardown: result was not REFUTED)")
            if a.svg and res.get("teardown"):
                svg = REP.svg_card(res["ledger"])
                if svg:
                    open(a.svg, "w").write(svg)
                    print("\n[share card written: %s]" % a.svg)
            return 0 if res.get("teardown") else 1
        if a.cmd == "replay":
            ok, text = replay(a.run_dir)
            print(text)
            return 0 if ok else 1
        if a.cmd == "stats":
            data, rendered = stats(a.target)
            print(json.dumps(data, indent=2) if a.as_json else rendered)
            return 0
        if a.cmd == "attest":
            if a.attest_cmd == "keygen":
                info = attest.keygen(force=a.force)
                print("key written: %s (0600)\npublic key:  %s\nkeyid:       %s"
                      % (info["key_path"], info["public_key"], info["keyid"]))
                return 0
            if a.attest_cmd == "sign":
                bundle, out = attest.sign_run(os.path.realpath(a.run_dir), key_path=a.key, out=a.out)
                print("signed: %s\nkeyid:  %s" % (out, bundle["envelope"]["signatures"][0]["keyid"]))
                return 0
            if a.attest_cmd == "verify":
                try:
                    bundle = json.load(open(a.bundle))
                except (OSError, ValueError) as e:
                    print("error: cannot read bundle: %s" % e, file=sys.stderr)
                    return 2
                pinned = None
                if a.key:
                    pinned = open(a.key).read().strip() if os.path.exists(a.key) else a.key.strip()
                ok, checks = attest.verify_bundle(bundle, pinned_pub_hex=pinned)
                print(attest.render_verify(bundle, ok, checks))
                if ok and a.replay:
                    rok, text = replay(os.path.dirname(os.path.realpath(a.bundle)))
                    print("\n" + text)
                    ok = ok and rok
                return 0 if ok else 1
    except ValueError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
