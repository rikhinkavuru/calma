"""calma.spike.orchestrator.tools_static — the static assessment tools (build plan §4a, Phase 1).

Cheap, deterministic, ZERO-LLM tools that profile a repo. They back the biggest coverage-per-effort win in
the plan: most repos are made runnable from static signals alone, and the LLM is invoked (Phase 2) only to
rank approaches when these signals are ambiguous. Every tool is `@register`ed as ``kind="static"`` and is
individually FCR-safe — none computes a metric, binds a claim, or decides a verdict; a wrong answer only
changes HOW we try to run the repo (worse coverage), never a verdict (§0).

Where the plan says "wrap", we call the existing heuristic and add signals/ranking around it (no behavior
change to the wrapped code). Where it says "new", the tool is implemented here and closes a specific
make-runnable audit edge case (A1/A3/B1/B3/B4/B5/C1/C2), noted per-tool.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess

from core import artifacts as ART
from core import determinism as DET
from runner import build
from runner import target_discovery as TD

from . import registry as REG
from .types import EntryCand

# dirs never worth scanning for entrypoints/deps (mirrors build._SKIP_DIRS + venvs/caches). ".calma" is
# Calma's own artifact/cache dir — excluded so orchestrator state written under a repo can never perturb the
# fingerprint or masquerade as repo source.
_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "env", ".venvs", "node_modules", "site-packages",
              "dist-packages", "build", "dist", ".mypy_cache", ".pytest_cache", ".ipynb_checkpoints", ".calma",
              ".conda-envs"}
_MAX_WALK_FILES = 4000
_MAX_READ = 200_000


# ── shared helpers ────────────────────────────────────────────────────────────────────────────────────────────
def _walk(repo_dir: str):
    """Yield (abs_path, rel_path) for every file under repo_dir, skipping vendored/cache dirs. Bounded."""
    n = 0
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".egg-info")]
        for fn in sorted(files):
            p = os.path.join(root, fn)
            yield p, os.path.relpath(p, repo_dir)
            n += 1
            if n >= _MAX_WALK_FILES:
                return


def _safe_join(repo_dir: str, rel: str) -> str | None:
    """Resolve ``rel`` under ``repo_dir``, refusing any path that escapes the repo (path-traversal guard). The
    agent's read/grep tools go through this so a prompt-injected 'read ../../etc/passwd' cannot leave the tree."""
    if not isinstance(rel, str) or not rel:
        return None
    root = os.path.realpath(repo_dir)
    full = os.path.realpath(os.path.join(root, rel))
    if full == root or full.startswith(root + os.sep):
        return full
    return None


# ── thin inspection wrappers (used by the agent during ranking/revise) ────────────────────────────────────────
@REG.register("list_tree", kind="static", cost="free",
              summary="List repo files (relative paths), skipping vendored/cache dirs.")
def list_tree(repo_dir: str, limit: int = 400) -> list[str]:
    out = []
    for _abs, rel in _walk(repo_dir):
        out.append(rel)
        if len(out) >= max(1, int(limit)):
            break
    return out


@REG.register("read_file", kind="static", cost="free",
              summary="Read a repo-relative text file (path-traversal-guarded, size-bounded).")
def read_file(repo_dir: str, rel: str, cap: int = _MAX_READ) -> str:
    full = _safe_join(repo_dir, rel)
    if not full or not os.path.isfile(full):
        return ""
    try:
        with open(full, errors="replace") as fh:
            return fh.read(max(0, int(cap)))
    except OSError:
        return ""


@REG.register("grep", kind="static", cost="cheap",
              summary="Regex-search repo text files; returns [(rel, lineno, line)] (bounded).")
def grep(repo_dir: str, pattern: str, max_hits: int = 100) -> list[tuple[str, int, str]]:
    try:
        rx = re.compile(pattern)
    except re.error:
        return []
    hits: list[tuple[str, int, str]] = []
    for abs_p, rel in _walk(repo_dir):
        if os.path.splitext(rel)[1] in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".zip", ".gz"):
            continue
        try:
            with open(abs_p, errors="replace") as fh:
                for i, line in enumerate(fh, 1):
                    if rx.search(line):
                        hits.append((rel, i, line.rstrip("\n")[:300]))
                        if len(hits) >= max_hits:
                            return hits
        except OSError:
            continue
    return hits


