"""calma.spike.core.textmetrics — IR + NLP-generation metric kernels (guide §B.3).

Pure-stdlib, deterministic, first-principles — the trusted INDEPENDENT recompute for retrieval
(nDCG / MRR / recall@k / precision@k / MAP) and generation (BLEU / ROUGE-N / ROUGE-L). The knobs that make
these metrics convention-sensitive (nDCG gain/k; BLEU tokenization/smoothing/scale) are kwargs, searched by
core.conventions exactly like Sharpe's annualization — the same 'a discrete, standard, un-captured
convention' pattern (guide's unifying insight).

LEARNED / embedding metrics (BERTScore / BLEURT / COMET) are DELIBERATELY absent: there is no independent
recompute of a neural metric — reproducing it means re-running the same checkpoint, which is the thing under
test, not an independent oracle. They fail closed to REPRODUCED-ONLY (see catalog.LEARNED_METRICS). This is
the honest, FCR-safe verdict; it prevents dressing up a non-independent number as CONFIRMED.

These kernels are validated against sklearn (nDCG) + reference values (BLEU/ROUGE) in tests, and — best
effort — against sacrebleu / rouge-score / pytrec_eval when those libraries are installed. A subtly-wrong
kernel can only FAIL CLOSED (no convention reproduces the number → REPRODUCED-ONLY/INVALIDATED), never a
false CONFIRM; the coincidental-value fuzz gate covers the text/IR grids too.
"""
from __future__ import annotations

import math
import re
import string

_INF, _NINF = float("inf"), float("-inf")


def _result(value, degenerate=False, note="", **terms):
    v = float(value) if value is not None else float("nan")
    if not (v == v and v not in (_INF, _NINF)):
        degenerate = True
    return {"value": v, "degenerate": bool(degenerate), "note": note, "terms": terms}


def _degen(note):
    return {"value": float("nan"), "degenerate": True, "note": note, "terms": {}}


# ---- IR / ranking ---------------------------------------------------------------------------------
def _ranked_relevances(inputs):
    """Relevances in RANKED order. Accepts {relevances:[...]} (already ranked) or {y_true, y_score}
    (ranked by score desc, ties broken by original order — matches sklearn on distinct scores)."""
    rel = inputs.get("relevances", inputs.get("relevance", inputs.get("gains")))
    if rel is not None:
        try:
            return [float(r) for r in rel]
        except (TypeError, ValueError):
            return None
    yt = inputs.get("y_true", inputs.get("labels"))
    ys = inputs.get("y_score", inputs.get("scores", inputs.get("y_pred")))
    if yt is not None and ys is not None and len(yt) == len(ys):
        order = sorted(range(len(ys)), key=lambda i: (-ys[i], i))
        try:
            return [float(yt[i]) for i in order]
        except (TypeError, ValueError):
            return None
    return None


def _dcg(rels, k, gain):
    rels = rels[:k] if k else rels
    s = 0.0
    for i, r in enumerate(rels):
        g = r if gain == "linear" else (2.0 ** r - 1.0)
        s += g / math.log2(i + 2)
    return s


def ndcg(inputs, kwargs) -> dict:
    """Normalized DCG. Convention axes: gain ∈ {linear (Järvelin, == sklearn default), exponential (Burges,
    2^rel-1)} and cutoff k. == sklearn.metrics.ndcg_score on distinct scores."""
    rels = _ranked_relevances(inputs)
    if not rels:
        return _degen("nDCG needs relevances (or y_true + y_score)")
    k = kwargs.get("k")
    k = int(k) if k else None
    gain = str(kwargs.get("gain", "linear"))
    idcg = _dcg(sorted(rels, reverse=True), k, gain)
    if idcg <= 0:
        return _degen("ideal DCG is zero (no positive relevance) — nDCG undefined")
    return _result(_dcg(rels, k, gain) / idcg, k=k, gain=gain)


def _binary_ranked(inputs):
    rels = _ranked_relevances(inputs)
    if rels is None:
        return None
    return [1 if r > 0 else 0 for r in rels]


