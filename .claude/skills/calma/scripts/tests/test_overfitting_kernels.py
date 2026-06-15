"""Tests for the WS2 overfitting kernels in numeric.py: normal CDF, Probabilistic / Deflated Sharpe
Ratio (Bailey-Lopez de Prado 2014), and PBO via CSCV (Bailey-Borwein-LdP-Zhu 2016). Validated here
against ANALYTIC + CONSTRUCTED-TRUTH anchors (no third-party deps). The dense bit-close validation vs a
paper-gated scipy reference lands with the frozen reference vectors (calibration step). Pure stdlib.
Run: python3 test_overfitting_kernels.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numeric as N  # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def isnan(x):
    return isinstance(x, float) and x != x


# ---- normal_cdf (built on the suite-validated derfc) ----
truth(abs(N.normal_cdf(0.0) - 0.5) < 1e-15, "Phi(0) == 0.5")
truth(abs(N.normal_cdf(1.96) - 0.9750021048517795) < 1e-9, "Phi(1.96) matches the known quantile")
truth(abs(N.normal_cdf(-1.96) - 0.0249978951482205) < 1e-9, "Phi(-1.96) matches")
truth(all(abs((N.normal_cdf(x) + N.normal_cdf(-x)) - 1.0) < 1e-12 for x in (0.3, 1.0, 2.5, 4.0)),
      "Phi(x) + Phi(-x) == 1 (symmetry)")

# ---- expected_max_sharpe ----
truth(N.expected_max_sharpe(1, 0.5) == 0.0, "a single trial has no multiple-testing inflation (SR0=0)")
_ems = [N.expected_max_sharpe(n, 1.0) for n in (2, 10, 100, 1000)]
truth(all(b > a for a, b in zip(_ems, _ems[1:])) and _ems[0] > 0, "E[max SR] strictly increases with N")
truth(isnan(N.expected_max_sharpe(10, -1.0)) and isnan(N.expected_max_sharpe(0, 1.0)),
      "degenerate var_sr / N -> NaN")
# scales with sqrt(var_sr)
truth(abs(N.expected_max_sharpe(50, 4.0) - 2.0 * N.expected_max_sharpe(50, 1.0)) < 1e-12,
      "E[max SR] scales with sqrt(var_sr)")

# ---- PSR ----
truth(abs(N.probabilistic_sharpe_ratio_vs(0.1, 0.1, 250, 0.0, 0.0) - 0.5) < 1e-12,
      "PSR(sr == benchmark) == 0.5")
truth(N.probabilistic_sharpe_ratio_vs(0.2, 0.0, 250, 0.0, 0.0) > 0.5, "PSR rises when sr > benchmark")
truth(N.probabilistic_sharpe_ratio_vs(0.0, 0.2, 250, 0.0, 0.0) < 0.5, "PSR falls when sr < benchmark")
truth(isnan(N.probabilistic_sharpe_ratio_vs(0.1, 0.0, 1, 0.0, 0.0)), "PSR with n_obs<=1 -> NaN")
# negative skew + fat tails inflate the variance term -> a lower PSR for the same sr
truth(N.probabilistic_sharpe_ratio_vs(0.15, 0.0, 250, -1.0, 5.0)
      < N.probabilistic_sharpe_ratio_vs(0.15, 0.0, 250, 0.0, 0.0),
      "negative skew / excess kurtosis lowers PSR (the higher-moment correction bites)")

# ---- DSR ----
truth(N.deflated_sharpe_ratio(0.30, 1000, 0.0, 0.0, 10, 0.01) > 0.99,
      "an edge far above the deflated benchmark -> DSR ~ 1")
truth(N.deflated_sharpe_ratio(0.02, 1000, 0.0, 0.0, 1000, 0.04) < 0.5,
      "an edge below the multiple-testing-deflated benchmark -> DSR < 0.5")
# DSR is exactly PSR evaluated at the expected-max-Sharpe benchmark
_sr0 = N.expected_max_sharpe(20, 0.02)
truth(abs(N.deflated_sharpe_ratio(0.12, 500, 0.1, 1.0, 20, 0.02)
          - N.probabilistic_sharpe_ratio_vs(0.12, _sr0, 500, 0.1, 1.0)) < 1e-15,
      "DSR == PSR(SR0): the deflation is exactly the expected-max-Sharpe benchmark")
# more trials -> a higher benchmark -> a lower DSR for the same realised track
truth(N.deflated_sharpe_ratio(0.12, 500, 0.0, 0.0, 5, 0.02)
      > N.deflated_sharpe_ratio(0.12, 500, 0.0, 0.0, 500, 0.02),
      "more trials deflate harder (DSR decreases in N)")


# ---- PBO via CSCV: constructed-truth anchors ----
# always-overfit: block0 favours col0, block1 favours col1 -> the IS winner is the OOS loser, both ways
_b0 = [[1 + 0.01 * ((i % 3) - 1), 0.01 * ((i % 3) - 1)] for i in range(10)]
_b1 = [[0.01 * ((i % 3) - 1), 1 + 0.01 * ((i % 3) - 1)] for i in range(10)]
truth(N.pbo_cscv(_b0 + _b1, 2) == 1.0, "always-overfit matrix -> PBO == 1.0 (exact)")
# rank-preserving: every column uniformly shifted by 10*j -> IS-best == OOS-best on every split
_rp = [[((i % 5) - 2) + 10 * j for j in range(3)] for i in range(24)]
truth(N.pbo_cscv(_rp, 4) == 0.0, "rank-preserving matrix -> PBO == 0.0 (exact)")
# symmetric noise: a single realisation scatters, but the MEAN over many realisations -> ~0.5
def _lcg(seed, m):
    s = seed & ((1 << 64) - 1)
    out = []
    for _ in range(m):
        s = (s * 6364136223846793005 + 1442695040888963407) % (1 << 64)
        out.append((s >> 11) / float(1 << 53))
    return out


_T, _S, _Nc = 100, 8, 6
_vals = []
for _seed in range(1, 201):
    _flat = _lcg(_seed * 7919, _T * _Nc)
    _M = [[_flat[i * _Nc + j] for j in range(_Nc)] for i in range(_T)]
    _vals.append(N.pbo_cscv(_M, _S))
_mean = sum(_vals) / len(_vals)
truth(abs(_mean - 0.5) < 0.05, "symmetric noise -> mean PBO ~ 0.5 over 200 realisations (got %.4f)" % _mean)
truth(all(0.0 <= v <= 1.0 for v in _vals), "every PBO is a probability in [0,1]")
# degenerate guards
truth(isnan(N.pbo_cscv(_rp, 3)), "odd n_splits -> NaN")
truth(isnan(N.pbo_cscv(_rp[:2], 4)), "T < n_splits -> NaN")
truth(isnan(N.pbo_cscv([[1.0]] * 20, 4)), "single strategy (N<2) -> NaN")
# determinism: identical inputs -> identical output (bit-stable, no RNG)
truth(N.pbo_cscv(_b0 + _b1, 2) == N.pbo_cscv(_b0 + _b1, 2), "PBO is deterministic")

print("overfitting_kernels: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
