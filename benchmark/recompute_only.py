"""T2 (real offline evidence): the RECOMPUTE-ONLY baseline - the deterministic, offline, $0 stand-in for
"a code-running agent that recomputes the headline number and checks it against the claim."

The real agent arm (run_agent.py, default backend) needs ANTHROPIC_API_KEY, so offline it was only a
plumbing smoke-test. But the agent arm's whole THESIS is measurable without any model:

  a verifier that only RECOMPUTES the number says "honest" whenever the number reproduces - and on the
  validity cut (leakage / overfitting / survivorship / omitted-costs / look-ahead / regime / shift) the
  number DOES reproduce; the result is invalid for a reason the number can't show. So a recompute-only
  verifier FALSE-CONFIRMS the entire validity cut. Calma INVALIDATES it.

This arm makes that the measured upper bound: it uses Calma's OWN recompute engine (recompute_contract -
pure, reads each case's committed verify.yaml, no sandbox, no network) to reproduce every headline number
it can, then predicts honest/flawed purely on the claim match - with the validity layer stripped. A real
LLM agent can only do WORSE (it recomputes imperfectly and its verdict flips across reruns), so a
recompute-only arm that already misses 100% of the validity cut is the strongest possible statement that
recompute != validity.

Emits results/recompute_only.json (same shape run_calma.py emits); score.py picks it up automatically as
the "recompute-only (no validity)" method. Run: python3 benchmark/recompute_only.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(HERE, "..", ".claude", "skills", "calma", "scripts")
sys.path.insert(0, SKILL)
import recompute as RC  # noqa: E402


def _band(claim):
    # honest iff the recompute lands within 1% of the claim (a deliberately generous band - the point is
    # that on the validity cut the recompute lands ON the claim, so ANY sane band false-confirms it).
    return max(0.01 * abs(claim), 1e-9)


def _predict(case):
    """Recompute the case's headline from its committed contract and decide honest/flawed/abstain on the
    NUMBER ALONE (no validity reasoning). abstain when the number can't be reproduced (degenerate / no
    contract / artifact absent) - a safe non-answer, never a wrong one."""
    vy = os.path.join(case["dir"], "verify.yaml")
    if not os.path.exists(vy):
        return "abstain", None
    try:
        out = RC.recompute_contract(vy, base=case["dir"])
    except Exception:  # noqa: BLE001 - any failure to reproduce is an abstain, never a crash
        return "abstain", None
    mets = [m for m in out.get("metrics", []) if m.get("metric_id") == case["metric"]] or out.get("metrics", [])
    if not mets:
        return "abstain", None
    m = mets[0]
    if m.get("degenerate") or not isinstance(m.get("value"), float) or m["value"] != m["value"]:
        return "abstain", None
    rec = m["value"]
    try:
        claim = float(case["claim"])
    except (TypeError, ValueError):
        return "abstain", rec
    return ("honest" if abs(rec - claim) <= _band(claim) else "flawed"), rec


def run():
    manifest = json.load(open(os.path.join(HERE, "manifest.json")))
    out = []
    for m in manifest:
        pred, rec = _predict(m)
        out.append({"id": m["id"], "metric": m["metric"], "claim": m["claim"], "label": m["label"],
                    "validity_family": m.get("validity_family"), "track": m.get("track"),
                    "tier": m.get("tier"), "prediction": pred, "recomputed": rec,
                    "correct": pred == m["label"]})
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    json.dump(out, open(os.path.join(HERE, "results", "recompute_only.json"), "w"), indent=2)
    _summary(out)
    return out


def _summary(rows):
    # report catch rates over SCORED cases only (a case whose artifact isn't committed abstains offline -
    # counting an abstain as a "miss" would understate the reproducibility axis). The validity cut ships
    # its artifacts, so it scores in full - that's the cut this arm exists to measure.
    scored = [r for r in rows if r["prediction"] != "abstain"]
    vrows = [r for r in scored if r.get("validity_family")]
    rrows = [r for r in scored if r["label"] == "flawed" and not r.get("validity_family")]
    flawed = [r for r in scored if r["label"] == "flawed"]
    honest = [r for r in scored if r["label"] == "honest"]
    fconf = sum(1 for r in flawed if r["prediction"] == "honest")          # the dangerous miss
    falarm = sum(1 for r in honest if r["prediction"] == "flawed")
    v_caught = sum(1 for r in vrows if r["prediction"] == "flawed")
    v_repro = sum(1 for r in vrows if r["prediction"] == "honest")          # number reproduced -> "honest"
    r_caught = sum(1 for r in rrows if r["prediction"] == "flawed")
    print("\n=== RECOMPUTE-ONLY (no validity) - deterministic, offline, $0 ===")
    print("  scored %d/%d cases (%d abstained - artifact not committed, can't reproduce offline w/o running)"
          % (len(scored), len(rows), len(rows) - len(scored)))
    print("  of scored: flawed %d (false-confirmed %d) | honest %d (false-alarm %d)"
          % (len(flawed), fconf, len(honest), falarm))
    print("  two axes (over scored cases):")
    print("    reproducibility cut (flaw shows in the NUMBER, n=%d): caught %d (%.0f%%)"
          % (len(rrows), r_caught, 100.0 * r_caught / len(rrows) if rrows else 0))
    print("    validity cut       (number REPRODUCES, n=%d): caught %d (%.0f%%)  <- false-confirmed %d/%d"
          % (len(vrows), v_caught, 100.0 * v_caught / len(vrows) if vrows else 0, v_repro, len(vrows)))
    print("  => recompute-only reproduces the headline yet MISSES the entire validity cut; this is exactly")
    print("     the gap Calma's validity layer closes (Calma INVALIDATES these by construction).")


if __name__ == "__main__":
    run()
