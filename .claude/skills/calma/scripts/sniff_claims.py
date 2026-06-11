"""Conservative checkable-claim detector for the zero-touch Stop hook.

Scans an agent's final message for numeric claims calma can verify (a metric word and a
number in claim syntax) and emits canonical claim strings. The design constraint is
PRECISION, not recall: a missed claim costs nothing (the user can always run
`calma verify` by hand); a false fire costs an unwanted re-execution and teaches the user
to disable the hook. Every rule below errs toward silence.

A candidate fires only when ALL of these hold:
  1. the metric term is in the curated STRONG vocabulary (unambiguous in running prose), or
     in CONDITIONAL with its strengthener present (e.g. "coverage" needs a % value), or it
     matches the "processed N rows" template;
  2. the number sits in claim syntax next to the term - only connector words between
     ("is", "of", "reached", ":", "=", ...), within a short window;
  3. the number is not a version, date, year, time, line/port/exit/seed reference, ordinal,
     count of files/tests/tokens, or a duration/size with a unit the metric doesn't expect;
  4. the sentence is not a question, not hypothetical/planning talk ("should", "target",
     "estimated"), not about a baseline/previous value, and the number is not negated;
  5. the value is plausible for the metric family (an "accuracy" of 7.3 is not a claim).

API:  sniff(text) -> [ {claim, metric, value, confidence, score, span, source}, ... ]
      (best candidate first; at most MAX_CLAIMS; every entry is high-confidence by
      construction - callers should treat the list as "safe to auto-verify")
CLI:  python3 sniff_claims.py [--debug] < message.txt   ->  JSON list on stdout
      (--debug adds a "rejected" list with one reason per discarded candidate)

Pure stdlib. The metric vocabulary maps into draft_contract.CLAIM_METRIC_HINTS so the
sniffer can never emit a metric id the engine does not serve (test-enforced).
"""
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import draft_contract as DC  # noqa: E402  (CLAIM_METRIC_HINTS, _CLAIM_NUM)

MAX_CLAIMS = 5

# ---------------------------------------------------------------------------
# vocabulary - every term must exist in CLAIM_METRIC_HINTS (the engine's table)
# ---------------------------------------------------------------------------
# STRONG: "<term> <number>" in a random prose sentence is, with high probability, a
# checkable claim. Generic words from the hint table ("total", "mean", "rows", "count",
# "memory", "ci", "var", "alpha", "beta", ...) are deliberately ABSENT - they are how a
# zero-touch hook becomes noise.
STRONG_TERMS = [
    "accuracy", "balanced accuracy",
    "auc", "pr auc", "pr-auc", "auprc", "average precision",
    "f1", "macro f1", "macro-f1", "micro f1", "micro-f1", "weighted f1", "weighted-f1",
    "fbeta", "f-beta",
    "rmse", "mae", "msle", "rmsle", "medae", "nrmse", "max error",
    "r2", "r^2", "adjusted r2", "adj r2",
    "mape", "smape", "wape", "mase", "pinball", "quantile loss", "forecast bias",
    "log loss", "logloss", "cross entropy",
    "mcc", "matthews", "brier", "ece", "calibration error",
    "ndcg", "mrr", "perplexity",
    "p-value", "p value", "pvalue",
    "chi-square", "chi-squared", "chi square", "chi2",
    "mann-whitney", "mann whitney", "anova",
    "effect size", "cohen's d", "cohens d",
    "jaccard", "iou", "kappa", "specificity",
    "sharpe", "sortino", "calmar", "drawdown",
    "cvar", "expected shortfall", "value at risk",
    "profit factor", "omega", "information ratio", "tracking error",
    "volatility", "downside deviation",
    "cagr", "npv", "irr",
    "hhi", "herfindahl", "gini",
    "skewness", "kurtosis", "jarque", "autocorrelation", "durbin",
    "apdex", "explained variance",
]
# CONDITIONAL: real metrics whose words also appear in ordinary engineering chatter.
# They fire only when the named strengthener holds for the matched number.
#   pct        - the number carries a % suffix
#   pct_or_01  - % suffix, or a bare value in [0, 1]
#   ratio_x    - the number is followed by x/X/times ("2.3x faster")
#   unit_time  - the number is followed by ms/us/µs/s/sec ("p95 latency 120ms")
#   unit_rate  - the number is followed by rps/qps//s/per sec
#   signed1    - |value| <= 1 (correlations)
CONDITIONAL_TERMS = {
    "precision": "pct_or_01", "recall": "pct_or_01", "exact match": "pct_or_01",
    "exact-match": "pct_or_01", "wer": "pct_or_01", "word error rate": "pct_or_01",
    "character error rate": "pct_or_01",
    "coverage": "pct",
    "win rate": "pct", "churn": "pct", "uptime": "pct", "availability": "pct",
    "error rate": "pct", "failure rate": "pct", "uplift": "pct", "lift": "pct",
    "margin": "pct", "return": "pct", "backtest": "pct",
    "speedup": "ratio_x", "speed-up": "ratio_x", "faster": "ratio_x",
    "latency": "unit_time",
    "throughput": "unit_rate", "rps": "unit_rate", "qps": "unit_rate",
    "correlation": "signed1", "pearson": "signed1", "spearman": "signed1",
}
# verb forms of metric words ("the strategy returned 23%"): term -> (metric id, the
# canonical noun used in the emitted claim string, strengthener kind). Verbs are weaker
# than nouns - anything "returns" a percentage in engineering prose (probes, checks,
# functions) - so an alias additionally requires a finance-shaped subject in the sentence.
_ALIASES = {"returned": ("total_return", "return", "pct"),
            "returns": ("total_return", "return", "pct")}