@REG.register("ast_imports", kind="static", cost="cheap",
              summary="Top-level import roots of one Python file (wraps build._imported_roots).")
def ast_imports(repo_dir: str, rel: str) -> list[str]:
    full = _safe_join(repo_dir, rel)
    if not full or not os.path.isfile(full):
        return []
    return sorted(build._imported_roots(full))


# ── A4: ranked entrypoint candidates ──────────────────────────────────────────────────────────────────────────
_LANG_PREFIXES = ("r:", "julia:", "shell:", "sh:")


def _entry_kind(argv: list[str]) -> str:
    if not argv:
        return "script"
    if argv[0] == "-m":
        return "module"
    if argv[0].endswith(".ipynb") or argv[0].startswith("nb:"):
        return "notebook"
    if any(argv[0].startswith(p) for p in _LANG_PREFIXES):
        return "lang"
    return "script"


@REG.register("find_entrypoints", kind="static", cost="cheap",
              summary="Ranked entrypoint candidates (EntryCand[]) — wraps build.detect_entrypoint as the top "
                      "pick and enumerates the rest (A4).")
def find_entrypoints(repo_dir: str) -> list[EntryCand]:
    """A4 (repo commits to one entrypoint): return a RANKED list so the loop can try candidates in order,
    instead of the single best guess build.detect_entrypoint returns today. The deterministic detector's pick
    anchors the top; we then enumerate root scripts, runnable packages, subdir drivers, and notebooks with the
    signals that justify each rank. Best-effort and fail-closed: a wrong pick → wrong/empty capture →
    DISCOVERED/REFUTED, never a false CONFIRM."""
    cands: list[EntryCand] = []
    seen: set[tuple[str, ...]] = set()

    def add(argv, conf, signals):
        key = tuple(argv)
        if key in seen:
            return
        seen.add(key)
        cands.append(EntryCand(argv=list(argv), kind=_entry_kind(argv), confidence=conf, signals=list(signals)))

    # Confidence reflects real SIGNAL STRENGTH, not the detector's arbitrary tie-break. build.detect_entrypoint
    # returns ONE pick even when several root scripts are indistinguishable (first __main__-guarded wins); if we
    # stamped that pick 0.9 we'd hide a genuine coin-flip and skip the LLM tie-break it needs. So we score each
    # candidate from its own signals; a weak tie leaves the top two within the ambiguity band (→ LLM ranks).
    readme = build._readme_run_command(repo_dir)          # a strong signal when present
    roots = build._root_scripts(repo_dir)
    base = re.sub(r"[^a-z0-9]", "", os.path.basename(repo_dir.rstrip("/")).lower())
    # (signal, confidence-floor) predicates, evaluated per root script; a script's confidence is the max floor
    # of the signals it hits, and its signal list is why it ranked there (surfaced in the Assessment Report).
    readme_names = bool(readme) and readme[0] != "-m"     # a README `python <script> …` command (may carry args)
    for f in roots:
        signals, conf = [], 0.45
        stem = re.sub(r"[^a-z0-9]", "", f[:-3].lower())
        checks = [
            # match on the SCRIPT (readme[0]), not exact-equality — _readme_run_command now preserves the
            # author's safe args, so `readme` is e.g. [run.py, --config, cfg.yaml], not just [run.py].
            (readme_names and readme[0] == f, "README run command", 0.9),
            (len(roots) == 1, "only root script", 0.85),
            (f in build._ENTRY_NAMES, "known entrypoint name", 0.8),
            (bool(stem) and len(stem) >= 4 and (stem in base or base in stem), "name matches repo", 0.78),
            (build._has_main_guard(os.path.join(repo_dir, f)), "__main__ guard", 0.7),
            (bool(build._imported_roots(os.path.join(repo_dir, f)) & build._METRIC_LIBS),
             "imports a metric library", 0.65),
            (f[:-3] in ("run", "main", "eval", "evaluate", "reproduce", "benchmark", "experiment", "train"),
             "driver-ish name", 0.6),
        ]
        for hit, label, floor in checks:
            if hit:
                signals.append(label)
                conf = max(conf, floor)
        if signals:
            # when the README names this script WITH args, run it AS the README says (with the args) rather
            # than bare — a script that REQUIRES a --config/--input would otherwise argparse-fail.
            add(readme if (readme_names and readme[0] == f and len(readme) > 1) else [f], conf, signals)

    # a README `-m pkg.mod` command (validated by build to resolve) — strong
    if readme and readme[0] == "-m":
        add(readme, 0.88, ["README module command"])

    # CI is the ground-truth run command — the repo's own workflow executes it on every push, and it often
    # names the exact entrypoint a README omits. Path/module-validated in build.ci_workflow_signals.
    for argv in build.ci_workflow_signals(repo_dir).get("entry", []):
        add(argv, 0.86, ["CI workflow run step"])

    # a runnable package (`-m pkg` when pkg/__main__.py exists)
    pkg = build._runnable_package(repo_dir)
    if pkg:
        add(["-m", pkg], 0.6, ["package with __main__.py"])

    # a __main__-guarded driver in a source subdir
    sub = build._subdir_driver_script(repo_dir)
    if sub:
        add(sub, 0.55, ["subdir driver (metric-importing, __main__)"])

    # multi-script pipelines (A4): in a numbered pipeline (01_prep … 12_eval …), the headline metric is usually
    # computed by a LATE script (an eval/experiment stage), NOT the first/obvious one. Rank the metric-computing
    # scripts high so the loop runs THEM (after acquire materializes their inputs) and captures the number —
    # instead of picking a data-prep script that builds features but computes no metric.
    for argv, conf, signals in find_pipeline_entrypoints(repo_dir):
        add(argv, conf, signals)

    # notebooks (A1) — lowest default rank; the loop escalates to run_notebook when scripts fail
    for nb in find_notebooks(repo_dir):
        add(["nb:" + nb], 0.4, ["jupyter notebook"])

    # non-Python drivers (A3 long-tail: R/Julia) — lowest rank, tried when no Python entry captures. The number
    # is recomputed from the emitted predictions in Python, so these only need to RUN (four-unlocks §3).
    for lang, rel in find_lang_entrypoints(repo_dir):
        add(["%s:%s" % (lang, rel)], 0.35, ["%s script" % lang])

    # safety net: guarantee the deterministic detector's authoritative pick is represented (some picks — a
    # subdir/module form — may not have surfaced above), at a mid confidence so it never masks a real tie.
    top = build.detect_entrypoint(repo_dir)
    if top and tuple(top) not in seen:
        add(top, 0.6, ["build.detect_entrypoint pick"])

    cands.sort(key=lambda c: (-c.confidence, c.argv))
    return cands


