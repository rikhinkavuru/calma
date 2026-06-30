"""calma.spike.pipeline — the end-to-end verification orchestration.

This is the product loop as code: static discovery, optional sandbox execution, captured-input recompute,
validity overlays, artifact-first verification, and structured stage tracing. The FastAPI server and tests
both call this module so the architecture is exercised outside the web UI.
"""
from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

from core import artifacts as A
from core import diff as D
from core import leakage as LEAK
from core import tolerance as T
from core import verdict as VD
from discovery import extract as DISC
from runner import build
from runner.local_runner import run_local
from synth import formula as SYNTH

DISCOVERED = "DISCOVERED"


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
    hooks: str = "sklearn"
    targets: list[dict] | None = None
    timeout: int = 600
    job_id: str = "pipeline"
    venvs_dir: str | None = None
    base_python: str | None = None


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


def _run_repo(repo_dir: str, opts: VerifyOptions, trace: Trace):
    entry = _argv(opts.entry)
    if opts.deep and not entry:
        entry = build.detect_entrypoint(repo_dir) or []
        if entry:
            trace.note("auto-detected entrypoint: %s" % " ".join(entry))
    if not entry:
        entry = ["eval.py"]

    trace.stage("building", "preparing runnable environment")
    if opts.runner == "e2b":
        from runner.e2b_runner import run_e2b

        # The E2B sandbox starts clean, so deps must be installed. If the caller didn't list them, infer:
        # requirements.txt, else the repo's actual imports. (Local runs use the harness python, which already
        # has the scientific stack — so we only auto-infer here, keeping local dev/tests offline + fast.)
        pip = opts.pip_install
        if not pip:
            pip, why = build.infer_requirements(repo_dir)
            if pip:
                trace.note("auto-deps (%s): %s" % (why, " ".join(pip)[:160]))
            else:
                trace.note("no deps detected (%s)" % why)
        trace.stage("running", "running in E2B microVM")
        return run_e2b(
            repo_dir,
            entry,
            k=opts.k,
            hooks=opts.hooks,
            targets=opts.targets,
            pip_install=pip,
            timeout=opts.timeout,
        ), entry

    venvs_dir = opts.venvs_dir or os.path.join(os.path.dirname(repo_dir), ".venvs")
    python, note = build.ensure_venv(opts.job_id, opts.pip_install, venvs_dir, base_python=opts.base_python or sys.executable)
    trace.note("env: %s" % note)
    trace.stage("running", "running %s" % " ".join(entry))
    return run_local(
        repo_dir,
        entry,
        k=opts.k,
        python=python,
        hooks=opts.hooks,
        targets=opts.targets,
        timeout=opts.timeout,
    ), entry


def _artifact_verify(repo_dir: str, claims: list[dict]) -> dict:
    out = {}
    for claim in claims:
        for path, cols in A.find_prediction_files(repo_dir):
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


def _diff_claims(claims: list[dict], run_result: dict, job_run: dict) -> list[dict]:
    records = []
    for claim in claims:
        if not run_result.get("runs"):
            records.append(_claim_out(claim, DISCOVERED, "deep verify could not run the entrypoint", {}))
            continue
        rec = D.diff_claim(claim, run_result["runs"], resolver=SYNTH.recompute_any)
        verdict, reason = rec["verdict"], rec.get("reason", "")
        if verdict == VD.INCONCLUSIVE and "no captured computation" in reason:
            verdict = DISCOVERED
            reason = (
                "the re-run did not recompute this number"
                + (" (the entrypoint failed to run)" if not job_run.get("ran") else " - point Calma at the script/args that compute it")
            )
        out = _claim_out(claim, verdict, reason, rec.get("diff", {}), provenance=rec.get("recompute_provenance"))
        # carry the always-on validity overlay (trivial-baseline / degenerate-distribution / chance-level)
        # through to the UI — it is what flipped a would-be CONFIRMED to INVALIDATED.
        out["validity"] = rec.get("validity", out["validity"])
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
    if opts.deep:
        run_result, entry = _run_repo(repo_dir, opts, trace)
        total_calls = sum(len(run) for run in run_result.get("runs", []))
        err, err_full = "", ""
        if not run_result.get("ran_ok"):
            err_full = (" ".join(m.get("stderr_tail", "") for m in run_result.get("meta", [])).strip())[-1200:]
            err = _error_summary(err_full)            # the actual exception, not the top of the traceback
            trace.note("run failed: %s" % (err or "entrypoint did not execute"))
        trace.note("captured %d computation(s)" % total_calls)
        job_run = {"ran": run_result.get("ran_ok"), "calls": total_calls, "entry": " ".join(entry),
                   "error": err, "error_full": err_full}

    claims = list(opts.claims or [])
    if opts.discover:
        trace.stage("discovering", "discovering reported numbers")
        stdout0 = run_result["meta"][0].get("stdout_tail", "") if (run_result and run_result.get("meta")) else ""
        discovered = DISC.discover(repo_dir, stdout_text=stdout0)
        trace.note("discovered %d claim(s)" % len(discovered))
        claims.extend(discovered)

    trace.stage("checking data", "checking committed splits and prediction artifacts")
    try:
        leakage = [r for r in LEAK.from_committed_splits(repo_dir) if r["findings"]]
        if leakage:
            trace.note("data leakage detected in %d dataset(s)" % len(leakage))
    except Exception:  # noqa: BLE001
        leakage = []

    artifacts = _artifact_verify(repo_dir, claims) if claims else {}
    if artifacts:
        trace.note("recomputed %d claim(s) from committed predictions" % len(artifacts))

    trace.stage("diffing", "comparing claimed vs produced vs recomputed")
    if opts.deep and run_result:
        records = _diff_claims(claims, run_result, job_run or {})
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
            for c in claims
        ]

    # fold dataset-level leakage back onto each attributed claim's verdict (the validity moat): a number
    # that reproduces perfectly is still INVALIDATED if its held-out split leaked.
    _apply_leakage_overlay(records, leakage)

    counts: dict[str, int] = {}
    for rec in records:
        counts[rec["verdict"]] = counts.get(rec["verdict"], 0) + 1

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
        "trace": trace.events,
    }
