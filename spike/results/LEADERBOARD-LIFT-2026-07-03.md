# Leaderboard lift — artifact ingestion + reverse map (slices 1+2)

_End-to-end before/after of the "re-run the paper" work (2026-07-03). Measured by
`optimize/leaderboard_eval.py`: generate N leaderboard repos (a driver that loops dataset × model computing
a sklearn metric with dataset/model context locals + writes a committed nested `results.json`; a decoy
quickstart; one misreported cell), then run the whole flow — detect_entrypoint → discover committed claims →
run_local (k=2) → diff per cell → verdict._

**Method.** Same instrument run against two git checkouts (deltas are exactly the two slices; capture-side
context extraction is equal in both trees, so it cancels):
- **BEFORE** = `468c3d1` (pre-session, before both slices).
- **AFTER** = `18ef723` (slice 1 `aa887fa` + slice 2 `18ef723`).

4 repos × 6 cells = **24 leaderboard cells**, 1 misreported cell/repo (expect REFUTED).

| Metric | BEFORE (468c3d1) | AFTER (18ef723) |
|---|---|---|
| Entrypoint = the real suite (not the quickstart) | **0%** (ran the decoy `check.py`) | **100%** (`run_all.py`) |
| Claims discovered | 16 (24 cells collapsed — dedup on value, no context) | **24** (per-cell) |
| Claims carrying dataset/model context | **0%** | **100%** |
| Cells bound to their own computation | n/a (bound to the decoy's single call) | **100%** |
| Cells with the correct verdict | **0 / 24** | **24 / 24** |
| Verdict distribution | 16 REFUTED (all false-refutes) | **20 CONFIRMED + 4 REFUTED** |
| Misreports caught | 0 / 4 | **4 / 4** |
| **False-confirm count** (the franchise) | **0** | **0** |

## What the two states mean

**BEFORE.** On a leaderboard repo Calma (a) ran the wrong script — the alphabetically-first runnable file
(`check.py`, a one-line quickstart) instead of the suite that wrote the committed table; (b) discovered only
16 of 24 cells because the nested `results.json` dropped each cell's dataset/model label, so same-valued
cells collapsed on `(metric, value)`; (c) with no context and the wrong computation captured, bound every
claim to the quickstart's single `accuracy=1.0` call and **false-refuted all 16** — zero correct verdicts.
The one invariant that held: no false-confirm.

**AFTER.** Slice 2's reverse map picks `run_all.py` (it writes `results.json`); slice 1 keeps each cell's
`model=… dataset=…` context, so all 24 cells discover distinctly and the context-binder pins each to its own
computation. Result: **20 honest cells CONFIRMED, 4 planted misreports caught, 0 false-confirms, 100%
verdict accuracy.**

## Caveats / scope

- Synthetic-but-faithful repos (real sklearn calls, real capture/bind/recompute/verdict path; only the data
  is generated deterministically). It isolates the two slices; it is **not** a real-repo corpus.
- Discovering committed claims **before** the run is load-bearing here: a producer entrypoint regenerates
  `results.json`, which would erase a committed misreport if discovery ran after. The linear `pipeline.py`
  discovers post-run — a repo whose entry overwrites its own committed results is a real edge worth a
  snapshot step (follow-up, not this slice).
- FCR=0 held in both trees — the slices are pure discovery + run-planning, never the verdict path.

## Next

Curate real leaderboard/benchmark GitHub repos into `repos.yaml` (`# real:` section) and re-measure with
`run_spike.py` to confirm the lift transfers off synthetic data — and then decide whether to promote
`artifact_producer` above the AI plan in `pipeline._entry` (held back pending this real-repo evidence).