_FINANCE_SUBJECT = re.compile(
    r"\b(strateg\w+|portfolio\w*|backtest\w*|funds?|trad\w+|positions?|stocks?|equit\w+|"
    r"etfs?|assets?|investments?|holdings?|btc|eth|crypto\w*|bonds?|index|sp500|s&p)\b",
    re.IGNORECASE)
# retrieval/eval @k families: "recall@10", "pass@5", "top-5 accuracy", "ndcg@20"
_AT_K_METRIC = {"recall": "recall_at_k", "precision": "precision_at_k", "pass": "pass_at_k",
                "map": "map_at_k", "hit": "hit_at_k", "top": "top_k_accuracy",
                "ndcg": "ndcg_at_k"}
_AT_K_RE = re.compile(r"(?<![a-z0-9])(recall|precision|pass|map|hit|ndcg|top)[@\-](\d{1,3})"
                      r"(?![a-z0-9])")
# latency percentiles: "p95 latency 120ms", "p99 2.1s" (term carries its own number - the
# percentile - so connector logic treats the WHOLE token as the term)
_PCTL_RE = re.compile(r"(?<![a-z0-9])(p50|p90|p95|p99)(?:\s+latency)?(?![a-z0-9.])")
_PCTL_METRIC = {"p50": "latency_p50", "p90": "latency_p90", "p95": "latency_p95",
                "p99": "latency_p99"}
# the one analytics template precise enough for zero-touch: a processing verb + N rows
_ROWS_RE = re.compile(r"\b(processed|cleaned|wrote|loaded|ingested|deduplicated|deduped)\b"
                      r"[\s:]+((?:\d{1,3}(?:,\d{3})+|\d+))\s+rows?\b", re.IGNORECASE)

# metric ids whose plausible value lives in [0,1] (after % scaling); a bare value in
# (1, 100] is AMBIGUOUS (probably percent-intent without the sign) -> skip, never fire
_BOUNDED01 = {"accuracy", "auc", "pr_auc", "f1", "macro_f1", "micro_f1", "weighted_f1",
              "fbeta", "precision", "recall", "balanced_accuracy", "specificity", "jaccard",
              "brier", "ece", "top_k_accuracy", "recall_at_k", "precision_at_k", "map_at_k",
              "ndcg_at_k", "mrr", "hit_at_k", "exact_match", "test_coverage", "win_rate",
              "churn_rate", "error_rate", "uptime_pct", "p_value", "wer", "log_loss"}
_SIGNED1 = {"mcc", "correlation", "cohen_kappa"}
# log_loss > 1 is possible but rare in claims; treating it as bounded only mutes, never lies