# ── A4: multi-script pipeline entrypoint ranking ──────────────────────────────────────────────────────────────
# a numbered pipeline step: 01_x.py, 02-y.py, step3_z.py … (same shape acquire detects).
_PIPE_NUM = re.compile(r"^(?:step[_-]?)?(\d{1,3})[_.\- ]")
# metric FUNCTION calls / tokens — a script containing these actually COMPUTES a reported number (vs one that
# only builds features or downloads data). Deliberately specific (not just "imports sklearn").
_METRIC_CALLS = (
    "roc_auc_score", "roc_auc", "auroc", "auprc", "average_precision", "accuracy_score", "f1_score",
    "precision_score", "recall_score", "r2_score", "mean_squared_error", "mean_absolute_error", "log_loss",
    "ndcg_score", "matthews_corrcoef", "cohen_kappa", "balanced_accuracy", "confusion_matrix", "brier_score",
    "pearsonr", "spearmanr", "kendalltau", "sharpe", "classification_report", "precision_recall_curve",
)
# name signals: a metric/eval stage vs a data-prep stage.
_METRIC_NAMES = ("eval", "experiment", "exp", "result", "metric", "score", "auroc", "auc", "analysis",
                 "benchmark", "report", "assess", "calibration", "recovery", "confound")
_PREP_NAMES = ("download", "fetch", "get", "prepare", "prep", "preprocess", "clean", "setup", "install",
               "load", "build", "make", "feature", "featur", "ingest", "data")
_PIPE_DIRS = ("", "code", "scripts", "src", "pipeline", "analysis", "experiments", "notebooks")


def _numbered_scripts(repo_dir: str) -> list[tuple[int, str]]:
    """(order, repo-relative path) for numbered .py scripts in the first pipeline-ish dir that has them."""
    for base in _PIPE_DIRS:
        d = os.path.join(repo_dir, base) if base else repo_dir
        if not os.path.isdir(d):
            continue
        out = []
        try:
            for f in sorted(os.listdir(d)):
                m = _PIPE_NUM.match(f)
                if m and f.endswith(".py") and f != "__init__.py":
                    out.append((int(m.group(1)), os.path.join(base, f) if base else f))
        except OSError:
            continue
        if len(out) >= 3:                                    # a real pipeline, not two stray numbered files
            return out
    return []


