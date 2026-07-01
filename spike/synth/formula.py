"""calma.spike.synth.formula — resolve a metric to a TRUSTED recompute, growing coverage on demand
(rebuild guide §4.8 novel-metric path + §10 catalog flywheel).

resolve order for a claimed metric:
  1. trusted catalog        — the curated, pre-validated implementations (core.catalog)
  2. formula store          — a previously synthesised + validated formula, fetched by vector match
                              (HelixDB in prod) → instant reuse, no re-discovery
  3. synthesise + validate  — Exa finds the metric's canonical definition; an LLM synthesises a candidate
                              recompute; we VALIDATE it against a reference oracle on random data before
                              trusting it; on pass, bank it in the store. On fail, refuse (fail-closed).
  4. none                   — unrecognised + unsynthesisable → no recompute (verdict stays reproduced-only).

We never trust an unvalidated synthesised formula (§4.8). Validated formulas are stored as restricted Python
source and executed in a locked-down namespace (no imports/builtins beyond safe math) — and, in production,
inside the sandbox. The heavy libs (sklearn/scipy) are used ONLY at validation time; the runtime recompute
path is pure-stdlib + the stored code, so a deployed worker needs no scientific stack.

The synthesis step here is grounded by real Exa retrieval (the definitions below were confirmed via Exa) and
the code is what an LLM would emit from that definition; productionising the LLM call (Claude API) is the one
remaining piece — the validate/store/reuse machinery around it is real and tested.
"""
from __future__ import annotations

import os
import random

from core import catalog as C  # the trusted catalog (pure-stdlib)

from . import store as S

# ---- restricted execution of a stored/synthesised formula ----------------------------------------
_SAFE_BUILTINS = {b.__name__: b for b in (
    len, sum, range, zip, abs, float, int, min, max, sorted, enumerate, map, filter,
    list, set, dict, tuple, str, round, pow, bool, any, all)}


def _ast_safe(code: str) -> None:
    """Reject a formula whose AST reaches for a sandbox escape BEFORE it runs. Restricting `__builtins__`
    alone is not a real sandbox — `().__class__.__bases__[0].__subclasses__()` can walk to os/subprocess with
    no builtins at all. A legitimate recompute only indexes its inputs, calls math, and does arithmetic; it
    never needs a dunder attribute, an import, or a `with`/global. So we deny exactly those. Raises ValueError
    on any escape vector (the caller turns it into a degenerate recompute — fail-closed). Defense-in-depth on
    top of validation + E2B isolation."""
    import ast  # noqa: PLC0415
    tree = ast.parse(code, "<formula>", "exec")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError("formula may not import")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ValueError("formula may not access dunder attribute %r" % node.attr)
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise ValueError("formula may not reference dunder name %r" % node.id)
        if isinstance(node, (ast.Global, ast.Nonlocal, ast.With, ast.AsyncWith, ast.Await)):
            raise ValueError("formula may not use %s" % type(node).__name__)


def exec_formula(code: str, inputs: dict, kwargs: dict | None = None):
    """Execute a formula's `def recompute(I, K) -> float` in a locked-down namespace (only safe builtins +
    math), after an AST escape-vector check. Returns the value, or raises — the caller turns a raise into a
    degenerate recompute (fail-closed)."""
    import math  # noqa: PLC0415
    _ast_safe(code)                              # deny dunder-attribute / import escapes before running
    ns = {"__builtins__": _SAFE_BUILTINS, "math": math}
    exec(compile(code, "<formula>", "exec"), ns)  # noqa: S102 - AST-guarded + sandboxed ns; validated; prod=in-VM
    fn = ns.get("recompute")
    if not callable(fn):
        raise ValueError("formula defines no recompute(I, K)")
    return float(fn(inputs, kwargs or {}))


