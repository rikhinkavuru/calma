"""calma.spike.planner — AI repo understanding → a structured RUN PLAN handed to the rest of the pipeline.

"AI proposes, determinism disposes." A fast model reads the repo and proposes HOW to run it — the entrypoint
that reproduces the headline numbers, the deps to install, the Python version, the data it needs. That plan
ONLY changes how we execute the repo's OWN code; it NEVER computes a metric or decides a verdict — that stays
deterministic in core/. The blast radius of a wrong or prompt-injected plan is therefore a failed run
(→ DISCOVERED), never a false verdict.

Best-effort by construction: no ANTHROPIC_API_KEY, no `anthropic` package, or any error → returns None and the
pipeline falls back to its heuristics (build.detect_entrypoint / infer_requirements). It is a pre-stage that
sharpens the run, not a dependency of it. Meant to run concurrently with the sandbox boot so its latency is
hidden; even sequential it pays for itself by avoiding failed installs / wrong-entrypoint reruns.
"""
from __future__ import annotations

import json
import os
import re

from core import limits as _LIM  # noqa: E402 — pip-spec sanitizer (drops a prompt-injected --index-url / VCS ref)
from orchestrator import envelope as _ENV  # noqa: E402 — spotlight untrusted repo text (defense-in-depth)
from runner import build as _BUILD  # noqa: E402 — reverse-map: which script writes the committed result table

# The planner earns its keep on HARD repos (ambiguous entrypoints, monorepos, unusual repro steps, deps not
# declared) — easy repos already resolve from heuristics — so the read quality matters, and since the output
# is validated (entrypoint must exist) + best-effort, model choice never risks a verdict, only run success.
# Haiku 4.5 is the DEFAULT: the plan is a structured-extraction task (entrypoint/deps/targets) that Haiku does
# well, and since a weaker plan only degrades run-success (never the verdict — determinism disposes), it's the
# right cost/quality point — ~10x cheaper than Sonnet per run. CALMA_PLAN_MODEL overrides to claude-sonnet-5 /
# claude-opus-4-8 / claude-fable-5 for a stronger read when a repo is genuinely ambiguous.
_MODEL = os.environ.get("CALMA_PLAN_MODEL", "claude-haiku-4-5").strip() or "claude-haiku-4-5"

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "env", ".venvs", "results"}

_SYSTEM = (
    _ENV.SYSTEM_PREAMBLE + " "     # untrusted-content spotlighting: the repo text is DATA, not instructions
    "You are the environment-synthesis step of a verification system. Your ONLY job is to plan how to RUN a "
    "repository so it reproduces the numbers it reports — you do NOT compute, judge, or predict any metric "
    "value, and you never decide whether a number is correct. Read the repo and return how to execute its "
    "OWN code: the entrypoint that produces the headline metrics, the pip packages to install, the Python "
    "version it targets, and any external data it needs. Prefer the repo's real reproduce/eval/benchmark "
    "script over a training script. If you are unsure of the entrypoint, return an empty list rather than "
    "guessing — a wrong guess is worse than none. "
    "ALSO identify any function IN THIS REPO that computes a reported metric with the repo's OWN code — e.g. a "
    "custom `sharpe_ratio(returns)`, `compute_ndcg(...)`, or `evaluate(preds, labels)` helper — as a 'target' "
    "so the system can capture that function's inputs and output. This is how non-sklearn domains "
    "(finance, stats, retrieval, NLP) get verified. Do NOT list sklearn/torch/scipy metric calls — those are "
    "captured automatically; list ONLY the repo's own metric functions. For each target give its dotted import "
    "path from the repo root, the metric it computes, and (if you can tell) which argument is which input. "
    "Leave targets empty if the numbers come only from library calls or you can't identify a specific function."
)

