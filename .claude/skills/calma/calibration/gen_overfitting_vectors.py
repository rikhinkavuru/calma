"""Generate frozen reference vectors for the WS2 overfitting kernels (Deflated Sharpe Ratio + PBO via
CSCV) from a PAPER-FAITHFUL scipy/numpy reference. Run ONCE in a pinned throwaway venv; the output
(assets/overfitting_reference_vectors.json + .manifest.json) is committed and CI validates the pure-
stdlib kernels against it with NO third-party imports.

These vectors live in their OWN file (not the recipe library's reference_vectors.json) so the overfitting
freeze never touches the parallel recipe session's generator/vectors.

Trust chain (each link asserted before any vector is minted):
  constructed-truth / analytic anchors  ->  scipy/numpy from-paper reference (must reproduce them)  ->
  pure-stdlib kernel (bit-close, rel-tol 1e-9, validated in tests).

Usage (pinned venv with numpy + scipy):
    /tmp/calma_calib_venv/bin/python gen_overfitting_vectors.py
"""
import hashlib
import itertools
import json
import math
import os
import sys

import numpy as np
from scipy import special, stats

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "overfitting_reference_vectors.json")
MANIFEST = OUT.replace(".json", ".manifest.json")
PBO_NOISE_SEED = 7919  # pinned; the CSCV enumeration is deterministic, only the matrix draw is random
_G = 0.5772156649015328606  # Euler-Mascheroni


# ---- the from-paper reference (scipy/numpy), independent of the stdlib kernel ----

def ref_expected_max_sharpe(n_trials, var_sr):
    return math.sqrt(var_sr) * ((1.0 - _G) * float(special.ndtri(1.0 - 1.0 / n_trials))
                                + _G * float(special.ndtri(1.0 - 1.0 / (n_trials * math.e))))


def ref_dsr(sr, n_obs, skew, kurt_excess, n_trials, var_sr):
    sr0 = ref_expected_max_sharpe(n_trials, var_sr)
    denom = 1.0 - skew * sr + (kurt_excess + 2.0) / 4.0 * sr * sr
    return float(stats.norm.cdf((sr - sr0) * math.sqrt(n_obs - 1.0) / math.sqrt(denom)))