def _score_pipeline_script(rel: str, text: str, order: int, n: int) -> tuple[float, list[str]]:
    """Likelihood a numbered-pipeline script COMPUTES the headline metric (→ the entrypoint to capture), from its
    metric-call content, name, position, and whether it writes a results file. Data-prep scripts score low."""
    low_name = os.path.basename(rel).lower()
    low_text = text.lower()
    conf, signals = 0.4, []
    if any(c in low_text for c in _METRIC_CALLS):
        conf += 0.3
        signals.append("computes a metric (metric-function call)")
    if any(w in low_name for w in _METRIC_NAMES):
        conf += 0.15
        signals.append("eval/experiment-stage name")
    if any(w in low_name for w in _PREP_NAMES):
        conf -= 0.2
        signals.append("data-prep-stage name")
    # writes a results/metrics artifact (the source of reported numbers)
    if re.search(r"(result|metric|score|auroc|calibration|summary)[\w./-]*\.(csv|json|tsv|parquet)", low_text):
        conf += 0.12
        signals.append("writes a results file")
    if n and order >= max(1, int(n * 0.5)):                  # later in the pipeline → likelier the eval stage
        conf += 0.1
        signals.append("late pipeline stage")
    return max(0.0, min(0.92, conf)), signals


@REG.register("find_pipeline_entrypoints", kind="static", cost="cheap",
              summary="Rank the metric-computing scripts of a numbered multi-script pipeline (A4).")
def find_pipeline_entrypoints(repo_dir: str) -> list[tuple]:
    """In a numbered pipeline, return (argv, confidence, signals) for the scripts that actually COMPUTE the
    reported metric — so the loop runs those (their inputs materialized by acquire) rather than a data-prep
    script. Empty when the repo isn't a numbered pipeline. Only the metric-computing scripts (conf ≥ 0.5) are
    returned; running them still flows through the unchanged fail-closed verify (a wrong pick → DISCOVERED)."""
    scripts = _numbered_scripts(repo_dir)
    if not scripts:
        return []
    n = len(scripts)
    out = []
    for order, rel in scripts:
        try:
            with open(os.path.join(repo_dir, rel), errors="replace") as fh:
                text = fh.read(60000)
        except OSError:
            continue
        conf, signals = _score_pipeline_script(rel, text, order, n)
        if conf >= 0.5:
            out.append(([rel], conf, signals))
    out.sort(key=lambda c: -c[1])
    return out[:4]                                           # the top few metric-computing stages


# ── A1: notebooks ─────────────────────────────────────────────────────────────────────────────────────────────
@REG.register("find_notebooks", kind="static", cost="free",
              summary="List *.ipynb files (A1: notebook-driven repos).")
def find_notebooks(repo_dir: str) -> list[str]:
    return [rel for _abs, rel in _walk(repo_dir) if rel.endswith(".ipynb")]


# non-Python entrypoints (A3 long-tail). Ranked below Python/notebook entries; drives run_lang in the polyglot
# E2B image. A driver-ish name (main/run/analyze/…) is preferred; else the shallowest script of each language.
_LANG_EXT = {".r": "r", ".jl": "julia"}
_LANG_DRIVER = ("main", "run", "analyze", "analysis", "eval", "evaluate", "reproduce", "benchmark", "experiment")


@REG.register("find_lang_entrypoints", kind="static", cost="free",
              summary="Ranked R/Julia driver scripts ((lang, relpath)[]) for run_lang (A3 long-tail).")
def find_lang_entrypoints(repo_dir: str) -> list[tuple[str, str]]:
    """Return (lang, relpath) candidates for R (.R) and Julia (.jl), one preferred driver per language. A
    driver-named script wins; otherwise the shallowest (fewest path segments, then shortest) script. Empty when
    the repo has no such scripts (the common Python case)."""
    by_lang: dict[str, list[str]] = {}
    for _abs, rel in _walk(repo_dir):
        lang = _LANG_EXT.get(os.path.splitext(rel)[1].lower())
        if lang:
            by_lang.setdefault(lang, []).append(rel)
    out: list[tuple[str, str]] = []
    for lang, rels in by_lang.items():
        driver = [r for r in rels if os.path.splitext(os.path.basename(r))[0].lower() in _LANG_DRIVER]
        pick = min(driver or rels, key=lambda r: (r.count("/"), len(r)))
        out.append((lang, pick))
    return out