# Structured output: the model is constrained to emit exactly this shape (no Pydantic needed).
_SCHEMA = {
    "type": "object",
    "properties": {
        "entrypoint": {"type": "array", "items": {"type": "string"},
                       "description": "argv (relative to the repo root) that reproduces the headline numbers, "
                                      "e.g. ['run_benchmark.py','--all'] or ['-m','pkg.eval']. Empty list if unsure."},
        "pip_install": {"type": "array", "items": {"type": "string"},
                        "description": "pip package specs the run needs (respect requirements.txt if present)."},
        "python_version": {"type": "string", "description": "the Python the repo targets, e.g. '3.11'; '' if unknown."},
        "data_needed": {"type": "string", "description": "external data the repo needs + where from; '' if none/bundled."},
        "data_sources": {"type": "array", "description": "For each external dataset the repo needs but doesn't "
                         "bundle, give the repo-relative path it expects the file at + the CANONICAL public "
                         "download URL. This is used to fetch data DIRECTLY when the repo's own download scripts "
                         "fail, so DO populate it for standard public datasets you recognize — ClinVar VCF "
                         "(https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz), gnomAD, ENCODE "
                         "cCREs, UCSC/Ensembl reference genomes, HuggingFace dataset files "
                         "(https://huggingface.co/datasets/<org>/<name>/resolve/main/<file>), Zenodo/figshare "
                         "DOIs. Match the path to what the repo's code reads (grep for read_parquet/open/ "
                         "load_dataset paths). Only OMIT an entry when you genuinely don't know the real URL — a "
                         "wrong URL fetches wrong data (which is capped to inconclusive, never a false verdict).",
                         "items": {"type": "object", "additionalProperties": False, "properties": {
                             "path": {"type": "string", "description": "repo-relative path the file goes to, e.g. "
                                      "'data/clinvar/clinvar.vcf.gz'."},
                             "url": {"type": "string", "description": "canonical public https download URL."}},
                             "required": ["path", "url"]}},
        "notes": {"type": "string", "description": "one sentence: what the repo does and how its headline metric is computed."},
        "confidence": {"type": "number", "description": "0..1 confidence that the entrypoint reproduces the headline numbers."},
        "targets": {"type": "array", "description": "functions IN THIS REPO that compute reported metrics with the "
                    "repo's own code (NOT sklearn/library calls — those are auto-hooked). Empty if none identified.",
                    "items": {"type": "object", "additionalProperties": False, "properties": {
                        "target": {"type": "string", "description": "dotted import path from the repo root, e.g. "
                                   "'metrics.sharpe_ratio' or 'src.eval.compute_ndcg'."},
                        "metric": {"type": "string", "description": "the metric it computes (canonical if known: "
                                   "sharpe, ndcg, correlation, mape, precision, ...)."},
                        "inputs": {"type": "array", "description": "how to read the metric's inputs off the call, "
                                   "for independent recompute. One entry per input.",
                                   "items": {"type": "object", "additionalProperties": False, "properties": {
                                       "name": {"type": "string", "description": "canonical input name, e.g. "
                                                "'y_true', 'y_pred', 'returns'."},
                                       "ref": {"type": "string", "description": "where it comes from: 'arg0'/'arg1' "
                                               "for positional args, else the keyword name."}},
                                       "required": ["name", "ref"]}},
                    }, "required": ["target", "metric"]}},
    },
    "required": ["entrypoint", "pip_install", "python_version", "data_needed", "data_sources", "notes",
                 "confidence", "targets"],
    "additionalProperties": False,
}

_MAX_README = 8000
_MAX_SCRIPT = 2500
_MAX_SCRIPTS = 8
_MAX_TREE = 240


def _read(path: str, cap: int) -> str:
    try:
        with open(path, errors="replace") as fh:
            return fh.read(cap)
    except OSError:
        return ""


