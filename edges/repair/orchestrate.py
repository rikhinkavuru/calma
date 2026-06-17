"""A4 orchestrator. AI proposes a minimal patch; Calma re-verifies the PATCHED code from scratch and
owns the verdict. A REFUTED flips to CONFIRMED iff the recompute on the new code closes the gap; the
goalposts are immutable; the user's working branch is never mutated (all work on an isolated scratch).

The agent reaches the verdict ONLY through engine.verify (a subprocess) -- no verdict-core import
(the P0 firewall enforces it)."""
import hashlib
import json
import os

from edges.common import engine, store
from edges.repair import checkpoints as CK
from edges.repair import memory as MEM
from edges.repair import review as RV
from edges.repair.diagnose import diagnose, next_hypothesis
from edges.repair.types import Goalposts, HypothesisResult, RepairResult

CLEAN = ("CONFIRMED", "CONFIRMED-WITH-CAVEATS")


def _headline_refuted_claim(ledger):
    """The headline broken claim + its linked blocker finding of the driving dimension. Returns
    (claim, finding) or raises if the run is not a catch (A4 only repairs REFUTED/INVALIDATED)."""
    claims = ledger.get("claims") or []
    broken = [c for c in claims if c.get("verdict") in ("REFUTED", "INVALIDATED")]
    head = next((c for c in broken if c.get("headline")), broken[0] if broken else None)
    if head is None:
        raise ValueError("run_dir is not a REFUTED/INVALIDATED catch -- nothing to repair")
    axis = head.get("driving_dimension")
    findings = ledger.get("findings") or []
    linked = [f for f in findings
              if f.get("claim_id") == head["id"] and f.get("severity") == "blocker"
              and f.get("dimension") == axis]
    finding = linked[0] if linked else next(
        (f for f in findings if f.get("claim_id") == head["id"]
         and f.get("severity") in ("blocker", "major")), None)
    return head, finding


def _gap_for(diff, metric_id):
    """(gap, effective_budget) for the metric from diff.json. gap_closed := gap is not None and
    gap <= effective_budget (== the per-metric `budget`)."""
    for m in (diff.get("metrics") or []):
        if m.get("metric_id") == metric_id:
            vi = m.get("verdict_inputs") or {}
            eff = vi.get("effective_budget", m.get("budget"))
            return m.get("gap"), eff
    return None, None


def _sha(p):
    h = hashlib.sha256()
    try:
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _capture_goalposts(target, ledger, claim, finding=None):
    """Freeze the verification identity from the ORIGINAL run, BEFORE any edit."""
    contract_path = os.path.join(target, "verify.yaml")
    art_paths, art_sha = (), {}
    if os.path.exists(contract_path):
        try:
            contract = json.load(open(contract_path))
            art_paths = tuple(a.get("path") for a in (contract.get("artifacts") or []) if a.get("path"))
            art_sha = {p: _sha(os.path.join(target, p)) for p in art_paths}
        except (OSError, ValueError):
            pass
    sc = ledger.get("scope") or {}
    return Goalposts(
        claim_value=claim.get("claimed_value"),
        metric_id=claim.get("metric"),
        contract_sha256=_sha(contract_path),
        artifact_paths=art_paths, artifact_sha256=art_sha,
        isolation_tier=sc.get("isolation_tier"),
        determinism_mode=sc.get("determinism_mode"),
    )


def _claim_scope(target, metric_id):
    """The author's OWN stated scope for the headline claim, read from the committed contract's `_claim`
    note (e.g. '... in-sample, best-of-N, no costs'). This is what the number is CLAIMED to be -- giving
    the debugger the claim's meaning is honest context, not a goalpost (the value/binding are untouched).
    Deterministic + path-independent."""
    try:
        contract = json.load(open(os.path.join(target, "verify.yaml")))
    except (OSError, ValueError):
        return ""
    for m in (contract.get("metrics") or []):
        if m.get("metric_id") == metric_id and m.get("_claim"):
            return str(m["_claim"])
    return ""


def _teardown_card(ledger, claim, claim_scope=""):
    """A compact, DETERMINISTIC 'why it breaks' built from the claim's stated scope + its linked findings
    (locators). Deliberately NOT read from the engine's teardown.txt: that file embeds the volatile
    run-id and a reproduce path, which would make the recorded LLM request hash unreproducible."""
    cid = claim.get("id")
    parts = ["claimed %s; the verifier recomputed a different value from the raw outputs."
             % claim.get("claimed_value")]
    if claim_scope:
        parts.append("the author's stated claim: %s" % claim_scope)
    for f in (ledger.get("findings") or []):
        if f.get("claim_id") == cid and f.get("locator"):
            parts.append("- [%s/%s] %s" % (f.get("dimension"), f.get("severity"), f.get("locator")))
    return "\n".join(parts)


def _trajectory_record(result):
    """A JSON-able summary of the repair trajectory for trajectories.jsonl (no ts -- caller-free)."""
    return {
        "target": os.path.basename(result.target),
        "before_verdict": result.before_verdict,
        "after_verdict": result.after_verdict,
        "accepted": result.accepted,
        "one_shot": result.one_shot,
        "metric_id": result.goalposts.metric_id,
        "hypotheses": [
            {"index": h.index, "after_verdict": h.after_verdict, "before_gap": h.before_gap,
             "after_gap": h.after_gap, "effective_budget": h.effective_budget,
             "gap_closed": h.gap_closed, "reviewers_passed": h.reviewers_passed,
             "accepted": h.accepted, "review_reasons": h.review_reasons,
             "target_files": list(h.diagnosis.target_files)}
            for h in result.trajectory
        ],
    }