# ── A3: make / shell / language ───────────────────────────────────────────────────────────────────────────────
_MAKE_TARGET = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*:(?!=)")


@REG.register("find_make_targets", kind="static", cost="free",
              summary="Parse Makefile targets (A3: make-driven repos).")
def find_make_targets(repo_dir: str) -> list[str]:
    for fn in ("Makefile", "makefile", "GNUmakefile"):
        p = os.path.join(repo_dir, fn)
        if os.path.isfile(p):
            try:
                text = open(p, errors="replace").read()
            except OSError:
                return []
            targets, seen = [], set()
            for line in text.splitlines():
                m = _MAKE_TARGET.match(line)
                if m and m.group(1) not in (".PHONY", ".DEFAULT") and m.group(1) not in seen:
                    seen.add(m.group(1))
                    targets.append(m.group(1))
            return targets
    return []


@REG.register("find_shell_scripts", kind="static", cost="free",
              summary="List *.sh scripts at root + common dirs (A3).")
def find_shell_scripts(repo_dir: str) -> list[str]:
    return [rel for _abs, rel in _walk(repo_dir)
            if rel.endswith(".sh") and rel.count(os.sep) <= 2]


@REG.register("detect_language", kind="static", cost="free",
              summary="Dominant repo language from file extensions (A3: python|r|julia|shell|mixed|unknown).")
def detect_language(repo_dir: str) -> str:
    counts = {"python": 0, "r": 0, "julia": 0, "shell": 0}
    ext = {".py": "python", ".r": "r", ".jl": "julia", ".sh": "shell"}
    for _abs, rel in _walk(repo_dir):
        e = os.path.splitext(rel)[1].lower()
        if e in ext:
            counts[ext[e]] += 1
    present = {k: v for k, v in counts.items() if v > 0}
    if not present:
        return "unknown"
    top = max(present, key=lambda k: present[k])
    # "mixed" only when a second language is a substantial fraction (>=30% of the top) — else the top wins
    others = sum(v for k, v in present.items() if k != top)
    return "mixed" if others >= max(1, present[top]) * 0.3 and len(present) > 1 else top


# ── B1: package manager + declared deps ───────────────────────────────────────────────────────────────────────
@REG.register("detect_pkg_manager", kind="static", cost="free",
              summary="Identify the dependency manager (B1): poetry|pyproject|pipenv|conda|requirements|setup|none.")
def detect_pkg_manager(repo_dir: str) -> str:
    pj = os.path.join(repo_dir, "pyproject.toml")
    if os.path.isfile(pj):
        try:
            txt = open(pj, errors="replace").read()
        except OSError:
            txt = ""
        if "[tool.poetry" in txt:
            return "poetry"
        if "[project" in txt:
            return "pyproject"
    if os.path.isfile(os.path.join(repo_dir, "Pipfile")):
        return "pipenv"
    if any(os.path.isfile(os.path.join(repo_dir, f)) for f in ("environment.yml", "environment.yaml", "conda.yml")):
        return "conda"
    if os.path.isfile(os.path.join(repo_dir, "requirements.txt")):
        return "requirements"
    if any(os.path.isfile(os.path.join(repo_dir, f)) for f in ("setup.py", "setup.cfg")):
        return "setup"
    return "none"


_DEP_LINE = re.compile(r'^\s*["\']?([A-Za-z0-9][A-Za-z0-9._-]*(?:\[[^\]]+\])?[^"\'#\n]*)')


def _conda_pip_and_conda(env_text: str) -> list[str]:
    """Extract dependency names from an environment.yml (both conda deps and a nested pip: list), best-effort
    without a YAML dependency (the sandbox may not have pyyaml). Handles the common two-space indent shape."""
    out, in_deps = [], False
    for raw in env_text.splitlines():
        line = raw.rstrip()
        if re.match(r"^\s*dependencies\s*:", line):
            in_deps = True
            continue
        if in_deps and re.match(r"^\s*-\s*pip\s*:\s*$", line):
            continue                                     # the `- pip:` marker; its sublist items match below
        if in_deps and re.match(r"^[A-Za-z]", line):     # a new top-level key ends the block
            in_deps = False
            continue
        m = re.match(r"^\s*-\s*(.+)$", line)
        if in_deps and m and not re.match(r"^\s*-\s*pip\s*:", line):
            spec = m.group(1).strip().strip("'\"")
            if spec and spec.lower() not in ("pip", "python") and not spec.startswith("python="):
                # conda uses `pkg=1.2` and `pkg==1.2`; normalize a single `=` to `==` for pip-style specs
                out.append(re.sub(r"(?<![<>=!~])=(?!=)", "==", spec.split()[0]))
    return out