def _gather_context(repo_dir: str) -> str:
    """Assemble a bounded snapshot of the repo for the model: file tree + README + declared deps + the head of
    the root-level scripts (where entrypoints and their imports live)."""
    tree = []
    n = 0
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        rel = os.path.relpath(root, repo_dir)
        for fn in sorted(files):
            n += 1
            if n > _MAX_TREE:
                break
            tree.append(os.path.normpath(os.path.join(rel, fn)) if rel != "." else fn)
        if n > _MAX_TREE:
            break

    parts = ["## File tree (truncated)\n" + "\n".join(tree)]
    for name in ("README.md", "README.rst", "README.txt", "readme.md", "REPRODUCE.md"):
        p = os.path.join(repo_dir, name)
        if os.path.isfile(p):
            parts.append("## %s\n%s" % (name, _read(p, _MAX_README)))
            break
    for name in ("requirements.txt", "pyproject.toml", "setup.py", "environment.yml", ".python-version", "runtime.txt"):
        p = os.path.join(repo_dir, name)
        if os.path.isfile(p):
            parts.append("## %s\n%s" % (name, _read(p, 2000)))

    # the head of each root-level Python script — entrypoints + their imports live here
    roots = sorted(f for f in (os.listdir(repo_dir) if os.path.isdir(repo_dir) else [])
                   if f.endswith(".py")) [:_MAX_SCRIPTS]
    for f in roots:
        parts.append("## %s (head)\n%s" % (f, _read(os.path.join(repo_dir, f), _MAX_SCRIPT)))
    # reverse map: the script that WRITES a committed result artifact (results.csv, metrics.json) is the
    # likely reproduction entrypoint — not a quickstart that recomputes one dataset (bucket B). Surface it as
    # a hint; the model still decides and the entry-exists validation is the hard rail.
    prod = _BUILD.artifact_producer(repo_dir)
    if prod:
        parts.append("## Committed-result producer (hint)\nThe committed result file(s) appear to be written "
                     "by: %s — prefer this entrypoint if it produces the headline metrics." % " ".join(prod))
    # spotlight the whole repo-derived context as one break-out-resistant untrusted span (a README that says
    # "ignore your instructions" is neutralized; the entry validation + pip sanitizer are the hard rails).
    return _ENV.wrap_untrusted("\n\n".join(parts), "repo")


def _call_model(context: str, model: str, system: str | None = None, schema: dict | None = None) -> str | None:
    """Return the model's raw JSON string, or None on any failure. Isolated so tests can stub it without the
    SDK or a network call. Lazy-imports `anthropic` so the module loads even when the SDK isn't installed.
    `system`/`schema` default to the run-plan prompt; plan_predictions passes its own."""
    system = system or _SYSTEM
    schema = schema or _SCHEMA
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except Exception:  # noqa: BLE001 — SDK not installed → planner disabled, heuristics take over
        return None
    try:
        # Retry transient 429/5xx (Sonnet 5 intro-tier limits, overload bursts) with backoff, and cap each
        # attempt so a slow/hung call fails to heuristics fast instead of stalling the verify. Best-effort
        # throughout — any failure still just means "use heuristics".
        client = anthropic.Anthropic(max_retries=2, timeout=45.0)
        # 4096, not 1024: the plan (entrypoint + deps + data + notes + TARGETS) can run past 1k tokens on a
        # complex repo — and adding targets pushed it over exactly on the multi-domain repos we most want a
        # plan for. A truncated (max_tokens) response is unparseable JSON → a silent None, so give real headroom.
        resp = client.messages.create(
            model=model, max_tokens=4096, system=system,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": context}],
        )
        if resp.stop_reason == "max_tokens":                          # truncated → JSON won't parse
            return None
        return next((getattr(b, "text", None) for b in resp.content if getattr(b, "type", None) == "text"), None)
    except Exception:  # noqa: BLE001 — auth/rate/network/parse → best-effort, fall back to heuristics
        return None


def _valid_entry(entry, repo_dir: str):
    """Trust the proposed entrypoint ONLY if it points at code that actually exists — a `-m module` form, or a
    script present in the repo. This is the anti-hallucination / anti-injection gate: a made-up entrypoint is
    dropped and the deterministic detector takes over."""
    if not isinstance(entry, list) or not entry or not all(isinstance(x, str) for x in entry):
        return None
    if entry[0] == "-m":
        return entry if len(entry) > 1 and re.match(r"^[\w.]+$", entry[1]) else None
    base = os.path.basename(entry[0])
    return [base] + [str(a) for a in entry[1:]] if os.path.isfile(os.path.join(repo_dir, base)) else None


