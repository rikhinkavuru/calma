"""calma.stream_reduce - constant-memory streaming reducers for recompute past the 256 MB artifact cap
(master roadmap W8(a) / P2-M9a). A recipe OPTS IN by declaring a `streaming` block in its manifest; the
600+ recipes that don't declare it keep the in-memory path verbatim (zero behaviour change).

The hard invariant: a streamed recompute is **bit-identical** to the in-memory recipe on the same data, so
`verdict.py` / the ledger / the diff / the validity rail need ZERO changes — they see a normal recompute
result and the K-run spread stays 0. Bit-identity is NOT achieved by per-chunk `math.fsum` partials (each
chunk-sum is re-rounded, so `fsum([fsum(c) for c in chunks])` can differ from `fsum(flat)` by ~1 ULP).
Instead the additive kernels use an **incremental Shewchuk exact-sum accumulator** (`ExactSum`) — the SAME
algorithm CPython's `math.fsum` implements — which keeps a bounded list of non-overlapping partials whose
exact sum equals the exact sum of every value fed so far. `math.fsum(partials)` is then the correctly-
rounded total == `math.fsum(flat)`, exactly, in constant memory.

Reduction classes (verified against numeric.py):
  * Class A (shipped here): `column_sum` (ExactSum), `column_mean` (ExactSum + count), `row_count` (count),
    `max_drawdown` (single-pass eq/peak/mdd fold, already online — bit-identical when chunk order = row
    order). All bit-identical to their in-memory kernels.
  * Deferred (documented, not yet streamed): `total_return` — its `pairwise_prod` divide-and-conquer tree
    differs at chunk boundaries, so a streamed value is bit-STABLE (K-spread 0) but not bit-EQUAL to the
    in-memory value; Class B (quantile/median — needs an exact external merge-sort); the grouped per-era
    Numerai correlation fold. These stay on the in-memory path until built.

Pure stdlib (math only).
"""
import math

_INF, _NINF = float("inf"), float("-inf")


def _finite(x):
    return isinstance(x, float) and x == x and x not in (_INF, _NINF)


class ExactSum:
    """Incremental Shewchuk summation: O(1)-amortized add, constant memory (partials bounded by the number
    of distinct binary exponents), and `result()` == `math.fsum` of every value added, bit-for-bit."""

    __slots__ = ("partials",)

    def __init__(self):
        self.partials = []

    def add(self, x):
        x = float(x)
        partials = self.partials
        i = 0
        for y in partials:
            if abs(x) < abs(y):
                x, y = y, x
            hi = x + y
            lo = y - (hi - x)
            if lo:
                partials[i] = lo
                i += 1
            x = hi
        del partials[i:]
        partials.append(x)

    def result(self):
        # the partials are non-overlapping and exactly represent the running sum -> fsum gives the
        # correctly-rounded total, identical to math.fsum over the original flat sequence.
        return math.fsum(self.partials)


class StreamReducer:
    """Constant-memory fold over per-chunk value lists. Subclasses set:
      numeric  -> True if the bound column must be float-converted before accumulate (False = raw strings).
      column(binding) -> the artifact column this reducer reads (None = any column, for a pure row count).
      accumulate(values) -> update bounded accumulators from one chunk's values.
      finalize() -> a {value, terms, near_zero_vol, path_dependent, degenerate} result dict.
    A non-finite cell sets `bad` in accumulate (the in-memory non-finite guard, moved to chunk time)."""

    numeric = True
    path_dependent = False

    def __init__(self, binding, convention=None):
        self.binding = binding
        self.convention = convention
        self.bad = False
        self.n = 0
        self._init()

    def _init(self):
        pass

    def column(self, binding):
        return binding.get("value")

    def accumulate(self, values):
        raise NotImplementedError

    def _degenerate(self):
        return {"value": float("nan"), "terms": {}, "near_zero_vol": False,
                "path_dependent": self.path_dependent, "degenerate": True}

    def finalize(self):
        raise NotImplementedError


class SumReducer(StreamReducer):
    """column_sum: math.fsum(xs), NaN if any non-finite. Bit-identical via ExactSum."""

    def _init(self):
        self.acc = ExactSum()

    def accumulate(self, values):
        for v in values:
            if not _finite(v):
                self.bad = True
                return
            self.acc.add(v)
        self.n += len(values)

    def finalize(self):
        if self.bad:
            return self._degenerate()
        return {"value": self.acc.result(), "terms": {"n": self.n},
                "near_zero_vol": False, "path_dependent": False, "degenerate": False}


class MeanReducer(StreamReducer):
    """column_mean: math.fsum(xs)/len(xs). Bit-identical via ExactSum + an exact integer count."""

    def _init(self):
        self.acc = ExactSum()

    def accumulate(self, values):
        for v in values:
            if not _finite(v):
                self.bad = True
                return
            self.acc.add(v)
        self.n += len(values)

    def finalize(self):
        if self.bad or self.n == 0:
            return self._degenerate()
        return {"value": self.acc.result() / self.n, "terms": {"n": self.n},
                "near_zero_vol": False, "path_dependent": False, "degenerate": False}


class CountReducer(StreamReducer):
    """row_count: len(rows). Reads no numeric column (counts any projected column's cells)."""

    numeric = False

    def column(self, binding):
        return binding.get("column")        # may be None -> _run_streaming uses any column

    def accumulate(self, values):
        self.n += len(values)

    def finalize(self):
        return {"value": float(self.n), "terms": {"column": self.binding.get("column")},
                "near_zero_vol": False, "path_dependent": False, "degenerate": False}


class MaxDrawdownReducer(StreamReducer):
    """max_drawdown: worst peak-to-trough on the cumulative-equity curve. Already a single-pass online fold
    (eq/peak/mdd carried scalars) -> bit-identical when chunk order == row order (guaranteed by file-order
    row-groups / CSV line order). path_dependent like the in-memory recipe."""

    path_dependent = True

    def column(self, binding):
        return binding.get("return")

    def _init(self):
        self.eq = 1.0
        self.peak = 1.0
        self.mdd = 0.0

    def accumulate(self, values):
        for r in values:
            if not _finite(r):
                self.bad = True
                return
            self.eq *= (1.0 + r)
            if self.eq > self.peak:
                self.peak = self.eq
            dd = self.eq / self.peak - 1.0
            if dd < self.mdd:
                self.mdd = dd
        self.n += len(values)

    def finalize(self):
        if self.bad:
            return self._degenerate()
        return {"value": self.mdd, "terms": {"n": self.n},
                "near_zero_vol": False, "path_dependent": True, "degenerate": False}


# the reducer registry: a recipe's manifest `streaming={"reducer": "<name>"}` names one of these.
REDUCERS = {
    "SumReducer": SumReducer,
    "MeanReducer": MeanReducer,
    "CountReducer": CountReducer,
    "MaxDrawdownReducer": MaxDrawdownReducer,
}