# connector words allowed between a metric term and its number ("accuracy is 0.91",
# "sharpe came in at 1.8", "RMSE: 12.4"); anything else between them = not a claim pair
_CONNECTOR_WORDS = {"is", "was", "are", "were", "of", "at", "to", "now", "equals", "equal",
                    "reached", "hit", "hits", "came", "comes", "come", "in", "stands",
                    "sits", "holds", "measured", "currently", "approximately", "about",
                    "around", "roughly", "exactly", "score", "scored", "scores", "value",
                    "a", "an", "the", "final", "overall", "test", "held-out", "holdout",
                    "out-of-sample", "validation", "achieved", "achieves", "achieving",
                    "yields", "yielded", "gives", "gave", "got", "gets", "landed",
                    "improved", "rose", "fell", "dropped", "increased", "decreased",
                    "climbed", "ended", "settled", "comes-to", "up", "down", "stayed",
                    "returned", "returns", "delivered", "produced", "shows", "showed",
                    "showing", "clocked", "clocks", "ratio", "coefficient", "statistic",
                    "out", "works", "worked", "computes", "computed"}
_CONNECTOR_STRIP = re.compile(r"[\s:=~≈\-–—()*_`'\",.]+")

# sentence-level guards: hypothetical/planning talk and baseline/previous references are
# not claims about the artifact on disk ("expected" is excluded: "expected shortfall" is a
# metric; "may" would false-trip on the month)
_HYPOTHETICAL = re.compile(
    r"\b(should|would|could|might|aim|aims|aiming|target|targets|targeting|goal|goals|"
    r"estimate|estimates|estimated|estimating|projected|projection|plan|plans|planned|"
    r"planning|hope|hopes|hoped|hoping|want|wants|wanted|going to|will|let's|lets|"
    r"propose|proposed|proposal|hypothetical|hypothetically|placeholder|dummy|fake|"
    r"synthetic|example|e\.g\.|if|unless|assuming|suppose|todo|wish|ideally|in theory|"
    r"once .{0,40}(?:done|finished|complete)|next step)\b", re.IGNORECASE)
_BASELINE = re.compile(r"\b(baseline|previous|previously|formerly|originally|before the|"
                       r"old|prior|last (?:run|time|week|month)|used to)\b", re.IGNORECASE)
_NEGATION = re.compile(r"\b(not|isn't|isnt|wasn't|wasnt|never|no longer|below|under|"
                       r"short of|fails? to (?:reach|hit))\b\s*$", re.IGNORECASE)

# config-assignment shape: "<set-verb> the ... <term> to <number>" is a knob being turned,
# not a result being measured ("I set the toxiproxy latency to 500ms"). The determiner
# after the verb distinguishes assignment "set the X" from the noun in "test set".
# Detected as: an assignment verb+determiner before the term AND a bare "to" in the
# term->number gap. Applies only on the term-then-number path.
_ASSIGN_VERB = re.compile(
    r"\b(?:set|sets|setting|reset|pin(?:ned|s)?|pinning|cap(?:ped|s)?|capping|"
    r"configur\w+|clamp(?:ed|s)?|clamping|hardcod\w+|hard-cod\w+|default(?:ed|s)?)\s+"
    r"(?:the|a|an|its|our|their|his|her|that|this|each|every)\b", re.IGNORECASE)
_GAP_TO = re.compile(r"\bto\b", re.IGNORECASE)
# deliberately fabricated values are configuration, not measurement ("injected latency")
_FABRICATED_BEFORE = re.compile(r"\b(?:injected|simulated|artificial|induced)\s*$",
                                re.IGNORECASE)