# ---- the synthesis registry: what an LLM would emit from each metric's (Exa-confirmed) definition ----
# Each entry: aliases, canonical inputs, the synthesised recompute source, the grounding definition, and the
# reference oracle + case generator used to VALIDATE it. These three are real metrics absent from the
# beachhead catalog; validation cross-checks against sklearn/scipy.
_MCC = '''
def recompute(I, K):
    yt, yp = I["y_true"], I["y_pred"]
    classes = sorted(set(yt) | set(yp), key=str)
    idx = {c: i for i, c in enumerate(classes)}
    n, s = len(classes), len(yt)
    Cm = [[0] * n for _ in range(n)]
    for a, b in zip(yt, yp):
        Cm[idx[a]][idx[b]] += 1
    t = [sum(Cm[k]) for k in range(n)]
    p = [sum(Cm[r][k] for r in range(n)) for k in range(n)]
    c = sum(Cm[k][k] for k in range(n))
    cov = c * s - sum(p[k] * t[k] for k in range(n))
    d1 = s * s - sum(pp * pp for pp in p)
    d2 = s * s - sum(tt * tt for tt in t)
    denom = math.sqrt(d1 * d2)
    return cov / denom if denom else 0.0
'''

_KAPPA = '''
def recompute(I, K):
    yt, yp = I["y_true"], I["y_pred"]
    classes = sorted(set(yt) | set(yp), key=str)
    idx = {c: i for i, c in enumerate(classes)}
    n, s = len(classes), len(yt)
    Cm = [[0] * n for _ in range(n)]
    for a, b in zip(yt, yp):
        Cm[idx[a]][idx[b]] += 1
    po = sum(Cm[k][k] for k in range(n)) / s
    t = [sum(Cm[k]) for k in range(n)]
    p = [sum(Cm[r][k] for r in range(n)) for k in range(n)]
    pe = sum(t[k] * p[k] for k in range(n)) / (s * s)
    return (po - pe) / (1 - pe) if (1 - pe) else 0.0
'''

_SPEARMAN = '''
def recompute(I, K):
    x = I.get("x", I.get("y_true"))
    y = I.get("y", I.get("y_pred"))
    def ranks(a):
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
    rx, ry = ranks(x), ranks(y)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return cov / (sx * sy) if sx * sy else 0.0
'''

SYNTH_REGISTRY = {
    "mcc": {
        "aliases": ["mcc", "matthews_corrcoef", "matthews correlation coefficient", "phi coefficient",
                    "matthews correlation"],
        "inputs": ["y_true", "y_pred"], "code": _MCC,
        "definition": "Matthews correlation coefficient: (TP·TN − FP·FN) / sqrt((TP+FP)(TP+FN)(TN+FP)(TN+FN)); "
                      "generalised via the R_k confusion-matrix form. Range [-1, 1].",
        "source": "exa:en.wikipedia.org/wiki/Phi_coefficient",
    },
    "cohen_kappa": {
        "aliases": ["cohen_kappa", "cohen_kappa_score", "cohen's kappa", "kappa", "cohens kappa"],
        "inputs": ["y_true", "y_pred"], "code": _KAPPA,
        "definition": "Cohen's kappa: (p_o − p_e) / (1 − p_e), agreement corrected for chance, where p_o is "
                      "observed agreement and p_e the expected-by-chance agreement.",
        "source": "exa:en.wikipedia.org/wiki/Cohen%27s_kappa",
    },
    "spearman": {
        "aliases": ["spearman", "spearmanr", "spearman correlation", "spearman rank correlation", "rho"],
        "inputs": ["x", "y"], "code": _SPEARMAN,
        "definition": "Spearman rank correlation: Pearson correlation of the rank variables (average ranks "
                      "for ties).",
        "source": "exa:en.wikipedia.org/wiki/Spearman%27s_rank_correlation_coefficient",
    },
}

_ALIAS_TO_METRIC = {a.lower(): m for m, e in SYNTH_REGISTRY.items() for a in list(e["aliases"]) + [m]}


def _registry_metric(metric: str):
    return _ALIAS_TO_METRIC.get((metric or "").strip().lower())


# ---- LLM synthesis (productionized): AI proposes a recompute, _validate_synth disposes -------------
# The one remaining piece of §B.3 productionization: instead of a hand-written formula, ask Claude to emit
# `def recompute(I, K) -> float` from the (Exa-grounded) definition. It is BEST-EFFORT + GATED exactly like
# the planner: no ANTHROPIC_API_KEY / no SDK / any error → None, and the registry code is the trusted
# fallback. Crucially the output is NEVER trusted until _validate_synth cross-checks it against a reference
# oracle on random inputs — so a wrong/prompt-injected formula fails validation and is discarded (the FCR gate
# is the validation, not the model). The synthesized code still runs only in the restricted exec_formula
# namespace (safe builtins + math, no imports).
_SYNTH_MODEL = os.environ.get("CALMA_SYNTH_MODEL", "claude-sonnet-5").strip() or "claude-sonnet-5"

