"""Run synthesize() over a batch of metric specs and report the coverage KPI. Every 'admitted' recipe
passed the FULL gate (differential + metamorphic + degeneracy + bit-stability) -- the KPI is honest by
construction because it counts only compiler.admit() successes. This is the time series that tracks
"623 -> thousands": admission_rate and mean iters-to-admit per run; a rising admission_rate across runs
(same manifest, growing constraint DB) is the A3 flywheel working, and a P3.4 kernel batch shows up as a
step change on the metrics it unlocked."""
import json
import os
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from edges.common import store
from edges.synth import cegis
from edges.synth.spec import Spec

SUMMARY = os.path.join(os.path.dirname(__file__), "data", "fleet_runs.jsonl")


def load_manifest(path):
    """A fleet manifest is a JSON list of objects with the Spec fields. Returns [Spec]."""
    rows = json.load(open(path))
    return [Spec(**r) for r in rows]


def run_fleet(specs, *, venv_python, budget=8, model=cegis.llm.SONNET, max_workers=1,
              compiled_path=None, desc_path=None, constraints_db=None, drafts_log=None,
              run_def_of_done=False, summary_path=None, ts=None):
    """Synthesize every spec and persist a KPI summary.

    SAFETY: synthesize() does an unsynchronized read-modify-write of the SHARED registry (compiler.admit
    write=True), the constraint DB, the enrichment file, and the drafts log -- concurrent writers corrupt
    the registry and lose admitted recipes (a silent false non-admit + a non-reproducible KPI). So the
    DEFAULT is serial (max_workers=1, the safe + tested + record/replay-deterministic path); when a caller
    opts into a pool, every synthesize() call is serialized behind a lock so the shared writes stay
    correct (the pool then buys nothing but cannot corrupt the registry). True parallel coverage needs
    per-spec registries merged at the end -- a future change; until then the lock keeps the KPI honest."""
    results = []
    _write_lock = threading.Lock()

    def _one(s):
        with _write_lock:                                     # serialize the shared-registry/DB writes
            return cegis.synthesize(s.metric_id, s, venv_python=venv_python, budget=budget, model=model,
                                    compiled_path=compiled_path, desc_path=desc_path,
                                    constraints_db=constraints_db, drafts_log=drafts_log,
                                    run_def_of_done=run_def_of_done)

    if max_workers <= 1:
        for s in specs:                                   # sequential: a shared registry/DB is safe
            try:
                results.append(_one(s))
            except Exception as e:                        # a crash is recorded, never aborts the fleet
                results.append(cegis.Result(metric_id=s.metric_id, admitted=False, iterations=0,
                                            last_stage="error:%s" % type(e).__name__))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(_one, s): s for s in specs}
            for fut in as_completed(futs):
                s = futs[fut]
                try:
                    results.append(fut.result())
                except Exception as e:
                    results.append(cegis.Result(metric_id=s.metric_id, admitted=False, iterations=0,
                                                last_stage="error:%s" % type(e).__name__))

    admitted = [r for r in results if r.admitted]
    stuck = Counter(r.last_stage for r in results if not r.admitted)
    summary = {
        "n": len(specs),
        "admitted": len(admitted),
        "admission_rate": (len(admitted) / len(specs)) if specs else 0.0,
        "mean_iters_to_admit": (sum(r.iterations for r in admitted) / len(admitted)) if admitted else None,
        "stage_failure_histogram": dict(stuck),           # where the loop gets stuck, per stage
        "admitted_recipes": [{"metric_id": r.metric_id, "program_sha256": r.program_sha256,
                              "iterations": r.iterations, "n_vectors": len(r.vectors)} for r in admitted],
        "budget": budget, "model": model,
    }
    if ts is not None:
        summary["ts"] = int(ts)
    store.append(summary_path or SUMMARY, summary)
    return summary


def format_summary(summary):
    """Human-readable KPI line for the console / a CI log."""
    h = summary["stage_failure_histogram"]
    return ("coverage fleet: %d/%d admitted (%.1f%%)  mean iters-to-admit %s  stuck: %s\n"
            "admitted: %s" % (
                summary["admitted"], summary["n"], 100 * summary["admission_rate"],
                ("%.1f" % summary["mean_iters_to_admit"]) if summary["mean_iters_to_admit"] else "-",
                ", ".join("%s=%d" % (k, v) for k, v in sorted(h.items())) or "-",
                ", ".join(r["metric_id"] for r in summary["admitted_recipes"]) or "-"))