# per-term context deny: sentences whose vocabulary marks the OTHER meaning of an
# ambiguous metric word. Each entry mutes one documented collision; a missed claim is
# free, a false fire is a release blocker.
_CONTEXT_DENY = {
    # numeric/rounding tolerance, not classifier precision ("a precision of 0.001")
    "precision": re.compile(r"\b(round(?:ed|ing|s)?|toleranc\w*|decimals?|floats?|"
                            r"floating[- ]?point|epsilon|compar\w+|"
                            r"significant (?:digits|figures))\b", re.IGNORECASE),
    # diff churn in code-review chatter, not customer churn
    "churn": re.compile(r"\b(diffs?|renam\w+|refactor\w*|commits?|merge[sd]?|prs?|"
                        r"pull requests?|review\w*|director\w+|files?|repo\w*|codebase)\b",
                        re.IGNORECASE),
    # byte-identical files, not the LLM-eval exact_match score
    "exact match": re.compile(r"\b(bytes?|byte-identical|identical|files?|artifacts?|"
                              r"checksums?|hash\w*|sha\d+|builds?|binar\w+|"
                              r"reproducib\w+|sbom)\b", re.IGNORECASE),
    # CSS margin, not profit margin
    "margin": re.compile(r"\b(css|px|paddings?|layouts?|viewports?|breakpoints?|"
                         r"tablets?|mobile|fonts?|hero|responsive|styl\w+)\b",
                         re.IGNORECASE),
}
_CONTEXT_DENY["exact-match"] = _CONTEXT_DENY["exact match"]

# context immediately BEFORE a number that marks it as a reference, not a result
_REF_BEFORE = re.compile(r"(?:\b(?:line|ln|lines|port|pid|exit|status|code|codes|page|"
                         r"step|steps|chunk|seed|epoch|epochs|iter|iteration|iterations|"
                         r"attempt|run|round|day|week|month|year|q|chapter|section|sec|"
                         r"figure|fig|table|issue|pr|version|ver|python|node|task)\b"
                         r"[\s#:.]*|#|v)$", re.IGNORECASE)
# units AFTER a number that mark it as a count/size/duration, not a metric value (time
# units are allowed only through the unit_time strengthener; "rows" only via the template)
_UNIT_AFTER = re.compile(r"^\s*(?:files?|tests?|lines?|rows?|columns?|commits?|items?|"
                         r"tokens?|samples?|records?|entries|epochs?|iterations?|steps?|"
                         r"results?|matches?|events?|duplicates?|errors?|warnings?|"
                         r"cents?|dollars?|bucks?|usd|eur|gbp|"
                         r"bytes?|kb|mb|gb|tb|kib|mib|gib|ms|us|µs|ns|s\b|sec|secs|"
                         r"seconds?|minutes?|mins?|hours?|hrs?|days?|weeks?|months?|"
                         r"years?|px|pt|deg|degrees)\b", re.IGNORECASE)
_SEMVER = re.compile(r"\d+\.\d+\.\d+")
_TIMELIKE = re.compile(r"^:\d")  # "14:32"
_DATELIKE = re.compile(r"^[-/]\d")  # "2026-06-11", "6/11"

_STRENGTH_UNIT_TIME = re.compile(r"^\s*(?:ms|us|µs|ns|s|sec|secs|seconds?|ms\b)",
                                 re.IGNORECASE)
_STRENGTH_RATIO_X = re.compile(r"^\s*(?:x|×|times)\b", re.IGNORECASE)
_STRENGTH_UNIT_RATE = re.compile(r"^\s*(?:rps|qps|/s|/sec|per s|per sec|req/s|ops/s|"
                                 r"ops/sec|requests?/s)", re.IGNORECASE)


def _hint_metric(term):
    """Map a vocabulary term to its engine metric id via CLAIM_METRIC_HINTS - the sniffer
    never invents a metric the engine does not serve."""
    low = term.lower()
    for word, mid in DC.CLAIM_METRIC_HINTS:
        if word == low:
            return mid
    return None


def _blank(text, pattern, flags=0):
    """Replace every match with spaces of equal length - offsets stay valid."""
    return re.sub(pattern, lambda m: " " * len(m.group(0)), text, flags=flags)


def _strip_nonprose(text):
    """Blank regions where numbers are never claims: fenced code, inline code, blockquotes,
    URLs, file paths, and shell-prompt lines. Length-preserving."""
    text = _blank(text, r"```.*?(?:```|\Z)", re.DOTALL)
    text = _blank(text, r"`[^`\n]*`")
    text = _blank(text, r"^\s*>.*$", re.MULTILINE)          # quoted text
    text = _blank(text, r"^\s*[$#]\s.*$", re.MULTILINE)      # shell prompts
    text = _blank(text, r"https?://\S+")
    text = _blank(text, r"(?:[\w.\-]+)?(?:/[\w.\-]+){2,}/?")  # paths: a/b/c
    return text


