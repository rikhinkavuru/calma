"""calma.recompute - recompute each metric from the RAW re-emitted artifacts via the canonical recipe
on the reference-deterministic path. Reads only machine-readable files (csv here); never a reported
value. Runs each recipe K times to capture residual numeric spread (0 on the deterministic path).

Library: recompute_contract(contract_path, base=None, k=3) -> dict.
CLI: recompute.py --contract verify.yaml [--base DIR] [-k K] --out recompute.json
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recipes as R  # noqa: E402


def _load_cols(path):
    with open(path, newline="") as fh:
        rd = csv.reader(fh)
        header = next(rd)
        cols = {h: [] for h in header}
        for row in rd:
            for h, v in zip(header, row):
                cols[h].append(v)
    return cols


def _to_numeric(raw, na_policy="error"):
    out = []
    for v in raw:
        v = (v or "").strip()
        if v == "" or v.lower() in ("nan", "na", "null", "none"):
            if na_policy == "drop":
                continue
            if na_policy == "zero-fill":
                out.append(0.0)
                continue
            out.append(float("nan"))
        else:
            out.append(float(v))
    return out


def _safe_join(base, rel):
    """Resolve rel under base and refuse anything that escapes base (abs path, .. traversal)."""
    full = os.path.realpath(os.path.join(base, rel))
    rb = os.path.realpath(base)
    if full != rb and not full.startswith(rb + os.sep):
        raise ValueError("artifact path escapes the contract base: %r" % rel)
    return full


def _numeric_cols(contract, artifact_path, binding, base):
    cols_raw = _load_cols(_safe_join(base, artifact_path))
    # find na_policy per column from the artifact spec
    na = {}
    for a in contract.get("artifacts", []):
        if a["path"] == artifact_path:
            for cname, spec in a.get("columns", {}).items():
                na[cname] = spec.get("na_policy", "error")
    cols = {}
    for col_name in binding.values():
        cols[col_name] = _to_numeric(cols_raw[col_name], na.get(col_name, "error"))
    return cols


def _run_recipe(metric_id, cols, binding, convention, k):
    fn = R.get(metric_id)
    if fn is None:
        return {"metric_id": metric_id, "error": "no recipe for %r" % metric_id, "degenerate": True}
    runs = [fn(cols, binding, convention) for _ in range(max(k, 1))]
    vals = [r["value"] for r in runs]
    finite = [v for v in vals if isinstance(v, float) and v == v]
    k_spread = (max(finite) - min(finite)) if len(finite) == len(vals) and finite else 0.0
    r0 = runs[0]
    return {
        "metric_id": metric_id, "value": r0["value"], "terms": r0["terms"],
        "k": len(runs), "k_spread": k_spread, "degenerate": r0["degenerate"],
        "near_zero_vol": r0["near_zero_vol"], "path_dependent": r0["path_dependent"],
    }


def recompute_contract(contract_path, base=None, k=3):
    with open(contract_path) as fh:
        contract = json.load(fh)
    base = base or os.path.dirname(os.path.abspath(contract_path))
    out = {"metrics": [], "baselines": []}
    for m in contract.get("metrics", []):
        cols = _numeric_cols(contract, m["artifact"], m["binding"], base)
        rec = _run_recipe(m["metric_id"], cols, m["binding"], m.get("convention"), k)
        rec["artifact"] = m["artifact"]
        out["metrics"].append(rec)
    for b in contract.get("baselines", []):
        cols = _numeric_cols(contract, b["artifact"], b["binding"], base)
        rec = _run_recipe(b["metric_id"], cols, b["binding"], b.get("convention"), k)
        rec["label"] = b.get("label")
        out["baselines"].append(rec)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", required=True)
    ap.add_argument("--base")
    ap.add_argument("-k", type=int, default=3)
    ap.add_argument("--out")
    a = ap.parse_args()
    res = recompute_contract(a.contract, a.base, a.k)
    text = json.dumps(res, indent=2)
    if a.out:
        with open(a.out, "w") as fh:
            fh.write(text)
    print(text)
    return 1 if any(m.get("degenerate") for m in res["metrics"]) else 0


if __name__ == "__main__":
    sys.exit(main())
