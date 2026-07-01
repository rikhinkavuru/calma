"""calma.spike.core.conventions — the bounded, CITED convention registry (guide §B.2).

Convention-sensitive metrics recompute to DIFFERENT values under different *standard* conventions: Sharpe
(annualization √periods_per_year, sample-vs-population stdev via ddof), Sortino (downside-denominator),
stdev/variance (ddof), correlation (pearson/spearman/kendall type). The repo's convention lives in its own
code (`* np.sqrt(252)`, `np.std` default ddof=0) and isn't captured, so a single-convention recompute
falsely disagrees with a *correct* number. `search()` tries a small grid of recognized conventions against
the REAL captured inputs; if one reproduces the produced value at the SAME tight tolerance as a normal
confirm, that IS the recompute — the number is a valid metric, not cheating.

The danger is entirely GRID GROWTH: every convention added is another chance for a fabricated/buggy number
to coincidentally match. So the registry is a HARD CONTRACT, enforced by tests (tests/test_conventions.py):

  1. Documented-standard only — every axis carries a citation (`sources`). If it isn't in a reference, it
     doesn't go in the grid.
  2. Size cap — len(grid) <= max_grid (~24). A large grid is a curve-fitter; the FCR argument only holds
     for a small set.
  3. No free continuous parameters — search only over discrete, semantically-meaningful settings
     (ppy=252 vs 12; ddof 0 vs 1). A continuous risk_free/target/scale could fit almost any number, so those
     are `forbidden_free_params` and NEVER a grid axis — they come from captured kwargs.
  4. Tight tolerance — the match uses the SAME confirm tolerance as a normal three-way confirm (injected).
  5. Gated on prior reproduction — diff.py only calls search() after produced ≈ claim and the DEFAULT
     recompute disagrees. It rescues 'this real runtime number is a legit metric under a standard
     convention', never blesses an arbitrary value.
  6. Ambiguity guard — every grid cell that matches necessarily equals `produced` to tolerance, so multiple
     matches agree on the value (safe); a value reproducible under NO standard cell is refused (fail closed).
  7. Audit surface — a confirm reached via search reports the matched convention as a first-class field
     (`convention` + a human note), never a bare CONFIRMED.
  8. Coincidental-value fuzz test — the standing FCR proof: random fabricated values against random inputs
     must match NO grid beyond the tolerance base rate (tests/test_conventions.py + optimize/convention_fuzz.py).

Pure-stdlib. `search()` is GENERIC over the recompute callable, so the SAME code path serves catalog metrics
(Sharpe/Sortino/...), and — in guide §B.3 — IR (nDCG variant + k) and NLP (tokenization + smoothing): a
metric whose value depends on a discrete, standard, un-captured convention is one pattern.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Convention:
    """A metric's declarative convention grid + its FCR-safety contract."""
    metric: str
    grid: list[dict]                        # discrete convention cells (kwargs overrides for recompute)
    sources: list[str] = field(default_factory=list)          # rule 1: every axis cited
    forbidden_free_params: list[str] = field(default_factory=list)   # rule 3: never a grid axis
    max_grid: int = 24                      # rule 2: combinatorial cap
    note: str = ""


def _sharpe_grid():
    # annualization √ppy × sample/population stdev. ppy set = per-period + daily variants (252/260/250) +
    # weekly/monthly/quarterly. (guide §B.2 / Composer / Quant Decoded / Stanford wfsharpe.)
    return [{"periods_per_year": p, "ddof": d}
            for p in (1.0, 252.0, 260.0, 250.0, 52.0, 12.0, 4.0) for d in (1, 0)]