def _sentences(text):
    """Yield (start, end, sentence_text) spans. Newlines end sentences so list items and
    table rows are judged independently. A '.' only ends a sentence when followed by
    whitespace/end - decimals ("accuracy 0.91") never split."""
    for lm in re.finditer(r"[^\n]+", text):
        line, base = lm.group(0), lm.start()
        for m in re.finditer(r".+?(?:[.!?]+(?=\s|$)|$)", line):
            s = m.group(0)
            if s.strip():
                yield base + m.start(), base + m.end(), s


def _connector_ok(between):
    """True iff the text between term and number contains only connector tokens."""
    words = [w for w in _CONNECTOR_STRIP.split(between.lower()) if w]
    return all(w in _CONNECTOR_WORDS for w in words)


def _number_after(text, start, window=48):
    """First claim-shaped number after `start` whose gap is pure connector. Returns the
    _CLAIM_NUM match (with positions absolute in `text`) or None."""
    seg = text[start:start + window]
    for m in DC._CLAIM_NUM.finditer(seg):
        if _connector_ok(seg[:m.start()]):
            return _AbsMatch(m, start)
        return None  # first number fails the gap -> no claim here (never skip forward)
    return None


def _number_before(text, end, window=24):
    """A number immediately before the term ("+19,971% backtest", "0.91 accuracy"): only
    whitespace/markdown may sit between."""
    seg = text[max(0, end - window):end]
    last = None
    for m in DC._CLAIM_NUM.finditer(seg):
        last = m
    if last is None:
        return None
    base = max(0, end - window)
    after = seg[last.end():]
    # an attached ratio token stays part of the number ("2.3x faster")
    if re.fullmatch(r"(?:x|×|times)?[\s*_`'\"()\-]*", after, re.IGNORECASE):
        return _AbsMatch(last, base)
    return None


class _AbsMatch(object):
    """A _CLAIM_NUM match re-based to absolute offsets in the full text."""

    def __init__(self, m, base):
        self.sign = m.group(1) or ""
        self.raw = m.group(2)
        self.suffix = m.group(3) or ""
        self.start = base + m.start()
        self.end = base + m.end()
        # absolute end of the numeric token itself (excludes trailing whitespace the
        # suffix group may have skipped)
        self.num_end = base + m.end(2)

    def text(self):
        return "%s%s%s" % (self.sign, self.raw, self.suffix)

    def value(self):
        v = float(self.raw.replace(",", ""))
        if self.sign == "-":
            v = -v
        scale = {"%": 0.01, "k": 1e3, "K": 1e3, "m": 1e6, "M": 1e6,
                 "b": 1e9, "B": 1e9}.get(self.suffix, 1.0)
        return v * scale


_UNIT_KINDS = {"unit_time", "unit_rate", "pctl"}  # kinds whose VALUE carries a unit


def _number_rejected(text, nm, kind):
    """Reason string when the matched number is a non-claim (version, date, year, count,
    reference); None when it survives. `nm` is an _AbsMatch. Unit-expecting kinds skip the
    counted-unit check - their strengthener validates the unit instead."""
    before = text[max(0, nm.start - 14):nm.start]
    if _REF_BEFORE.search(before):
        return "reference-prefix"
    if _NEGATION.search(text[max(0, nm.start - 22):nm.start]):
        return "negated"
    after_num = text[nm.num_end:nm.num_end + 12]
    if _TIMELIKE.match(after_num) or _DATELIKE.match(after_num):
        return "date-or-time"
    if _SEMVER.search(text[max(0, nm.start - 1):nm.end + 8]):
        return "version-string"
    if kind not in _UNIT_KINDS and not nm.suffix and _UNIT_AFTER.match(after_num):
        # a unit the metric does not expect -> a count/size/duration, not a value
        return "counted-unit"
    if not nm.suffix and "." not in nm.raw and "," not in nm.raw:
        iv = int(nm.raw)
        if 1900 <= iv <= 2100:
            return "year-like"
    return None


