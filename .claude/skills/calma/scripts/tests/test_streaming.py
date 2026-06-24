"""Tests for the W8(a) streaming recompute (P2-M9a): constant-memory folds that recompute a genuinely-large
artifact past the 256 MB cap, bit-identical to the in-memory recipe. Pure stdlib. Run: python3 test_streaming.py

Covers: the exact Shewchuk accumulator == math.fsum; streaming == in-memory bit-for-bit for every opted-in
recipe (column_sum/mean, row_count, max_drawdown); K-spread 0; a non-finite cell degenerates identically; an
OVER-CAP artifact verifies via streaming where the eager path would degenerate; the iter_csv_chunks DoS
guards (projection, non-regular file, row wall); and that NON-streaming recipes are unchanged.
"""
import math
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import recompute as RC  # noqa: E402
import pathsafe as PS  # noqa: E402
import stream_reduce as SR  # noqa: E402

_n = _fail = 0


def expect(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def _bits(x):
    return x.hex() if isinstance(x, float) and x == x else x


def write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        f.write(",".join(header) + "\n")
        for r in rows:
            f.write(",".join(repr(x) if isinstance(x, float) else str(x) for x in r) + "\n")


def recompute_one(contract, metric, base, k=3, stream_threshold=None, max_artifact=None):
    """Drive a single metric through recompute._recompute_one with the streaming threshold / eager cap
    temporarily overridden (both are module constants read at import)."""
    old_t, old_c = RC._STREAM_THRESHOLD, RC._MAX_ARTIFACT_BYTES
    if stream_threshold is not None:
        RC._STREAM_THRESHOLD = stream_threshold
    if max_artifact is not None:
        RC._MAX_ARTIFACT_BYTES = max_artifact
    try:
        return RC._recompute_one(contract, metric, base, k)
    finally:
        RC._STREAM_THRESHOLD, RC._MAX_ARTIFACT_BYTES = old_t, old_c


# ---- 1. the exact Shewchuk accumulator is bit-identical to math.fsum (incl. adversarial cancellation) ----
adversarial = ([1e16, 1.0, -1e16, 1.0] * 2000) + ([0.1] * 30000) + ([-3.7, 2.2e8, 1e-9, -2.2e8] * 1000)
es = SR.ExactSum()
for x in adversarial:
    es.add(x)
expect(es.result() == math.fsum(adversarial), "ExactSum == math.fsum on adversarial data")
expect(_bits(es.result()) == _bits(math.fsum(adversarial)), "ExactSum bit-identical to math.fsum")
es2 = SR.ExactSum()  # empty
expect(es2.result() == 0.0, "ExactSum() empty == 0.0")

# ---- 2. streaming == in-memory recompute, BIT-FOR-BIT, for every opted-in recipe ----
# a deterministic, varied series (negatives + magnitudes) so sum/mean/maxdd all exercise real arithmetic.
N = 5000
vals = [((i % 97) - 48) * 0.013 + ((i * 7) % 13) * 0.0007 - (1.0 if i % 50 == 0 else 0.0) for i in range(N)]
rets = [v * 0.01 for v in vals]   # small returns so the equity curve is well-behaved for max_drawdown
tmp = tempfile.mkdtemp()
csv_path = os.path.join(tmp, "big.csv")
write_csv(csv_path, ["value", "ret"], [(vals[i], rets[i]) for i in range(N)])
contract = {"artifacts": [{"path": "big.csv", "columns": {}}]}

CASES = [
    ("column_sum", {"value": "value"}, None),
    ("column_mean", {"value": "value"}, None),
    ("row_count", {"column": "value"}, None),
    ("max_drawdown", {"return": "ret"}, "compounded"),
]
for metric_id, binding, conv in CASES:
    m = {"metric_id": metric_id, "artifact": "big.csv", "binding": binding, "convention": conv}
    eager = recompute_one(contract, m, tmp, stream_threshold=10 ** 12)   # threshold huge -> in-memory
    streamed = recompute_one(contract, m, tmp, stream_threshold=0)        # threshold 0 -> streaming
    expect(not eager.get("degenerate") and not streamed.get("degenerate"),
           "%s: both paths produce a finite value" % metric_id)
    expect(_bits(eager["value"]) == _bits(streamed["value"]),
           "%s: streamed value BIT-IDENTICAL to in-memory (%r vs %r)"
           % (metric_id, eager["value"], streamed["value"]))
    expect(streamed.get("streamed") is True, "%s: streamed result is flagged streamed" % metric_id)
    expect(streamed["k_spread"] == 0.0, "%s: K-spread 0 (deterministic chunk boundaries)" % metric_id)
    expect(eager["value"] == streamed["value"], "%s: equality (%r)" % (metric_id, eager["value"]))

# cross-check the streamed value against the raw kernel (sanity: column_sum == math.fsum, exactly)
expect(recompute_one(contract, {"metric_id": "column_sum", "artifact": "big.csv",
       "binding": {"value": "value"}}, tmp, stream_threshold=0)["value"] == math.fsum(vals),
       "streamed column_sum == math.fsum(vals)")

# ---- 3. an OVER-CAP artifact verifies via streaming where the eager path would degenerate ----
# eager cap tiny (so the whole-file read would raise) + streaming threshold 0 (so a streaming recipe routes
# around it). The streaming recipe gets a real value; a NON-streaming recipe on the same file degenerates.
over = recompute_one(contract, {"metric_id": "column_sum", "artifact": "big.csv",
                     "binding": {"value": "value"}}, tmp, stream_threshold=0, max_artifact=64)
expect(not over.get("degenerate") and over["value"] == math.fsum(vals),
       "over-cap artifact verifies via streaming (no false CAN'T-CONFIRM)")
non_stream = recompute_one(contract, {"metric_id": "column_std", "artifact": "big.csv",
                           "binding": {"value": "value"}}, tmp, stream_threshold=0, max_artifact=64)
expect(non_stream.get("degenerate"), "a NON-streaming recipe over the eager cap still degenerates (DoS cap holds)")

# ---- 4. a non-finite cell degenerates identically on both paths ----
bad_path = os.path.join(tmp, "bad.csv")
write_csv(bad_path, ["value"], [(1.0,), (2.0,), ("inf",), (4.0,)])
mb = {"metric_id": "column_sum", "artifact": "bad.csv", "binding": {"value": "value"}}
eager_bad = recompute_one(contract, mb, tmp, stream_threshold=10 ** 12)
stream_bad = recompute_one(contract, mb, tmp, stream_threshold=0)
expect(eager_bad.get("degenerate") and stream_bad.get("degenerate"),
       "a non-finite cell degenerates on BOTH the eager and streaming paths")

# ---- 5. iter_csv_chunks: projection, chunking, DoS guards ----
chunks = list(PS.iter_csv_chunks(csv_path, columns=["value"], chunksize=1000))
expect(len(chunks) == 5 and all(set(c) == {"value"} for c in chunks), "iter_csv_chunks projects + chunks (5x1000)")
expect(sum(len(c["value"]) for c in chunks) == N, "iter_csv_chunks yields all rows")
try:
    list(PS.iter_csv_chunks(csv_path, columns=["nope"]))
    expect(False, "iter_csv_chunks raises on an absent column")
except ValueError:
    expect(True, "iter_csv_chunks raises on an absent column")
try:
    list(PS.iter_csv_chunks(csv_path, columns=["value"], max_rows=10))
    expect(False, "iter_csv_chunks enforces the row wall")
except ValueError:
    expect(True, "iter_csv_chunks enforces the row wall")
try:
    list(PS.iter_csv_chunks(os.path.join(tmp, "does-not-exist.csv")))
    expect(False, "iter_csv_chunks raises on a non-regular file")
except ValueError:
    expect(True, "iter_csv_chunks raises on a non-regular file")

# ---- 6. a NON-streaming recipe (no manifest `streaming`) is unchanged below the cap ----
import recipes as R  # noqa: E402
expect(R.get("column_sum").manifest.get("streaming") is not None, "column_sum opted into streaming")
expect(R.get("sharpe").manifest.get("streaming") is None, "sharpe did NOT opt in (unchanged)")
small = recompute_one(contract, {"metric_id": "column_sum", "artifact": "big.csv",
                      "binding": {"value": "value"}}, tmp)   # default threshold = cap -> in-memory
expect(small.get("streamed") is None and small["value"] == math.fsum(vals),
       "below the threshold, a streaming-capable recipe still uses the in-memory path")

# ---- 7. GROUPED streaming: the Numerai per-era CORR fold (the multi-GB ICP case) ----
# an era-sorted CSV (era, pred, target); the streamed grouped fold == the in-memory per-era recipe bit-for-bit.
eras_rows = []
for e in range(8):                                   # 8 eras x 20 rows, a real (noisy) pred/target relationship
    for j in range(20):
        p = ((e * 20 + j) % 17 - 8) * 0.1 + j * 0.01
        t = p * 0.5 + ((e * 7 + j) % 11 - 5) * 0.05
        eras_rows.append(("era%02d" % e, round(p, 5), round(t, 5)))
num_path = os.path.join(tmp, "numerai.csv")
write_csv(num_path, ["era", "pred", "target"], eras_rows)
ncontract = {"artifacts": [{"path": "numerai.csv", "columns": {}}]}
nbind = {"prediction": "pred", "target": "target", "era": "era"}
for mid in ("numerai_corr", "numerai_sharpe"):
    m = {"metric_id": mid, "artifact": "numerai.csv", "binding": nbind}
    eager = recompute_one(ncontract, m, tmp, stream_threshold=10 ** 12)
    streamed = recompute_one(ncontract, m, tmp, stream_threshold=0)
    expect(not eager.get("degenerate") and not streamed.get("degenerate"),
           "%s: both paths produce a finite value" % mid)
    expect(_bits(eager["value"]) == _bits(streamed["value"]),
           "%s: GROUPED streamed value BIT-IDENTICAL to in-memory (%r vs %r)"
           % (mid, eager["value"], streamed["value"]))
    expect(streamed.get("streamed") is True and streamed["terms"].get("eras") == eager["terms"].get("eras"),
           "%s: streamed, same era count (%s)" % (mid, eager["terms"].get("eras")))
# the regrouper yields one contiguous era slice at a time (bounded memory = one era), across chunk boundaries
groups = list(RC._iter_groups(PS.iter_csv_chunks(num_path, columns=["era", "pred", "target"], chunksize=7), "era"))
expect(len(groups) == 8 and all(len(set(g[1]["era"])) == 1 for g in groups),
       "_iter_groups yields 8 contiguous era slices (one group per era, spanning chunk boundaries)")
# non-contiguous groups (an unsorted file) -> ValueError -> the recompute degenerates (honest; eager handles unsorted)
write_csv(os.path.join(tmp, "unsorted.csv"), ["era", "pred", "target"],
          [("eA", 1.0, 1.0), ("eB", 2.0, 2.0), ("eA", 3.0, 3.0), ("eB", 4.0, 4.0)])
try:
    list(RC._iter_groups(PS.iter_csv_chunks(os.path.join(tmp, "unsorted.csv"), chunksize=10), "era"))
    expect(False, "_iter_groups raises on non-contiguous groups")
except ValueError:
    expect(True, "_iter_groups raises on non-contiguous (unsorted) groups")

# ---- 8. Class B: exact quantile / median / percentile streaming via external merge-sort ----
import numeric as N  # noqa: E402 - the in-memory kernel to cross-check bit-identity against
qvals = [((i * 37) % 101 - 50) * 0.1 + (i % 7) * 0.013 for i in range(523)]   # 523 -> odd n, real interpolation
qpath = os.path.join(tmp, "q.csv")
write_csv(qpath, ["value"], [(v,) for v in qvals])
qcontract = {"artifacts": [{"path": "q.csv", "columns": {}}]}
# median (q=0.5 fixed in the manifest)
mm = {"metric_id": "column_median", "artifact": "q.csv", "binding": {"value": "value"}}
eager = recompute_one(qcontract, mm, tmp, stream_threshold=10 ** 12)
streamed = recompute_one(qcontract, mm, tmp, stream_threshold=0)
expect(_bits(eager["value"]) == _bits(streamed["value"]),
       "column_median: streamed == in-memory BIT-IDENTICAL (%r vs %r)" % (eager["value"], streamed["value"]))
expect(_bits(streamed["value"]) == _bits(N.quantile(qvals, 0.5)), "streamed median == numeric.quantile(.,0.5)")
expect(streamed.get("streamed") is True and streamed["k_spread"] == 0.0, "median streamed, K-spread 0")
# percentile (q resolved from the convention "p95")
mp = {"metric_id": "percentile", "artifact": "q.csv", "binding": {"value": "value"}, "convention": "p95"}
e95 = recompute_one(qcontract, mp, tmp, stream_threshold=10 ** 12)
s95 = recompute_one(qcontract, mp, tmp, stream_threshold=0)
expect(_bits(e95["value"]) == _bits(s95["value"]) and _bits(s95["value"]) == _bits(N.quantile(qvals, 0.95)),
       "percentile p95: streamed == in-memory == numeric.quantile(.,0.95), bit-identical")
# the external-sort spills a run per chunk, is exact across runs, and cleans up its temp files
qs = SR.ExternalSortQuantile()
qs.add_chunk(qvals[:200])
qs.add_chunk(qvals[200:])
qtmpdir = qs._tmpdir
expect(len(qs.runs) == 2 and os.path.isdir(qtmpdir), "ExternalSortQuantile spills one sorted run per chunk")
res = qs.result(0.5)
expect(_bits(res) == _bits(N.quantile(qvals, 0.5)) and not os.path.isdir(qtmpdir),
       "ExternalSortQuantile.result is exact over the merged runs + cleans up its temp dir")
# a non-finite cell -> degenerate (mirrors the in-memory _has_nan degrade)
write_csv(os.path.join(tmp, "qbad.csv"), ["value"], [(1.0,), ("inf",), (3.0,)])
expect(recompute_one(qcontract, {"metric_id": "column_median", "artifact": "qbad.csv",
       "binding": {"value": "value"}}, tmp, stream_threshold=0).get("degenerate"),
       "quantile streaming: a non-finite cell -> degenerate (like the in-memory path)")

# ---- 9. audit-fix regressions (adversarial review 2026-06-24) ----
# BLOCKER: grouped streaming must DEGENERATE on a non-finite cell under na_policy=error — NEVER silently drop
# a NaN era (which manufactured a CONFIRMED where the in-memory path is INCONCLUSIVE).
nan_rows = [list(r) for r in eras_rows]
nan_rows[25][1] = ""                                          # an empty `pred` cell in era01 (default error)
write_csv(os.path.join(tmp, "numerai_nan.csv"), ["era", "pred", "target"], nan_rows)
nan_c = {"artifacts": [{"path": "numerai_nan.csv", "columns": {}}]}
nnm = {"metric_id": "numerai_corr", "artifact": "numerai_nan.csv", "binding": nbind}
eager_nan = recompute_one(nan_c, nnm, tmp, stream_threshold=10 ** 12)
stream_nan = recompute_one(nan_c, nnm, tmp, stream_threshold=0)
expect(eager_nan.get("degenerate") and stream_nan.get("degenerate"),
       "grouped: a non-finite cell degenerates on BOTH paths (no false CONFIRMED from a dropped NaN era)")
# BLOCKER: grouped streaming refuses na_policy=drop (per-era vs whole-column drop can diverge)
drop_c = {"artifacts": [{"path": "numerai.csv", "columns": {"pred": {"na_policy": "drop"}}}]}
expect(recompute_one(drop_c, {"metric_id": "numerai_corr", "artifact": "numerai.csv", "binding": nbind},
                     tmp, stream_threshold=0).get("degenerate"),
       "grouped streaming refuses na_policy=drop (degenerates, never a divergent number)")
# MINOR: streaming row_count with an EMPTY binding degenerates (matches the in-memory NaN), not a stray count
expect(recompute_one(ncontract, {"metric_id": "row_count", "artifact": "numerai.csv", "binding": {}},
                     tmp, stream_threshold=0).get("degenerate"),
       "streaming row_count with an empty binding degenerates (matches the in-memory path)")
# MAJOR: ExternalSortQuantile.cleanup rmtree's an ORPHAN run file (a failed add_chunk) -> no leaked temp dir
qs2 = SR.ExternalSortQuantile()
orphan = os.path.join(qs2._tmpdir, "run-0.bin")
with open(orphan, "wb") as _f:
    _f.write(b"\x00" * 8)                                     # a partial write that never reached runs.append()
qs2.cleanup()
expect(not os.path.exists(orphan) and not os.path.isdir(qs2._tmpdir),
       "ExternalSortQuantile.cleanup removes an orphan run file + the temp dir (no leak)")

print("streaming: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
