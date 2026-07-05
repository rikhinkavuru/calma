"""calma.spike.orchestrator.assess — build a deterministic RepoProfile from the static tools (Phase 1).

``assess(repo_dir)`` runs every static assessment tool (zero LLM cost) and assembles a ``RepoProfile``: the
structured, honest snapshot the Phase-2 loop reasons over. It classifies layout (root-script / package /
src-layout / notebook / monorepo / make-driven) and an advisory domain (ml / genomics / quant / …) from
import + salience signals. Nothing here is a verdict input — the profile only shapes HOW we try to run the
repo. Pure and cheap: safe to run on every repo, cache-checked by fingerprint (Phase 4).
"""
from __future__ import annotations

import os

from . import tools_static as S
from .types import RepoProfile

# advisory domain signal: import root → domain. Never a verdict input; drives the Assessment Report + capture
# target hints. First match by priority order wins.
_DOMAIN_LIBS = [
    ("genomics", {"Bio", "pysam", "anndata", "scanpy", "biopython", "cyvcf2", "pyfaidx", "gffutils"}),
    ("ml", {"sklearn", "torch", "tensorflow", "keras", "xgboost", "lightgbm", "catboost", "transformers",
            "jax", "flax"}),
    ("nlp", {"nltk", "spacy", "gensim", "rank_bm25", "sentence_transformers", "sacrebleu", "rouge_score"}),
    ("quant", {"backtrader", "zipline", "vectorbt", "pyfolio", "quantlib", "ta", "ffn", "empyrical"}),
    ("analytics", {"pandas", "polars", "duckdb", "pyarrow"}),
    ("stats", {"statsmodels", "scipy", "pingouin", "lifelines"}),
]


def _classify_layout(repo_dir: str, entry_cands, notebooks, make_targets) -> str:
    top_script = any(c.kind == "script" and os.sep not in c.argv[0] for c in entry_cands)
    module_entry = any(c.kind == "module" for c in entry_cands)
    # monorepo: >1 immediate subdir that is itself a project (own manifest) — a light heuristic
    subprojects = 0
    try:
        for name in os.listdir(repo_dir):
            d = os.path.join(repo_dir, name)
            if os.path.isdir(d) and name not in S._SKIP_DIRS:
                if any(os.path.isfile(os.path.join(d, m))
                       for m in ("setup.py", "pyproject.toml", "requirements.txt")):
                    subprojects += 1
    except OSError:
        pass
    if subprojects >= 2:
        return "monorepo"
    if os.path.isdir(os.path.join(repo_dir, "src")):
        return "src-layout"
    if notebooks and not top_script and not module_entry:
        return "notebook"
    if make_targets and not top_script:
        return "make-driven"
    if module_entry and not top_script:
        return "package"
    if top_script:
        return "root-script"
    if entry_cands:
        return "package"
    return "unknown"


def _classify_domain(repo_dir: str, entry_cands) -> str | None:
    """Union the import roots of the top few entrypoint files + root scripts, match against _DOMAIN_LIBS."""
    roots: set[str] = set()
    files = []
    for c in entry_cands[:4]:
        if c.kind == "script" and c.argv and c.argv[0].endswith(".py"):
            files.append(c.argv[0])
    files += [f for f in S.build._root_scripts(repo_dir)][:6]
    for rel in dict.fromkeys(files):
        p = os.path.join(repo_dir, rel)
        if os.path.isfile(p):
            roots |= S.build._imported_roots(p)
    if not roots:
        # fall back to a shallow scan of any python file's imports
        for _abs, rel in S._walk(repo_dir):
            if rel.endswith(".py"):
                roots |= S.build._imported_roots(_abs)
            if len(roots) > 40:
                break
    for domain, libs in _DOMAIN_LIBS:
        if roots & libs:
            return domain
    return None