def _plausible(metric, value, suffix):
    """Reason string when the value is implausible for the metric family; None when fine.
    Bare values in (1, 100] for [0,1]-bounded metrics are percent-ambiguous -> skip."""
    if metric == "log_loss" and suffix == "%":
        # cross-entropy is never expressed as a percentage; "0.4% log loss" is SRE
        # chatter about lost log lines, not an ML claim
        return "percent-on-log-loss"
    if metric in _BOUNDED01:
        if suffix == "%":
            return None if -0.0001 <= value <= 1.0001 else "percent-out-of-range"
        if 0.0 <= value <= 1.0001:
            return None
        if 1.0001 < value <= 100.0:
            return "percent-ambiguous"
        return "out-of-range"
    if metric in _SIGNED1:
        return None if abs(value) <= 1.0001 else "out-of-range"
    return None


def _strengthener_ok(kind, text, nm):
    """Check a CONDITIONAL term's strengthener against the matched number."""
    after = text[nm.num_end:nm.num_end + 14]
    if kind == "pct":
        return nm.suffix == "%"
    if kind == "pct_or_01":
        return nm.suffix == "%" or (not nm.suffix and 0.0 <= abs(nm.value()) <= 1.0001)
    if kind == "ratio_x":
        return bool(_STRENGTH_RATIO_X.match(after))
    if kind == "unit_time":
        return bool(_STRENGTH_UNIT_TIME.match(after))
    if kind == "unit_rate":
        return bool(_STRENGTH_UNIT_RATE.match(after))
    if kind == "pctl":  # "p95 of the distribution is 4.2" is a data percentile, not
        return bool(_STRENGTH_UNIT_TIME.match(after))  # latency - require a time unit
    if kind == "signed1":
        return not nm.suffix and abs(nm.value()) <= 1.0001
    return False


def _term_occurrences(text):
    """Yield (term_text, start, end, metric_id, kind) for every vocabulary hit.
    kind: 'strong' | conditional strengthener name | 'at_k' | 'pctl'."""
    low = text.lower()
    for term in STRONG_TERMS:
        mid = _hint_metric(term)
        if mid is None:
            continue
        for m in re.finditer(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(term), low):
            yield term, m.start(), m.end(), mid, "strong"
    for term, kind in CONDITIONAL_TERMS.items():
        mid = _hint_metric(term)
        if mid is None:
            continue
        for m in re.finditer(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(term), low):
            # "p95 latency" is the pctl occurrence's claim - the bare "latency" term
            # would mis-bind it to latency_p50
            if term == "latency" and _PCTL_RE.search(low[max(0, m.start() - 8):m.start()]):
                continue
            yield term, m.start(), m.end(), mid, kind
    for term, (mid, _canon, kind) in _ALIASES.items():
        for m in re.finditer(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(term), low):
            yield term, m.start(), m.end(), mid, kind
    for m in _AT_K_RE.finditer(low):
        yield m.group(0), m.start(), m.end(), _AT_K_METRIC[m.group(1)], "at_k"
    for m in _PCTL_RE.finditer(low):
        yield m.group(0), m.start(), m.end(), _PCTL_METRIC[m.group(1)], "pctl"


