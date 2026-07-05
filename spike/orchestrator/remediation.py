"""orchestrator.remediation — the fault taxonomy → HOW-only remediation registry (build plan §5, slice S1).

Formalizes ``runner.build.classify_failure`` (a flat signature→kind map) into a structured, extensible
taxonomy: each fault kind maps to an ordered list of remediations, each carrying

  (a) the HOW-only **action** (which registry tool / channel applies it),
  (b) a **deterministic evidence collector** ``evidence_fn(repo_dir, stderr) -> Evidence`` that must LICENSE the
      action before it may fire — the self-healing "constrained autonomy" rule: act only with sufficient
      evidence + bounded risk, never on an attacker-influenced traceback alone, and
  (c) the **validation** the independent Judge re-checks (documentation; the actual gate is the unchanged
      downstream recompute).

The loop consults ``propose()`` BEFORE any LLM revise — the self-healing "error-signature → cached fix, no
model call" property (Kestra: MTTR 13h→3s). ``classify()`` is the one structured view the observe step (S2)
and the ReAct trace read (self-healing lit: the trace is an audit feature).

FCR (build plan §0): every remediation is HOW-only — it supplies inputs, installs a declared tool, or relinks
a path; it never edits compute to force a number. A wrong remediation can only mismatch the independent
recompute (→ REFUTED / INCONCLUSIVE), never manufacture a CONFIRM. Whether an apply modifies source/data (→
the loop folds it into ``source_modified`` → REPRODUCED-ONLY) is decided per-apply by the tool's returned
``modified`` list, not asserted here. This module imports NO ``core.verdict`` / ``core.diff`` (CI firewall).

Not yet wired as loop remediations (documented contracts a later slice lights up by adding an evidence_fn +
flipping ``wired``): ``results-location`` → ``locate_results`` (S4), ``scoped-metric`` → ``bind_artifact``
(S4), ``multi-step`` → order approaches by data-flow. The evidence-collector seam is where each plugs in.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Callable

from runner import build as _build


@dataclass(frozen=True)
class Evidence:
    """What a deterministic collector found in the repo + failure that LICENSES (or refuses) a remediation.
    ``facts`` carries the structured specifics for the trace/audit (which file, which binary)."""
    licenses: bool
    detail: str = ""
    facts: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Remediation:
    """A HOW-only fix for a fault signature. ``evidence_fn(repo_dir, stderr) -> Evidence`` must license it
    before it may fire. ``wired`` = the apply-side exists on the run path today (else it is a documented
    contract). ``caps_verdict`` is advisory — the real REPRODUCED-ONLY cap is driven by the apply tool's
    ``modified`` list, so a same-basename relink stays uncapped while a rewrite/substitution caps."""
    fault: str
    action: str
    summary: str
    evidence_fn: Callable[[str, str], "Evidence"]
    validation: str
    wired: bool = True
    caps_verdict: bool = False


@dataclass(frozen=True)
class RemediationPlan:
    """A remediation whose evidence licensed it for THIS failure — what the loop applies + records."""
    remediation: Remediation
    evidence: Evidence

    @property
    def fault(self) -> str:
        return self.remediation.fault

    @property
    def action(self) -> str:
        return self.remediation.action

    @property
    def detail(self) -> str:
        return self.evidence.detail


# ── deterministic evidence collectors (pure, hermetic, no network, no LLM) ────────────────────────────────────
def _ev_committed_data(repo_dir: str, stderr: str) -> Evidence:
    """Licenses the hardcoded-path relink: the missing file's basename IS committed in-repo (a genuine
    path mismatch — code reads ``/Users/…/results/x.csv``, the file is at ``results/x.csv``), OR the repo has
    exactly one committed dataset (a renamed/moved single dataset). Reuses the ``data_resolver`` primitives so
    the evidence matches exactly what ``make_data_available`` will do — a licensed relink can never fail for
    lack of a file the collector claimed was there."""
    from runner import data_resolver as _dr   # local: keep module import cheap + firewall-obvious
    miss = _dr.missing_data_path(stderr or "")
    if not miss:
        return Evidence(False, "no missing data file named in the failure")
    base = os.path.basename(str(miss).replace("\\", "/"))
    src = _dr._find_committed(repo_dir, base) if base else None
    if src:
        rel = os.path.relpath(src, repo_dir)
        return Evidence(True, "basename %s is committed at %s" % (base, rel),
                        {"missing": miss, "committed_at": rel, "substitution": False})
    sole = _dr._sole_committed_dataset(repo_dir) if (base and base.lower().endswith(_dr._DATA_SUFFIX)) else None
    if sole:
        rel = os.path.relpath(sole, repo_dir)
        return Evidence(True, "the sole committed dataset %s can substitute for %s" % (os.path.basename(sole), base),
                        {"missing": miss, "committed_at": rel, "substitution": True})
    return Evidence(False, "%s is not committed in-repo and there is no unique dataset to substitute" % base,
                    {"missing": miss})


def _declared_binaries(repo_dir: str) -> set[str]:
    """CLI tools the repo's OWN setup names — the CI ``apt install`` step, an ``environment.yml`` dependency,
    or a README ``apt-get install`` / ``conda install`` line. This is the supply-chain rail: we only license
    installing what the repo itself declares, never an arbitrary name from an attacker-influenced traceback."""
    named: set[str] = set()
    try:
        named.update(_build.ci_workflow_signals(repo_dir).get("apt") or [])   # the repo's CI apt-install step
    except Exception:  # noqa: BLE001 — evidence collection is best-effort; a parse hiccup just narrows it
        pass
    # conda environment.yml: bare dependency entries (`  - bedtools`, `  - samtools=1.19`) are declared tools.
    for fn in ("environment.yml", "environment.yaml"):
        p = os.path.join(repo_dir, fn)
        if not os.path.isfile(p):
            continue
        try:
            text = open(p, errors="replace").read()[:40000]
        except OSError:
            continue
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("- "):                              # a yaml list item under dependencies:
                tok = re.split(r"[=<>!~ ]", s[2:].strip(), maxsplit=1)[0].strip()
                if tok and tok not in ("pip", "python"):
                    named.add(tok)
    # README / Makefile: an explicit `apt(-get) install X` or `conda/micromamba install X` line.
    for fn in ("README.md", "README.rst", "README.txt", "Makefile"):
        p = os.path.join(repo_dir, fn)
        if not os.path.isfile(p):
            continue
        try:
            text = open(p, errors="replace").read()[:40000]
        except OSError:
            continue
        for m in _build._CI_APT.finditer(text):
            named.update(t.strip() for t in m.group(1).replace(",", " ").split() if t.strip())
        for m in re.finditer(r"(?:conda|micromamba)\s+install\s+([^\n#&|;]+)", text):
            named.update(t for t in m.group(1).split()
                         if t and not t.startswith("-") and "=" not in t and t not in ("install",))
    return {b.lower() for b in named}


def _ev_missing_binary(repo_dir: str, stderr: str) -> Evidence:
    """Licenses a system-binary install: an ALLOWLISTED CLI tool is named missing in the failure AND the repo
    declares it (CI / environment.yml / README). We install what the repo asks for, never an arbitrary name."""
    from runner.e2b_runner import _missing_binaries_from   # the allowlist + parser — single source of truth
    bins = _missing_binaries_from(stderr or "")
    if not bins:
        return Evidence(False, "no allowlisted missing binary named in the failure")
    declared = _declared_binaries(repo_dir)
    named = [b for b in bins if b.lower() in declared]
    if named:
        return Evidence(True, "the repo declares the missing tool(s): %s" % ", ".join(named), {"binaries": named})
    return Evidence(False, "missing tool(s) %s not declared in the repo's CI/environment.yml/README"
                    % ", ".join(bins), {"binaries": bins})


# ── the taxonomy: fault kind → ordered HOW-only remediations (cheapest/safest first) ──────────────────────────
REMEDIATIONS: dict[str, list[Remediation]] = {
    "missing-data": [
        Remediation(
            fault="missing-data", action="resolve_data_path",
            summary="relink a committed file (or substitute the sole committed dataset) to where the code reads it",
            evidence_fn=_ev_committed_data,
            validation="the independent recompute runs on the placed data; a wrong file only mismatches "
                       "(→ REFUTED/INCONCLUSIVE), and a rewrite/substitution caps the verdict at REPRODUCED-ONLY",
            wired=True, caps_verdict=False),
    ],
    "missing-binary": [
        Remediation(
            fault="missing-binary", action="install_binary",
            summary="apt / bioconda-install an allowlisted CLI tool the repo declares",
            evidence_fn=_ev_missing_binary,
            validation="the run proceeds and its numbers are recomputed independently (a tool install is HOW-only)",
            # apply exists on the E2B acquire path (e2b_runner._install_binary); promoting it to a first-class
            # main-path remediation is the follow-up. Evidence is wired + tested now so observe/audit can name it.
            wired=False, caps_verdict=False),
    ],
}


def propose(fault_kind: str | None, repo_dir: str | None, stderr: str) -> RemediationPlan | None:
    """The deterministic dispatch the loop consults BEFORE the LLM: the first WIRED remediation for
    ``fault_kind`` whose evidence licenses it, else None (→ the loop revises / surfaces honestly). No LLM,
    no network — pure signature + repo evidence."""
    if not fault_kind or not repo_dir:
        return None
    for rem in REMEDIATIONS.get(fault_kind, ()):
        if not rem.wired:
            continue
        ev = rem.evidence_fn(repo_dir, stderr or "")
        if ev.licenses:
            return RemediationPlan(rem, ev)
    return None


def classify(stderr: str, repo_dir: str | None = None) -> dict:
    """The taxonomy view of a failure: the classified fault ``kind`` + ``hint`` (from ``build.classify_failure``)
    plus, when a ``repo_dir`` is given, the LICENSED remediation (if any) and its evidence. One structured
    object for the observe step (S2) and the ReAct trace — never a verdict."""
    base = _build.classify_failure(stderr or "")
    plan = propose(base.get("kind"), repo_dir, stderr) if repo_dir else None
    return {"kind": base.get("kind"), "hint": base.get("hint"),
            "remediation": plan.action if plan else None,
            "evidence": plan.detail if plan else None,
            "plan": plan}