def mrr(inputs, kwargs) -> dict:
    """Mean reciprocal rank. Single ranking → reciprocal rank of the first relevant; {ranks:[...]} (first-
    relevant rank per query) → mean(1/rank)."""
    ranks = inputs.get("ranks")
    if ranks is not None:
        try:
            rr = [1.0 / int(r) for r in ranks if int(r) > 0]
        except (TypeError, ValueError, ZeroDivisionError):
            return _degen("bad ranks")
        if not rr:
            return _degen("no positive ranks")
        return _result(sum(rr) / len(ranks), n_queries=len(ranks))
    rels = _binary_ranked(inputs)
    if rels is None:
        return _degen("MRR needs a ranked relevance list or {ranks:[...]}")
    for i, r in enumerate(rels):
        if r:
            return _result(1.0 / (i + 1), rank=i + 1)
    return _result(0.0, note="no relevant item in the ranking")


def _k_of(inputs, kwargs, n):
    k = kwargs.get("k")
    return int(k) if k else n


def recall_at_k(inputs, kwargs) -> dict:
    rels = _binary_ranked(inputs)
    if rels is None:
        return _degen("recall@k needs a ranked relevance list")
    total = sum(rels)
    if total == 0:
        return _degen("no relevant items — recall undefined")
    k = _k_of(inputs, kwargs, len(rels))
    return _result(sum(rels[:k]) / total, k=k, total_relevant=total)


def precision_at_k(inputs, kwargs) -> dict:
    rels = _binary_ranked(inputs)
    if rels is None:
        return _degen("precision@k needs a ranked relevance list")
    k = _k_of(inputs, kwargs, len(rels))
    if k <= 0:
        return _degen("k must be positive")
    return _result(sum(rels[:k]) / k, k=k)


def hit_at_k(inputs, kwargs) -> dict:
    rels = _binary_ranked(inputs)
    if rels is None:
        return _degen("hit@k needs a ranked relevance list")
    k = _k_of(inputs, kwargs, len(rels))
    return _result(1.0 if any(rels[:k]) else 0.0, k=k)


def average_precision(inputs, kwargs) -> dict:
    """Average precision of a single ranked list (mean of precision@k at each relevant position)."""
    rels = _binary_ranked(inputs)
    if rels is None:
        return _degen("average precision needs a ranked relevance list")
    total = sum(rels)
    if total == 0:
        return _degen("no relevant items")
    hits = 0
    s = 0.0
    for i, r in enumerate(rels):
        if r:
            hits += 1
            s += hits / (i + 1)
    return _result(s / total, n_relevant=total)


# ---- NLP generation: BLEU / ROUGE -----------------------------------------------------------------
_PUNCT_RE = re.compile(r"([" + re.escape(string.punctuation) + r"])")


def _tokenize(text, mode, lower):
    if isinstance(text, (list, tuple)):
        return [str(t) for t in text]
    s = str(text)
    if lower:
        s = s.lower()
    if mode == "char":
        return list(s.replace(" ", ""))
    if mode in ("13a", "intl"):
        s = _PUNCT_RE.sub(r" \1 ", s)
        return s.split()
    return s.split()                                       # 'none' / whitespace


def _ngrams(toks, n):
    d: dict = {}
    for i in range(len(toks) - n + 1):
        g = tuple(toks[i:i + n])
        d[g] = d.get(g, 0) + 1
    return d


def _as_sentences(cand, refs):
    """Normalize (candidate, references) to corpus form: [cand_tokens...], [[ref_tokens...]...].
    Accepts a single hyp string / a list of hyp strings; refs as a string, list of strings, or list-of-lists."""
    cands = cand if (isinstance(cand, list) and cand and isinstance(cand[0], (str, list))) else [cand]
    # references: align to candidates. A single hypothesis with multiple string refs is one group.
    if len(cands) == 1:
        rl = refs if isinstance(refs, list) else [refs]
        # a list of token-lists vs a list of strings both fine; a single string wrapped above
        refs_list = [rl]
    else:
        refs_list = [r if isinstance(r, list) else [r] for r in refs]
    return cands, refs_list


