"""calma.spike.pipeline — the end-to-end verification orchestration.

This is the product loop as code: static discovery, optional sandbox execution, captured-input recompute,
validity overlays, artifact-first verification, and structured stage tracing. The FastAPI server and tests
both call this module so the architecture is exercised outside the web UI.
"""
from __future__ import annotations

import concurrent.futures
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
    fetch_data: bool = False        # opt-in: on a "missing input file" failure, fetch the data via Exa + retry
    heal_deps: bool = True          # self-heal: pip-install a dep the imports didn't reveal (openpyxl) + retry
    repair: bool = False            # feature 1: iterative env-only repair loop (deps/env/argv/data) until the
    #                                 entrypoint runs. Never edits repo compute; a bad step → DISCOVERED, not a
    #                                 confirm. A post-repair source change caps the verdict at REPRODUCED-ONLY.
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
    m = _MODERR_RE.search(err)
    name = next((g for g in m.groups() if g), None) if m else None
    top = name.split(".")[0] if name else None
    return top if (top and not top.startswith("_")) else None


def _with_static_targets(repo_dir: str, tgts, trace: Trace):
    """Cycle-2 binding fix: append target_discovery's deterministic, name-matched fallback targets (marked
    `static: True`, capped below CONFIRMED downstream — core/diff.py's `heuristic_bind`) to whatever the
    caller/AI planner already proposed. Dedup by function name; never overrides an existing (higher-trust)
    proposal. Best-effort — any failure here just means fewer fallback targets, never a broken run."""
    try:
        have = {t.get("target") for t in (tgts or [])}
        extra = [t for t in TD.propose(repo_dir) if t.get("target") not in have]
    except Exception:  # noqa: BLE001 — a repo-scanning heuristic must never break the verify
        extra = []
    if not extra:
        return tgts
    trace.note("static fallback capture targets (name-matched, capped below CONFIRMED): %s"
              % ", ".join(t["target"] for t in extra)[:160])
    return list(tgts or []) + extra


def _run_repo(repo_dir: str, opts: VerifyOptions, trace: Trace, k: int | None = None, get_plan=None):
    k = opts.k if k is None else k                    # adaptive-k passes an effective k (1 when proven det.)

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

        # Deferred resolution: run_e2b calls this AFTER the microVM boots, so the run-plan (running in a
        # background thread) overlaps the boot instead of preceding it. Precedence: explicit opts > AI plan >
        # heuristics. The E2B sandbox starts clean, so deps must be installed — the caller's list, else the AI
        # plan's, else inferred from requirements.txt / the repo's imports.
        holder: dict = {}

        def _resolve():
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
                    pip, era = build.era_pin(pip, repo_dir)            # pin INFERRED deps to the repo's commit-date era
                    if era:
                        trace.note("era-pinned inferred deps to %s" % era)
                trace.note(("auto-deps (%s): %s" % (why, " ".join(pip)[:160])) if pip
                           else "no deps detected (%s)" % why)
            tgts = opts.targets or (plan.get("targets") if plan else None)   # AI-identified metric fns to capture
            if tgts and not opts.targets:
                trace.note("AI-planned capture targets: %s" % ", ".join(t["target"] for t in tgts)[:160])
            tgts = _with_static_targets(repo_dir, tgts, trace)
            holder.update(entry=entry, pip=pip, strict=strict, targets=tgts)
            return entry, pip, strict, tgts

        trace.stage("running", "running in E2B microVM")
        result = run_e2b(repo_dir, resolve=_resolve, k=k, hooks=opts.hooks,
                         python_version=pyver, timeout=opts.timeout, log=trace.note, fuzz=opts.fuzz)
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
            result = run_e2b(repo_dir, entry, k=k, hooks=opts.hooks, targets=tgts,
                             pip_install=pip, pip_strict=strict, python_version=pyver, timeout=opts.timeout,
                             log=trace.note, fuzz=opts.fuzz)
        return result, entry

    # local path — no sandbox boot to hide behind, so join the plan synchronously
    plan = get_plan() if get_plan else None
    entry = _entry(plan)
    pip = opts.pip_install or (plan.get("pip_install") if plan else None)
    tgts = opts.targets or (plan.get("targets") if plan else None)      # AI-identified metric fns to capture
    tgts = _with_static_targets(repo_dir, tgts, trace)
    venvs_dir = opts.venvs_dir or os.path.join(os.path.dirname(repo_dir), ".venvs")
    base_py = opts.base_python or sys.executable
    python, note = build.ensure_venv(opts.job_id, pip, venvs_dir, base_python=base_py)
    trace.note("env: %s" % note)
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
        result, manifest = REPAIR.repair_loop(_runfn, propose, _apply, max_steps=4,
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


def _artifact_verify(repo_dir: str, claims: list[dict]) -> dict:
    out: dict = {}
    # Scan the repo for committed prediction files ONCE — it's a pure function of repo_dir. Doing it inside
    # the per-claim loop re-walked + re-read the repo for every claim; a benchmark that discovers hundreds of
    # claims (gb_kmer: 838) turned that into ~838 full repo scans = a ~15-minute stall.
    pred_files = A.find_prediction_files(repo_dir)
    if not pred_files:
        return out
    for claim in claims:
        for path, cols in pred_files:
            res = A.recompute_from_cols(cols, claim.get("metric"), SYNTH.recompute_any)
            if not res:
                continue
            recomputed = res["value"]
            ok, _ = T.claim_close(claim.get("value"), recomputed)
            fname = os.path.basename(path)
            reason = (
                "claim matches the committed predictions (%s · recomputed %.5g)" % (fname, recomputed)
                if ok
                else "claim %r != recompute from committed predictions (%s = %.5g)"
                % (claim.get("value"), fname, recomputed)
            )
            out[claim.get("id")] = _claim_out(
                claim,
                VD.CONFIRMED if ok else VD.REFUTED,
                reason,
                {"claimed": claim.get("value"), "recomputed": recomputed},
                provenance="artifact:" + (res.get("provenance") or "recipe"),
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

    run_result, entry = None, _argv(opts.entry)
    job_run = None
    static_det = False
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
        run_result, entry = _run_repo(repo_dir, opts, trace, k=eff_k, get_plan=_get_plan)
        if not run_result.get("ran_ok") and opts.fetch_data:    # opt-in: grab missing external data, then retry
            from runner import data_resolver as _DR
            miss = _DR.missing_data_path(" ".join(m.get("stderr_tail", "") for m in run_result.get("meta", [])))
            if miss:
                ok, note = _DR.resolve_missing_data(repo_dir, miss)
                trace.note("data-fetch: %s" % note)
                if ok:
                    run_result, entry = _run_repo(repo_dir, opts, trace, get_plan=_get_plan)
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
        discovered = DISC.discover(repo_dir, stdout_text=stdout0)
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
        leakage = [r for r in LEAK.from_committed_splits(repo_dir) if r["findings"]]
        if leakage:
            trace.note("data leakage detected in %d dataset(s)" % len(leakage))
    except Exception:  # noqa: BLE001
        leakage = []

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
    return {
        "status": "done",
        "stage": "done",
        "repo_dir": repo_dir,
        "run": job_run,
        "claims": records,
        "counts": counts,
        "n_claims": len(claims),
        "leakage": leakage,
        "receipt": receipt,
        "trace": trace.events,
    }
