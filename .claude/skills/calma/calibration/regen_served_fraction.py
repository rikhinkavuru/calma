"""Regenerate assets/served_fraction.json by running the full real-repo + cross-language corpus through
the 4-gate served-fraction instrument and recording each terminal verdict. This is a recording script
(like calibrate.py), run on the dev host on demand - NOT in CI: the two vendored live-data members
restore real dependencies, and the cross-language members need their toolchains.

Run with an interpreter whose base prefix is sandbox-readable (Homebrew python3.13, base under /opt) so
the restored venv used by the momentum member can run under the network-off Seatbelt profile:

    /opt/homebrew/bin/python3.13 calibration/regen_served_fraction.py

Each spec is {dir, language, label}; the committed verify.yaml in each member supplies claim+binding.
"""
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, HERE)
import served_fraction as SF  # noqa: E402

A = os.path.join(ROOT, "assets")
SPECS = [
    {"dir": os.path.join(A, "btc"), "language": "python", "label": "btc-overfit backtest (vendored snapshot)"},
    {"dir": os.path.join(A, "leakage"), "language": "python", "label": "ml-leakage civil-war repro"},
    {"dir": os.path.join(A, "corpus", "momentum-strategy"), "language": "python",
     "label": "sh-mukherjee/momentum-strategy (MIT, yfinance -> vendored snapshot)"},
    {"dir": os.path.join(A, "corpus", "btc-sma-crossover"), "language": "python",
     "label": "HilmiSamdya/btc-sma-backtest (MIT, Coinbase via record/replay shim)"},
    {"dir": os.path.join(A, "lang", "r"), "language": "r", "label": "R total-return fixture (honest)"},
    {"dir": os.path.join(A, "lang", "julia"), "language": "julia", "label": "Julia total-return fixture (honest)"},
    {"dir": os.path.join(A, "lang", "cpp"), "language": "cpp", "label": "C++ total-return fixture (flawed claim)"},
    {"dir": os.path.join(A, "lang", "rust"), "language": "rust", "label": "Rust total-return fixture (honest)"},
    {"dir": os.path.join(A, "lang", "node"), "language": "node", "label": "Node total-return fixture (honest)"},
]


def _clean(d):
    shutil.rmtree(os.path.join(d, ".calma"), ignore_errors=True)
    for junk in (".calma_bin", ".calma_contract.json"):
        p = os.path.join(d, junk)
        if os.path.exists(p):
            os.remove(p)


def main():
    rows = []
    for s in SPECS:
        r = SF.assess(s["dir"], label=s["label"])
        rows.append({
            "repo": r["repo"], "language": s["language"], "label": s["label"],
            "gates": r["gates"], "served": r["served"], "failing_gate": r["failing_gate"],
            "verdict": r["verdict"], "determinism": r["determinism"],
        })
        _clean(s["dir"])

    served = sum(1 for r in rows if r["served"])
    by_lang = {}
    for r in rows:
        b = by_lang.setdefault(r["language"], {"served": 0, "n": 0, "verdicts": {}})
        b["n"] += 1
        b["served"] += 1 if r["served"] else 0
        b["verdicts"][r["verdict"]] = b["verdicts"].get(r["verdict"], 0) + 1
    for b in by_lang.values():
        b["served_fraction"] = round(b["served"] / b["n"], 3) if b["n"] else 0.0
    terminal = {}
    for r in rows:
        terminal[r["verdict"]] = terminal.get(r["verdict"], 0) + 1

    out = {
        "n": len(rows), "served": served,
        "served_fraction": round(served / len(rows), 3) if rows else 0.0,
        "by_language": {k: {"served": v["served"], "n": v["n"],
                           "served_fraction": v["served_fraction"], "verdicts": v["verdicts"]}
                        for k, v in sorted(by_lang.items())},
        "terminal_verdicts": terminal,
        "rows": rows,
    }
    path = os.path.join(A, "served_fraction.json")
    json.dump(out, open(path, "w"), indent=2)
    print(json.dumps({"served_fraction": out["served_fraction"], "served": served, "n": len(rows),
                      "terminal_verdicts": terminal}, indent=2))
    print("wrote", path)


if __name__ == "__main__":
    main()
