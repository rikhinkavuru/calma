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

import os


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


def homology_overlap(train_seqs, test_seqs, k: int = 6, sim: float = 0.8, sample: int = 300,
                     max_candidates: int = 25) -> dict:
    """Fraction of (sampled) test sequences with a train sequence of k-mer Jaccard >= sim — near-duplicate /
    homology leakage. An inverted k-mer index makes this scale: each test sequence is compared only to the
    train sequences that share the most k-mers (true homologs are top candidates; random pairs share ~none),
    not to all of train. O(index build + sample · candidates) instead of O(sample · |train|)."""
    train_k = [_kmers(s, k) for s in train_seqs]
    index: dict = {}
    for ti, ks in enumerate(train_k):
        for km in ks:
            index.setdefault(km, []).append(ti)
    test = test_seqs[:sample] if len(test_seqs) > sample else list(test_seqs)
    if not test or not train_k:
        return {"overlap_frac": 0.0, "n_overlap": 0, "n_sampled": len(test), "k": k, "sim": sim}
    n = 0
    for ts in test:
        tk = _kmers(ts, k)
        cand: dict = {}
        for km in tk:
            for ti in index.get(km, ()):
                cand[ti] = cand.get(ti, 0) + 1
        for ti in sorted(cand, key=cand.get, reverse=True)[:max_candidates]:   # most-shared k-mers first
            if _jaccard(tk, train_k[ti]) >= sim:
                n += 1
                break
    return {"overlap_frac": n / len(test), "n_overlap": n, "n_sampled": len(test), "k": k, "sim": sim}


_SEQ_COLS = ("sequence", "seq", "sequences", "text", "smiles", "peptide", "dna", "rna", "x", "input")
_LABEL_COLS = ("label", "target", "y", "class", "id", "index", "split")


def _seq_column(header):
    low = [h.strip().lower() for h in header]
    for name in _SEQ_COLS:
        if name in low:
            return low.index(name)
    for i, h in enumerate(header):                 # else the first non-label column
        if h.strip().lower() not in _LABEL_COLS:
            return i
    return 0 if header else None


def _read_seq_col(path, cap=200000):
    import csv
    try:
        with open(path, newline="", errors="replace") as fh:
            rd = csv.reader(fh)
            header = next(rd, None)
            if not header:
                return []
            idx = _seq_column(header)
            out = []
            for i, row in enumerate(rd):
                if i >= cap:
                    break
                if len(row) > idx:
                    out.append(row[idx])
            return out
    except (OSError, csv.Error):
        return []


def _split_pairs(repo_dir):
    """Find <name>_train.csv / <name>_test.csv pairs anywhere in the repo (the committed-splits pattern)."""
    pairs = {}
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
        for fn in files:
            low = fn.lower()
            if not low.endswith(".csv"):
                continue
            for suf, role in (("_train.csv", "train"), ("_test.csv", "test"),
                              ("train.csv", "train"), ("test.csv", "test")):
                if low.endswith(suf):
                    name = (low[:-len(suf)].rstrip("_") or os.path.basename(root))
                    pairs.setdefault(name, {})[role] = os.path.join(root, fn)
                    break
    return {n: p for n, p in pairs.items() if "train" in p and "test" in p}


def _stride(xs, cap):
    """Deterministic subsample to <= cap via a stride (a bounded estimate; the leak magnitude is a lower
    bound under sampling — conservative). MinHash-LSH over the full set is the exact scale path."""
    if len(xs) <= cap:
        return xs
    step = max(1, len(xs) // cap)
    return xs[::step][:cap]


def from_committed_splits(repo_dir, max_pairs=20, train_cap=4000, test_cap=800):
    """Run leakage detection on a repo's COMMITTED train/test split files — no re-run. Returns a result per
    dataset {dataset, n_train, n_test, sampled, findings}. The cheap, data-only validity check; the magnitude
    is estimated on a bounded sample (a lower bound on the true leak)."""
    out = []
    for name, p in list(_split_pairs(repo_dir).items())[:max_pairs]:
        train, test = _read_seq_col(p["train"]), _read_seq_col(p["test"])
        if not train or not test:
            continue
        n_train, n_test = len(train), len(test)
        train, test = _stride(train, train_cap), _stride(test, test_cap)
        seqs = sum(1 for s in test[:50] if isinstance(s, str) and len(s) > 20
                   and s[:30].isalpha()) / max(1, len(test[:50])) > 0.5
        out.append({"dataset": name, "n_train": n_train, "n_test": n_test, "sequences": seqs,
                    "sampled": n_train > train_cap or n_test > test_cap,
                    "findings": check_leakage(train, test, sequences=seqs)})
    return out


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
