"""The repo's own BLEU — standard whitespace-tokenized, unsmoothed corpus BLEU-4, reported on the 0-100
scale (sacrebleu convention). Calma's default recompute is on the 0-1 scale; the BLEU convention search
(tokenize × smooth × scale) reproduces this under scale=percent → CONFIRMED (guide §B.3)."""
import math


def _ngrams(toks, n):
    d = {}
    for i in range(len(toks) - n + 1):
        g = tuple(toks[i:i + n])
        d[g] = d.get(g, 0) + 1
    return d


def compute_bleu(candidate, reference):
    c, r = candidate.split(), reference.split()
    precs = []
    for n in range(1, 5):
        cc, rc = _ngrams(c, n), _ngrams(r, n)
        m = sum(min(v, rc.get(g, 0)) for g, v in cc.items())
        t = sum(cc.values())
        precs.append(m / t if t else 0.0)
    geo = 0.0 if min(precs) <= 0 else math.exp(sum(math.log(p) for p in precs) / 4)
    bp = 1.0 if len(c) > len(r) else (math.exp(1 - len(r) / len(c)) if c else 0.0)
    return bp * geo * 100.0                              # 0-100 scale
