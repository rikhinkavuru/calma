"""The repo's own correlation — it computes a SPEARMAN rank correlation but the README just calls it
'correlation'. Calma's default recompute is Pearson, which disagrees; the correlation TYPE-search
(pearson/spearman/kendall) reproduces it under 'spearman' → CONFIRMED (guide §B.2 correlation-type)."""
import math


def _ranks(a):
    order = sorted(range(len(a)), key=lambda i: a[i])
    r = [0.0] * len(a)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and a[order[j + 1]] == a[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def compute_correlation(x, y):
    rx, ry = _ranks(x), _ranks(y)      # Spearman = Pearson of the rank variables
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return cov / (sx * sy)
