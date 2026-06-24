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

print("streaming: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