def ref_pbo(matrix, n_splits):
    A = np.asarray(matrix, dtype=float)
    T, Nc = A.shape
    bs = T // n_splits
    blocks = [A[i * bs:(i + 1) * bs] for i in range(n_splits)]
    below = total = 0
    for combo in itertools.combinations(range(n_splits), n_splits // 2):
        cs = set(combo)
        IS = np.vstack([blocks[b] for b in range(n_splits) if b in cs])
        OOS = np.vstack([blocks[b] for b in range(n_splits) if b not in cs])
        issr = IS.mean(0) / IS.std(0, ddof=1)
        oossr = OOS.mean(0) / OOS.std(0, ddof=1)
        ns = int(np.argmax(issr))
        ov = oossr[ns]
        wins = sum(1.0 if ov > oossr[k] else 0.5 if ov == oossr[k] else 0.0 for k in range(Nc) if k != ns)
        total += 1
        if wins / (Nc - 1) <= 0.5:
            below += 1
    return below / total


# ---- constructed-truth matrices (analytic PBO) ----

def _noise(n):
    return [0.001 * ((i % 3) - 1) for i in range(n)]


def m_always_overfit():
    nz = _noise(10)
    b0 = [[1 + nz[i], nz[i]] for i in range(10)]
    b1 = [[nz[i], 1 + nz[i]] for i in range(10)]
    return b0 + b1, 2, 1.0  # IS-winner is the OOS-loser both ways -> PBO 1.0


def m_rank_preserving():
    return [[((i % 5) - 2) + 10 * j for j in range(3)] for i in range(24)], 4, 0.0


def m_exact_tie():
    nz = _noise(10)
    b0 = [[10 + nz[i], 1 + nz[i], 2 + nz[i], 3 + nz[i], 4 + nz[i]] for i in range(10)]
    b1 = [[2.5 + nz[i], 1 + nz[i], 2 + nz[i], 3 + nz[i], 4 + nz[i]] for i in range(10)]
    return b0 + b1, 2, 0.5  # one combo lands the IS-winner at w==0.5 exactly -> PBO 0.5 (pins <=)


def _lcg(seed, m):
    s = seed & ((1 << 64) - 1)
    out = []
    for _ in range(m):
        s = (s * 6364136223846793005 + 1442695040888963407) % (1 << 64)
        out.append((s >> 11) / float(1 << 53))
    return out


def m_noise(seed, T, S, Nc):
    flat = _lcg(seed * PBO_NOISE_SEED, T * Nc)
    return [[flat[i * Nc + j] for j in range(Nc)] for i in range(T)], S


def build_cases():
    cases = []

    # ---- gate the reference against constructed-truth BEFORE minting anything ----
    for fn in (m_always_overfit, m_rank_preserving, m_exact_tie):
        M, S, truth = fn()
        got = ref_pbo(M, S)
        assert got == truth, "reference PBO failed constructed-truth %s: got %r want %r" % (fn.__name__, got, truth)
    # DSR reference sanity: at sr == SR0 the probability is exactly 0.5
    _sr0 = ref_expected_max_sharpe(20, 0.04)
    assert abs(ref_dsr(_sr0, 500, 0.0, 0.0, 20, 0.04) - 0.5) < 1e-12, "reference DSR(sr==SR0) != 0.5"

    # ---- DSR cases: scipy-from-paper reference (dense + analytic-edge) ----
    dsr_inputs = [
        ("dsr_strong", 0.30, 1000, 0.0, 0.0, 10, 0.01),
        ("dsr_negskew_fattail", 0.05, 500, -0.5, 3.0, 100, 0.04),
        ("dsr_mid", 0.12, 250, 0.2, 1.0, 50, 0.02),
        ("dsr_deeptail_N1000", 0.02, 2000, -1.0, 5.0, 1000, 0.09),
        ("dsr_atbenchmark", round(ref_expected_max_sharpe(20, 0.04), 12), 500, 0.0, 0.0, 20, 0.04),
        ("dsr_small_n", 0.25, 30, 0.0, 0.0, 5, 0.05),
        ("dsr_highvar", 0.40, 800, 0.3, 2.0, 200, 0.16),
    ]
    for cid, sr, n, sk, ku, Nt, V in dsr_inputs:
        cases.append({"id": cid, "kind": "deflated_sharpe", "anchor": "scipy-from-paper",
                      "args": {"sr": sr, "n_obs": n, "skew": sk, "kurt_excess": ku, "n_trials": Nt, "var_sr": V},
                      "expected": ref_dsr(sr, n, sk, ku, Nt, V), "atol": 1e-9, "rtol": 1e-9})

    # ---- PBO cases: constructed-truth (analytic) ----
    for cid, (M, S, truth) in (("pbo_always_overfit", m_always_overfit()),
                               ("pbo_rank_preserving", m_rank_preserving()),
                               ("pbo_exact_tie", m_exact_tie())):
        cases.append({"id": cid, "kind": "pbo_cscv", "anchor": "constructed-truth",
                      "args": {"matrix": M, "n_splits": S}, "expected": truth, "atol": 0.0, "rtol": 0.0})

    # ---- PBO cases: seeded noise vs the numpy CSCV reference (matrices frozen in-args) ----
    for seed, T, S, Nc in ((101, 120, 8, 6), (202, 96, 6, 5), (303, 144, 12, 8), (404, 100, 10, 7)):
        M, S = m_noise(seed, T, S, Nc)
        cases.append({"id": "pbo_noise_seed%d" % seed, "kind": "pbo_cscv", "anchor": "numpy-cscv",
                      "args": {"matrix": M, "n_splits": S}, "expected": ref_pbo(M, S), "atol": 1e-12, "rtol": 1e-12})
    return cases


def main():
    cases = build_cases()
    blob = json.dumps(cases, sort_keys=True, separators=(",", ":")).encode()
    anchors = {}
    for c in cases:
        anchors[c["anchor"]] = anchors.get(c["anchor"], 0) + 1
    manifest = {
        "schema": "calma/overfitting-reference@1",
        "generated_with": {
            "python": sys.version.split()[0], "numpy": np.__version__,
            "scipy": __import__("scipy").__version__, "sklearn": __import__("sklearn").__version__,
        },
        "pbo_noise_seed": PBO_NOISE_SEED,
        "n_cases": len(cases),
        "anchors": anchors,
        "cases_sha256": hashlib.sha256(blob).hexdigest(),
        "note": ("Pure-stdlib kernels in numeric.py are validated against these frozen vectors at "
                 "rel-tol 1e-9; the reference libs are NEVER needed at run/CI time. Trust chain: "
                 "constructed-truth/analytic -> scipy/numpy from-paper reference (gated on reproducing "
                 "them) -> stdlib kernel. (Literal published worked-example numbers from Bailey-LdP 2014 "
                 "/ Bailey-Borwein-LdP-Zhu 2016 can be pinned additionally from the PDFs - the analytic "
                 "+ scipy-from-paper anchors here are the reproducible substitute.)"),
    }
    with open(OUT, "w") as fh:
        json.dump({"n_cases": len(cases), "cases": cases}, fh, indent=1)
    with open(MANIFEST, "w") as fh:
        json.dump(manifest, fh, indent=2)
    print("wrote %d overfitting cases -> %s" % (len(cases), os.path.abspath(OUT)))
    print("manifest -> %s" % os.path.abspath(MANIFEST))


if __name__ == "__main__":
    main()
