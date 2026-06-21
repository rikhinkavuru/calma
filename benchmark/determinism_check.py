"""The deterministic-verdict invariant, made into a standing gate (roadmap Operating Principle #1).

The verdict must be "one byte-re-derivable deterministic function of (code, data, claim)." This asserts
the load-bearing half of that: Calma's recompute path is byte-identical across runs AND has zero residual
numeric spread (k_spread == 0) on the reference-deterministic path - across kernels that exercise the
delicate reductions (compounding returns, tie-aware ranking + gaussianize, per-era aggregation, ROC-AUC,
order statistics). If a refactor ever introduces nondeterminism into a kernel (set iteration, dict order,
float reduction order), this fails loudly in `make eval` before it can reach a verdict.

Pure stdlib, no sandbox, no network. Run: python3 benchmark/determinism_check.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(HERE, "..", ".claude", "skills", "calma", "scripts")
sys.path.insert(0, SKILL)
import recompute as RC  # noqa: E402

# Each case = (label, columns, contract metrics). Chosen to span the reduction-order-sensitive kernels:
# compounding (total_return), ranking+inverse-normal+^1.5 per group (numerai_corr/sharpe), rank-sum
# (auc), centered cross-products (r2), and order statistics (median/var_at_risk).
_CASES = [
    ("total_return", {"return": [0.10, -0.05, 0.20, 0.00, 0.05, -0.02, 0.11]},
     [{"metric_id": "total_return", "artifact": "d.csv", "binding": {"return": "return"}, "headline": True}]),
    ("auc", {"y": [0, 0, 0, 1, 0, 1, 1, 0, 1, 1], "s": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95]},
     [{"metric_id": "auc", "artifact": "d.csv", "binding": {"label": "y", "score": "s"},
       "convention": "roc-auc", "headline": True}]),
    ("r2", {"target": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
            "prediction": [1.2, 1.8, 3.5, 3.9, 5.5, 5.8, 7.2, 8.4]},
     [{"metric_id": "r2", "artifact": "d.csv", "binding": {"target": "target", "prediction": "prediction"},
       "headline": True}]),
    ("numerai_corr", {"era": ["era01", "era01", "era01", "era01", "era02", "era02", "era02", "era02"],
                      "prediction": [0.1, 0.5, 0.3, 0.9, 0.2, 0.7, 0.4, 0.6],
                      "target": [0.0, 0.25, 0.5, 1.0, 0.25, 0.75, 0.5, 1.0]},
     [{"metric_id": "numerai_corr", "artifact": "d.csv",
       "binding": {"prediction": "prediction", "target": "target", "era": "era"}, "headline": True},
      {"metric_id": "numerai_sharpe", "artifact": "d.csv",
       "binding": {"prediction": "prediction", "target": "target", "era": "era"}}]),
    ("value_at_risk", {"return": [-0.08, 0.02, -0.03, 0.05, -0.12, 0.01, -0.06, 0.03, -0.01, 0.04,
                                  -0.09, 0.02, -0.04, 0.06, -0.02, 0.03, -0.07, 0.01, -0.05, 0.02]},
     [{"metric_id": "value_at_risk", "artifact": "d.csv", "binding": {"return": "return"},
       "convention": "p95", "headline": True}]),
]


def _materialize(cols, metrics, d):
    names = list(cols)
    n = len(cols[names[0]])
    with open(os.path.join(d, "d.csv"), "w", newline="") as f:
        f.write(",".join(names) + "\n")
        for i in range(n):
            f.write(",".join(repr(cols[c][i]) if isinstance(cols[c][i], float) else str(cols[c][i])
                              for c in names) + "\n")
    contract = {"run": {"entrypoint": "d.csv", "network": "off"}, "env": {"ecosystem": "python"},
                "artifacts": [{"path": "d.csv", "columns": {c: {} for c in names}}], "metrics": metrics}
    cpath = os.path.join(d, "verify.json")
    json.dump(contract, open(cpath, "w"))
    return cpath


def run():
    fails = 0
    print("%-16s %-10s %s" % ("case", "k_spread", "status"))
    print("-" * 56)
    for label, cols, metrics in _CASES:
        d = tempfile.mkdtemp(prefix="calma_det_")
        cpath = _materialize(cols, metrics, d)
        # recompute TWICE, independently, k=3 each (k>1 captures intra-run spread; two runs capture
        # inter-run nondeterminism). The canonical serialization must be byte-identical.
        r1 = json.dumps(RC.recompute_contract(cpath, base=d, k=3), sort_keys=True)
        r2 = json.dumps(RC.recompute_contract(cpath, base=d, k=3), sort_keys=True)
        spreads = [m.get("k_spread", 0.0) for m in json.loads(r1)["metrics"]]
        max_spread = max(spreads) if spreads else 0.0
        identical = (r1 == r2)
        zero_spread = (max_spread == 0.0)
        ok = identical and zero_spread
        status = "ok" if ok else (
            "NONDETERMINISTIC (runs differ)" if not identical else "NONZERO k_spread=%g" % max_spread)
        if not ok:
            fails += 1
        print("%-16s %-10g %s" % (label, max_spread, status))
    print("-" * 56)
    print("%d/%d cases byte-identical across runs with k_spread==0" % (len(_CASES) - fails, len(_CASES)))
    return fails


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