def _bleu_corpus(cand_tok, refs_tok, max_order, smooth):
    matches = [0] * max_order
    totals = [0] * max_order
    cand_len = ref_len = 0
    for cand, refs in zip(cand_tok, refs_tok):
        cand_len += len(cand)
        ref_len += min((len(r) for r in refs), key=lambda rl, cl=len(cand): (abs(rl - cl), rl))
        for n in range(1, max_order + 1):
            cc = _ngrams(cand, n)
            maxref: dict = {}
            for r in refs:
                for g, c in _ngrams(r, n).items():
                    if c > maxref.get(g, 0):
                        maxref[g] = c
            for g, c in cc.items():
                matches[n - 1] += min(c, maxref.get(g, 0))
                totals[n - 1] += c
    precisions = []
    invcnt = 1
    for n in range(max_order):
        m, t = matches[n], totals[n]
        if smooth in ("add1", "add-k"):
            precisions.append((m + 1.0) / (t + 1.0) if t + 1.0 > 0 else 0.0)
        elif smooth == "exp" and m == 0 and t > 0:          # Chen & Cherry method 3 (exponential decay)
            invcnt *= 2
            precisions.append(1.0 / (invcnt * t))
        elif smooth == "floor" and m == 0:
            precisions.append(1e-9)
        elif t == 0:
            precisions.append(0.0)
        else:
            precisions.append(m / t)
    if min(precisions) <= 0:
        geo = 0.0
    else:
        geo = math.exp(sum(math.log(p) for p in precisions) / max_order)
    if cand_len == 0:
        bp = 0.0
    elif cand_len > ref_len:
        bp = 1.0
    else:
        bp = math.exp(1.0 - ref_len / cand_len)
    return bp * geo


def bleu(inputs, kwargs) -> dict:
    """Corpus/sentence BLEU (Papineni). Convention axes: tokenize ∈ {none, 13a, char}, smooth ∈ {none, exp,
    floor, add1}, scale ∈ {unit (0-1), percent (0-100)}. sacreBLEU emits 0-100; nltk/HF emit 0-1 — the scale
    axis reconciles the 100× mismatch that would otherwise masquerade as REFUTED."""
    cand = inputs.get("candidate", inputs.get("hypothesis", inputs.get("prediction",
                      inputs.get("predictions", inputs.get("hypotheses")))))
    refs = inputs.get("references", inputs.get("reference", inputs.get("refs", inputs.get("targets"))))
    if cand is None or refs is None:
        return _degen("BLEU needs candidate + references (text)")
    max_order = int(kwargs.get("max_order", 4))
    smooth = str(kwargs.get("smooth", "none"))
    tok = str(kwargs.get("tokenize", "none"))
    lower = bool(kwargs.get("lowercase", False))
    scale = str(kwargs.get("scale", "unit"))
    try:
        cands, refs_list = _as_sentences(cand, refs)
        cand_tok = [_tokenize(c, tok, lower) for c in cands]
        refs_tok = [[_tokenize(r, tok, lower) for r in group] for group in refs_list]
    except Exception as e:  # noqa: BLE001
        return _degen("BLEU tokenization failed: %s" % e)
    if any(len(c) == 0 for c in cand_tok):
        return _degen("empty candidate")
    val = _bleu_corpus(cand_tok, refs_tok, max_order, smooth)
    if scale == "percent":
        val *= 100.0
    return _result(val, tokenize=tok, smooth=smooth, scale=scale, max_order=max_order)


def _lcs(a, b):
    """Longest common subsequence length (for ROUGE-L)."""
    m, n = len(a), len(b)
    if m == 0 or n == 0:
        return 0
    prev = [0] * (n + 1)
    for i in range(1, m + 1):
        cur = [0] * (n + 1)
        ai = a[i - 1]
        for j in range(1, n + 1):
            cur[j] = prev[j - 1] + 1 if ai == b[j - 1] else (prev[j] if prev[j] >= cur[j - 1] else cur[j - 1])
        prev = cur
    return prev[n]


def _rouge_n(inputs, kwargs, n):
    cand = inputs.get("candidate", inputs.get("hypothesis", inputs.get("prediction", inputs.get("predictions"))))
    refs = inputs.get("references", inputs.get("reference", inputs.get("refs")))
    if cand is None or refs is None:
        return _degen("ROUGE needs candidate + reference (text)")
    lower = bool(kwargs.get("lowercase", True))
    tok = str(kwargs.get("tokenize", "none"))
    ref = refs[0] if (isinstance(refs, list) and refs and isinstance(refs[0], (list, str))) else refs
    c = _tokenize(cand, tok, lower)
    r = _tokenize(ref, tok, lower)
    cc, rc = _ngrams(c, n), _ngrams(r, n)
    overlap = sum(min(v, cc.get(g, 0)) for g, v in rc.items())
    c_total = sum(cc.values())
    r_total = sum(rc.values())
    if c_total == 0 or r_total == 0:
        return _degen("empty n-grams")
    prec = overlap / c_total
    rec = overlap / r_total
    variant = str(kwargs.get("score", "f"))
    if variant == "precision":
        val = prec
    elif variant == "recall":
        val = rec
    else:
        val = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
    return _result(val, precision=prec, recall=rec, n=n)


