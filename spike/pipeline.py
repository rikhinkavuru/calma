"""calma.spike.pipeline — the end-to-end verification orchestration.

This is the product loop as code: static discovery, optional sandbox execution, captured-input recompute,
validity overlays, artifact-first verification, and structured stage tracing. The FastAPI server and tests
both call this module so the architecture is exercised outside the web UI.
"""
from __future__ import annotations

import concurrent.futures
import math
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

from core import anomaly as ANOM
from core import artifacts as A
from core import determinism as DET
from core import diff as D
from core import leakage as LEAK
from core import redteam_gate as RTG
from core import refstore as REFSTORE
from core import tolerance as T
from core import verdict as VD
from attest import receipt as RCPT
from discovery import extract as DISC
from discovery import salience as SAL
from runner import build
from runner import target_discovery as TD
from runner.local_runner import run_local
from synth import formula as SYNTH

import planner as PLAN  # noqa: E402 — AI run-plan pre-stage ("AI proposes"); best-effort, never touches verdicts

DISCOVERED = "DISCOVERED"

# The AI run-plan runs in a background thread so it overlaps the sandbox boot (its latency is hidden, not
# added). Daemon threads; a tiny pool is plenty since the supervisor already gates verify concurrency.
_PLAN_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="calma-plan")

# feature 11 — the persistent verified-run reference store (dark-launched; only read/written when opts.anomaly).
_REFSTORE = REFSTORE.RefStore(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".calma", "refstore.json"))
_ANOMALY_MIN_N = 15
_VERIFIED = (VD.CONFIRMED, VD.CONFIRMED_STOCHASTIC, VD.REPRODUCED_ONLY)


@dataclass
class VerifyOptions:
    """Runtime choices for one repo verification."""

    runner: str = "local"
    deep: bool = False
    entry: str | list[str] | None = None
    pip_install: list[str] | None = None
    discover: bool = True
    claims: list[dict] = field(default_factory=list)
    k: int = 2
    top_k: int = 1_000_000          # deep-verify only the top-K salient claims (tier cap); the rest stay
    #                                 DISCOVERED ("upgrade to verify"). Fail-closed: never confirms a wrong number.
    hooks: str = "sklearn"
    targets: list[dict] | None = None
    timeout: int = 600
    job_id: str = "pipeline"
    venvs_dir: str | None = None
    base_python: str | None = None
    cpu_cores: int = 0              # tier vCPU for the sandbox (0 = default E2B template); realised by template routing
    acquire_data: bool = False      # opt-in (paid): run the repo's OWN data-download pipeline in a gated internet
    #                                 phase on a missing-data failure, then re-run + recompute (download-first repos)
    acquire_env: dict | None = None  # four-unlocks §8: per-tenant secrets (HF_TOKEN/cloud creds) injected into the
    #                                 ACQUIRE step only — never the eval run (keeps recompute credential-free / FCR)
    acquire_allow_out: list | None = None  # egress allowlist for the acquire phase (default-deny + these hosts)
    fetch_data: bool = False        # opt-in: on a "missing input file" failure, fetch the data via Exa + retry
    heal_deps: bool = True          # self-heal: pip-install a dep the imports didn't reveal (openpyxl) + retry
    repair: bool = False            # feature 1: iterative env-only repair loop (deps/env/argv/data) until the
    #                                 entrypoint runs. Never edits repo compute; a bad step → DISCOVERED, not a
    #                                 confirm. A post-repair source change caps the verdict at REPRODUCED-ONLY.
    repair_steps: int = 4           # tier-scaled env-repair budget (the loop's max_steps); 0 → repair off.
    disk_gb: int = 0                # tier ephemeral-disk budget (Modal GPU sandbox; big-dataset acquire). 0=default.
    mem_mb: int = 0                 # per-sandbox RSS cap from the tier; 0 = supervisor's container-derived default.
    #                                 The supervisor caps the child at min(container-derived, this) when set.
    adaptive_k: bool = True         # if the run is statically proven deterministic, verify with k=1 (half the
    #                                 runs) — still fail-closed: any doubt keeps the empirical k≥2 check
    plan: bool = True               # AI run-plan pre-stage: propose entrypoint/deps/data (build.py heuristics
    #                                 fall back if unavailable). NEVER touches the recompute or the verdict.
    classify_llm: bool = False      # feature 4 P1: best-effort LLM claim-salience refinement (P0 always on).
    #                                 Legibility only — re-ranks the discovered claims, never a value/verdict.
    fuzz: bool = False              # feature 2/7/10: re-invoke the repo's own metric callable on fresh inputs
    #                                 (differential / metamorphic / fabrication). Downgrade-only; needs targets.
    repo_meta: dict | None = None   # feature 18: {repo, commit} folded into the reproducibility receipt.
    anomaly: bool = False           # feature 11 (dark-launched): flag cross-run outliers vs the verified-run
    #                                 store. ADVISORY only — never changes a verdict, never auto-refutes.
    allow_gpu: bool = False         # four-unlocks §7: on a `needs-gpu` CPU failure, escalate to the Modal GPU
    #                                 backend (E2B can't do GPU). Enterprise-gated + GPU-budget-checked upstream;
    #                                 FCR-safe (the GPU run flows through the same capture→recompute→verdict).
    orchestrate: bool = False       # repo-assessment orchestrator (build plan): replace the fixed make-runnable
    #                                 ladder with assess→rank→bounded execute/observe/revise over a typed tool
    #                                 registry. FCR-safe by construction (§0): it only changes HOW a repo runs;
    #                                 the RunResult flows through the UNCHANGED diff/verdict. Flag-gated behind
    #                                 the heuristic default (owner/enterprise) until the corpus clears it.
    synthesize_predictions: bool = False   # opt-in last resort: when NO entrypoint captures a number, AI-synthesize
    #                                 a predict-and-dump driver (repo's OWN model → predictions), recompute the
    #                                 metric INDEPENDENTLY from those predictions. The driver is a source
    #                                 modification → verdict capped at REPRODUCED-ONLY (a synthesized harness can
    #                                 never CONFIRM). Requires opts.orchestrate. Default OFF until corpus-proven.


def _argv(entry) -> list[str]:
    if not entry:
        return []
    if isinstance(entry, str):
        return entry.split()
    return list(entry)


def _claim_out(claim, verdict, reason, diff, provenance=None):
    return {
        "id": claim.get("id"),
        "metric": claim.get("metric"),
        "claimed": claim.get("value"),
        "context": claim.get("context", ""),
        "location": claim.get("location", ""),
        "source": claim.get("source", "stated"),
        "confidence": claim.get("confidence"),
        "verdict": verdict,
        "reason": reason,
        "diff": diff,
        "provenance": provenance,
        # always present so the API returns a validity assessment alongside the number, never just the
        # numeric verdict. diff_claim() fills this for deep-verified claims; the leakage overlay (below)
        # adds dataset-level findings; everyone else gets the empty-but-explicit shape.
        "validity": {"invalidating": [], "advisory": []},
    }


_EXC_RE = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Warning|Interrupt))\b.*")


