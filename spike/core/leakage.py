"""calma.spike.core.leakage — verify the DATA, not just the number (the validity moat, rebuild guide §4.6).

A metric can be computed perfectly yet be INVALID because the evaluation leaked: rows (or, for sequences,
near-duplicates / homologs) shared between train and test. This catches the failure that recompute alone
cannot — a 0.95 AUROC that re-runs and recomputes to 0.95 but is meaningless because the test set leaked.

Two detectors:
  - exact_overlap   : duplicate-row leakage — test rows that appear verbatim in train.
  - homology_overlap: near-duplicate / homology leakage — test items whose k-mer Jaccard to a train item
                      exceeds a threshold. This is the genomics failure (rankings invert under homology
                      leakage); k-mer shingling is sequence-agnostic and pure-stdlib.

Pure-stdlib. `check_leakage` returns findings the validity layer turns into INVALIDATED when the claim
asserts a held-out / out-of-sample result. The scale path (LSH index) replaces the sampled O(n·m) homology
scan; the math here is the same.
"""
from __future__ import annotations


def _canon(row) -> str:
    if isinstance(row, (list, tuple)):
        return "|".join(str(c).strip() for c in row)
    return str(row).strip()


def exact_overlap(train_rows, test_rows) -> dict:
    """Fraction of test rows that appear EXACTLY in train (duplicate-row leakage)."""
    train = {_canon(r) for r in train_rows}
    if not test_rows:
        return {"overlap_frac": 0.0, "n_overlap": 0, "n_test": 0}
    n = sum(1 for r in test_rows if _canon(r) in train)
    return {"overlap_frac": n / len(test_rows), "n_overlap": n, "n_test": len(test_rows)}


def _kmers(s, k: int) -> set:
    s = str(s).strip()
    return {s[i:i + k] for i in range(len(s) - k + 1)} if len(s) >= k else {s}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def homology_overlap(train_seqs, test_seqs, k: int = 6, sim: float = 0.8, sample: int = 200) -> dict:
    """Fraction of (sampled) test sequences with a train sequence of k-mer Jaccard >= sim — near-duplicate /
    homology leakage. Sampled to stay cheap (O(sample · |train|)); an LSH index is the scale path."""
    train_k = [_kmers(s, k) for s in train_seqs]
    test = test_seqs[:sample] if len(test_seqs) > sample else list(test_seqs)
    if not test or not train_k:
        return {"overlap_frac": 0.0, "n_overlap": 0, "n_sampled": len(test), "k": k, "sim": sim}
    n = 0
    for ts in test:
        tk = _kmers(ts, k)
        if any(_jaccard(tk, trk) >= sim for trk in train_k):
            n += 1
    return {"overlap_frac": n / len(test), "n_overlap": n, "n_sampled": len(test), "k": k, "sim": sim}


def check_leakage(train, test, *, sequences: bool = False, exact_thresh: float = 0.01,
                  homology_thresh: float = 0.05) -> list[dict]:
    """Return leakage findings (possibly empty). Exact-row overlap always; homology overlap when the data is
    sequences. Each finding is invalidating IF the claim asserts a held-out result (the validity layer gates
    that)."""
    findings = []
    ex = exact_overlap(train, test)
    if ex["overlap_frac"] >= exact_thresh:
        findings.append({
            "kind": "duplicate-row leakage", "invalidating": True, "magnitude": ex["overlap_frac"],
            "detail": "%d of %d test rows (%.1f%%) appear verbatim in train — the held-out evaluation is "
                      "contaminated" % (ex["n_overlap"], ex["n_test"], 100 * ex["overlap_frac"])})
    if sequences:
        ho = homology_overlap(train, test)
        if ho["overlap_frac"] >= homology_thresh:
            findings.append({
                "kind": "homology leakage", "invalidating": True, "magnitude": ho["overlap_frac"],
                "detail": "%d of %d sampled test sequences (%.1f%%) are near-duplicates of a train sequence "
                          "(k-mer Jaccard ≥ %.2f, k=%d) — the held-out evaluation is contaminated by homology"
                          % (ho["n_overlap"], ho["n_sampled"], 100 * ho["overlap_frac"], ho["sim"], ho["k"])})
    return findings
