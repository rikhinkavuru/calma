"""calma.spike.pipeline — the end-to-end verification orchestration.

This is the product loop as code: static discovery, optional sandbox execution, captured-input recompute,
validity overlays, artifact-first verification, and structured stage tracing. The FastAPI server and tests
both call this module so the architecture is exercised outside the web UI.
"""
from __future__ import annotations

import os
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
    }


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

        trace.stage("running", "running in E2B microVM")
        return run_e2b(
            repo_dir,
            entry,
            k=opts.k,
            hooks=opts.hooks,
            targets=opts.targets,
            pip_install=opts.pip_install,
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
        records.append(_claim_out(claim, verdict, reason, rec.get("diff", {}), provenance=rec.get("recompute_provenance")))
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
        err = ""
        if not run_result.get("ran_ok"):
            err = (" ".join(m.get("stderr_tail", "") for m in run_result.get("meta", [])).strip())[-260:]
            trace.note("run failed: %s" % err[-200:])
        trace.note("captured %d computation(s)" % total_calls)
        job_run = {"ran": run_result.get("ran_ok"), "calls": total_calls, "entry": " ".join(entry), "error": err}

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