@REG.register("read_declared_deps", kind="static", cost="cheap",
              summary="Declared deps from the resolved manifest (B1): pyproject/poetry/Pipfile/conda/setup.")
def read_declared_deps(repo_dir: str) -> list[str]:
    """B1: read declared deps from WHATEVER manifest the repo uses, not just requirements.txt. Returns a flat
    list of specs (best-effort, stdlib-only parsing). requirements.txt is handled by
    resolve_requirements_includes (B3); this covers the rest."""
    mgr = detect_pkg_manager(repo_dir)
    out: list[str] = []
    if mgr in ("pyproject", "poetry", "setup"):
        pj = os.path.join(repo_dir, "pyproject.toml")
        if os.path.isfile(pj):
            try:
                txt = open(pj, errors="replace").read()
            except OSError:
                txt = ""
            # PEP 621 [project] dependencies = ["a>=1", "b"]
            m = re.search(r"(?ms)^\s*dependencies\s*=\s*\[(.*?)\]", txt)
            if m:
                out += [s.strip().strip("'\"") for s in re.findall(r"['\"]([^'\"]+)['\"]", m.group(1))]
            # poetry [tool.poetry.dependencies] name = "^1.2"
            pm = re.search(r"(?ms)^\s*\[tool\.poetry\.dependencies\]\s*(.*?)(?:^\s*\[|\Z)", txt)
            if pm:
                for line in pm.group(1).splitlines():
                    dm = re.match(r'^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*=', line)
                    if dm and dm.group(1).lower() != "python":
                        out.append(dm.group(1))
        for fn in ("setup.py", "setup.cfg"):
            p = os.path.join(repo_dir, fn)
            if os.path.isfile(p):
                try:
                    txt = open(p, errors="replace").read()
                except OSError:
                    continue
                im = re.search(r"(?ms)install_requires\s*=\s*\[(.*?)\]", txt)
                if im:
                    out += [s.strip().strip("'\"") for s in re.findall(r"['\"]([^'\"]+)['\"]", im.group(1))]
    elif mgr == "pipenv":
        p = os.path.join(repo_dir, "Pipfile")
        if os.path.isfile(p):
            try:
                txt = open(p, errors="replace").read()
            except OSError:
                txt = ""
            pk = re.search(r"(?ms)^\s*\[packages\]\s*(.*?)(?:^\s*\[|\Z)", txt)
            if pk:
                for line in pk.group(1).splitlines():
                    dm = re.match(r'^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*=', line)
                    if dm:
                        out.append(dm.group(1))
    elif mgr == "conda":
        for fn in ("environment.yml", "environment.yaml", "conda.yml"):
            p = os.path.join(repo_dir, fn)
            if os.path.isfile(p):
                try:
                    out += _conda_pip_and_conda(open(p, errors="replace").read())
                except OSError:
                    pass
                break
    # de-dup, order-preserving
    seen, dedup = set(), []
    for s in out:
        s = s.strip()
        if s and s not in seen:
            seen.add(s)
            dedup.append(s)
    return dedup


# ── B3: requirements includes / editable-self ────────────────────────────────────────────────────────────────
@REG.register("resolve_requirements_includes", kind="static", cost="cheap",
              summary="Follow -r/-c includes in requirements.txt and flag `-e .`/`.` self-install (B3).")