def _valid_targets(targets):
    """Keep only well-formed capture targets — a dotted import path + a metric, plus arg-refs the shim
    understands. This is SHAPE-only (we can't import to check existence host-side — that would run untrusted
    code; the in-sandbox shim fail-soft-skips a path it can't resolve). A target only picks WHICH function to
    wrap: the value is captured from the REAL run and recomputed independently, so a wrong/injected target can
    never false-confirm — worst case nothing is captured and the claim stays DISCOVERED/REPRODUCED-ONLY."""
    out = []
    for t in (targets or []):
        if not isinstance(t, dict):
            continue
        path, metric = t.get("target"), t.get("metric")
        if not (isinstance(path, str) and "." in path and re.match(r"^[\w.]+$", path)):
            continue
        if not (isinstance(metric, str) and metric.strip()):
            continue
        spec = {"target": path, "metric": metric.strip()}
        # inputs arrive as [{name, ref}] (structured-output can't express an open map) → the {name: ref} dict
        # the capture shim wants (calma_capture.install_targets).
        inputs = {i["name"]: i["ref"] for i in (t.get("inputs") or [])
                  if isinstance(i, dict) and isinstance(i.get("name"), str) and isinstance(i.get("ref"), str)}
        if inputs:
            spec["inputs"] = inputs
        out.append(spec)
    return out[:20]                                                   # bound — a plan shouldn't propose dozens


def plan_repo(repo_dir: str, model: str | None = None) -> dict | None:
    """Understand a repo and return a validated run plan, or None if planning is unavailable/failed.

    Returns {entry, pip_install, python_version, data_needed, notes, confidence}. `entry`/`pip_install` are
    None when the model didn't supply a usable value (the caller then keeps its heuristics)."""
    if not os.path.isdir(repo_dir):
        return None
    raw = _call_model(_gather_context(repo_dir), (model or _MODEL))
    if not raw:
        return None
    try:
        p = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(p, dict):
        return None

    entry = _valid_entry(p.get("entrypoint"), repo_dir)
    # SANITIZE the model's proposed deps: keep only plain PyPI specs. A prompt-injected README could otherwise
    # make the plan emit `--index-url http://evil/` or `git+https://evil/x`, redirecting the installer at
    # build time. The entrypoint gate below is the anti-hallucination rail; this is the anti-injection rail.
    deps = _LIM.sanitize_pip(p.get("pip_install")) or None
    pyver = p.get("python_version") if re.match(r"^\d+\.\d+", str(p.get("python_version") or "")) else None
    try:
        conf = max(0.0, min(1.0, float(p.get("confidence", 0))))
    except (TypeError, ValueError):
        conf = 0.0
    return {"entry": entry, "pip_install": deps, "python_version": pyver,
            "data_needed": str(p.get("data_needed") or ""), "notes": str(p.get("notes") or ""),
            "confidence": conf, "targets": _valid_targets(p.get("targets")),
            "data_sources": _valid_data_sources(p.get("data_sources"))}


