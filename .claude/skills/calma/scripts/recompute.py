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


def _na_policies(contract, artifact_path):
    na = {}
    for a in contract.get("artifacts", []):
        if a["path"] == artifact_path:
            for cname, spec in a.get("columns", {}).items():
                na[cname] = spec.get("na_policy", "error")
    return na


def _numeric_cols(contract, artifact_path, binding, base, metric_id=None):
    """Load the bound columns. Two extensions over the M1 loader:
    - a binding value 'other.csv::col' reads `col` from a SIBLING artifact (join_row_loss,
      cross-file speedup); the cols dict is keyed by the full 'path::col' string so recipes
      stay artifact-agnostic.
    - binding keys named in the recipe manifest's `string_tags` keep RAW (stripped) cell
      strings instead of floats (group keys, IDs, text predictions, null detection)."""
    fn = R.get(metric_id) if metric_id else None
    string_tags = set((fn.manifest.get("string_tags") if fn else []) or [])
    cache = {}
    na_cache = {}

    def load(path):
        if path not in cache:
            cache[path] = _load_cols(_safe_join(base, path))
        return cache[path]

    def na_policies(path):  # memoized per artifact - avoid re-walking contract.artifacts per column
        if path not in na_cache:
            na_cache[path] = _na_policies(contract, path)
        return na_cache[path]

    cols = {}
    for tag, col_name in binding.items():
        if "::" in str(col_name):
            art, _, cname = str(col_name).partition("::")
        else:
            art, cname = artifact_path, col_name
        raw = load(art)[cname]
        if tag in string_tags:
            cols[col_name] = [str(v).strip() for v in raw]
        else:
            cols[col_name] = _to_numeric(raw, na_policies(art).get(cname, "error"))
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
    import draft_contract as _DC
    contract = _DC.load_contract(contract_path)
    base = base or os.path.dirname(os.path.abspath(contract_path))
    out = {"metrics": [], "baselines": []}
    for m in contract.get("metrics", []):
        rec = _recompute_one(contract, m, base, k)
        rec["artifact"] = m["artifact"]
        out["metrics"].append(rec)
    for b in contract.get("baselines", []):
        rec = _recompute_one(contract, b, base, k)
        rec["label"] = b.get("label")
        out["baselines"].append(rec)
    return out


def _recompute_one(contract, m, base, k):
    """Recompute a single contract metric. A broken binding (missing file/column, a non-numeric
    cell in a numeric column, a path escape) is a DEGENERATE recompute - the verdict guard turns
    it into INCONCLUSIVE with the error named - never an uncaught traceback."""
    try:
        cols = _numeric_cols(contract, m["artifact"], m["binding"], base, m["metric_id"])
        return _run_recipe(m["metric_id"], cols, m["binding"], m.get("convention"), k)
    except (KeyError, ValueError, OSError) as e:
        detail = ("column %s not found in the artifact" % e) if isinstance(e, KeyError) else str(e)
        return {"metric_id": m["metric_id"], "value": float("nan"), "terms": {},
                "k": 0, "k_spread": 0.0, "degenerate": True,
                "near_zero_vol": False, "path_dependent": False,
                "error": "binding failed: %s" % detail}


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
