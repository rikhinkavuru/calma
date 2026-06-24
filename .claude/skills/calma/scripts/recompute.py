"""calma.recompute - recompute each metric from the RAW re-emitted artifacts via the canonical recipe
on the reference-deterministic path. Reads only machine-readable files (csv here); never a reported
value. Runs each recipe K times to capture residual numeric spread (0 on the deterministic path).

Library: recompute_contract(contract_path, base=None, k=3) -> dict.
CLI: recompute.py --contract verify.yaml [--base DIR] [-k K] --out recompute.json
"""
import argparse
import csv
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pathsafe as PS  # noqa: E402
import recipes as R  # noqa: E402

_INF, _NINF = float("inf"), float("-inf")


# DoS bound: the artifact is emitted by the (sandboxed but UNTRUSTED) entrypoint and then read by the HOST
# verifier OUTSIDE the sandbox (recompute runs post-execution). Cap the on-disk size so a hostile multi-GB
# CSV can't OOM the verifier / CI runner; over the cap is a degenerate recompute (-> INCONCLUSIVE), never
# an unbounded load. Generous vs any real artifact (Numerai/Gauntlet datasets are < a few MB); override
# with CALMA_MAX_ARTIFACT_MB.
_MAX_ARTIFACT_BYTES = int(float(os.environ.get("CALMA_MAX_ARTIFACT_MB", "256")) * 1024 * 1024)

# W8(a) streaming: when a recipe DECLARES `streaming` in its manifest AND its artifact is over this
# threshold, recompute via the constant-memory fold (stream_reduce) instead of the eager whole-file load —
# so a legitimate multi-GB artifact verifies instead of degenerating to CAN'T-CONFIRM at the byte cap.
# Default = the eager cap (zero behaviour change below it); CALMA_STREAM_THRESHOLD_BYTES overrides it (set
# to 0 to force streaming and prove the streamed value equals the in-memory value bit-for-bit).
_STREAM_THRESHOLD = int(os.environ.get("CALMA_STREAM_THRESHOLD_BYTES", str(_MAX_ARTIFACT_BYTES)))