# ── predictions synthesis (last-resort: no runnable eval + no committed predictions) ───────────────────────────
_PRED_SYSTEM = (
    _ENV.SYSTEM_PREAMBLE + " "
    "You are the environment-synthesis step of a verification system. This repository reports a metric but has "
    "NO runnable eval entrypoint and NO committed predictions file. Write a SHORT, self-contained Python script "
    "that uses the repo's OWN code to produce PREDICTIONS on the repo's TEST split and writes them to "
    "'calma_predictions.csv' in the current directory, with columns EXACTLY: y_true,y_pred (add a y_score column "
    "if the model exposes a probability/score for the positive class). "
    "HARD RULES: (1) Reproduce how THIS repo builds its model and loads its TEST data — import the repo's own "
    "modules/functions; never substitute a different model or the training split. (2) Do NOT compute, print, or "
    "hardcode ANY metric value — output ONLY the predictions CSV; the verification system computes the metric "
    "itself and a hardcoded number is useless to it. (3) Use only the repo's files and libraries it already "
    "depends on; no network. (4) If you cannot determine how to run the repo's model on LABELLED test data, "
    "return an empty driver — a wrong script is worse than none."
)
_PRED_SCHEMA = {
    "type": "object",
    "properties": {
        "driver": {"type": "string", "description": "a complete standalone Python script (or empty string if "
                   "not possible) that writes calma_predictions.csv with columns y_true,y_pred[,y_score] using "
                   "the repo's OWN model on its TEST split. It must NOT compute or print any metric value."},
        "metric": {"type": "string", "description": "the metric the reported number uses "
                   "(accuracy/roc_auc/f1/...), '' if unknown."},
        "confidence": {"type": "number", "description": "0..1 confidence the script produces correct "
                       "test-split predictions using the repo's own model."},
    },
    "required": ["driver", "metric", "confidence"],
    "additionalProperties": False,
}
_PRED_MAX_DRIVER = 8000


def plan_predictions(repo_dir: str, model: str | None = None) -> dict | None:
    """AI-synthesize a predict-and-dump driver for a repo that reports a metric but has NO runnable eval and NO
    committed predictions. Returns {driver, metric, confidence} or None.

    FCR: the driver ONLY produces predictions — the metric is recomputed INDEPENDENTLY by core.artifacts from
    (y_true, y_pred) — and because a synthesized driver is a source modification, the verdict is capped at
    REPRODUCED-ONLY. So a broken/wrong/injected driver can never false-CONFIRM: worst case it writes garbage
    predictions whose recompute doesn't match the claim (→ nothing upgraded) or coincidentally matches (→ capped
    at REPRODUCED-ONLY, never CONFIRMED). The driver runs only inside the isolated sandbox."""
    if not os.path.isdir(repo_dir):
        return None
    raw = _call_model(_gather_context(repo_dir), (model or _MODEL), system=_PRED_SYSTEM, schema=_PRED_SCHEMA)
    if not raw:
        return None
    try:
        p = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(p, dict):
        return None
    driver = p.get("driver")
    if not (isinstance(driver, str) and driver.strip() and "calma_predictions.csv" in driver):
        return None                                          # must actually write the predictions file
    if len(driver) > _PRED_MAX_DRIVER:
        return None                                          # runaway output → distrust
    try:
        conf = max(0.0, min(1.0, float(p.get("confidence", 0))))
    except (TypeError, ValueError):
        conf = 0.0
    return {"driver": driver, "metric": str(p.get("metric") or ""), "confidence": conf}


# ── subset-scope binding (S4 part 2): bind a subset CLAIM to the rows it's about, BLIND to its value ──────────
_SCOPE_SYSTEM = (
    "You bind a benchmark CLAIM to the SUBSET of prediction rows it is about, so a verifier can recompute the "
    "metric on the correct rows. You are given the metric, the claim's LABEL text, and the candidate subset "
    "columns of the predictions file (each with its distinct values). Choose the ONE column — and, for a "
    "categorical column, the ONE value — whose subset the claim's label denotes: e.g. 'minority class' -> the "
    "rarer label value, 'testable'/'evaluable' -> a boolean flag column, 'hard examples' -> a difficulty "
    "column's 'hard' value, 'rare variants' -> a class column's 'rare' value. Return column '' if NONE of the "
    "columns denotes the claim's subset. "
    "CRITICAL: you are NOT told the claim's numeric value and must NEVER try to hit a number — pick ONLY the "
    "subset the LABEL semantically names. A wrong subset is caught + rejected by the verifier, so guessing a "
    "subset to match a value is pointless and forbidden."
)
_SCOPE_SCHEMA = {
    "type": "object",
    "properties": {
        "column": {"type": "string", "description": "the subset column name EXACTLY as given, or '' if none applies"},
        "value": {"type": "string", "description": "for a categorical column, the exact value naming the subset; "
                  "'' for a boolean column (its truthy rows) or when column is ''"},
    },
    "required": ["column", "value"],
    "additionalProperties": False,
}