def resolve_requirements_includes(repo_dir: str, start: str = "requirements.txt") -> dict:
    """B3: a requirements.txt often does `-r base.txt` / `-c constraints.txt` and `-e .` (install the repo
    itself). The naive reader dropped all of these. Return {"specs": [...], "self_install": bool,
    "constraints": [...]} with includes followed (bounded, cycle-safe)."""
    specs: list[str] = []
    constraints: list[str] = []
    self_install = False
    seen_files: set[str] = set()

    def _read(rel: str, depth: int):
        nonlocal self_install
        if depth > 8:
            return
        full = _safe_join(repo_dir, rel)
        if not full or full in seen_files or not os.path.isfile(full):
            return
        seen_files.add(full)
        base = os.path.dirname(rel)
        try:
            lines = open(full, errors="replace").read().splitlines()
        except OSError:
            return
        for raw in lines:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if line in (".", "-e .", "-e.") or re.match(r"^-e\s+\.$", line):
                self_install = True
                continue
            m = re.match(r"^-(?:r|-requirement)\s+(.+)$", line)
            if m:
                _read(os.path.normpath(os.path.join(base, m.group(1).strip())), depth + 1)
                continue
            m = re.match(r"^-(?:c|-constraint)\s+(.+)$", line)
            if m:
                inc = os.path.normpath(os.path.join(base, m.group(1).strip()))
                cfull = _safe_join(repo_dir, inc)
                if cfull and os.path.isfile(cfull):
                    try:
                        for cl in open(cfull, errors="replace").read().splitlines():
                            cl = cl.split("#", 1)[0].strip()
                            if cl and not cl.startswith("-"):
                                constraints.append(cl)
                    except OSError:
                        pass
                continue
            if line.startswith("-"):          # some other flag (--index-url etc.) — dropped (B-safety)
                continue
            specs.append(line)

    _read(start, 0)
    seen, dedup = set(), []
    for s in specs:
        if s not in seen:
            seen.add(s)
            dedup.append(s)
    return {"specs": dedup, "self_install": self_install, "constraints": constraints}


# ── B4: import → distribution name ────────────────────────────────────────────────────────────────────────────
_DISTS_CACHE: dict[str, list[str]] | None = None


def _packages_distributions() -> dict[str, list[str]]:
    global _DISTS_CACHE
    if _DISTS_CACHE is None:
        try:
            from importlib.metadata import packages_distributions
            _DISTS_CACHE = dict(packages_distributions())
        except Exception:  # noqa: BLE001 — older interpreter / import error → table-only mapping
            _DISTS_CACHE = {}
    return _DISTS_CACHE


@REG.register("import_to_dist", kind="static", cost="free",
              summary="Map a Python import root to its PyPI distribution (B4): installed metadata + alias table.")
def import_to_dist(import_root: str) -> str:
    """B4: the old 15-entry hand table missed most import→PyPI renames. Prefer the interpreter's own installed
    metadata (`packages_distributions()`, authoritative for anything installed), then build._PKG_ALIASES, then
    identity. Returns the best distribution name."""
    if not import_root:
        return import_root
    dists = _packages_distributions().get(import_root)
    if dists:
        return sorted(dists)[0]
    return build._PKG_ALIASES.get(import_root, import_root)


# ── B5: entry-seeded transitive imports ──────────────────────────────────────────────────────────────────────
@REG.register("entry_seeded_imports", kind="static", cost="cheap",
              summary="Third-party import roots reachable from the entrypoint via BFS over local modules (B5).")
def entry_seeded_imports(repo_dir: str, entry: list[str]) -> list[str]:
    """B5: infer_requirements scans up to 120 files in arbitrary filesystem order and can both miss the
    entrypoint's real deps and pull unrelated ones. Instead, BFS from the entrypoint file, follow LOCAL
    modules, and collect the THIRD-PARTY import roots actually reached. Falls back to [] for a `-m`/notebook
    entry the BFS can't seed from a single file (the caller then uses infer_requirements)."""
    if not entry:
        return []
    start_rel = None
    if entry[0] == "-m" and len(entry) > 1:
        base = os.path.join(repo_dir, *entry[1].split("."))
        for cand in (base + ".py", os.path.join(base, "__main__.py")):
            if os.path.isfile(cand):
                start_rel = os.path.relpath(cand, repo_dir)
                break
    elif entry[0].endswith(".py"):
        if os.path.isfile(os.path.join(repo_dir, entry[0])):
            start_rel = entry[0]
    if not start_rel:
        return []

    import sys
    stdlib = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}
    local_names = build._local_module_names(repo_dir)
    third_party: set[str] = set()
    visited: set[str] = set()
    queue = [start_rel]
    while queue and len(visited) < 500:
        rel = queue.pop()
        if rel in visited:
            continue
        visited.add(rel)
        full = os.path.join(repo_dir, rel)
        if not os.path.isfile(full):
            continue
        for root in build._imported_roots(full):
            if not root or root.startswith("_") or root in stdlib:
                continue
            if root in local_names:
                # follow the local module (a file at repo root or a package dir) to keep the BFS honest
                for cand in (root + ".py", os.path.join(root, "__init__.py")):
                    cpath = os.path.join(repo_dir, cand)
                    if os.path.isfile(cpath):
                        queue.append(os.path.relpath(cpath, repo_dir))
                continue
            third_party.add(import_to_dist(root))
    return sorted(third_party)