def _load_cols(path, columns=None):
    if not os.path.isfile(path):
        # a FIFO / socket / device artifact would BLOCK open() forever (a hostile entrypoint can
        # plant one in runs/); fail it as a degenerate recompute instead of hanging the verifier.
        raise ValueError("artifact %s is not a regular file" % os.path.basename(path))
    # WS-A: an optional .parquet artifact is read by the lazy, firewalled pyarrow adapter (calma[parquet]).
    # Memory is bounded by the adapter's row guard + COLUMN PROJECTION (the wide tournament file is never
    # fully materialized), so the on-disk byte-cap - the wrong guard for a projected columnar read - does
    # not apply here; the pure-stdlib core never imports pyarrow (the import is lazy, inside io_parquet).
    if path.lower().endswith(".parquet"):
        import io_parquet as IOPQ  # noqa: PLC0415 - intentionally lazy (keeps the core import graph clean)
        return IOPQ.read_columns(path, columns=columns)
    sz = os.path.getsize(path)
    if sz > _MAX_ARTIFACT_BYTES:
        raise ValueError("artifact %s is %d MB, over the %d MB recompute cap (a hostile entrypoint can "
                         "emit a giant file to OOM the host verifier); raise CALMA_MAX_ARTIFACT_MB for a "
                         "genuinely large dataset" % (os.path.basename(path), sz // (1024 * 1024),
                                                      _MAX_ARTIFACT_BYTES // (1024 * 1024)))
    with open(path, newline="") as fh:
        rd = csv.reader(fh)
        header = next(rd, None)
        if header is None:  # a 0-byte / header-less emitted artifact: a clean degenerate, not a crash
            raise ValueError("artifact %s is empty (no header row)" % os.path.basename(path))
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
            f = float(v)
            # a literal inf/-inf/Infinity cell is corrupt data, not a value: map it to NaN so the
            # recompute degenerates (-> INCONCLUSIVE) instead of an order-statistic silently
            # returning a finite-but-from-corrupt-data number (e.g. median([10,20,inf]) = 20).
            out.append(f if math.isfinite(f) else float("nan"))
    return out


def _safe_join(base, rel):
    """Resolve rel under base and refuse anything that escapes base (abs path / .. traversal /
    symlink-out). Delegates to the shared guard (pathsafe) so there is ONE audited containment
    implementation (L1); recompute was historically the reference copy every detector mirrored."""
    return PS.safe_join(base, rel)


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
    # the bound column NAMES (the bare cname, dropping any 'other.csv::col' sibling-artifact ref) - passed
    # as the projection set so a .parquet artifact materializes ONLY these columns, not the full width.
    needed = sorted({str(cn).partition("::")[2] or str(cn)
                     for v in binding.values() for cn in (v if isinstance(v, list) else [v])})

    def load(path):
        if path not in cache:
            cache[path] = _load_cols(_safe_join(base, path), columns=needed)
        return cache[path]

    def na_policies(path):  # memoized per artifact - avoid re-walking contract.artifacts per column
        if path not in na_cache:
            na_cache[path] = _na_policies(contract, path)
        return na_cache[path]

    cols = {}
    for tag, col_name in binding.items():
        # a binding value may be a LIST of columns (a feature SET, e.g. FNC / max-feature-exposure
        # neutralizers); each is read into cols keyed by its own name, so the recipe does
        # [cols[c] for c in binding["features"]]. A scalar value behaves exactly as before.
        for cn in (col_name if isinstance(col_name, list) else [col_name]):
            if "::" in str(cn):
                art, _, cname = str(cn).partition("::")
            else:
                art, cname = artifact_path, cn
            raw = load(art)[cname]
            if tag in string_tags:
                cols[cn] = [str(v).strip() for v in raw]
            else:
                cols[cn] = _to_numeric(raw, na_policies(art).get(cname, "error"))
    return cols


def _run_recipe(metric_id, cols, binding, convention, k):
    fn = R.get(metric_id)
    if fn is None:
        return {"metric_id": metric_id, "error": "no recipe for %r" % metric_id, "degenerate": True}
    # A non-finite value in any bound NUMERIC column (an inf/NaN cell, or an unfilled NA under
    # na_policy=error) makes the recompute degenerate. Order-statistic kernels (median/min/max/
    # quantile/iqr) that don't SELECT the bad value would otherwise return a finite-but-from-corrupt
    # -data number (median([10,20,inf]) = 20 -> a misleading CONFIRMED-WITH-CAVEATS). String columns
    # (null/distinct/duplicate recipes, declared via string_tags) hold raw strings, so they're skipped
    # here and still see their own NA/empty cells. Set na_policy: drop|zero-fill to clean instead.
    for col_vals in cols.values():
        if any(isinstance(x, float) and not (x == x and x not in (_INF, _NINF)) for x in col_vals):
            return {"metric_id": metric_id, "value": float("nan"), "terms": {}, "k": 0,
                    "k_spread": 0.0, "degenerate": True, "near_zero_vol": False,
                    "path_dependent": False,
                    "error": "a bound numeric column contains a non-finite value (NaN/Inf cell, "
                             "or an unfilled NA under na_policy=error)"}
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
    """Recompute a single contract metric. ANY failure - a broken binding (missing file/column,
    a non-numeric cell, a path escape) OR a kernel that cannot produce a finite number on this
    data (overflow on near-float-max magnitudes, a division by zero, a degenerate index) - is a
    DEGENERATE recompute. The verdict guard (G2) turns it into INCONCLUSIVE with the error named;
    it is NEVER an uncaught traceback. A recompute that raises is, by definition, a number that
    could not be reproduced, which is exactly INCONCLUSIVE - so the catch-all is sound, not a
    swallow (KeyboardInterrupt/SystemExit still propagate: we catch Exception, not BaseException)."""
    try:
        # W8(a): a streaming-capable recipe over the streaming threshold takes the constant-memory fold,
        # so a genuinely-large artifact verifies instead of degenerating at the eager byte cap. Below the
        # threshold (the default = the eager cap), the in-memory path is unchanged for every recipe.
        fn = R.get(m["metric_id"])
        sm = fn.manifest.get("streaming") if fn else None
        if sm and _should_stream(_safe_join(base, m["artifact"])):
            return _run_streaming(m, contract, base, sm, k)
        cols = _numeric_cols(contract, m["artifact"], m["binding"], base, m["metric_id"])
        return _run_recipe(m["metric_id"], cols, m["binding"], m.get("convention"), k)
    except (KeyError, ValueError, OSError) as e:
        detail = ("column %s not found in the artifact" % e) if isinstance(e, KeyError) else str(e)
        return _degenerate(m["metric_id"], "binding failed: %s" % detail)
    except Exception as e:  # noqa: BLE001 - any kernel failure is a degenerate recompute, not a crash
        return _degenerate(m["metric_id"],
                           "recompute could not produce a finite value: %s: %s"
                           % (type(e).__name__, str(e)[:120]))


def _degenerate(metric_id, error):
    return {"metric_id": metric_id, "value": float("nan"), "terms": {},
            "k": 0, "k_spread": 0.0, "degenerate": True,
            "near_zero_vol": False, "path_dependent": False, "error": error}


def _should_stream(path):
    """Route a streaming-capable recipe to the constant-memory fold when its artifact is over the streaming
    threshold (default: the eager byte cap). Below it, the in-memory path is unchanged."""
    try:
        return os.path.getsize(path) > _STREAM_THRESHOLD
    except OSError:
        return False


def _iter_chunks(path, columns):
    """File-order, constant-memory {col: [str]} chunks — parquet row-groups (the lazy, firewalled adapter)
    or CSV lines — mirroring _load_cols's extension branch. Chunk order == row order (so a path-dependent
    online fold like max_drawdown stays bit-identical)."""
    if path.lower().endswith(".parquet"):
        import io_parquet as IOPQ  # noqa: PLC0415 - intentionally lazy (keeps the core import graph clean)
        return IOPQ.iter_batches(path, columns=columns)
    return PS.iter_csv_chunks(path, columns=columns)


def _run_streaming(m, contract, base, sm, k):
    """Constant-memory streaming recompute for a recipe that declared `streaming` in its manifest. Drives the
    declared reducer over file-order chunks, runs it k times (K-spread must stay 0), and returns the SAME
    result dict shape as _run_recipe — so verdict.py, the ledger, the diff, and the validity rail see a
    normal recompute result and need zero changes. Bit-identical to the in-memory recipe (the additive
    reducers use an exact Shewchuk accumulator; max_drawdown is an order-stable online fold)."""
    import stream_reduce as SR  # noqa: PLC0415 - sibling module, lazy to keep import-time minimal
    if sm.get("class") == "quantile":                    # Class B: external merge-sort (no registered reducer)
        return _run_streaming_quantile(m, contract, base, sm, k)
    reducer_cls = SR.REDUCERS.get(sm.get("reducer"))
    if reducer_cls is None:
        return _degenerate(m["metric_id"], "unknown streaming reducer %r" % sm.get("reducer"))
    if sm.get("class") == "grouped":
        return _run_streaming_grouped(m, contract, base, sm, reducer_cls, k)
    binding, convention = m["binding"], m.get("convention")
    path = _safe_join(base, m["artifact"])
    col = reducer_cls(binding, convention).column(binding)   # the bound column (None = pure row count)
    numeric = reducer_cls.numeric
    na = _na_policies(contract, m["artifact"]).get(col, "error") if col else "error"
    proj = [col] if col else None

    def run_once():
        reducer = reducer_cls(binding, convention)
        for raw_chunk in _iter_chunks(path, proj):
            if col is None:                                  # row count over any projected column
                vals = next(iter(raw_chunk.values()), [])
            elif numeric:
                vals = _to_numeric(raw_chunk[col], na)
            else:
                vals = raw_chunk[col]
            reducer.accumulate(vals)
        return reducer.finalize()

    runs = [run_once() for _ in range(max(k, 1))]
    vals = [r["value"] for r in runs]
    finite = [v for v in vals if isinstance(v, float) and v == v]
    k_spread = (max(finite) - min(finite)) if len(finite) == len(vals) and finite else 0.0
    r0 = runs[0]
    return {
        "metric_id": m["metric_id"], "value": r0["value"], "terms": r0["terms"],
        "k": len(runs), "k_spread": k_spread, "degenerate": r0["degenerate"],
        "near_zero_vol": r0["near_zero_vol"], "path_dependent": r0["path_dependent"], "streamed": True,
    }


def _run_streaming_quantile(m, contract, base, sm, k):
    """Class-B streaming recompute (quantile / median / percentile): an EXACT external merge-sort over the
    bound value column, then numpy 'linear' interpolation at q — bit-identical to numeric.quantile over the
    fully-sorted vector. q is the manifest's fixed q (column_median: 0.5) or resolved from the recipe's
    convention (percentile). Same result-dict shape as _run_recipe; K-spread 0; temp runs cleaned up."""
    import stream_reduce as SR  # noqa: PLC0415
    col = m["binding"].get("value")
    if not col:
        return _degenerate(m["metric_id"], "quantile streaming requires a 'value' binding")
    q = sm.get("q")
    if q is None and sm.get("q_from") == "convention":
        import recipes as R  # noqa: PLC0415 - lazy; reuse the recipe's exact convention->q parser
        try:
            q = R._conv_q(m.get("convention"))
        except Exception:  # noqa: BLE001 - an unparseable convention -> degenerate, never a crash
            q = None
    if not (isinstance(q, (int, float)) and 0.0 <= q <= 1.0):
        return _degenerate(m["metric_id"], "quantile streaming: q not resolvable (%r)" % (q,))
    path = _safe_join(base, m["artifact"])
    na = _na_policies(contract, m["artifact"]).get(col, "error")

    def run_once():
        qs = SR.ExternalSortQuantile()
        try:
            for raw_chunk in _iter_chunks(path, [col]):
                qs.add_chunk(_to_numeric(raw_chunk[col], na))
            return qs.result(float(q)), qs.n
        finally:
            qs.cleanup()

    runs = [run_once() for _ in range(max(k, 1))]
    vals = [r[0] for r in runs]
    finite = [v for v in vals if isinstance(v, float) and v == v]
    k_spread = (max(finite) - min(finite)) if len(finite) == len(vals) and finite else 0.0
    v0 = vals[0]
    degenerate = not (isinstance(v0, float) and v0 == v0 and v0 not in (_INF, _NINF))
    return {
        "metric_id": m["metric_id"], "value": v0, "terms": {"n": runs[0][1], "q": float(q), "method": "linear"},
        "k": len(runs), "k_spread": k_spread, "degenerate": degenerate,
        "near_zero_vol": False, "path_dependent": False, "streamed": True,
    }


def _iter_groups(chunks, group_col):
    """Regroup a {col:[str]} chunk stream into CONTIGUOUS group slices, yielding (group_key, {col:[str]}).
    Bounded memory = one group (e.g. one Numerai era). Raises ValueError if a group key recurs non-
    contiguously — the data is not group-sorted, so it can't be streamed in constant memory (the eager
    in-memory path handles unsorted data; streaming requires the file be group-sorted, which the Numerai
    validation parquet is)."""
    seen = set()
    cur_key, cur = None, None
    started = False
    for chunk in chunks:
        cols = list(chunk)
        if group_col not in chunk:
            raise ValueError("group column %r not in the artifact" % group_col)
        gv = chunk[group_col]
        for i in range(len(gv)):
            k = gv[i]
            if not started or k != cur_key:
                if cur is not None:
                    yield cur_key, cur
                if k in seen:
                    raise ValueError("group %r recurs non-contiguously — the artifact is not group-sorted, "
                                     "so it cannot be streamed in constant memory" % k)
                seen.add(k)
                cur_key, cur, started = k, {c: [] for c in cols}, True
            for c in cols:
                cur[c].append(chunk[c][i])
    if cur is not None:
        yield cur_key, cur


def _run_streaming_grouped(m, contract, base, sm, reducer_cls, k):
    """Grouped streaming recompute (Numerai per-era fold): drive the reducer over CONTIGUOUS group slices,
    computing each group's metric in-memory on its bounded slice. The multi-GB era-sorted file never lands
    in RAM. Bit-identical to the in-memory per-era recipe; K-spread 0. Same result-dict shape as _run_recipe."""
    binding, convention = m["binding"], m.get("convention")
    path = _safe_join(base, m["artifact"])
    group_tag = sm.get("group") or "era"
    pred_col, tgt_col = binding["prediction"], binding["target"]
    group_col = binding[group_tag]
    na = _na_policies(contract, m["artifact"])
    na_pred, na_tgt = na.get(pred_col, "error"), na.get(tgt_col, "error")
    needed = sorted({pred_col, tgt_col, group_col})

    def run_once():
        reducer = reducer_cls(binding, convention)
        for _gkey, gcols in _iter_groups(_iter_chunks(path, needed), group_col):
            pred = _to_numeric(gcols[pred_col], na_pred)
            tgt = _to_numeric(gcols[tgt_col], na_tgt)
            reducer.accumulate_group(_gkey, pred, tgt)
        return reducer.finalize()

    runs = [run_once() for _ in range(max(k, 1))]
    vals = [r["value"] for r in runs]
    finite = [v for v in vals if isinstance(v, float) and v == v]
    k_spread = (max(finite) - min(finite)) if len(finite) == len(vals) and finite else 0.0
    r0 = runs[0]
    return {
        "metric_id": m["metric_id"], "value": r0["value"], "terms": r0["terms"],
        "k": len(runs), "k_spread": k_spread, "degenerate": r0["degenerate"],
        "near_zero_vol": r0["near_zero_vol"], "path_dependent": r0["path_dependent"], "streamed": True,
    }


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