def sniff(text, debug=False):
    """Detect checkable claims in an agent message. Returns a list of candidate dicts,
    best first (score desc, then later position): {claim, metric, value, confidence,
    score, span, source}. With debug=True returns (candidates, rejected)."""
    rejected = []

    def reject(term, reason, pos):
        if debug:
            rejected.append({"term": term, "reason": reason, "pos": pos})

    if not text or not text.strip():
        return ([], rejected) if debug else []
    clean = _strip_nonprose(text)
    sents = list(_sentences(clean))

    def sentence_of(pos):
        for s0, s1, stext in sents:
            if s0 <= pos < s1:
                return s0, s1, stext
        return None

    out = []
    seen = set()

    def consider(term, t0, t1, mid, kind, nm, num_first):
        sent = sentence_of(t0)
        if sent is None:
            return reject(term, "no-sentence", t0)
        s0, s1, stext = sent
        if not (s0 <= nm.start < s1):
            return reject(term, "crosses-sentence", t0)
        if stext.strip().endswith("?"):
            return reject(term, "question", t0)
        if _HYPOTHETICAL.search(stext):
            return reject(term, "hypothetical", t0)
        if _BASELINE.search(stext):
            return reject(term, "baseline-reference", t0)
        deny = _CONTEXT_DENY.get(term)
        if deny and deny.search(stext):
            return reject(term, "domain-context", t0)
        if term in _ALIASES and not _FINANCE_SUBJECT.search(stext):
            return reject(term, "no-finance-subject", t0)
        if _FABRICATED_BEFORE.search(clean[max(0, t0 - 24):t0]):
            return reject(term, "fabricated-value", t0)
        if (not num_first and _GAP_TO.search(clean[t1:nm.start])
                and _ASSIGN_VERB.search(stext[:max(0, t0 - s0)])):
            return reject(term, "config-assignment", t0)
        why = _number_rejected(clean, nm, kind)
        if why:
            return reject(term, why, t0)
        if kind not in ("strong", "at_k") and not _strengthener_ok(kind, clean, nm):
            return reject(term, "strengthener-missing:%s" % kind, t0)
        value = nm.value()
        why = _plausible(mid, value, nm.suffix)
        if why:
            return reject(term, why, t0)
        key = (mid, round(value, 12))
        if key in seen:
            return reject(term, "duplicate", t0)
        seen.add(key)
        # canonical claim string: "<term> <number>" (or "<number> <term>" when the number
        # led, e.g. "+19,971% backtest") so parse_claim recovers the same value+metric;
        # verb aliases canonicalize to their noun ("returned" -> "return")
        numtext = nm.text()
        cterm = _ALIASES[term][1] if term in _ALIASES else term
        claim = ("%s %s" % (numtext, cterm)) if num_first else ("%s %s" % (cterm, numtext))
        if kind == "pctl":  # "p95 120ms" alone is ambiguous; name the family
            claim = "%s latency %s" % (term.split()[0], numtext)
        dist = (t0 - nm.end) if num_first else (nm.start - t1)
        score = 1.0
        if kind not in ("strong", "at_k", "pctl"):
            score -= 0.10
        if num_first:
            score -= 0.05
        score -= 0.004 * max(0, dist)
        snippet = stext.strip()
        out.append({"claim": claim, "metric": mid, "value": value, "confidence": "high",
                    "score": round(score, 4), "span": [min(t0, nm.start), max(t1, nm.end)],
                    "source": snippet[:160]})

    for term, t0, t1, mid, kind in _term_occurrences(clean):
        nm = _number_after(clean, t1)
        if nm is not None:
            consider(term, t0, t1, mid, kind, nm, num_first=False)
            continue
        nm = _number_before(clean, t0)
        if nm is not None:
            consider(term, t0, t1, mid, kind, nm, num_first=True)
        else:
            reject(term, "no-number", t0)

    # the "processed N rows" template (the one analytics shape precise enough for
    # zero-touch); same sentence guards apply
    for m in _ROWS_RE.finditer(clean):
        sent = sentence_of(m.start())
        if sent is None:
            continue
        _s0, _s1, stext = sent
        if (stext.strip().endswith("?") or _HYPOTHETICAL.search(stext)
                or _BASELINE.search(stext)):
            reject(m.group(0), "guarded-sentence", m.start())
            continue
        n = m.group(2)
        key = ("row_count", float(n.replace(",", "")))
        if key in seen:
            continue
        seen.add(key)
        out.append({"claim": "%s rows" % n, "metric": "row_count",
                    "value": float(n.replace(",", "")), "confidence": "high",
                    "score": 0.85, "span": [m.start(), m.end()],
                    "source": stext.strip()[:160]})

    out.sort(key=lambda c: (-c["score"], -c["span"][0]))
    out = out[:MAX_CLAIMS]
    return (out, rejected) if debug else out


def main(argv):
    debug = "--debug" in argv
    text = sys.stdin.read()
    if debug:
        cands, rej = sniff(text, debug=True)
        print(json.dumps({"claims": cands, "rejected": rej}, indent=2))
    else:
        print(json.dumps(sniff(text), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
