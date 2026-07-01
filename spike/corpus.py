"""calma.spike.corpus — the corpus as a MEASURED DISTRIBUTION, not a list (guide §A.2).

Loads repos.yaml and enforces the intake rubric: every entry declares a `meta` block
(domain / tier / split / license / commit_date) so the corpus is auditable and describable as
"n per domain × difficulty tier." This is the measurement instrument the scorecard (optimize/scorecard.py)
and the schema test (tests/test_corpus_schema.py) both build on.

Pure-stdlib + PyYAML; no engine imports, so it stays a cheap, side-effect-free descriptor of the corpus.
"""
from __future__ import annotations

import os

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REPOS = os.path.join(HERE, "repos.yaml")

# The controlled vocabularies (guide §A.2 / §A.3). Kept here so intake is machine-checkable in ONE place.
DOMAINS = ("ml", "finance", "statistics", "ir", "nlp", "deeplearning", "genomics", "analytics")
TIERS = ("T1", "T2", "T3", "T4")
SPLITS = ("dev", "test")

# a priori tier meaning (guide §A.2) — surfaced in reports so an operator reads the corpus, not just counts.
TIER_MEANING = {
    "T1": "trivial — single library-metric call, seeded, light deps (regression floor; must stay ~100%)",
    "T2": "standard — custom metric / .score() / committed artifact, medium deps (the real product surface)",
    "T3": "hard — multi-candidate / hand-rolled / convention-sensitive / __main__-defined (the honest-limits frontier)",
    "T4": "adversarial/negative — fabricated/leaked/trivial/convention-mismatched/nondeterministic/coincidental "
          "(the standing FCR=0 proof; a false CONFIRM here is P0)",
}

# verdicts whose graded truth is NOT a positive confirm — a claim in this set that Calma CONFIRMs is a
# false-confirm (the cardinal sin). Mirrors verdict.POSITIVE but kept import-free here.
NON_CONFIRM_EXPECTS = ("REFUTED", "INVALIDATED", "NON-DETERMINISTIC", "INCONCLUSIVE", "REPRODUCED-ONLY", "DISCOVERED")


def load(path: str | None = None) -> list[dict]:
    """Return the raw repo specs from repos.yaml."""
    import yaml  # noqa: PLC0415 — lazy so the module imports even where PyYAML is absent
    with open(path or DEFAULT_REPOS) as fh:
        return yaml.safe_load(fh)["repos"]


def meta_of(spec: dict) -> dict:
    """The intake metadata for a repo, defaulting missing keys to 'unknown' (never KeyError)."""
    m = dict(spec.get("meta") or {})
    m.setdefault("domain", "unknown")
    m.setdefault("tier", "unknown")
    m.setdefault("split", "unknown")
    m.setdefault("license", "unknown")
    m.setdefault("commit_date", "unknown")
    return m


def validate(specs: list[dict] | None = None, path: str | None = None) -> list[str]:
    """Machine-checkable intake enforcement (guide §A.2). Returns a list of human-readable violations;
    an empty list means the corpus conforms. Used by tests/test_corpus_schema.py as a hard CI gate."""
    specs = specs if specs is not None else load(path)
    errs: list[str] = []
    seen: set[str] = set()
    for spec in specs:
        name = spec.get("name", "<unnamed>")
        if name in seen:
            errs.append("%s: duplicate repo name" % name)
        seen.add(name)
        meta = spec.get("meta")
        if not isinstance(meta, dict):
            errs.append("%s: missing `meta` block (guide §A.2 intake rubric)" % name)
            continue
        dom, tier, split = meta.get("domain"), meta.get("tier"), meta.get("split")
        if dom not in DOMAINS:
            errs.append("%s: domain=%r not in %s" % (name, dom, DOMAINS))
        if tier not in TIERS:
            errs.append("%s: tier=%r not in %s" % (name, tier, TIERS))
        if split not in SPLITS:
            errs.append("%s: split=%r not in %s" % (name, split, SPLITS))
        if not meta.get("license"):
            errs.append("%s: license missing (use an SPDX id / 'internal' / 'unknown')" % name)
        if not meta.get("commit_date"):
            errs.append("%s: commit_date missing (use YYYY-MM-DD or 'unknown')" % name)
    return errs


def distribution(specs: list[dict] | None = None, path: str | None = None) -> dict:
    """Describe the corpus as a distribution: counts per domain, per tier, per split, and the domain×tier
    matrix. This is what proves the corpus isn't an 'iris trap' (guide §A.1 lesson 1)."""
    specs = specs if specs is not None else load(path)
    by_domain: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    by_split: dict[str, int] = {}
    matrix: dict[tuple[str, str], int] = {}
    for spec in specs:
        m = meta_of(spec)
        by_domain[m["domain"]] = by_domain.get(m["domain"], 0) + 1
        by_tier[m["tier"]] = by_tier.get(m["tier"], 0) + 1
        by_split[m["split"]] = by_split.get(m["split"], 0) + 1
        matrix[(m["domain"], m["tier"])] = matrix.get((m["domain"], m["tier"]), 0) + 1
    return {"n": len(specs), "by_domain": by_domain, "by_tier": by_tier, "by_split": by_split,
            "matrix": {"%s/%s" % k: v for k, v in matrix.items()}}


def graded_claims(specs: list[dict] | None = None, path: str | None = None):
    """Yield (repo_name, meta, claim) for every hand-graded claim (has an `expect`). The scorecard scores
    verdict-accuracy + the FCR gate over these; discover:true repos contribute unlabelled claims elsewhere."""
    specs = specs if specs is not None else load(path)
    for spec in specs:
        m = meta_of(spec)
        for claim in spec.get("claims", []) or []:
            if claim.get("expect") is not None:
                yield spec.get("name"), m, claim