CONVENTIONS: dict[str, Convention] = {
    "sharpe": Convention(
        metric="sharpe",
        grid=_sharpe_grid(),
        sources=["help.composer.trade/article/19-sharpe-ratio",
                 "quantdecoded.com/en/the-sharpe-ratio-measuring-risk-adjusted-returns",
                 "web.stanford.edu/~wfsharpe/art/sr/SR.htm"],
        forbidden_free_params=["risk_free", "scale"],
        max_grid=24,
        note="arithmetic-mean numerator only; geometric Sharpe is nonstandard and excluded.",
    ),
    "sortino": Convention(
        metric="sortino",
        grid=[{"periods_per_year": p, "downside_denom": d}
              for p in (1.0, 252.0, 52.0, 12.0) for d in ("full", "downside")],
        sources=["quantt.co.uk/resources/risk-adjusted-returns-guide",
                 "quantdecoded.com/en/the-sharpe-ratio-measuring-risk-adjusted-returns"],
        forbidden_free_params=["risk_free", "target", "mar"],
        max_grid=16,
        note="target/MAR taken from captured risk_free, never searched; downside-denom ∈ {N, N_downside}.",
    ),
    "calmar": Convention(
        metric="calmar",
        grid=[{"periods_per_year": p} for p in (252.0, 52.0, 12.0, 1.0)],
        sources=["quantt.co.uk/resources/risk-adjusted-returns-guide"],
        forbidden_free_params=["scale"],
        max_grid=8,
        note="numerator is already a CAGR — no extra √ppy; ppy only annualizes CAGR from n periods.",
    ),
    "information_ratio": Convention(
        metric="information_ratio",
        grid=[{"periods_per_year": p, "ddof": d}
              for p in (1.0, 252.0, 52.0, 12.0) for d in (1, 0)],
        sources=["web.stanford.edu/~wfsharpe/art/sr/SR.htm"],
        forbidden_free_params=["risk_free"],
        max_grid=16,
        note="disambiguated from Sharpe-of-active by the required benchmark input.",
    ),
    "stdev": Convention(
        metric="stdev",
        grid=[{"ddof": 1}, {"ddof": 0}],
        sources=["numpy.org (np.std ddof=0)", "pandas.pydata.org (Series.std ddof=1)"],
        forbidden_free_params=[],
        max_grid=2,
        note="the classic numpy(ddof=0)-vs-pandas(ddof=1) discrepancy.",
    ),
    "variance": Convention(
        metric="variance",
        grid=[{"ddof": 1}, {"ddof": 0}],
        sources=["numpy.org (np.var ddof=0)", "pandas.pydata.org (Series.var ddof=1)"],
        forbidden_free_params=[],
        max_grid=2,
    ),
    "correlation": Convention(
        metric="correlation",
        grid=[{"method": "pearson"}, {"method": "spearman"}, {"method": "kendall"}],
        sources=["docs.scipy.org/doc/scipy/reference/stats (pearsonr/spearmanr/kendalltau)"],
        forbidden_free_params=[],
        max_grid=3,
        note="correlation TYPE resolved as a convention; confirm only if exactly one type reproduces.",
    ),
    # ---- IR + NLP generation (guide §B.3): the same 'discrete standard un-captured convention' pattern ----
    "ndcg": Convention(
        metric="ndcg",
        grid=[{"gain": g, "k": k} for g in ("linear", "exponential") for k in (None, 5, 10, 20)],
        sources=["Järvelin&Kekäläinen 2002 (linear-gain nDCG)", "Burges 2005 (exponential gain)",
                 "scikit-learn.org (ndcg_score)", "github.com/cvangysel/pytrec_eval (ndcg_cut@k)"],
        forbidden_free_params=[],
        max_grid=8,
        note="gain (Järvelin linear vs Burges 2^rel-1) × cutoff k — the two real nDCG divergences.",
    ),
    "bleu": Convention(
        metric="bleu",
        grid=[{"tokenize": t, "smooth": s, "scale": sc}
              for t in ("none", "13a", "char") for s in ("none", "exp", "floor") for sc in ("unit", "percent")],
        sources=["github.com/mjpost/sacrebleu (reproducibility signature tok/smooth/case)",
                 "github.com/huggingface/evaluate/metrics/bleu"],
        forbidden_free_params=[],
        max_grid=24,
        note="tokenization × smoothing × scale (0-1 vs 0-100) — sacreBLEU's whole reason for a signature; "
             "scale reconciles the 100× nltk-vs-sacrebleu mismatch that would masquerade as REFUTED.",
    ),
}


def has_grid(metric_id: str | None) -> bool:
    return bool(metric_id) and metric_id in CONVENTIONS


def _fmt(cell: dict) -> str:
    def _v(v):
        return ("%g" % v) if isinstance(v, (int, float)) else str(v)
    return ", ".join("%s=%s" % (k, _v(v)) for k, v in cell.items())


def search(metric_id: str, inputs: dict, produced: float, base_kwargs: dict, recompute, close) -> dict | None:
    """Try the recognized conventions for `metric_id` against the captured `inputs`; return a Result dict
    (with a `convention` + audit note) for the FIRST cell whose recompute reproduces `produced` at `close`
    tolerance, else None. GENERIC over `recompute(metric_id, inputs, kwargs) -> Result` and `close(a, b)`.

    FCR contract: the base_kwargs (captured metric options) are the floor; each grid cell only OVERRIDES the
    discrete convention axes. A degenerate cell can never match. Because every returned cell reproduced
    `produced` to tolerance, the ambiguity guard (rule 6) holds automatically."""
    conv = CONVENTIONS.get(metric_id)
    if conv is None or produced is None or inputs is None:
        return None
    base = dict(base_kwargs or {})
    for cell in conv.grid:
        alt = recompute(metric_id, inputs, {**base, **cell})
        if alt and not alt.get("degenerate") and close(produced, alt.get("value")):
            out = dict(alt)
            out["convention"] = dict(cell)
            out["note"] = "matched the repo's convention (%s)" % _fmt(cell)
            return out
    return None


# ---- contract enforcement (used by tests/test_conventions.py as a hard CI gate) -------------------
def validate_registry() -> list[str]:
    """Return a list of contract violations across the whole registry (empty == conforms). Enforces rules
    1–3 statically (rules 4–8 are behavioral, checked by the diff + fuzz tests)."""
    errs: list[str] = []
    for key, conv in CONVENTIONS.items():
        if conv.metric != key:
            errs.append("%s: metric field %r != registry key" % (key, conv.metric))
        if not conv.grid:
            errs.append("%s: empty grid" % key)
        if len(conv.grid) > conv.max_grid:
            errs.append("%s: grid size %d > max_grid %d (rule 2 — a large grid is a curve-fitter)"
                        % (key, len(conv.grid), conv.max_grid))
        if not conv.sources:
            errs.append("%s: no sources cited (rule 1 — documented-standard only)" % key)
        # rule 3: a forbidden continuous param must never appear as a grid axis
        for cell in conv.grid:
            for p in conv.forbidden_free_params:
                if p in cell:
                    errs.append("%s: forbidden free param %r appears in a grid cell (rule 3)" % (key, p))
        # no duplicate cells (a duplicate is dead weight that inflates the coincidence base rate)
        seen = set()
        for cell in conv.grid:
            k = tuple(sorted(cell.items()))
            if k in seen:
                errs.append("%s: duplicate grid cell %s" % (key, cell))
            seen.add(k)
    return errs