def rouge1(inputs, kwargs) -> dict:
    return _rouge_n(inputs, kwargs, 1)


def rouge2(inputs, kwargs) -> dict:
    return _rouge_n(inputs, kwargs, 2)


def rouge_l(inputs, kwargs) -> dict:
    """ROUGE-L (LCS-based F-measure), default beta=1.2 like the reference ROUGE-1.5.5 / rouge-score."""
    cand = inputs.get("candidate", inputs.get("hypothesis", inputs.get("prediction", inputs.get("predictions"))))
    refs = inputs.get("references", inputs.get("reference", inputs.get("refs")))
    if cand is None or refs is None:
        return _degen("ROUGE-L needs candidate + reference (text)")
    lower = bool(kwargs.get("lowercase", True))
    tok = str(kwargs.get("tokenize", "none"))
    ref = refs[0] if (isinstance(refs, list) and refs and isinstance(refs[0], (list, str))) else refs
    c = _tokenize(cand, tok, lower)
    r = _tokenize(ref, tok, lower)
    if not c or not r:
        return _degen("empty sequence")
    lcs = _lcs(c, r)
    prec = lcs / len(c)
    rec = lcs / len(r)
    variant = str(kwargs.get("score", "f"))
    if variant == "precision":
        val = prec
    elif variant == "recall":
        val = rec
    else:
        val = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
    return _result(val, precision=prec, recall=rec)


# ---- registry (merged into catalog) ---------------------------------------------------------------
TEXT_CATALOG = {
    "ndcg": ndcg, "mrr": mrr, "recall_at_k": recall_at_k, "precision_at_k": precision_at_k,
    "hit_at_k": hit_at_k, "average_precision": average_precision,
    "bleu": bleu, "rouge1": rouge1, "rouge2": rouge2, "rouge_l": rouge_l,
}

TEXT_ALIASES = {
    "ndcg_score": "ndcg", "ndcg@k": "ndcg", "ndcg@10": "ndcg", "normalized_dcg": "ndcg",
    "mean_reciprocal_rank": "mrr", "reciprocal_rank": "mrr",
    "recall@k": "recall_at_k", "recall_at": "recall_at_k", "recall@10": "recall_at_k",
    "precision@k": "precision_at_k", "precision_at": "precision_at_k",
    "hit@k": "hit_at_k", "hit_rate": "hit_at_k", "hits@k": "hit_at_k",
    "map": "average_precision", "mean_average_precision": "average_precision", "ap": "average_precision",
    "average_precision_score": "average_precision",
    "bleu_score": "bleu", "sacrebleu": "bleu", "sentence_bleu": "bleu", "corpus_bleu": "bleu",
    "rouge-1": "rouge1", "rouge_1": "rouge1", "rouge-2": "rouge2", "rouge_2": "rouge2",
    "rougel": "rouge_l", "rouge-l": "rouge_l", "rougelsum": "rouge_l",
}

# LEARNED / embedding metrics: no INDEPENDENT recompute exists (recompute == re-running the same neural
# checkpoint). Fail closed to REPRODUCED-ONLY with an honest note. (guide §B.3 (c))
LEARNED_METRICS = {
    "bertscore": "BERTScore", "bert_score": "BERTScore", "bertscore_f1": "BERTScore",
    "bleurt": "BLEURT", "comet": "COMET", "comet_score": "COMET", "moverscore": "MoverScore",
    "bartscore": "BARTScore", "prism": "Prism", "unieval": "UniEval", "gptscore": "GPTScore",
}


def learned_metric(name: str) -> str | None:
    """Return the display name if `name` is a learned/embedding metric (no independent recompute), else None."""
    if not name:
        return None
    return LEARNED_METRICS.get(name.strip().lower().replace(" ", "_").replace("-", "_"))
