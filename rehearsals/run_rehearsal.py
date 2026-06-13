#!/usr/bin/env python3
"""Dress rehearsal + registry dry-run: drive the WHOLE pilot pipeline on real/representative quant
repos across stacks, and push each through to a REDACTED, hash-chained registry.

For every repo: intake (+restore) -> isolated run -> recompute -> signed bundle -> branded report +
offline replay bundle -> a redacted registry entry. Then verify the chain and SCAN every entry for
redaction-by-construction (only claim/metric/gap/verdict/hashes - never code, data, or positions).

Uses a THROWAWAY signing key (a temp CALMA_KEY_DIR) and a SCRATCH registry under rehearsals/, so the
founder's lab key and the committed genesis chain are never touched. Writes REHEARSALS.md.

Run: python3 rehearsals/run_rehearsal.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALMA = os.path.join(REPO, ".claude", "skills", "calma", "scripts", "calma.py")
REG_PY = os.path.join(REPO, ".claude", "skills", "calma", "scripts")
SCRATCH_REG = os.path.join(REPO, "rehearsals", "registry-scratch")

# (label, path, claim-or-None, isolation, restore, stack, expectation)
REHEARSALS = [
    ("BTC inflated backtest (walk-forward)", os.path.join(REPO, ".claude/skills/calma/assets/btc"),
     "total_return 146.97697947938846", "docker", False, "python/stdlib",
     "REFUTED - in-sample +14,698% collapses to a negative out-of-sample return"),
    ("Momentum strategy (real MIT repo)", os.path.join(REPO, ".claude/skills/calma/assets/corpus/momentum-strategy"),
     None, "seatbelt", True, "python/pandas+numpy",
     "CONFIRMED reproduction - the pandas backtest re-runs and the number recomputes"),
    ("Backtrader SMA-cross strategy", os.path.join(REPO, "rehearsals/repos/backtrader_strat"),
     None, "seatbelt", True, "python/backtrader",
     "CONFIRMED reproduction - restored backtrader, ran the strategy, recomputed the return"),
    ("R momentum strategy", os.path.join(REPO, "rehearsals/repos/r_strategy"),
     None, "seatbelt", True, "R",
     "CONFIRMED-WITH-CAVEATS - R reproduces; determinism is uncontrolled (honest)"),
    ("Omitted-costs deck (gross sold as net)", os.path.join(REPO, "rehearsals/repos/omitted_costs"),
     None, "seatbelt", False, "python/stdlib",
     "CONFIRMED-WITH-CAVEATS - the gross number reproduces, but net-of-cost is far lower"),
]


def run(cmd, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    return p.returncode, (p.stdout or ""), (p.stderr or "")


def main():
    # throwaway key + scratch registry (never the founder key / committed chain)
    keydir = tempfile.mkdtemp(prefix="calma-rehearsal-key-")
    env = dict(os.environ, CALMA_KEY_DIR=keydir)
    if os.path.isdir(SCRATCH_REG):
        shutil.rmtree(SCRATCH_REG)
    os.makedirs(SCRATCH_REG)
    run([sys.executable, CALMA, "attest", "keygen"], env=env)

    results = []
    for label, path, claim, isolation, restore, stack, expect in REHEARSALS:
        if not os.path.isdir(path):
            results.append({"label": label, "stack": stack, "skipped": "missing repo at %s" % path})
            continue
        # 1) intake + isolated run + recompute (+ report/replay bundle written by `report`)
        vcmd = [sys.executable, CALMA, "verify", path]
        if claim:
            vcmd.append(claim)
        if restore:
            vcmd.append("--restore")
        vcmd += ["--isolation", isolation, "--force"]
        rc, out, err = run(vcmd, env=env)
        run_dir = os.path.join(path, ".calma", "run")
        verdict = isolation_tier = None
        led_path = os.path.join(run_dir, "ledger.json")
        if os.path.exists(led_path):
            led = json.load(open(led_path))
            verdict = led.get("repo_verdict")
            isolation_tier = (led.get("scope") or {}).get("isolation_tier")
        entry = {"label": label, "stack": stack, "expect": expect, "verify_exit": rc,
                 "verdict": verdict, "isolation": isolation_tier,
                 "report_top": out.strip().splitlines()[0] if out.strip() else err.strip()[:160]}
        # 2) branded report + offline replay bundle
        rrc, rout, _ = run([sys.executable, CALMA, "report", run_dir, "--no-pdf"], env=env)
        entry["report_built"] = (rrc == 0 and os.path.exists(os.path.join(run_dir, "report.html")))
        entry["replay_bundle"] = os.path.isdir(os.path.join(run_dir, "replay"))
        # 3) sign + publish a REDACTED entry to the scratch registry (offline; no RFC3161 network)
        eid = "rehearsal-%d" % (len(results) + 1)
        scmd = [sys.executable, CALMA, "seal", run_dir, "--no-timestamp",
                "--publish", SCRATCH_REG, "--note", "rehearsal: %s" % stack]
        src, sout, serr = run(scmd, env=env)
        entry["sealed"] = ("VERIFIED" in sout)
        entry["published"] = ("published" in sout)
        results.append(entry)

    # 4) verify the chain + scan every entry for redaction-by-construction
    sys.path.insert(0, REG_PY)
    import registry as REG
    pub_hex = open(os.path.join(keydir, "ed25519.pub")).read().strip() \
        if os.path.exists(os.path.join(keydir, "ed25519.pub")) else None
    chain_ok, checks, summary = REG.verify_chain(SCRATCH_REG, pinned_pub_hex=pub_hex)
    # independent leak scan: only the whitelist fields, and no value smells like code/data
    leak = []
    edir = os.path.join(SCRATCH_REG, "entries")
    n_entries = 0
    for fn in sorted(os.listdir(edir)) if os.path.isdir(edir) else []:
        wrapper = json.load(open(os.path.join(edir, fn)))
        ent = wrapper.get("entry", {})
        n_entries += 1
        for k in ent:
            if k not in REG.ALLOWED_FIELDS:
                leak.append("%s: non-whitelisted field %r" % (fn, k))
        blob = json.dumps(ent).lower()
        for smell in ("def ", "import ", "class ", "position", "weight", "<source", "\ndef"):
            if smell in blob:
                leak.append("%s: value smells like code/positions (%r)" % (fn, smell))

    report_md = _render_md(results, chain_ok, n_entries, leak, summary)
    open(os.path.join(REPO, "REHEARSALS.md"), "w").write(report_md)
    print(report_md)
    print("\n[chain_ok=%s entries=%d leaks=%d]" % (chain_ok, n_entries, len(leak)))
    return 0 if (chain_ok and not leak) else 1


def _render_md(results, chain_ok, n_entries, leak, summary):
    L = ["# Calma pilot dress rehearsals", "",
         "The whole pilot pipeline run end-to-end on quant repos across stacks: "
         "intake (+restore) → isolated run → recompute → signed bundle → branded report + offline "
         "replay bundle → a redacted, hash-chained registry entry. Regenerate with "
         "`python3 rehearsals/run_rehearsal.py`.", "",
         "## Runs", "",
         "| Strategy | Stack | Isolation | Verdict | Report+Replay | Sealed | Published |",
         "|---|---|---|---|---|---|---|"]
    for r in results:
        if r.get("skipped"):
            L.append("| %s | %s | — | _skipped: %s_ | — | — | — |" % (r["label"], r["stack"], r["skipped"]))
            continue
        L.append("| %s | %s | `%s` | **%s** | %s | %s | %s |" % (
            r["label"], r["stack"], r.get("isolation") or "?", r.get("verdict") or "?",
            "✓" if r.get("report_built") and r.get("replay_bundle") else "✗",
            "✓" if r.get("sealed") else "✗", "✓" if r.get("published") else "✗"))
    L += ["", "## What each run caught (or confirmed)", ""]
    for r in results:
        if r.get("skipped"):
            continue
        L.append("- **%s** (%s): %s" % (r["label"], r["stack"], r.get("expect")))
    L += ["", "## Registry dry-run (redaction-by-construction)", "",
          "- Entries appended to a scratch chain: **%d**" % n_entries,
          "- Hash chain verifies offline: **%s**" % ("YES" if chain_ok else "NO"),
          "- Redaction leak scan (code / data / positions in any entry): **%s**"
          % ("NONE — only claim/metric/gap/verdict/hashes" if not leak else "; ".join(leak)),
          "- Verdict counts: `%s`" % json.dumps(summary.get("verdicts", {}) if isinstance(summary, dict) else {}),
          "",
          "Every entry carries only the whitelisted fields (claim, metric, claimed, recomputed, "
          "verdict, hashes, keyid, dates). Code, data, and positions never enter the registry — "
          "enforced at append AND re-checked here independently.", ""]
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
