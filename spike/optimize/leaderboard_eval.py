#!/usr/bin/env python
"""optimize.leaderboard_eval — end-to-end measurement of the artifact-ingestion + reverse-map lift.

This is the meta-eval for the "re-run the paper" frontier work (2026-07-03): committed-artifact claim
ingestion (nested-JSON context + markdown wide tables) and the artifact->producer reverse map. Unlike
binding.py (which measures the binder on synthetic call metadata), this runs the WHOLE flow on generated
leaderboard repos:

    detect_entrypoint -> discover (committed claims) -> run_local (k=2) -> diff_claim per cell -> verdict

Each generated repo is a leaderboard: a driver (run_all.py) loops dataset x model computing a sklearn metric
with dataset/model context locals and writes a committed nested results.json; a DECOY quickstart (check.py)
runs one degenerate computation; one cell is misreported in results.json (expect REFUTED). Reports:

  entry_producer_rate   chose the script that WROTE the committed table, not the quickstart   [reverse map]
  context_rate          fraction of discovered claims carrying a dataset/model context label   [ingestion]
  bind_rate             discovered cells that bound to their own computation
  cells_correct         cells with the right verdict (honest -> CONFIRMED, misreport -> REFUTED)
  false_confirm_count   misreport -> POSITIVE  (MUST be 0 — the franchise invariant)

Before/after against a pre-slice tree: run the sibling copy under a git worktree checked out before the work
(the deltas are exactly the two slices; capture-side context extraction is equal in both trees, so it
cancels). Needs sklearn (spike venv). Claims are discovered BEFORE the run — a producer entrypoint
regenerates results.json, so a committed misreport must be read from disk first (the faithful flow).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SPIKE = os.path.dirname(HERE)
sys.path.insert(0, SPIKE)
sys.path.insert(0, os.path.join(SPIKE, "capture"))

from core import diff as D               # noqa: E402
from core import verdict as VD           # noqa: E402
from discovery import extract as DISC    # noqa: E402
from runner import build                 # noqa: E402
from runner.local_runner import run_local  # noqa: E402

DATASETS = ["cifar10", "mnist", "svhn"]
MODELS = ["resnet", "vit"]
TAMPER = ("vit", "svhn")                  # the one misreported cell -> expect REFUTED, never CONFIRMED


def _y(dataset, model):
    """Deterministic balanced (y_true, y_pred), n=200, cell-specific NON-degenerate accuracy ~0.81-0.90
    (balanced -> trivial baseline is 0.5; never perfect -> honest cells CONFIRM cleanly). No RNG."""
    seed = (sum(map(ord, dataset)) + sum(map(ord, model))) % 7
    n = 200
    y_true = [0, 1] * (n // 2)
    y_pred = list(y_true)
    for i in range(20 + 3 * seed):
        y_pred[i] = 1 - y_pred[i]
    return y_true, y_pred


def _acc(y_true, y_pred):
    return sum(int(a == b) for a, b in zip(y_true, y_pred)) / len(y_true)


DRIVER = '''\
import json
from sklearn.metrics import accuracy_score
DATASETS = %r
MODELS = %r
def _y(dataset, model):
    seed = (sum(map(ord, dataset)) + sum(map(ord, model))) %% 7
    y_true = [0, 1] * 100
    y_pred = list(y_true)
    for i in range(20 + 3 * seed):
        y_pred[i] = 1 - y_pred[i]
    return y_true, y_pred
def main():
    results = {}
    for dataset in DATASETS:
        for model in MODELS:
            y_true, y_pred = _y(dataset, model)
            acc = accuracy_score(y_true, y_pred)          # captured with context {dataset, model}
            results.setdefault(model, {})[dataset] = {"accuracy": round(acc, 4)}
    with open("results.json", "w") as fh:
        json.dump(results, fh, indent=2)
    print("wrote results.json")
if __name__ == "__main__":
    main()
'''

DECOY = '''\
from sklearn.metrics import accuracy_score
if __name__ == "__main__":
    y_true = [0, 1] * 100                                  # a quickstart: ONE computation, no loop, no context
    print("quickstart accuracy", accuracy_score(y_true, y_true))
'''


def gen_repo(root):
    os.makedirs(root, exist_ok=True)
    committed = {}
    for model in MODELS:
        for dataset in DATASETS:
            committed.setdefault(model, {})[dataset] = {"accuracy": round(_acc(*_y(dataset, model)), 4)}
    committed[TAMPER[0]][TAMPER[1]]["accuracy"] = round(
        committed[TAMPER[0]][TAMPER[1]]["accuracy"] + 0.15, 4)                # misreport this cell
    with open(os.path.join(root, "results.json"), "w") as fh:
        json.dump(committed, fh, indent=2)
    with open(os.path.join(root, "README.md"), "w") as fh:
        fh.write("# Leaderboard\n\nResults in `results.json` (model -> dataset -> accuracy).\n")
    with open(os.path.join(root, "run_all.py"), "w") as fh:
        fh.write(DRIVER % (DATASETS, MODELS))
    with open(os.path.join(root, "check.py"), "w") as fh:                     # decoy (alphabetically first)
        fh.write(DECOY)
    expect = {(m, d): ("REFUTED" if (m, d) == TAMPER else "CONFIRMED") for m in MODELS for d in DATASETS}
    return expect


def _cell(claim):
    toks = {t.lower() for t in (claim.get("context") or "").replace("=", " ").split()}
    return (next((m for m in MODELS if m in toks), None), next((d for d in DATASETS if d in toks), None))


def measure_repo(root, expect):
    entry = build.detect_entrypoint(root) or ["check.py"]
    claims = DISC.discover(root, stdout_text="", entry=entry)                 # committed claims, BEFORE the run
    r = run_local(root, entry, k=2, python=sys.executable, hooks="sklearn", timeout=180)
    acc_claims = [c for c in claims if c["metric"] == "accuracy"]
    bound = cells_correct = graded = false_confirm = 0
    vdist: dict = {}
    for c in acc_claims:
        rec = D.diff_claim(c, r["runs"]) if r["runs"] else {"verdict": VD.INCONCLUSIVE, "binding": {}}
        v = rec["verdict"]
        vdist[v] = vdist.get(v, 0) + 1
        bound += bool(rec.get("binding", {}).get("bound"))
        cell = _cell(c)
        exp = expect.get(cell)
        if exp and cell[0] and cell[1]:
            graded += 1
            cells_correct += (v == exp)
            false_confirm += (v in VD.POSITIVE and exp == "REFUTED")
    return {"entry": entry, "entry_is_producer": entry == ["run_all.py"],
            "n_acc_claims": len(acc_claims), "with_context": sum(1 for c in acc_claims if c.get("context")),
            "bound": bound, "vdist": vdist, "graded": graded, "cells_correct": cells_correct,
            "false_confirm": false_confirm, "ran": r["ran_ok"]}


def measure(n_repos=4, workdir=None):
    workdir = workdir or tempfile.mkdtemp(prefix="calma_lb_")
    rows = [measure_repo(os.path.join(workdir, "lb_%d" % i), gen_repo(os.path.join(workdir, "lb_%d" % i)))
            for i in range(n_repos)]
    claims = sum(r["n_acc_claims"] for r in rows)
    return {
        "n_repos": n_repos,
        "entry_producer_rate": round(sum(r["entry_is_producer"] for r in rows) / n_repos, 3),
        "claims_total": claims,
        "context_rate": round(sum(r["with_context"] for r in rows) / max(1, claims), 3),
        "bind_rate": round(sum(r["bound"] for r in rows) / max(1, claims), 3),
        "cells_graded": sum(r["graded"] for r in rows),
        "cells_correct": sum(r["cells_correct"] for r in rows),
        "cells_correct_rate": round(sum(r["cells_correct"] for r in rows) / max(1, sum(r["graded"] for r in rows)), 3),
        "false_confirm_count": sum(r["false_confirm"] for r in rows),
        "verdicts": _merge([r["vdist"] for r in rows]),
        "rows": rows,
    }


def _merge(dicts):
    out: dict = {}
    for d in dicts:
        for k, v in d.items():
            out[k] = out.get(k, 0) + v
    return out


def main():
    m = measure()
    with open(os.path.join(HERE, "leaderboard_metrics.json"), "w") as fh:
        json.dump(m, fh, indent=2)
    print("=== LEADERBOARD end-to-end meta-eval (artifact ingestion + reverse map) ===")
    print("repos=%d  cells=%d" % (m["n_repos"], m["claims_total"]))
    print("entry-producer rate (ran the real suite, not the quickstart): %s  [target 1.0]"
          % m["entry_producer_rate"])
    print("context rate        (claims carry dataset/model label):       %s  [target 1.0]" % m["context_rate"])
    print("bind rate           (cells bound to own computation):         %s  [target 1.0]" % m["bind_rate"])
    print("cells correct       (honest->CONFIRMED, misreport->REFUTED):  %d/%d (%s)"
          % (m["cells_correct"], m["cells_graded"], m["cells_correct_rate"]))
    print("FALSE-CONFIRM count (misreport->POSITIVE):                    %d  [target 0 — the franchise]"
          % m["false_confirm_count"])
    print("verdicts:", m["verdicts"])
    return 0 if m["false_confirm_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