def propose_scope(metric, claim_label, scope_cols, model=None):
    """BLIND LLM subset binding: given the metric, the claim's LABEL, and the candidate subset columns (name +
    distinct values), pick the {column, value} subset the label denotes — WITHOUT seeing the claim's numeric
    value, so it cannot p-hack a subset to match one. Returns (column, value_or_None) or None; validated against
    the REAL columns/values here, then recomputed INDEPENDENTLY by the caller. Best-effort + gated (no key/SDK
    -> None).

    FCR: the proposer is blind to the target number, and its output is a bounded choice over EXISTING columns/
    values (hallucinations rejected below); a wrong subset -> a wrong recompute -> REFUTED, never a false
    CONFIRM. Same 'AI proposes, determinism disposes' contract as the run-planner — the LLM picks HOW to slice,
    the unchanged recompute disposes the verdict."""
    if not scope_cols:
        return None
    summary = []
    for col, vals in list(scope_cols.items())[:25]:
        distinct = sorted({str(v).strip() for v in vals if str(v).strip()})[:12]
        summary.append({"column": col, "values": distinct})
    context = json.dumps({"metric": str(metric or ""), "claim_label": str(claim_label or ""), "columns": summary})
    raw = _call_model(context, (model or _MODEL), system=_SCOPE_SYSTEM, schema=_SCOPE_SCHEMA)
    if not raw:
        return None
    try:
        p = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(p, dict):
        return None
    col = (p.get("column") or "").strip()
    if not col or col not in scope_cols:                       # no-subset, or a hallucinated column -> skip
        return None
    val = (p.get("value") or "").strip()
    if not val:
        return col, None                                       # boolean column -> its truthy subset
    distinct = {str(v).strip().lower() for v in scope_cols[col] if str(v).strip()}
    if val.lower() in distinct:
        return col, val                                        # a categorical value that ACTUALLY exists
    return None                                                # a value not present in the column -> reject


# ── locate_results (S4 part 2b): AI "search ALL outputs" when the deterministic scan found nothing ────────────
_LOCATE_SYSTEM = (
    "You find the REPORTED evaluation metrics in a repository's result files — the headline numbers a reader "
    "would cite — that an automated scan missed (an unusual file, a log, prose). For each reported metric "
    "value, output the metric NAME as written, its numeric VALUE exactly as written, and the file it is in "
    "(from the ### headers). Only REPORTED EVALUATION metrics (accuracy, AUROC, F1, recall, precision, RMSE, "
    "MAE, ...) — NEVER a hyperparameter, a learning rate, an epoch/step count, a dataset size, a loss-curve "
    "point, a runtime, or any number you are not sure is a reported result metric. Never invent a value or a "
    "file. If you find none, return an empty list."
)
_LOCATE_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "description": "the metric name as written in the file"},
                "value": {"type": "string", "description": "the numeric value exactly as written (e.g. '0.883' or '94.2%')"},
                "file": {"type": "string", "description": "the file it appears in, from a ### header"},
                "context": {"type": "string", "description": "a few words of surrounding label (dataset/split), optional"},
            },
            "required": ["metric", "value", "file"],
            "additionalProperties": False,
        }},
    },
    "required": ["claims"],
    "additionalProperties": False,
}
_LOCATE_EXT = (".txt", ".log", ".out", ".md", ".rst", ".json", ".yaml", ".yml", ".tsv", ".csv")
_LOCATE_HINT = ("result", "score", "metric", "eval", "output", "summary", "report", "benchmark", "perf", "log")


