"""The repo's own nDCG — EXPONENTIAL-gain (Burges: 2^rel-1), a standard-but-non-default convention. Calma's
default recompute is linear-gain (Järvelin); the nDCG convention search (gain × k) reproduces this → CONFIRMED."""
import math


def compute_ndcg(relevances):
    def dcg(rels):
        return sum((2 ** r - 1) / math.log2(i + 2) for i, r in enumerate(rels))
    ideal = dcg(sorted(relevances, reverse=True))
    return dcg(relevances) / ideal if ideal else 0.0