def _error_summary(stderr: str) -> str:
    """Pull the one informative line out of a captured stderr tail: the final exception (e.g.
    'ModuleNotFoundError: No module named genomic_benchmarks'), not the top of the traceback. Falls back to
    the last non-empty line. This is what tells a user WHY the re-run failed instead of a generic message."""
    lines = [ln.strip() for ln in (stderr or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    for ln in reversed(lines):                       # the exception is at the bottom of a traceback
        if _EXC_RE.match(ln):
            return ln[:240]
    return lines[-1][:240]


def _norm_ds(s) -> str:
    """Normalise a dataset name for matching (lowercase, alphanumerics only)."""
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


# context/location tokens that name the dataset a claim is about, e.g. "dataset=human_nontata_promoters"
_DS_KEY_RE = re.compile(r"(?:dataset|data|task|name|split_source)\s*=\s*([A-Za-z0-9_\-./]+)")


def _claim_dataset_tokens(rec) -> set[str]:
    """The dataset name(s) a claim record is attributed to (from its context / location label)."""
    toks: set[str] = set()
    for fieldval in (rec.get("context", ""), rec.get("location", "")):
        for m in _DS_KEY_RE.finditer(fieldval or ""):
            toks.add(_norm_ds(m.group(1)))
    return {t for t in toks if t}


def _apply_leakage_overlay(records: list[dict], leakage: list[dict]) -> None:
    """Tie dataset-level leakage findings into the PER-CLAIM verdict (in place).

    The validity moat (guide §4.6): a number can reproduce and recompute perfectly yet be INVALID because
    the held-out evaluation leaked. Leakage is detected on committed train/test splits independently of any
    re-run, so we fold it back onto every claim attributed to a contaminated dataset — a CONFIRMED accuracy
    on a leaked split is not correct, it is INVALIDATED. We only downgrade on an explicit dataset match (the
    claim's `dataset=…` label equals the leaked split's name) so we never mis-attribute one dataset's leak to
    another; the job-level banner still warns about unattributable leakage.
    """
    leaky: dict[str, list[dict]] = {}
    for d in leakage or []:
        inv = [f for f in d.get("findings", []) if f.get("invalidating")]
        if inv:
            leaky[_norm_ds(d.get("dataset"))] = inv
    if not leaky:
        return
    for rec in records:
        hits = [f for ds, finds in leaky.items() if ds in _claim_dataset_tokens(rec) for f in finds]
        if not hits:
            continue
        rec.setdefault("validity", {"invalidating": [], "advisory": []})
        notes = [f["detail"] for f in hits]
        rec["validity"]["invalidating"].extend(notes)
        # REFUTED (the number itself is misreported) is already the strongest "not correct" — keep it, but
        # annotate. Everything else (CONFIRMED / REPRODUCED-ONLY / DISCOVERED / INCONCLUSIVE / NON-DET) is
        # invalidated by the contaminated evaluation, regardless of whether we recomputed the number.
        if rec["verdict"] == VD.REFUTED:
            rec["reason"] = (rec.get("reason", "") + " — and the evaluation is contaminated: %s" % notes[0]).strip(" —")
            continue
        was = rec["verdict"]
        rec["verdict"] = VD.INVALIDATED
        if was == DISCOVERED:
            rec["reason"] = ("the held-out evaluation is contaminated — %s. The number itself was not "
                             "recomputed, but data leakage invalidates the claim regardless." % notes[0])
        else:
            rec["reason"] = "reproducible but invalid: %s" % "; ".join(notes)


def _as_fraction(raw):
    """Normalize a reported classification score to a 0..1 fraction for the baseline compare: '80%' and '80'
    and 0.8 all → 0.80. A bare number > 1.5 is read as a percentage (an accuracy of '85' means 85%). Returns
    None if unparseable or non-finite."""
    try:
        s = str(raw).strip()
        pct = s.endswith("%")
        v = float(s.rstrip("%").strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    if pct or v > 1.5:
        v = v / 100.0
    return v


def _r2_value(rec: dict) -> float | None:
    """The record's R² as a float (raw — R² is never a percent), or None if it isn't an R² claim / won't parse."""
    if (rec.get("metric") or "").lower() not in ("r2", "rsquared", "r_squared", "r^2"):
        return None
    try:
        return float(str(rec.get("claimed", rec.get("value"))).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None


def _apply_baseline_overlay(records: list[dict], leakage: list[dict]) -> None:
    """Trivial-baseline / degenerate-distribution overlay from a split's LABEL distribution (in place). A number
    that reproduces perfectly is still INVALID if it's no better than a constant predictor, at/below chance, or
    computed on a single-class test set — the 'looks great, means nothing' bug. Uses the label stats the leakage
    scan attached (from committed OR materialized/downloaded data), dataset-name-matched like the leakage overlay
    so one dataset's baseline never mis-attributes to another. Downgrade-only; never a false CONFIRM."""
    stats: dict[str, dict] = {}
    for d in leakage or []:
        ls = d.get("label_stats")
        if ls:
            stats[_norm_ds(d.get("dataset"))] = ls
    # exactly ONE labelled dataset → it applies to EVERY classification claim in the repo (there is no other
    # dataset to mis-attribute to). This is the common "one committed CSV" shape, where the dataset-name match
    # below would otherwise miss a leaderboard claim keyed by model, not dataset — and so the baseline never
    # fired. Multiple datasets keep the strict name match (no cross-attribution).
    single = next(iter(stats.values())) if len(stats) == 1 else None
    # A repo that reports a positive R² somewhere AND a ≤0 R² elsewhere is almost always contrasting its result
    # (0.87) against a weak baseline / ablation (-0.03). Branding that -0.03 INVALIDATED is a false accusation on
    # an honest paper. So a ≤0 R² only invalidates when it is the repo's headline/only R² (no better R² present)
    # or when Calma actually recomputed it ≤0; otherwise it is an advisory. (Precomputed once over all records.)
    _has_better_r2 = any(v is not None and v > 0.0 for v in (_r2_value(r) for r in records))
    for rec in records:
        metric = (rec.get("metric") or "").lower()
        val = _as_fraction(rec.get("claimed", rec.get("value")))   # "80%" / "80" / 0.8 → 0.80 (baseline is 0..1)
        note = None
        checked = False              # did a REAL comparison basis exist for this claim? (drives the wedge card)
        # data-INDEPENDENT degenerate metric: a regression R² ≤ 0 is no better than predicting the mean. Invalidate
        # only the repo's headline/only degenerate R² (or one Calma recomputed ≤0) — never a contrasted baseline.
        if metric in ("r2", "rsquared", "r_squared", "r^2"):
            rv = _r2_value(rec)
            if rv is not None and rv <= 0.0:
                txt = "R² %.4g ≤ 0 — no better than predicting the mean (no explanatory power)" % rv
                grounded = (str(rec.get("provenance") or "").startswith("artifact")
                            or (rec.get("diff") or {}).get("recomputed") is not None)
                if grounded or not _has_better_r2:
                    note, checked = txt, True         # headline/only degenerate R², or recomputed ≤0 → real catch
                else:
                    rec.setdefault("validity", {"invalidating": [], "advisory": []})["advisory"].append(
                        txt + " — a contrasted baseline (the repo reports a better R² elsewhere)")
        # data-DEPENDENT trivial-baseline (needs a committed/materialized label distribution)
        if note is None and stats:
            toks = _claim_dataset_tokens(rec)
            ls = next((s for ds, s in stats.items() if ds in toks), None) or single
            if ls:
                checked = True                        # a real label distribution existed to compare against
            if ls and ls.get("n_classes", 2) <= 1:
                note = "the test set has a single class — the score is vacuous (degenerate distribution)"
            elif ls and val is not None and val == val:
                maj = ls.get("majority_frac") or 0.0
                if metric in ("accuracy", "acc", "balanced_accuracy") and val <= maj + 1e-9:
                    note = ("accuracy %.4g is at or below the majority-class baseline %.4g — a constant "
                            "predictor matches it (no signal)" % (val, maj))
                elif metric in ("auroc", "auc", "roc_auc", "roc-auc") and val <= 0.5 + 1e-9:
                    note = "AUROC %.4g is at or below chance (0.50) — the model has no discrimination" % val
        if checked:
            rec["baseline_checked"] = True            # positive signal the wedge card reads (checked-clean ≠ unchecked)
        if not note:
            continue
        rec.setdefault("validity", {"invalidating": [], "advisory": []})
        rec["validity"]["invalidating"].append(note)
        if rec["verdict"] not in (VD.REFUTED, VD.INVALIDATED):
            rec["verdict"] = VD.INVALIDATED
            rec["reason"] = note


def _apply_anomaly_overlay(records: list[dict], store) -> None:
    """Feature 11 (in place, ADVISORY): flag a claim's value as a cross-run outlier vs the verified-run history
    for its (dataset, metric). It NEVER changes a verdict and NEVER auto-refutes — a genuine SOTA is also an
    outlier, so an outlier is only 'unusual', not 'wrong'. Then update the store from the VERIFIED records only
    (so the baseline can't be poisoned by unverified claims)."""
    for rec in records:
        ds = _claim_dataset_tokens(rec)
        if not ds:
            continue
        diff = rec.get("diff") or {}
        val = diff.get("recomputed")
        if val is None:
            val = diff.get("produced")
        if val is None:
            continue
        for d in ds:
            z = ANOM.robust_z(val, store.values(d, rec.get("metric")), min_n=_ANOMALY_MIN_N)
            if z.get("is_outlier"):
                rec.setdefault("validity", {"invalidating": [], "advisory": []})["advisory"].append(
                    "cross-run outlier vs %d verified runs (robust z=%.2f) — unusual, not necessarily wrong"
                    % (z["n"], z["z"]))
                rec["anomaly"] = z
                break
    for rec in records:                       # update the store AFTER flagging, verified records only
        if rec.get("verdict") not in _VERIFIED:
            continue
        diff = rec.get("diff") or {}
        val = diff.get("recomputed")
        if val is None:
            val = diff.get("produced")
        if val is None:
            continue
        for d in _claim_dataset_tokens(rec):
            store.append(d, rec.get("metric"), val)


def _apply_agent_modified_cap(records: list[dict], modified: list[str]) -> None:
    """Feature 1 second rail (in place): if the repair loop changed a compute-path source file, an agreeing
    number can no longer be attributed to the repo's OWN code, so cap every CONFIRMED at REPRODUCED-ONLY via
    verdict.monotone (downgrade-only). No source change → no-op."""
    if not modified:
        return
    note = "the run required repairs that modified repo source (%s) — capped below CONFIRMED" % ", ".join(modified[:3])
    for rec in records:
        # any AFFIRMATIVE verdict (CONFIRMED or CONFIRMED-STOCHASTIC) attributes the number to the repo's OWN
        # code, which is what a source change undermines. REFUTED/INVALIDATED/etc. are negative statements
        # unaffected by the edit.
        if rec.get("verdict") in VD.AFFIRMATIVE:
            rec["verdict"] = VD.REPRODUCED_ONLY
            rec["reason"] = note
            rec.setdefault("validity", {"invalidating": [], "advisory": []})["advisory"].append(note)


def _apply_redteam_gate(records: list[dict], claims: list[dict], runs) -> None:
    """Feature 8 — the inline red-team overlay (in place). An independent, downgrade-only second opinion on
    every CONFIRMED record: re-bind the claim to its captured computation and re-screen it for degeneracy /
    single-class / trivial-baseline / value-coincidence (core.redteam_gate), then fold any charge through
    verdict.monotone. Structurally cannot raise a verdict, so it can only ever REMOVE a false confirm, never
    add one — a no-op on honest CONFIRMEDs, a backstop if the primary confirm path regresses."""
    if not runs:
        return
    base = runs[0] if runs else []
    by_id = {c.get("id"): c for c in claims}
    for rec in records:
        if rec.get("verdict") not in VD.AFFIRMATIVE:      # screen CONFIRMED and CONFIRMED-STOCHASTIC alike
            continue
        claim = by_id.get(rec.get("id"))
        if claim is None:
            continue
        call, status, _ = D._bound_call(claim, base)
        if status != "bound" or not call:
            continue
        proposed, reason = RTG.screen(rec.get("metric") or "", call, base)
        new = VD.monotone(rec["verdict"], proposed)
        if new != rec["verdict"]:
            rec["redteam"] = {"downgraded_from": rec["verdict"], "to": new, "charge": reason}
            rec["verdict"] = new
            rec["reason"] = "red-team gate downgrade — %s" % reason
            rec.setdefault("validity", {"invalidating": [], "advisory": []})
            rec["validity"]["invalidating"].append("red-team: " + (reason or ""))


class Trace:
    def __init__(self, update: Callable[..., None] | None = None, log: Callable[[str], None] | None = None):
        self.events: list[dict] = []
        self.update = update
        self.log = log

    def stage(self, name: str, detail: str = ""):
        self.events.append({"stage": name, "detail": detail, "t": time.time()})
        if self.update:
            self.update(stage=name)
        if detail and self.log:
            self.log(detail)

    def note(self, msg: str):
        if self.log:
            self.log(msg)
        self.events.append({"stage": "note", "detail": msg, "t": time.time()})


# a dep a run says is missing — plain ModuleNotFoundError + pandas' optional-dep messages ("Missing optional
# dependency 'openpyxl'", "`Import openpyxl` failed"). Lets a run SELF-HEAL deps the imports don't reveal.
_MODERR_RE = re.compile(r"No module named '([\w.]+)'|Missing optional dependency '([\w.]+)'|Import\W+([\w.]+)\W+failed")


def _missing_module_from(run_result):
    """The top-level missing module in a run's stderr, if it's a plausible PyPI package (not a private
    C-extension like _tkinter, not the repo's own module). None → nothing safe to auto-install."""
    err = " ".join(m.get("stderr_tail", "") for m in (run_result.get("meta") or []))
    # pandas' "Unable to find a usable engine; tried using: 'pyarrow', 'fastparquet'" is a missing parquet
    # backend — install pyarrow (the standard one). Handled explicitly so it heals regardless of tail wording.
    if "Unable to find a usable engine" in err or "pyarrow is required" in err:
        return "pyarrow"
    m = _MODERR_RE.search(err)
    name = next((g for g in m.groups() if g), None) if m else None
    top = name.split(".")[0] if name else None
    return top if (top and not top.startswith("_")) else None


def _with_static_targets(repo_dir: str, tgts, trace: Trace, entry=None):
    """Cycle-2 binding fix: append target_discovery's deterministic, name-matched fallback targets (marked
    `static: True`, capped below CONFIRMED downstream — core/diff.py's `heuristic_bind`) to whatever the
    caller/AI planner already proposed. Dedup by function name; never overrides an existing (higher-trust)
    proposal. Best-effort — any failure here just means fewer fallback targets, never a broken run."""
    try:
        have = {t.get("target") for t in (tgts or [])}
        extra = [t for t in TD.propose(repo_dir, entry=entry) if t.get("target") not in have]
    except Exception:  # noqa: BLE001 — a repo-scanning heuristic must never break the verify
        extra = []
    if not extra:
        return tgts
    trace.note("static fallback capture targets (name-matched, capped below CONFIRMED): %s"
              % ", ".join(t["target"] for t in extra)[:160])
    return list(tgts or []) + extra


def _run_repo(repo_dir: str, opts: VerifyOptions, trace: Trace, k: int | None = None, get_plan=None,
              acquire=None, data_fetch=None):
    k = opts.k if k is None else k                    # adaptive-k passes an effective k (1 when proven det.)

    if opts.orchestrate:                              # build plan: assess→rank→bounded execute/observe/revise
        return _run_repo_orchestrated(repo_dir, opts, trace, k, get_plan, acquire=acquire, data_fetch=data_fetch)

    def _entry(plan):                                 # precedence: explicit opts > AI plan > auto-detect > default
        e = _argv(opts.entry)
        if not e and plan and plan.get("entry"):
            e = plan["entry"]
            trace.note("AI-planned entrypoint: %s" % " ".join(e))
        elif not e and opts.deep:
            e = build.detect_entrypoint(repo_dir) or []
            if e:
                trace.note("auto-detected entrypoint: %s" % " ".join(e))
        return e or ["eval.py"]

    trace.stage("building", "preparing runnable environment")
    if opts.runner == "e2b":
        from runner.e2b_runner import run_e2b

        pyver = build.detect_python_version(repo_dir)     # faithful repro under the declared interpreter (plan-independent)
        if pyver:
            trace.note("declared Python %s — provisioning it for a faithful repro" % pyver)

        # conda: an environment.yml means the deps (and any bioconda system binaries — Foldseek / HMMER /
        # samtools / …) are solved by micromamba in-sandbox, not pip. Route the heuristic path to the conda
        # builder too (only the orchestrator did before), so a genomics/bio repo with a conda env actually builds.
        _builder = "conda-micromamba" if os.path.isfile(os.path.join(repo_dir, "environment.yml")) else None
        if _builder:
            trace.note("environment.yml found — solving the env with conda (micromamba)")

        # flywheel (HOW-only, default-on; off in tests / with CALMA_ORCH_FLYWHEEL=0): reuse a known-good
        # run-plan for this exact tree so a repeat/sibling scan skips re-derivation + the AI planner. Best-
        # effort — never let a cache hiccup break a run. A cached plan still flows through the full verify.
        _fp, _rpc = None, None
        if os.environ.get("CALMA_ORCH_FLYWHEEL", "1") != "0" and "PYTEST_CURRENT_TEST" not in os.environ:
            try:
                from orchestrator import cache as _OCACHE
                from orchestrator.tools_static import repo_fingerprint as _repo_fp
                _fp, _rpc = _repo_fp(repo_dir), _OCACHE.runplan_cache()
            except Exception:  # noqa: BLE001 — the flywheel is optional; degrade to full derivation
                _fp, _rpc = None, None

        # Deferred resolution: run_e2b calls this AFTER the microVM boots, so the run-plan (running in a
        # background thread) overlaps the boot instead of preceding it. Precedence: explicit opts > AI plan >
        # heuristics. The E2B sandbox starts clean, so deps must be installed — the caller's list, else the AI
        # plan's, else inferred from requirements.txt / the repo's imports.
        holder: dict = {}

        def _resolve():
            if _rpc is not None and _fp and not opts.pip_install and not opts.entry:
                try:
                    cached = _rpc.get(_fp)
                except Exception:  # noqa: BLE001
                    cached = None
                if cached:
                    entry = list(cached["entry"])
                    pip = build.dedup_pip(list(cached.get("pip") or []) or None)
                    tgts = _with_static_targets(repo_dir, opts.targets or None, trace, entry=entry)
                    trace.note("flywheel: reusing a known-good run-plan — %s" % " ".join(entry))
                    holder.update(entry=entry, pip=pip, strict=False, targets=tgts)
                    return entry, pip, False, tgts
            plan = get_plan() if get_plan else None
            entry = _entry(plan)
            pip, strict = opts.pip_install, True
            if not pip and plan and plan.get("pip_install"):
                pip, strict = plan["pip_install"], False               # AI-proposed deps install tolerantly
                trace.note("AI-planned deps: %s" % " ".join(pip)[:160])
            elif not pip:
                pip, why = build.infer_requirements(repo_dir)
                strict = (why == "requirements.txt")                   # inferred deps install tolerantly (best-effort)
                if pip and why != "requirements.txt":
                    # era-pin INFERRED deps to the repo's commit-date era, THEN relax any pin the run interpreter
                    # can't load (era_pin_compat defaults to the sandbox Python when the repo declares none).
                    from orchestrator.tools_exec import era_pin_compat as _epc
                    pip, era, _notes = _epc(pip, repo_dir, pyver)
                    for _n in _notes:
                        trace.note("era-compat: " + _n)
                    if era:
                        trace.note("era-pinned inferred deps to %s" % era)
                trace.note(("auto-deps (%s): %s" % (why, " ".join(pip)[:160])) if pip
                           else "no deps detected (%s)" % why)
            tgts = opts.targets or (plan.get("targets") if plan else None)   # AI-identified metric fns to capture
            if tgts and not opts.targets:
                trace.note("AI-planned capture targets: %s" % ", ".join(t["target"] for t in tgts)[:160])
            tgts = _with_static_targets(repo_dir, tgts, trace, entry=entry)
            pip = build.dedup_pip(pip)                          # 'numpy==2.4.6' + 'numpy' -> one install, not two
            if _builder == "conda-micromamba":
                pip, strict = None, False                       # conda (micromamba) solves environment.yml; don't also pip-install
            holder.update(entry=entry, pip=pip, strict=strict, targets=tgts)
            return entry, pip, strict, tgts

        trace.stage("running", "running in E2B microVM")
        from runner import data_resolver as _DR
        result = run_e2b(repo_dir, resolve=_resolve, k=k, hooks=opts.hooks, builder=_builder,
                         python_version=pyver, timeout=opts.timeout, log=trace.note, fuzz=opts.fuzz,
                         cpu_cores=opts.cpu_cores, acquire=acquire,
                         acquire_env=(opts.acquire_env if acquire else None),
                         acquire_allow_out=(opts.acquire_allow_out if acquire else None),
                         data_fetch=data_fetch,
                         data_resolver=(_DR.resolve_file_url if (acquire and opts.fetch_data) else None),
                         repo_ctx=((get_plan() or {}).get("data_needed", "") if get_plan else ""))
        entry = holder.get("entry") or _entry(get_plan() if get_plan else None)
        pip, strict, tgts = holder.get("pip"), holder.get("strict", True), holder.get("targets")
        for _ in range(2 if opts.heal_deps else 0):       # self-heal a dep the imports didn't reveal
            if result.get("ran_ok"):
                break
            mod = _missing_module_from(result)
            if not mod:
                break
            pip = (pip or []) + [build._PKG_ALIASES.get(mod, mod)]
            trace.note("missing dep %s — installing + retrying" % mod)
            result = run_e2b(repo_dir, entry, k=k, hooks=opts.hooks, targets=tgts, builder=_builder,
                             pip_install=pip, pip_strict=strict, python_version=pyver, timeout=opts.timeout,
                             log=trace.note, fuzz=opts.fuzz, cpu_cores=opts.cpu_cores)
        # flywheel: remember the plan that VERIFIABLY captured, so the next scan of this tree reuses it.
        if _rpc is not None and _fp and result.get("ran_ok") and (result.get("runs") and result["runs"][0]):
            try:
                _rpc.put(_fp, {"entry": holder.get("entry"), "pip": holder.get("pip"), "python": pyver})
            except Exception:  # noqa: BLE001
                pass
        return result, entry

    # local path — no sandbox boot to hide behind, so join the plan synchronously
    plan = get_plan() if get_plan else None
    entry = _entry(plan)
    pip = build.dedup_pip(opts.pip_install or (plan.get("pip_install") if plan else None))
    tgts = opts.targets or (plan.get("targets") if plan else None)      # AI-identified metric fns to capture
    tgts = _with_static_targets(repo_dir, tgts, trace, entry=entry)
    venvs_dir = opts.venvs_dir or os.path.join(os.path.dirname(repo_dir), ".venvs")
    base_py = opts.base_python or sys.executable
    python, note = build.ensure_venv(opts.job_id, pip, venvs_dir, base_python=base_py)
    trace.note("env: %s" % note)
    # data-acquisition (paid, gated upstream): run the repo's own download pipeline with network before the
    # eval, so the datasets exist. Local path = host subprocess; FCR-safe (only writes inputs, recompute stays
    # independent). A failed step stops the chain; the eval then runs (and honestly fails again if data missing).
    if acquire:
        from runner import acquire as _ACQ
        res = _ACQ.run_acquisition(acquire, _ACQ.local_run_cmd(repo_dir, python), log=trace.note)
        trace.note("data-acquisition: %s — %d step(s) run" % ("complete" if res["ok"] else "incomplete", len(res["ran"])))
    trace.stage("running", "running %s" % " ".join(entry))

    def _local(cur_entry=None, env_extra=None):
        return run_local(repo_dir, cur_entry or entry, k=k, python=python, hooks=opts.hooks, targets=tgts,
                         timeout=opts.timeout, fuzz=opts.fuzz, env_extra=env_extra)
    result = _local()
    # feature 1 — iterative env-only repair loop (opt-in). Generalizes the 2-shot dep heal into a bounded
    # loop that can also set env vars, add argv, and fetch data. Only into a per-repo venv (never the shared
    # base python). Env-only action space → FCR-safe; a post-repair source change caps the verdict downstream.
    if opts.repair and python != base_py and not result.get("ran_ok"):
        from runner import repair as REPAIR
        state = {"entry": list(entry), "env": {}, "result": result}

        def _runfn(_action):
            r = _local(state["entry"], state["env"] or None)
            state["result"] = r
            return r

        def _apply(action):
            t, arg = action.get("type"), action.get("arg")
            if t == "PIP" and arg:
                if not REPAIR.is_safe_pip(arg):          # reject pip arg-injection / VCS / path (prompt-inject guard)
                    trace.note("repair: refused unsafe pip arg %r" % (arg,)[:80])
                    return False
                subprocess.run([python, "-m", "pip", "install", "-q", build._PKG_ALIASES.get(arg, arg)],
                               timeout=300, check=False)
                return True
            if t == "SETENV" and isinstance(arg, dict):
                state["env"].update({str(kk): str(vv) for kk, vv in arg.items()})
                return True
            if t == "SETENV" and isinstance(arg, str) and "=" in arg:
                kk, vv = arg.split("=", 1)
                state["env"][kk] = vv
                return True
            if t == "ENTRYPOINT_ARG" and arg:
                state["entry"] += (arg if isinstance(arg, list) else str(arg).split())
                return True
            if t == "FETCH_DATA":
                from runner import data_resolver as _DR
                miss = _DR.missing_data_path(" ".join(m.get("stderr_tail", "")
                                                       for m in (state["result"].get("meta") or [])))
                if miss:
                    ok, _n = _DR.resolve_missing_data(repo_dir, miss)
                    return ok
                return False
            return False

        propose = REPAIR.llm_propose(_missing_module_from) if os.environ.get("ANTHROPIC_API_KEY") \
            else REPAIR.heuristic_propose(_missing_module_from)
        result, manifest = REPAIR.repair_loop(_runfn, propose, _apply, max_steps=(opts.repair_steps or 4),
                                              snapshot_fn=lambda: REPAIR.snapshot_pyfiles(repo_dir),
                                              log=trace.note)
        result["repair_manifest"] = manifest
        return result, state["entry"]
    # self-heal a missing runtime dep (openpyxl etc.) — ONLY into a dedicated per-repo venv, never the shared
    # harness/base python (installing there would pollute it for every later run).
    for _ in range(2 if (opts.heal_deps and python != base_py) else 0):
        if result.get("ran_ok"):
            break
        mod = _missing_module_from(result)
        if not mod:
            break
        trace.note("missing dep %s — installing + retrying" % mod)
        subprocess.run([python, "-m", "pip", "install", "-q", build._PKG_ALIASES.get(mod, mod)],
                       timeout=300, check=False)
        result = _local()
    return result, entry


def _run_repo_orchestrated(repo_dir: str, opts: VerifyOptions, trace: Trace, k: int, get_plan=None,
                           acquire=None, data_fetch=None):
    """The make-runnable BRAIN (build plan §1): the orchestrator replaces the fixed entrypoint ladder. It
    profiles the repo, ranks typed RunApproach candidates (reusing the background planner turn), and drives a
    bounded execute/observe/revise loop over the real runners — returning the SAME run dict shape the heuristic
    path returns, so everything downstream (_diff_claims, overlays, verdict) is unchanged. FCR-safe: the loop
    owns no verdict; a wrong choice → wrong/empty capture → DISCOVERED/REFUTED, never a false CONFIRM. C3: on
    total failure it returns an honest empty run (ran_ok=False), NEVER a fabricated eval.py."""
    from orchestrator import orchestrate as ORCH
    from orchestrator import tools_exec as XT
    from orchestrator.types import RunResult as ORR
    from runner import data_resolver as _DR

    venvs_dir = os.path.abspath(opts.venvs_dir or os.path.join(os.path.dirname(os.path.abspath(repo_dir)),
                                                               ".venvs"))
    base_py = opts.base_python or sys.executable
    pyver = build.detect_python_version(repo_dir)
    if pyver:
        trace.note("declared Python %s" % pyver)
    plan = get_plan() if get_plan else None                # reuse the background planner turn (boot-overlap)
    holder: dict = {"acquired": False}                     # carries the winning run's fuzz emit + raw cost;
    #                                                        `acquired` runs the download pipeline ONCE (data
    #                                                        doesn't persist across microVMs, but re-downloading
    #                                                        per approach is wasteful — do it on the first E2B run)

    def _wrap(r, approach):
        holder["fuzz"] = r.get("fuzz")
        if r.get("data_auto_resolved"):
            holder["data_auto_resolved"] = True     # carry the auto-fetch flag → mismatch cap downstream
        if r.get("leakage"):
            holder["leakage"] = r["leakage"]        # carry materialized-data leakage findings → validity stage
        return ORR(ran_ok=bool(r.get("ran_ok")), runs=(r.get("runs") or []), meta=(r.get("meta") or []),
                   cost=(r.get("cost") or {}), source_modified=[], approach=approach)

    def run_approach(approach):
        entry = list(approach.entry)
        targets = opts.targets or approach.capture_targets or None
        deps = build.dedup_pip(list(approach.deps))            # 'numpy==2.4.6' + 'numpy' -> one install
        head = str(entry[0]) if entry else ""

        # A3: Makefile target → run_make (recipe's python child auto-arms capture). Runs host-side (a make
        # recipe is trusted-repo shape); kept out of the sandbox routing below.
        if head.startswith("make:"):
            return _wrap(XT.run_make(repo_dir, head[5:], k=k, hooks=opts.hooks, targets=targets,
                                     timeout=opts.timeout, env_extra=(approach.env or None)), approach)

        # E2B path: scripts, modules, notebooks (nb:), non-Python (r:/julia:), and conda all dispatch here now
        # that the image ships the notebook runtime + micromamba + polyglot interpreters (four-unlocks §1-3).
        # run_e2b picks the right in-sandbox command per entry kind and solves environment.yml for a conda builder.
        if opts.runner == "e2b":
            from runner.e2b_runner import run_e2b
            conda = approach.builder == "conda-micromamba"
            pip, strict = (None if conda else deps), (approach.builder == "declared")
            if pip and approach.builder != "declared":
                pip, era, notes = XT.era_pin_compat(pip, repo_dir, pyver)   # C1: interpreter-aware era pin
                for n in notes:
                    trace.note("era-compat: " + n)
                if era:
                    trace.note("era-pinned inferred deps to %s" % era)
            # data-acquisition (paid "Download the repo's data"): run the repo's own download pipeline WITH
            # network in this approach's sandbox before the eval. Only on the FIRST E2B run (data is re-fetched
            # per microVM, so once is enough to prove it — after which the run either captures or honestly fails).
            acq, fetch = None, None
            if (acquire or data_fetch) and not holder["acquired"]:
                acq, fetch, holder["acquired"] = acquire, data_fetch, True
            # the reactive resolver (AI-backed) fetches inputs a failed acquire step names, to the exact path;
            # gated on fetch_data (paid). repo_ctx = the plan's data description, so the resolver knows the sources.
            _resolver = _DR.resolve_file_url if (acq and opts.fetch_data) else None
            r = run_e2b(repo_dir, entry, k=k, hooks=opts.hooks, targets=targets, pip_install=pip or None,
                        pip_strict=strict, python_version=pyver, timeout=opts.timeout, log=trace.note,
                        fuzz=opts.fuzz, cpu_cores=opts.cpu_cores, builder=approach.builder,
                        acquire=acq, acquire_env=(opts.acquire_env if acq else None),
                        acquire_allow_out=(opts.acquire_allow_out if acq else None), data_fetch=fetch,
                        data_resolver=_resolver, repo_ctx=(plan or {}).get("data_needed", ""))
            return _wrap(r, approach)

        # ── local path (fixtures / curated) ──────────────────────────────────────────────────────────────────
        # A1: notebook → run_notebook (kernel-armed capture).
        if head.startswith("nb:"):
            return _wrap(XT.run_notebook(repo_dir, head, k=k, hooks=opts.hooks, targets=targets,
                                         timeout=opts.timeout), approach)
        # A3 long-tail: non-Python entry (r:/julia:/shell:) → run_lang. The verdict comes from recomputing the
        # emitted predictions in Python (core.artifacts) — the capture shim can't see R/Julia calls.
        for _lang in ("r", "julia", "shell", "sh"):
            if head.startswith(_lang + ":"):
                argv = [head[len(_lang) + 1:]] + [str(a) for a in entry[1:]]
                return _wrap(XT.run_lang(repo_dir, _lang, argv, k=k, hooks=opts.hooks, targets=targets,
                                         timeout=opts.timeout, env_extra=(approach.env or None)), approach)
        # B2: a conda builder provisions the interpreter from environment.yml via micromamba.
        if approach.builder == "conda-micromamba":
            conda = XT.build_conda(repo_dir, envs_dir=os.path.join(os.path.dirname(os.path.abspath(repo_dir)),
                                                                   ".conda-envs"))
            trace.note("conda: %s" % conda["note"])
            if conda["ok"] and conda["python"]:
                r = run_local(repo_dir, entry, k=k, python=conda["python"], hooks=opts.hooks, targets=targets,
                              timeout=opts.timeout, fuzz=opts.fuzz, env_extra=(approach.env or None))
                return _wrap(r, approach)
            # micromamba unavailable → fall through to a pip venv from the (conda-declared) deps, best-effort
        # The local runner is the fixtures/curated path: like the heuristic path, it runs against the harness
        # python and only builds a venv for EXPLICIT deps (opts.pip_install). Inferred/declared deps drive the
        # E2B path (real installs); installing them into a local venv both diverges from the heuristic baseline
        # and can fail on a wheel-less interpreter. venvs_dir is absolute so run_local's cwd change can resolve it.
        local_pip = opts.pip_install or None
        python, note = build.ensure_venv(opts.job_id + "-orch", local_pip, venvs_dir, base_python=base_py)
        trace.note("env: %s" % note)
        r = run_local(repo_dir, entry, k=k, python=python, hooks=opts.hooks, targets=targets,
                      timeout=opts.timeout, fuzz=opts.fuzz, env_extra=(approach.env or None))
        return _wrap(r, approach)

    trace.stage("assessing", "assessing the repo (static profile → run approach)")
    # tier-scaled budget: no repair budget → a single approach, no revise (free tier); else the full loop.
    if opts.repair:
        budget = ORCH.Budget(step_cap=8, max_approaches=5)
    else:
        budget = ORCH.Budget(step_cap=3, max_approaches=2)     # even with no repair budget, actually run the loop
    # flywheel (env-gated so it stays off in the hermetic test suite; prod enables it): fingerprint→approach
    # cache + error→fix hint store. HOW-only — a cache hit still flows through the full fail-closed verify.
    cache = hints = None
    # the flywheel is ON by default: the reproduction cache (fingerprint→approach) + experience store
    # (error→fix) make repeat/sibling repos cheaper and carry a learned fix across runs — HOW-only, so a stale
    # entry can only cost coverage, never a verdict. Kept OUT of the hermetic test suite (cache persistence
    # would couple tests); force off with CALMA_ORCH_FLYWHEEL=0.
    if os.environ.get("CALMA_ORCH_FLYWHEEL", "1") != "0" and "PYTEST_CURRENT_TEST" not in os.environ:
        from orchestrator import cache as OCACHE
        cache, hints = OCACHE.approach_cache(), OCACHE.hint_store()
    trace.stage("running", "running the chosen approach")
    # belt-and-suspenders FCR rail (parity with the heuristic repair loop): fingerprint repo compute source
    # before/after; if the build/run changed any .py (a package post-install, a fetched file), cap AFFIRMATIVE
    # → REPRODUCED-ONLY downstream. The action space is env-only, so this is expected to stay empty.
    from runner import repair as _REPAIR
    _src_before = _REPAIR.snapshot_pyfiles(repo_dir)
    result = ORCH.orchestrate(repo_dir, run_approach, use_llm=opts.plan, plan=plan, budget=budget,
                              cache=cache, hints=hints, log=trace.note,
                              synthesize=opts.synthesize_predictions)
    _src_changed = _REPAIR._changed(_src_before, _REPAIR.snapshot_pyfiles(repo_dir))
    for line in (result.cost.get("assessment") or []):
        trace.note(line)
    if result.cost.get("launch"):
        trace.note("reproduce: %s" % result.cost["launch"])
    run_dict = result.to_run_dict()
    if holder.get("fuzz") is not None:
        run_dict["fuzz"] = holder["fuzz"]                  # preserve the un-foolability emit for diff_claim
    if holder.get("data_auto_resolved"):
        run_dict["data_auto_resolved"] = True              # → _diff_claims caps a mismatch to INCONCLUSIVE
    if holder.get("leakage"):
        run_dict["leakage"] = holder["leakage"]            # materialized-data leakage → the validity stage
    # unify the source-edit rail with the heuristic path so _apply_agent_modified_cap works identically. Dedupe:
    # a synthesized calma_eval.py is reported by BOTH the orchestrator (source_modified) and the snapshot diff
    # (_src_changed) — list it once so the cap note reads cleanly.
    _modified = list(dict.fromkeys((result.source_modified or []) + _src_changed))
    run_dict["repair_manifest"] = {"source_modified": _modified, "orchestrator_trace": result.trace}
    # a human/discovery-facing entry label: strip the nb:/make: routing prefixes (make: has no python entry to
    # scope discovery against, so it drops to []; nb: keeps the notebook path).
    entry_out: list[str] = []
    for e in (result.approach.entry if result.approach else []):
        s = str(e)
        if s.startswith("nb:"):
            entry_out.append(s[3:])
        elif s.startswith(("r:", "julia:", "shell:", "sh:")):
            entry_out.append(s.split(":", 1)[1])       # strip the lang routing prefix for the human label
        elif s.startswith("make:"):
            continue
        else:
            entry_out.append(s)
    return run_dict, entry_out


_ARTIFACT_BAN_TOKENS = {"", "csv", "tsv", "json", "parquet", "npy", "npz", "results", "result", "predictions",
                        "preds", "pred", "data", "output", "outputs", "test", "train", "val", "eval", "final"}


def _artifact_binds(claim: dict, path: str, n_metric_claims: int, n_files: int) -> bool:
    """Does this claim plausibly correspond to THIS committed predictions file? Recomputing a number from a
    predictions file and matching/mismatching a claim only means something if the claim is ABOUT that file —
    otherwise it's a mis-bind: a stray number (a config value, a table cell from another experiment, a bare
    number in prose) glued to the nearest recomputable artifact, giving a false REFUTED *or* a false CONFIRMED
    (value-coincidence). Confident when: (a) UNIQUE — exactly one claim of this metric + one predictions file
    (so there's no question which computation the claim refers to); or (b) the claim's location/context shares
    an identifying token with the file's path (locality). A benchmark that reports the SAME metric hundreds of
    times across datasets (n_metric_claims ≫ 1) must NOT bind them all to one file — the homology-repo mis-bind."""
    if n_files == 1 and n_metric_claims == 1:
        return True
    ptoks = {t for t in re.split(r"[^a-z0-9]+", str(path).lower()) if t not in _ARTIFACT_BAN_TOKENS}
    ctoks = {t for t in re.split(r"[^a-z0-9]+",
                                 (str(claim.get("location") or "") + " " + str(claim.get("context") or "")).lower())
             if t not in _ARTIFACT_BAN_TOKENS}
    return bool(ptoks & ctoks)


def _artifact_verify(repo_dir: str, claims: list[dict]) -> dict:
    out: dict = {}
    # Scan the repo for committed prediction files ONCE — it's a pure function of repo_dir. Doing it inside
    # the per-claim loop re-walked + re-read the repo for every claim; a benchmark that discovers hundreds of
    # claims (gb_kmer: 838) turned that into ~838 full repo scans = a ~15-minute stall.
    pred_files = A.find_prediction_files(repo_dir)
    if not pred_files:
        return out
    metric_counts: dict = {}
    for c in claims:
        m = (c.get("metric") or "").lower()
        metric_counts[m] = metric_counts.get(m, 0) + 1
    for claim in claims:
        for path, cols in pred_files:
            res = A.recompute_from_cols(cols, claim.get("metric"), SYNTH.recompute_any)
            if not res:
                continue
            # only give an artifact verdict when the claim confidently corresponds to THIS file — never glue a
            # stray number to an unrelated predictions file (the false-REFUTED / value-coincidence-CONFIRMED hole).
            if not _artifact_binds(claim, path, metric_counts.get((claim.get("metric") or "").lower(), 1),
                                   len(pred_files)):
                continue
            recomputed = res["value"]
            ok, _ = T.claim_close(claim.get("value"), recomputed)
            fname = os.path.basename(path)
            # distinguish Calma's OWN synthesized predict-and-dump output (reserved name) from a genuinely
            # committed artifact — an auditor must be able to tell "reproduced via a synthesized driver" (which
            # the source_modified cap already forces to REPRODUCED-ONLY) from "matches the repo's committed file".
            synth = fname == "calma_predictions.csv"
            kind = "synthesized predictions" if synth else "committed predictions"
            reason = (
                "claim matches the %s (%s · recomputed %.5g)" % (kind, fname, recomputed)
                if ok
                else "claim %r != recompute from %s (%s = %.5g)" % (claim.get("value"), kind, fname, recomputed)
            )
            out[claim.get("id")] = _claim_out(
                claim,
                VD.CONFIRMED if ok else VD.REFUTED,
                reason,
                {"claimed": claim.get("value"), "recomputed": recomputed},
                provenance="artifact:" + ("synthesized" if synth else (res.get("provenance") or "recipe")),
            )
            break
    return out


def _diff_claims(claims: list[dict], run_result: dict, job_run: dict,
                 static_deterministic: bool = False) -> list[dict]:
    records = []
    for claim in claims:
        if not run_result.get("runs"):
            records.append(_claim_out(claim, DISCOVERED, "deep verify could not run the entrypoint", {}))
            continue
        rec = D.diff_claim(claim, run_result["runs"], resolver=SYNTH.recompute_any,
                           static_deterministic=static_deterministic, fuzz=run_result.get("fuzz"))
        verdict, reason = rec["verdict"], rec.get("reason", "")
        if verdict == VD.INCONCLUSIVE and "no captured computation" in reason:
            verdict = DISCOVERED
            if not job_run.get("ran"):
                fail = job_run.get("failure") or {}
                reason = "the re-run did not recompute this number — " + (fail.get("hint") or "the entrypoint failed to run")
            else:
                reason = "the re-run did not recompute this number — point Calma at the script/args that compute it"
        # SAFETY: data Calma auto-fetched (a canonical source, NOT the repo's own committed data) can legitimately
        # CONFIRM a match — independent data agreeing is strong evidence — but must NEVER false-REFUTE: a mismatch
        # could be a data-version difference, not a wrong claim. So cap a would-be REFUTED to INCONCLUSIVE.
        if run_result.get("data_auto_resolved") and verdict == VD.REFUTED:
            verdict = VD.INCONCLUSIVE
            reason = ("recomputed against data Calma auto-fetched (not the repo's own) — a mismatch here may be a "
                      "data-version difference, so this is inconclusive rather than refuted; commit a predictions "
                      "file or the exact data for a definitive verdict")
        out = _claim_out(claim, verdict, reason, rec.get("diff", {}), provenance=rec.get("recompute_provenance"))
        # carry the always-on validity overlay (trivial-baseline / degenerate-distribution / chance-level)
        # through to the UI — it is what flipped a would-be CONFIRMED to INVALIDATED.
        out["validity"] = rec.get("validity", out["validity"])
        # surface HOW determinism was established: {tested, stable, proven, k}. A CONFIRMED with tested=False,
        # proven=True is "deterministic by construction (k=1)"; tested=True is "reproduced ×k". Distinct on
        # purpose so the two are never conflated.
        if rec.get("determinism"):
            out["determinism"] = rec["determinism"]
        cands = (rec.get("binding") or {}).get("candidates")
        if cands:
            out["scope_options"] = cands       # the scope-the-claim choices the UI offers for an ambiguous bind
        if rec.get("convention"):
            out["convention"] = rec["convention"]   # audit: the standard convention a convention-search confirm used
        records.append(out)
    return records


def verify_repo(
    repo_dir: str,
    opts: VerifyOptions | None = None,
    *,
    update: Callable[..., None] | None = None,
    log: Callable[[str], None] | None = None,
) -> dict:
    """Verify one already-materialized repo directory and return a structured result."""

    opts = opts or VerifyOptions()
    trace = Trace(update=update, log=log)
    trace.stage("initializing", "starting verification")
    # FCR hygiene: drop any reserved Calma artifacts (calma_eval.py / calma_predictions.csv) left in a REUSED
    # checkout by an earlier synthesis run — they are Calma's own output, never the repo's. Purging here (before
    # ANY run, on every path) means the artifact recompute can only ever read predictions produced in THIS
    # verify — where the synthesized driver is recorded in source_modified and the verdict is capped. Without
    # this, a stale calma_predictions.csv would be read as a "committed" artifact on a later non-synthesis run
    # (its calma_eval.py unchanged → no cap) → an uncapped CONFIRMED on stale AI predictions.
    from orchestrator.orchestrate import _purge_reserved as _PURGE_RESERVED
    _PURGE_RESERVED(repo_dir)

    run_result, entry = None, _argv(opts.entry)
    job_run = None
    static_det = False
    committed_file_claims: list = []   # committed result-file claims snapshotted pre-run (see the deep block)
    if opts.deep:
        # AI run-plan pre-stage ("AI proposes, determinism disposes"): a fast model reads the repo and proposes
        # how to RUN it (entrypoint / deps). Kicked off in a BACKGROUND THREAD so it runs CONCURRENTLY with the
        # sandbox boot + upload and is joined only at the last moment (right before deps install, inside
        # run_e2b) — its latency is hidden, not added. Only fills what the caller didn't specify, validated
        # (the entrypoint must exist), best-effort (no key / any failure → heuristics). Never touches the verdict.
        plan_future = _PLAN_POOL.submit(PLAN.plan_repo, repo_dir) if opts.plan else None
        if opts.plan:
            trace.stage("understanding", "planning the run (concurrent with sandbox boot)")
        _plan_cache: dict = {}

        def _get_plan():                              # join once, log once, cache — safe to call from any stage
            if "v" not in _plan_cache:
                p = None
                if plan_future is not None:
                    try:                              # don't let a slow/stuck plan stall the verify
                        p = plan_future.result(timeout=60)
                    except Exception:  # noqa: BLE001 — timeout / thread error → heuristics
                        p = None
                if p:
                    trace.note("AI plan (%.0f%% conf): %s"
                               % (100 * p.get("confidence", 0), (p.get("notes") or "")[:140]))
                    if p.get("data_needed"):
                        trace.note("data note: %s" % p["data_needed"][:160])
                elif plan_future is not None:          # attempted but failed — say so, don't fail silently
                    trace.note("AI plan unavailable this run — using heuristics")
                _plan_cache["v"] = p
            return _plan_cache["v"]

        # adaptive-k gate: if the run is statically PROVEN deterministic-by-construction (every RNG seeded),
        # one run suffices and can reach CONFIRMED; otherwise keep the empirical k≥2 determinism check. Fail-
        # closed — any doubt keeps k≥2, so this can only ever spend fewer runs, never confirm a flaky number.
        det = DET.analyze(repo_dir) if opts.adaptive_k else {"level": DET.AT_RISK, "detail": "adaptive-k off"}
        static_det = det.get("level") == DET.DETERMINISTIC
        eff_k = 1 if (static_det and opts.k > 1) else opts.k
        if static_det:
            trace.note("determinism proven by construction — %s → verifying with k=1 (was k=%d)"
                       % (det.get("detail", ""), opts.k))
        elif opts.adaptive_k:
            trace.note("determinism not statically proven (%s) → keeping the empirical k=%d check"
                       % (det.get("detail", "at risk"), opts.k))
        # snapshot committed result-FILE claims BEFORE the run — the entrypoint (especially a producer picked
        # by the reverse map) can regenerate results.json/results.csv, silently overwriting a committed
        # MISREPORT with an honest value and hiding it. Pin these to their committed value; stdout and
        # runtime-only files come from the post-run pass. README/markdown sources aren't regenerated by a run.
        if opts.discover:
            committed_file_claims = [c for c in DISC.discover(repo_dir)
                                     if c.get("source") in ("results-json", "results-csv")]
        run_result, entry = _run_repo(repo_dir, opts, trace, k=eff_k, get_plan=_get_plan)
        if not run_result.get("ran_ok"):
            from runner import data_resolver as _DR
            _stderr = " ".join(m.get("stderr_tail", "") for m in run_result.get("meta", []))
            miss = _DR.missing_data_path(_stderr)
            # FREE first: the file is often committed elsewhere in the repo (code reads data/x.csv, it's at
            # x.csv). Relink it where the code reads — no network, no cost, no source change → full verdict.
            if miss:
                placed = _DR.relink_committed_data(repo_dir, miss)
                if placed:
                    trace.note("data relink: placed committed '%s' where the entrypoint reads it" % placed)
                    run_result, entry = _run_repo(repo_dir, opts, trace, k=eff_k, get_plan=_get_plan)
            # opt-in fetch: a single missing file from a mirror (paid), then retry
            if not run_result.get("ran_ok") and opts.fetch_data and miss:
                ok, note = _DR.resolve_missing_data(repo_dir, miss)
                trace.note("data-fetch: %s" % note)
                if ok:
                    run_result, entry = _run_repo(repo_dir, opts, trace, k=eff_k, get_plan=_get_plan)
        # opt-in (paid): run the repo's OWN data-acquisition pipeline (numbered download scripts / make-data
        # target), then retry. Distinct from fetch_data (one file via Exa) — this is the download-first research
        # repo case. Only fires on a genuine missing-data failure, so we never pay for a download that isn't needed.
        if not run_result.get("ran_ok") and (opts.acquire_data or opts.fetch_data):
            _errtxt = " ".join(m.get("stderr_tail", "") for m in run_result.get("meta", []))
            if build.classify_failure(_errtxt).get("kind") == "missing-data":
                from runner import acquire as _ACQ
                cmds = _ACQ.find_acquisition(repo_dir) if opts.acquire_data else []
                # BYPASS an imperfect repo pipeline: the AI plan's canonical data-source URLs are fetched directly
                # into the sandbox (opts.fetch_data), so a repo whose own download scripts fail still gets its
                # inputs. Fetch runs BEFORE the repo's acquire scripts (which then process the materialized files).
                sources = []
                if opts.fetch_data:
                    _plan = _get_plan() or {}
                    # the AI plan's URLs + deterministic canonical URLs for standard datasets (data_catalog) —
                    # so a common data-blocked repo resolves reliably even when the model fumbles a URL.
                    from runner import data_catalog as _CAT
                    sources = _CAT.augment_sources(_plan.get("data_sources"), _plan.get("data_needed", ""))
                if cmds or sources:
                    what = []
                    if sources:
                        what.append("fetching %d data file(s) from canonical sources" % len(sources))
                    if cmds:
                        what.append("running the repo's %d-step acquisition pipeline" % len(cmds))
                    trace.stage("acquiring data", " + ".join(what) + " (network allowed)")
                    run_result, entry = _run_repo(repo_dir, opts, trace, k=eff_k, get_plan=_get_plan,
                                                  acquire=cmds, data_fetch=sources)
                else:
                    trace.note("missing data, but no acquisition scripts found and the plan proposed no data "
                               "sources — commit the data or a predictions file to verify")
        # GPU escalation (four-unlocks §7): a CPU run that failed *because* it needs a GPU escalates to the Modal
        # GPU backend — E2B's Firecracker microVMs can't do GPU passthrough. Enterprise-gated + GPU-budget-checked
        # upstream (opts.allow_gpu is only set when the tier allows GPU and budget remains). FCR-safe: the GPU run
        # flows through the SAME capture→recompute→verdict, so a misroute yields DISCOVERED, never a false CONFIRM.
        if not run_result.get("ran_ok") and getattr(opts, "allow_gpu", False):
            _gtxt = " ".join(m.get("stderr_tail", "") for m in run_result.get("meta", []))
            from runner import gpu as _GPU
            # REACTIVE (primary): the failure explicitly says needs-gpu. SECONDARY: an ambiguous runtime error in
            # a repo that STATICALLY reaches for CUDA — but never on a missing-dep/data/entrypoint failure (a GPU
            # wouldn't fix those), so a CPU repo is never billed for a GPU it didn't need.
            _fk = build.classify_failure(_gtxt).get("kind")
            _want_gpu = _GPU.needs_gpu_from_failure(_gtxt) or (
                _fk in ("errored", "too-heavy") and _GPU.scan_repo_for_gpu(repo_dir)["needs_gpu"])
            if _want_gpu:
                from runner.modal_runner import modal_available, run_modal
                if modal_available():
                    gpu_pip, _why = build.infer_requirements(repo_dir)
                    trace.stage("gpu", "escalating to a GPU sandbox (Modal) — the CPU run reported needs-gpu")
                    gpu_res = run_modal(repo_dir, entry, k=eff_k, hooks=opts.hooks, targets=opts.targets,
                                        timeout=opts.timeout, pip_install=(gpu_pip or None),
                                        python_version=build.detect_python_version(repo_dir),
                                        cpu_cores=opts.cpu_cores, fuzz=opts.fuzz, log=trace.note,
                                        disk_gb=getattr(opts, "disk_gb", 0))
                    if gpu_res.get("runs"):
                        run_result = gpu_res
                        trace.note("GPU run: %s — %d computation(s) captured"
                                   % ("ok" if gpu_res.get("ran_ok") else "still failed",
                                      sum(len(r) for r in gpu_res.get("runs", []))))
                else:
                    trace.note("needs-gpu, but no Modal GPU backend is configured — reporting needs-gpu")
        total_calls = sum(len(run) for run in run_result.get("runs", []))
        err, err_full, failure = "", "", None
        if not run_result.get("ran_ok"):
            err_full = (" ".join(m.get("stderr_tail", "") for m in run_result.get("meta", [])).strip())[-1200:]
            err = _error_summary(err_full)            # the actual exception, not the top of the traceback
            failure = build.classify_failure(err_full)   # needs-gpu / too-heavy / missing-data / …
            trace.note("run failed (%s): %s" % (failure["kind"], err or failure["hint"]))
        trace.note("captured %d computation(s)" % total_calls)
        cost = run_result.get("cost", {})
        if cost.get("sandbox_seconds"):
            trace.note("sandbox: %.1fs (build %.1fs + %d run(s)) — one sandbox reused"
                       % (cost.get("sandbox_seconds", 0), cost.get("build_seconds", 0), cost.get("runs", 0)))
        job_run = {"ran": run_result.get("ran_ok"), "calls": total_calls, "entry": " ".join(entry),
                   "error": err, "error_full": err_full, "failure": failure, "cost": cost}

    claims = list(opts.claims or [])
    if opts.discover:
        trace.stage("discovering", "discovering reported numbers")
        stdout0 = run_result["meta"][0].get("stdout_tail", "") if (run_result and run_result.get("meta")) else ""
        discovered = DISC.discover(repo_dir, stdout_text=stdout0, entry=entry)
        # a result file present before the run is authoritative for its committed value: drop the post-run
        # (possibly regenerated) claims from those same files and use the pre-run snapshot, so an entrypoint
        # that rewrites its own results table can't erase a committed misreport before we verify it.
        if committed_file_claims:
            pinned = {c["location"] for c in committed_file_claims}
            regenerated = sum(1 for c in discovered
                              if c.get("location") in pinned and c.get("value")
                              not in {p.get("value") for p in committed_file_claims
                                      if p.get("location") == c.get("location")})
            discovered = committed_file_claims + [c for c in discovered if c.get("location") not in pinned]
            if regenerated:
                trace.note("pinned %d committed result-file claim(s) — the run regenerated its results table"
                           % regenerated)
        trace.note("discovered %d claim(s)" % len(discovered))
        claims.extend(discovered)

    # feature 4 — rank every claim by salience so the UI leads with the headline number instead of a wall of
    # table cells. Pure re-ordering + two added fields (salience, is_metric_claim); never mutates a value or a
    # verdict, so FCR surface is zero. LLM refinement (P1) is opt-in + best-effort.
    if claims:
        SAL.score_claims(claims, repo_dir, use_llm=opts.classify_llm)
        if claims:
            trace.note("top claim by salience: %s=%s (%.2f)"
                       % (claims[0].get("metric"), claims[0].get("claimed", claims[0].get("value")),
                          claims[0].get("salience", 0.0)))

    trace.stage("checking data", "checking committed splits and prediction artifacts")
    try:
        scans = LEAK.from_committed_splits(repo_dir)
        # ALSO scan a single committed DATASET (not a split) for its label distribution — the trivial-baseline
        # overlay then catches an inflated accuracy claim on the common "one committed CSV" repo shape, no run.
        scans += LEAK.from_committed_dataset(repo_dir)
        leakage = [r for r in scans if r["findings"]]              # findings-only → leakage overlay + UI
        baseline_sources = [r for r in scans if r.get("label_stats")]  # ALL label distributions → baseline overlay
        # ALSO fold in leakage found on MATERIALIZED data — the in-sandbox probe checked the actual downloaded
        # train/test split (runner/e2b_runner._run_leakage_probe), which a committed-splits-only scan can't see.
        mat = [r for r in ((run_result or {}).get("leakage") or []) if r.get("findings")]
        if mat:
            have = {r.get("dataset") for r in leakage}
            leakage.extend(r for r in mat if r.get("dataset") not in have)
            trace.note("leakage checked on materialized (downloaded) data — %d contaminated dataset(s)" % len(mat))
        b_have = {b.get("dataset") for b in baseline_sources}
        baseline_sources.extend(r for r in ((run_result or {}).get("leakage") or [])
                                if r.get("label_stats") and r.get("dataset") not in b_have)
        if leakage:
            trace.note("data leakage detected in %d dataset(s)" % len(leakage))
    except Exception:  # noqa: BLE001
        leakage = []
        baseline_sources = []

    # tier top-K gate (PRICING.md): with claims already sorted most-salient first, deep-verify only the K
    # highest-salience claims; hold the rest as DISCOVERED ("upgrade to verify"). Purely fail-closed — an
    # un-verified claim is never CONFIRMED, so this cannot admit a wrong number (FCR surface is zero).
    top_k = getattr(opts, "top_k", 0) or 0
    held = claims[top_k:] if (opts.deep and top_k and len(claims) > top_k) else []
    deep_claims = claims[:top_k] if held else claims
    if held:
        trace.note("tier cap: deep-verifying the top %d of %d claims by salience; %d held as DISCOVERED"
                   % (top_k, len(claims), len(held)))

    artifacts = _artifact_verify(repo_dir, deep_claims) if deep_claims else {}
    if artifacts:
        trace.note("recomputed %d claim(s) from committed predictions" % len(artifacts))

    trace.stage("diffing", "comparing claimed vs produced vs recomputed")
    if opts.deep and run_result:
        records = _diff_claims(deep_claims, run_result, job_run or {}, static_deterministic=static_det)
        records = [artifacts.get(rec["id"], rec) if rec["verdict"] == DISCOVERED else rec for rec in records]
    else:
        records = [
            artifacts.get(c.get("id"))
            or _claim_out(
                c,
                DISCOVERED,
                "discovered in %s - provide an entrypoint or committed predictions to verify" % c.get("source", "the repo"),
                {},
            )
            for c in deep_claims
        ]
    # claims beyond the tier's top-K are listed but not re-run (kept honest: DISCOVERED, not a verdict).
    for c in held:
        records.append(_claim_out(
            c, DISCOVERED,
            "not deep-verified on this tier (ranked #%d+ by salience) - upgrade to verify more claims" % (top_k + 1),
            {}))

    # fold dataset-level leakage back onto each attributed claim's verdict (the validity moat): a number
    # that reproduces perfectly is still INVALIDATED if its held-out split leaked.
    _apply_leakage_overlay(records, leakage)
    # trivial-baseline / degenerate on the SAME (materialized or committed) split label distribution: an accuracy
    # at/below the majority-class baseline, an AUROC at/below chance, or a single-class test set is INVALID.
    _apply_baseline_overlay(records, baseline_sources)
    # inline red-team gate (feature 8): a second, independent screen of every CONFIRMED, downgrade-only.
    _apply_redteam_gate(records, claims, run_result.get("runs") if (opts.deep and run_result) else None)
    # feature 1 second rail: if the repair loop changed repo source, cap CONFIRMED → REPRODUCED-ONLY.
    if opts.deep and run_result:
        _apply_agent_modified_cap(records, (run_result.get("repair_manifest") or {}).get("source_modified") or [])
    # feature 11 (dark-launched): advisory cross-run outlier flags + verified-run store update.
    if opts.anomaly:
        _apply_anomaly_overlay(records, _REFSTORE)

    counts: dict[str, int] = {}
    for rec in records:
        counts[rec["verdict"]] = counts.get(rec["verdict"], 0) + 1

    # feature 18 — the reproducibility receipt: a canonical, content-addressed serialization of the decided
    # records + run (the payload feature 3 signs). Built here, strictly downstream of every verdict; it never
    # feeds decide(), so its FCR surface is zero. Best-effort — a receipt error must not fail a verification.
    try:
        receipt = RCPT.build_receipt(records, job_run, opts.repo_meta)
    except Exception:  # noqa: BLE001
        receipt = None

    trace.stage("done", "verification complete")
    from core import report as REPORT
    summary = REPORT.summarize(records, job_run, leakage)      # plain-language explanation (leads the UI)
    trace.note("summary: " + summary["headline"])
    return {
        "status": "done",
        "stage": "done",
        "repo_dir": repo_dir,
        "run": job_run,
        "claims": records,
        "counts": counts,
        "n_claims": len(claims),
        "leakage": leakage,
        "summary": summary,
        "receipt": receipt,
        "trace": trace.events,
    }