def select_subproject(repo_dir: str) -> str | None:
    """Monorepo sub-project selection (build plan Phase 5): pick the immediate subdir most likely to hold the
    headline result — one with its own manifest AND a high-confidence entrypoint (bonus for a README/results).
    Returns the subdir name or None. Best-effort + bounded; the caller then re-assesses that subdir. Fail-open:
    a wrong pick only changes which sub-project we try, never a verdict."""
    best, best_score = None, 0.0
    try:
        names = sorted(os.listdir(repo_dir))
    except OSError:
        return None
    for name in names[:50]:
        d = os.path.join(repo_dir, name)
        if not os.path.isdir(d) or name in S._SKIP_DIRS:
            continue
        has_manifest = any(os.path.isfile(os.path.join(d, m))
                           for m in ("setup.py", "pyproject.toml", "requirements.txt", "environment.yml"))
        if not has_manifest:
            continue
        cands = S.find_entrypoints(d)
        score = (cands[0].confidence if cands else 0.0)
        if any(os.path.isfile(os.path.join(d, r)) for r in ("README.md", "results.json", "results.csv")):
            score += 0.1
        if score > best_score:
            best, best_score = name, score
    return best


def assess(repo_dir: str) -> RepoProfile:
    """Run all static tools and return a RepoProfile. Deterministic, no LLM, no sandbox."""
    entry_cands = S.find_entrypoints(repo_dir)
    notebooks = S.find_notebooks(repo_dir)
    make_targets = S.find_make_targets(repo_dir)

    # declared deps: merge requirements.txt (includes-resolved, B3) with any other manifest (B1), then dedup by
    # PACKAGE NAME preferring the pinned spec — an exact-string merge kept both 'numpy==2.4.6' and a bare
    # 'numpy' (pyproject + requirements list the same dep differently), which then double-installed and showed
    # a doubled reproduce command.
    declared: list[str] = []
    req = S.resolve_requirements_includes(repo_dir)
    declared += req.get("specs", [])
    declared += S.read_declared_deps(repo_dir)
    declared = S.build.dedup_pip(declared)

    profile = RepoProfile(
        language=S.detect_language(repo_dir),
        layout=_classify_layout(repo_dir, entry_cands, notebooks, make_targets),
        pkg_manager=S.detect_pkg_manager(repo_dir),
        py_version=S.detect_python_version(repo_dir),
        entry_candidates=entry_cands,
        notebooks=notebooks,
        make_targets=make_targets,
        declared_deps=declared,
        data_needs=S.find_data_refs(repo_dir),
        determinism=S.analyze_determinism(repo_dir),
        domain=_classify_domain(repo_dir, entry_cands),
        fingerprint=S.repo_fingerprint(repo_dir),
    )
    return profile


def report_lines(profile: RepoProfile) -> list[str]:
    """Human-readable Assessment Report lines (build plan §2 'Transparent'). Surfaced in job logs + the UI:
    'how Calma approached this repo'. Read-only view of the profile — no decision here."""
    top = profile.entry_candidates[0] if profile.entry_candidates else None
    lines = [
        "Assessment: %s repo, %s layout, %s deps." % (profile.language, profile.layout, profile.pkg_manager),
        "Python: %s." % (profile.py_version or "unspecified"),
    ]
    if top:
        lines.append("Primary entrypoint: %s (confidence %.2f; %s)."
                     % (" ".join(top.argv), top.confidence, ", ".join(top.signals) or "heuristic"))
    if len(profile.entry_candidates) > 1:
        lines.append("Fallback entrypoints: %s."
                     % "; ".join(" ".join(c.argv) for c in profile.entry_candidates[1:4]))
    if profile.notebooks:
        lines.append("Notebooks: %d found." % len(profile.notebooks))
    if profile.make_targets:
        lines.append("Make targets: %s." % ", ".join(profile.make_targets[:8]))
    if profile.declared_deps:
        lines.append("Declared deps: %s%s." % (", ".join(profile.declared_deps[:10]),
                                               " …" if len(profile.declared_deps) > 10 else ""))
    if profile.data_needs:
        lines.append("External data referenced (not in tree): %s." % ", ".join(profile.data_needs[:6]))
    if profile.domain:
        lines.append("Domain: %s." % profile.domain)
    det = (profile.determinism or {}).get("level")
    if det:
        lines.append("Determinism (static): %s." % det)
    return lines