_SYNTH_SYSTEM = (
    "You implement a single metric as PURE PYTHON. Return ONLY a function `def recompute(I, K) -> float` "
    "where I is a dict of the metric's canonical inputs (e.g. y_true/y_pred, or candidate/references) and K "
    "is a dict of options. Use ONLY the `math` module and Python builtins — NO imports, NO file/network/OS "
    "access (the code runs in a locked-down namespace and anything else will fail). Implement the metric "
    "exactly from the definition given; do not approximate. The result is validated against a reference "
    "implementation on random inputs before it is ever trusted, so correctness is mandatory."
)

_SYNTH_SCHEMA = {
    "type": "object",
    "properties": {"code": {"type": "string", "description": "a `def recompute(I, K) -> float` body, "
                            "pure-Python, math + builtins only, no imports."}},
    "required": ["code"], "additionalProperties": False,
}


def _llm_synthesize(metric: str, definition: str, model: str | None = None):
    """Ask Claude to emit a `def recompute(I, K)` for `metric` from its definition. Returns the code string,
    or None (no key / SDK / error / unusable output). Isolated so tests can stub it without the SDK or a call."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return None
    try:
        import json  # noqa: PLC0415
        client = anthropic.Anthropic(max_retries=2, timeout=45.0)
        resp = client.messages.create(
            model=(model or _SYNTH_MODEL), max_tokens=1500, system=_SYNTH_SYSTEM,
            output_config={"format": {"type": "json_schema", "schema": _SYNTH_SCHEMA}},
            messages=[{"role": "user", "content": "Metric: %s\nDefinition: %s" % (metric, definition[:2000])}],
        )
        if getattr(resp, "stop_reason", None) == "max_tokens":
            return None
        raw = next((getattr(b, "text", None) for b in resp.content if getattr(b, "type", None) == "text"), None)
        if not raw:
            return None
        code = json.loads(raw).get("code")
        return code if (isinstance(code, str) and "def recompute" in code) else None
    except Exception:  # noqa: BLE001 — auth/rate/network/parse → best-effort, fall back to the registry code
        return None


# ---- text/IR reference oracles for validating a SYNTHESIZED text metric (guide §B.3) ----------------
# Used ONLY at validation time, ONLY when the reference library is installed — 'validate on random inputs of
# the correct type' (text/rankings, not floats). The real pytrec_eval empty-qrels bug (NDCG>1, issue #57) is
# guarded: every generated ndcg case has >=1 relevant doc, so we never validate against a wrong reference.
def _nonempty_qrels_case(rng):
    n = rng.randint(4, 12)
    rels = [rng.randint(0, 3) for _ in range(n)]
    if sum(rels) == 0:                       # guard the empty-qrels reference bug (pytrec_eval #57)
        rels[rng.randint(0, n - 1)] = rng.randint(1, 3)
    return {"relevances": [float(r) for r in rels]}


def _text_oracle(metric: str, rng):
    """(case_generator, refval_fn, why). case/refval are None when no installed library can serve as the
    oracle for `metric` (→ _validate_synth refuses; fail-closed). Best-effort by design."""
    m = (metric or "").strip().lower()
    if m in ("bleu", "sacrebleu"):
        try:
            import sacrebleu  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            return None, None, "sacrebleu not installed (no BLEU oracle) — fail closed"
        vocab = "the a cat dog runs fast on mat over under quick brown fox".split()

        def case():
            hyp = " ".join(rng.choice(vocab) for _ in range(rng.randint(6, 14)))
            ref = " ".join(rng.choice(vocab) for _ in range(rng.randint(6, 14)))
            return {"candidate": hyp, "references": [ref]}

        def refval(inp):
            return float(sacrebleu.corpus_bleu([inp["candidate"]], [[inp["references"][0]]],
                                               tokenize="none").score) / 100.0
        return case, refval, "sacrebleu"
    if m in ("ndcg", "ndcg_score"):
        def refval(inp):
            return C.recompute("ndcg", inp, {})["value"]    # sklearn-validated catalog nDCG, empty-qrels-guarded
        return (lambda: _nonempty_qrels_case(rng)), refval, "catalog-ndcg (sklearn-validated)"
    return None, None, "no reference oracle for %r" % metric


# ---- validation: cross-check the synthesised code against a reference oracle on random data ----------
def _validate_synth(metric: str, code: str, trials: int = 40, tol: float = 1e-9):
    """Run the synthesised formula on random inputs and compare to a trusted reference (sklearn/scipy).
    Returns (ok, evidence). Refuses (ok=False) if any trial diverges beyond tol — never trust an
    unvalidated formula."""
    rng = random.Random(0xC0FFEE)
    try:
        if metric in ("mcc", "cohen_kappa"):
            from sklearn.metrics import cohen_kappa_score, matthews_corrcoef  # noqa: PLC0415
            ref = matthews_corrcoef if metric == "mcc" else cohen_kappa_score

            def case():
                n = rng.randint(8, 200)
                k = rng.randint(2, 4)
                return {"y_true": [rng.randint(0, k - 1) for _ in range(n)],
                        "y_pred": [rng.randint(0, k - 1) for _ in range(n)]}

            def refval(inp):
                return float(ref(inp["y_true"], inp["y_pred"]))
        elif metric == "spearman":
            from scipy.stats import spearmanr  # noqa: PLC0415

            def case():
                n = rng.randint(8, 200)
                return {"x": [rng.gauss(0, 1) for _ in range(n)], "y": [rng.gauss(0, 1) for _ in range(n)]}

            def refval(inp):
                r = spearmanr(inp["x"], inp["y"])
                return float(getattr(r, "correlation", getattr(r, "statistic", float("nan"))))
        else:
            # TEXT / IR metrics: generate TEXT/ranking cases (not floats) and validate against the reference
            # LIBRARY when installed (guide §B.3: 'validate on random inputs of the correct type'). Best-
            # effort — absent the lib we refuse (fail-closed), never trust an un-cross-checked text formula.
            case, refval, why = _text_oracle(metric, rng)
            if case is None:
                return False, {"method": why}
    except Exception as e:  # noqa: BLE001 - the validation stack is missing -> cannot trust
        return False, {"method": "validation deps unavailable: %s" % e}

    max_err = 0.0
    for _ in range(trials):
        inp = case()
        try:
            got = exec_formula(code, inp, {})
            want = refval(inp)
        except Exception as e:  # noqa: BLE001
            return False, {"method": "raised during validation: %s" % e}
        if want == want:  # skip degenerate reference (NaN on constant input)
            max_err = max(max_err, abs(got - want))
            if abs(got - want) > tol:
                return False, {"method": "diverged from reference", "max_err": abs(got - want)}
    return True, {"method": "cross-checked vs reference oracle", "trials": trials, "max_err": max_err}


# cost telemetry: how many times the Exa fallback actually hit the network this process (cache hits don't
# count). Banked formulas mean a metric is Exa'd at most once ever, but this tracks the live spend.
EXA_CALLS = 0


def exa_call_count() -> int:
    return EXA_CALLS


def _exa_define(metric: str):
    """Fetch a metric's canonical definition via the Exa API when EXA_API_KEY is set (production path).
    Returns a definition string or None. In the prototype the registry already carries Exa-confirmed
    definitions, so a miss here is non-fatal."""
    key = os.environ.get("EXA_API_KEY")
    if not key:
        return None
    global EXA_CALLS
    EXA_CALLS += 1                                    # a real (paid) Exa request is about to fire
    try:
        import json
        import urllib.request  # noqa: PLC0415
        body = json.dumps({"query": "%s metric definition and formula" % metric,
                           "numResults": 3, "contents": {"text": True}}).encode()
        req = urllib.request.Request("https://api.exa.ai/search", data=body,
                                     headers={"x-api-key": key, "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310
            data = json.loads(r.read())
        return " ".join((res.get("text") or "")[:1500] for res in data.get("results", []))[:4000]
    except Exception:  # noqa: BLE001
        return None


def _synthesize_and_validate(metric: str, store):
    """Synthesise a candidate formula (registry = the LLM's output, grounded by Exa) and validate it.
    Banks it in the store on success; returns the FormulaRecord or None."""
    key = _registry_metric(metric)
    if not key:
        return None
    entry = SYNTH_REGISTRY[key]
    definition = str(entry["definition"])
    exa = _exa_define(metric)  # production: re-ground + drive the LLM synth from fresh retrieval
    if exa:
        definition = definition + "\n\n[exa] " + exa[:500]
    # AI proposes: Claude emits a recompute from the grounded definition (best-effort). Determinism disposes:
    # validate it against the reference oracle; if the LLM code is unavailable or fails validation, fall back
    # to the hand-grounded registry code (also validated). NEVER bank an unvalidated formula.
    llm_code = _llm_synthesize(key, definition)
    code, source = (llm_code, str(entry["source"]) + "+llm") if llm_code else (str(entry["code"]), str(entry["source"]))
    ok, evidence = _validate_synth(key, code)
    if not ok and llm_code:                       # the LLM's guess didn't validate → fall back to registry code
        code, source = str(entry["code"]), str(entry["source"])
        ok, evidence = _validate_synth(key, code)
    if not ok:
        return None
    rec = S.FormulaRecord(metric=key, aliases=list(entry["aliases"]), inputs=list(entry["inputs"]), code=code,
                          definition=definition, source=source, validation=evidence)
    store.add(rec)
    return rec


# ---- the public resolver ---------------------------------------------------------------------------
def _result(value, *, degenerate=False, provenance="", note="", formula=""):
    return {"value": float(value), "degenerate": bool(degenerate), "note": note,
            "provenance": provenance, "formula": formula, "terms": {}}


def recompute_any(metric: str, inputs: dict, kwargs: dict | None = None, store=None):
    """Recompute `metric` from `inputs` using the best trusted source: catalog → store → synth → none.
    Returns a catalog-style Result dict with a `provenance` field. Fail-closed on a true miss."""
    cid = C.canonical(metric)
    if cid:
        r = C.recompute(cid, inputs, kwargs)
        r["provenance"] = "catalog"
        r.setdefault("formula", cid)
        return r
    # learned / embedding metric (BERTScore/BLEURT/COMET) — fail closed: there is NO independent recompute
    # (reproducing it means re-running the same neural checkpoint, which is the thing under test). This keeps
    # a non-independent number out of CONFIRMED → REPRODUCED-ONLY with an honest reason. (guide §B.3 (c))
    lname = C.learned_metric(metric)
    if lname:
        return _result(float("nan"), degenerate=True, provenance="learned",
                       note="%s is a learned/embedding metric — no independent recompute is possible "
                            "(it would require re-running the same neural checkpoint, not an independent "
                            "oracle)" % lname)
    # the lifted 626-recipe catalog (the previous engine's trusted math)
    try:
        from recipes import adapter as RA  # noqa: PLC0415 - lazy; recipes is a top-level spike package
        rr = RA.recompute_recipe(metric, inputs, kwargs)
        if rr is not None and not rr.get("degenerate"):
            return rr
    except Exception:  # noqa: BLE001 - recipes unavailable → fall through to the flywheel
        pass
    store = store or S.get_store()
    hit = store.lookup(metric, text=metric)
    if hit:
        rec, score = hit
        try:
            return _result(exec_formula(rec.code, inputs, kwargs), provenance="store:%s" % store.name,
                           note="reused validated formula (match %.2f)" % score, formula=rec.metric)
        except Exception as e:  # noqa: BLE001
            return _result(float("nan"), degenerate=True, provenance="store:%s" % store.name,
                           note="stored formula failed: %s" % e)
    rec = _synthesize_and_validate(metric, store)
    if rec:
        try:
            return _result(exec_formula(rec.code, inputs, kwargs), provenance="synth",
                           note="synthesized + validated (%s, max_err %.1e)"
                           % (rec.validation.get("method", ""), rec.validation.get("max_err", 0.0)),
                           formula=rec.metric)
        except Exception as e:  # noqa: BLE001
            return _result(float("nan"), degenerate=True, provenance="synth", note="synth exec failed: %s" % e)
    return _result(float("nan"), degenerate=True, provenance="none",
                   note="metric %r not in catalog, store, or synthesisable set" % metric)