# ── C2: data references not present in the tree ───────────────────────────────────────────────────────────────
_DATA_REF = re.compile(
    r"""(?:open|read_csv|read_parquet|read_json|read_excel|load|np\.load|loadtxt|read_table|Path)\s*\(\s*"""
    r"""["']([^"']+\.(?:csv|parquet|json|jsonl|txt|tsv|xlsx?|npy|npz|pkl|pickle|h5|hdf5|feather|dat|data))["']""",
    re.I)


@REG.register("find_data_refs", kind="static", cost="cheap",
              summary="Referenced data paths NOT present in the tree — the repo's external data needs (C2/data).")
def find_data_refs(repo_dir: str) -> list[str]:
    refs: set[str] = set()
    for abs_p, rel in _walk(repo_dir):
        if not rel.endswith(".py"):
            continue
        try:
            txt = open(abs_p, errors="replace").read(_MAX_READ)
        except OSError:
            continue
        for m in _DATA_REF.finditer(txt):
            ref = m.group(1)
            if ref.startswith(("http://", "https://", "s3://", "gs://")):
                continue
            if not os.path.isabs(ref) and os.path.exists(os.path.join(repo_dir, ref)):
                continue        # present in the tree → not a need
            refs.add(ref)
    return sorted(refs)[:50]


# ── wrapped existing heuristics ───────────────────────────────────────────────────────────────────────────────
@REG.register("detect_python_version", kind="static", cost="free",
              summary="Declared interpreter version (wraps build.detect_python_version) (C1).")
def detect_python_version(repo_dir: str):
    return build.detect_python_version(repo_dir)


@REG.register("git_era", kind="static", cost="free",
              summary="Repo HEAD commit date for era-pinning (wraps build.repo_commit_date) (C1).")
def git_era(repo_dir: str):
    return build.repo_commit_date(repo_dir)


@REG.register("propose_capture_targets", kind="static", cost="cheap",
              summary="Repo-own metric functions to hook (wraps runner.target_discovery.propose).")
def propose_capture_targets(repo_dir: str, known_metrics=None, entry=None) -> list[dict]:
    return TD.propose(repo_dir, known_metrics=known_metrics, entry=entry)


@REG.register("analyze_determinism", kind="static", cost="cheap",
              summary="Static determinism analysis for adaptive-k (wraps core.determinism.analyze).")
def analyze_determinism(repo_dir: str) -> dict:
    return DET.analyze(repo_dir)


@REG.register("find_prediction_files", kind="static", cost="cheap",
              summary="Committed prediction CSVs for the $0 artifact-recompute path (wraps core.artifacts).")
def find_prediction_files(repo_dir: str, limit: int = 12) -> list[str]:
    return ART.find_prediction_files(repo_dir, limit=limit)


# ── repo fingerprint (cache key; build plan §4 / Phase 4) ─────────────────────────────────────────────────────
@REG.register("repo_fingerprint", kind="static", cost="cheap",
              summary="Deterministic tree-hash + commit fingerprint (the flywheel cache key).")
def repo_fingerprint(repo_dir: str) -> str:
    """tree-hash + commit: sha256 over sorted (relpath, size) of every non-vendored file, plus the git HEAD
    when present. Deterministic (no mtime), cheap, and stable across clones of the same commit — the cache key
    that lets a repeat/sibling repo skip the LLM (build plan §4, Phase 4)."""
    h = hashlib.sha256()
    for _abs, rel in _walk(repo_dir):
        try:
            size = os.path.getsize(_abs)
        except OSError:
            size = -1
        h.update(("%s:%d\n" % (rel, size)).encode("utf-8", "replace"))
    try:
        out = subprocess.run(["git", "-C", repo_dir, "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        commit = (out.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        commit = ""
    return hashlib.sha256((h.hexdigest() + "|" + commit).encode()).hexdigest()[:32]


def _json_default(o):
    return json.loads(json.dumps(o, default=str))