def repair(run_dir, *, budget=4, model=None, episodes_path=None):
    """Repair a single catch. Returns RepairResult. Never mutates the user's working branch."""
    run_dir = os.path.realpath(run_dir)
    target = os.path.dirname(os.path.dirname(run_dir))   # <target>/.calma/<run-id> -> <target>
    ledger = engine.read_ledger(run_dir)
    diff = engine.read_diff(run_dir)
    claim, finding = _headline_refuted_claim(ledger)
    goalposts = _capture_goalposts(target, ledger, claim, finding)
    before_verdict = ledger.get("repo_verdict")
    before_gap, eff_budget = _gap_for(diff, goalposts.metric_id)
    teardown_card = _teardown_card(ledger, claim, _claim_scope(target, goalposts.metric_id))
    episodes_path = episodes_path or os.path.join(os.path.dirname(__file__), "data", "episodes.jsonl")

    # episodic seed (P4.4): the nearest prior fix of this (dimension + locator_signature)
    prior = MEM.retrieve(episodes_path, dimension=claim.get("driving_dimension"),
                         locator=(finding or {}).get("locator", ""))

    # isolated scratch clone -- the user's working branch is NEVER touched (P4.2)
    scratch = CK.make_scratch(target)
    trajectory = []
    accepted = None
    try:
        base_ckpt = CK.checkpoint(scratch)                       # the clean pre-repair state
        history = []                                             # rejected diffs, fed back to avoid repeats
        for i in range(budget):
            branch = CK.branch_for_hypothesis(scratch, i)        # one isolated branch per hypothesis
            CK.revert(scratch, base_ckpt)                        # always start each hypothesis clean

            if i == 0:
                diag = diagnose(scratch, claim, finding, diff, goalposts,
                                teardown_card=teardown_card, prior=prior, model=model)
            else:
                diag = next_hypothesis(scratch, claim, finding, diff, goalposts,
                                       teardown_card=teardown_card, history=history,
                                       prior=prior, model=model)

            applied = CK.apply_diff(scratch, diag.unified_diff)  # False if the diff is empty OR doesn't apply
            if not applied:
                # Distinguish the two non-apply paths honestly in the persisted trajectory: an EMPTY diff
                # is the proposer DECLINING -- "no honest code-only fix exists" (the sanctioned RULE-5
                # fallback) -- not a malformed patch the applier rejected. The record must say which.
                reason = ("empty diff -- no code-only fix proposed (RULE 5)"
                          if not (diag.unified_diff or "").strip() else "diff did not apply cleanly")
                trajectory.append(HypothesisResult(i, diag, branch, before_verdict, None,
                                                   before_gap, None, eff_budget, False, False,
                                                   [reason]))
                # The MODEL-facing feedback is kept verbatim ("diff did not apply") so the next-hypothesis
                # prompt hash is unchanged and the recorded replay fixtures stay valid; only the PERSISTED
                # trajectory reason above is sharpened. (Re-record with the model live to unify the wording.)
                history.append((diag, "diff did not apply"))
                continue

            # capture the TRUE patch (the code change) BEFORE the re-verify re-emits artifacts + writes
            # .calma into the scratch -- the reviewers must judge the patch, not the regenerated outputs.
            patch_diff = CK.diff_since(scratch, base_ckpt)

            # RE-VERIFY the PATCHED code FROM SCRATCH, under the ORIGINAL claim + metric + --force.
            res = engine.verify(scratch, claim=goalposts.claim_value, metric=goalposts.metric_id,
                                extra_args=("--force",))
            after_verdict = res.get("verdict")
            new_diff = engine.read_diff(res["run_dir"])
            new_ledger = engine.read_ledger(res["run_dir"])
            after_gap, after_eff = _gap_for(new_diff, goalposts.metric_id)
            gap_closed = (after_gap is not None and after_eff is not None and after_gap <= after_eff)

            ok_rev, reasons = RV.review(scratch, diag, goalposts, new_ledger, new_diff,
                                        res, finding, base_ckpt=base_ckpt, applied_diff=patch_diff)

            accept = (after_verdict in CLEAN) and gap_closed and ok_rev
            hr = HypothesisResult(i, diag, branch, before_verdict, after_verdict,
                                  before_gap, after_gap, after_eff, gap_closed, ok_rev,
                                  reasons, accepted=accept)
            trajectory.append(hr)
            if accept:
                accepted = hr
                break
            history.append((diag, "verdict=%s gap_closed=%s reviewers=%s (%s)"
                            % (after_verdict, gap_closed, ok_rev, "; ".join(reasons))))
            CK.revert(scratch, base_ckpt)

        result = RepairResult(
            run_dir=run_dir, target=target, accepted=bool(accepted),
            before_verdict=before_verdict,
            after_verdict=accepted.after_verdict if accepted else None,
            patch=accepted.diagnosis.unified_diff if accepted else None,
            goalposts=goalposts, trajectory=trajectory,
            one_shot=bool(accepted and accepted.index == 0))
        if accepted:
            MEM.record(episodes_path, claim, finding, goalposts, accepted)   # P4.4
        store.append(os.path.join(os.path.dirname(episodes_path), "trajectories.jsonl"),
                     _trajectory_record(result))
        return result
    finally:
        CK.cleanup_scratch(scratch)   # the accepted patch lives in RepairResult.patch; scratch is disposable
