"""M2 served-fraction instrument. For each real repo, record which of the 4 capability gates succeed
(restore deps | run entrypoint | emit machine-readable output | bind a graded metric) and the terminal
verdict. Aggregates the served-fraction (fraction reaching a real verdict vs UNVERIFIABLE) - the honest
per-language coverage number M2 must publish.

Usage (library): assess(repo_dir, claim=..., metric=...) -> row ; run([specs]) -> table.
A spec is {"dir": "...", "claim": <num or None>, "metric": "<id or None>", "label": "..."}.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCR)
import compare as CMP  # noqa: E402
import draft_contract as DC  # noqa: E402
import recompute as RC  # noqa: E402
import run_hermetic as H  # noqa: E402

MACHINE_READABLE = (".csv", ".json", ".parquet", ".npy", ".npz", ".arrow", ".tsv")


def _restore(repo):
    """restore gate: install requirements into a throwaway venv (timeout). stdlib -> trivially ok."""
    req = os.path.join(repo, "requirements.txt")
    if not os.path.exists(req):
        return True, "no requirements.txt (stdlib/assumed available)"
    venv = os.path.join(repo, ".calma_venv")
    try:
        subprocess.run([sys.executable, "-m", "venv", venv], check=True, capture_output=True, timeout=120)
        pip = os.path.join(venv, "bin", "pip")
        r = subprocess.run([pip, "install", "-q", "-r", req], capture_output=True, text=True, timeout=600)
        return r.returncode == 0, (r.stderr or "")[-200:] if r.returncode else "installed"
    except (subprocess.SubprocessError, OSError) as e:
        return False, "restore error: %s" % type(e).__name__


def _emitted(repo):
    found = []
    for dp, _, names in os.walk(repo):
        if ".calma" in dp or ".calma_venv" in dp:
            continue
        for n in names:
            if n.lower().endswith(MACHINE_READABLE):
                found.append(os.path.relpath(os.path.join(dp, n), repo))
    return found


def assess(repo, claim=None, metric=None, label=None):
    repo = os.path.realpath(repo)
    gates = {"restore": None, "run": None, "emit_raw": None, "bind": None}
    notes = {}

    rok, rnote = _restore(repo)
    gates["restore"] = rok
    notes["restore"] = rnote

    committed = os.path.join(repo, "verify.yaml")
    if os.path.exists(committed):
        contract = json.load(open(committed))
        cpath = committed
    else:
        contract = DC.draft(repo, claim=claim, metric=metric)
        cpath = os.path.join(repo, ".calma_contract.json")
        json.dump(contract, open(cpath, "w"))
    bound = [m for m in contract.get("metrics", []) if m.get("binding_status") in ("independently-bound", "plausibly-bound")]
    gates["bind"] = bool(bound)

    run_res, verdict = None, "INCONCLUSIVE"
    try:
        run_res = H.run(cpath, base=repo, timeout=180)
        gates["run"] = run_res.get("exit_code") == 0
        gates["emit_raw"] = bool(_emitted(repo))
        if gates["run"] and gates["bind"]:
            rec = RC.recompute_contract(cpath, base=repo)
            diff = CMP.compare(rec, contract, isolation_tier=run_res.get("isolation_tier", "none"),
                               determinism_mode=run_res.get("determinism_mode", "uncontrolled"),
                               exit_codes=[run_res.get("exit_code", 0)], killed=run_res.get("killed", False))
            verdict = diff["metrics"][0]["verdict"] if diff["metrics"] else "INCONCLUSIVE"
    except Exception as e:  # never let one repo crash the corpus run
        notes["run_error"] = "%s: %s" % (type(e).__name__, str(e)[:160])

    served = all(gates[g] for g in ("restore", "run", "emit_raw", "bind"))
    failing_gate = next((g for g in ("restore", "run", "emit_raw", "bind") if not gates[g]), None)
    return {"repo": os.path.basename(repo), "label": label, "gates": gates, "served": served,
            "failing_gate": failing_gate, "verdict": verdict,
            "determinism": (run_res or {}).get("determinism_mode"),
            "isolation": (run_res or {}).get("isolation_tier"), "notes": notes}


def run(specs):
    rows = [assess(s["dir"], s.get("claim"), s.get("metric"), s.get("label")) for s in specs]
    served = sum(1 for r in rows if r["served"])
    gate_fail = {}
    for r in rows:
        if r["failing_gate"]:
            gate_fail[r["failing_gate"]] = gate_fail.get(r["failing_gate"], 0) + 1
    verdicts = {}
    for r in rows:
        verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
    return {"n": len(rows), "served": served, "served_fraction": served / len(rows) if rows else 0.0,
            "gate_failures": gate_fail, "terminal_verdicts": verdicts, "rows": rows}


if __name__ == "__main__":
    specs = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else []
    print(json.dumps(run(specs), indent=2, default=str))