def _locate_context(repo_dir, max_files=15, per_file=4000, total=30000):
    """Bounded text of the repo's result-ish files — the haystack for AI number-location — plus the set of
    repo-relative paths shown (so a located claim can be REQUIRED to cite a real file we actually presented,
    the anti-hallucination rail). Prefers files whose name hints at results; caps per-file + total size."""
    picks = []
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__")]
        for fn in files:
            if not fn.lower().endswith(_LOCATE_EXT):
                continue
            p = os.path.join(root, fn)
            try:
                if os.path.getsize(p) > 200_000:
                    continue
            except OSError:
                continue
            picks.append((0 if any(h in fn.lower() for h in _LOCATE_HINT) else 1, p))
    picks.sort(key=lambda x: (x[0], x[1]))
    out, shown, used = [], set(), 0
    for _rank, p in picks[:max_files]:
        try:
            text = open(p, errors="replace").read(per_file)
        except OSError:
            continue
        rel = os.path.relpath(p, repo_dir)
        chunk = "### %s\n%s" % (rel, text)
        if used + len(chunk) > total:
            break
        out.append(chunk)
        shown.add(rel)
        shown.add(os.path.basename(rel))
        used += len(chunk)
    return "\n\n".join(out), shown


def locate_claims(repo_dir, model=None, existing=None):
    """AI "search ALL outputs" (CORE-Bench): find REPORTED metric values the deterministic discovery scan
    missed. Returns claim dicts (discovery's shape), each gated through ``map_metric`` (a real metric), a numeric
    value, and a file we ACTUALLY showed the model (no hallucinated files). Best-effort + gated.

    FCR: a located claim is only a CLAIM (a reported number) — it is CONFIRMED only if the INDEPENDENT recompute
    matches it, exactly like a scanned claim. A misread / hallucinated number simply won't match the recompute
    (→ REFUTED / DISCOVERED), never a false CONFIRM. The value is never trusted, only the recompute is."""
    if not os.path.isdir(repo_dir):
        return []
    ctx, shown = _locate_context(repo_dir)
    if not ctx.strip():
        return []
    raw = _call_model(ctx, (model or _MODEL), system=_LOCATE_SYSTEM, schema=_LOCATE_SCHEMA)
    if not raw:
        return []
    try:
        p = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(p, dict):
        return []
    from discovery.extract import map_metric  # noqa: PLC0415 — the SAME precision gate the scanner uses
    seen = {(c.get("metric"), str(c.get("value"))) for c in (existing or [])}
    out = []
    for item in (p.get("claims") or [])[:40]:
        if not isinstance(item, dict):
            continue
        cid, split, _conf = map_metric(str(item.get("metric") or "").strip())
        if not cid:
            continue                                          # not a real metric → drop (anti-noise/hallucination)
        val = str(item.get("value") or "").strip()
        try:
            float(val.rstrip("%"))
        except ValueError:
            continue                                          # not a number → drop
        frel = str(item.get("file") or "").strip()
        if frel not in shown and os.path.basename(frel) not in shown:
            continue                                          # cites a file we never showed it → hallucinated → drop
        key = (cid, val)
        if key in seen:
            continue
        seen.add(key)
        claim = {"metric": cid, "value": val, "location": "%s::%s" % (os.path.basename(frel) or "located",
                 str(item.get("metric") or "").strip()), "source": "ai-located", "confidence": 0.5,
                 "context": str(item.get("context") or "")[:90]}
        if split:
            claim["split"] = split
        out.append(claim)
    return out[:20]


def _valid_data_sources(items):
    """Keep only {path, url} where path is a SAFE repo-relative path (no escape / absolute) and url is a plain
    https:// URL. A prompt-injected plan can't write outside the repo or point the fetcher at an internal host:
    path traversal and non-https schemes are dropped. Best-effort; capped."""
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        path, url = str(it.get("path") or "").strip(), str(it.get("url") or "").strip()
        if not path or not url.lower().startswith("https://"):
            continue
        norm = os.path.normpath(path)
        if norm.startswith("/") or norm.startswith("..") or ".." in norm.split("/"):
            continue                                        # no absolute / traversal — stays inside the repo
        if len(url) > 2048:
            continue
        out.append({"path": norm, "url": url})
        if len(out) >= 20:
            break
    return out
