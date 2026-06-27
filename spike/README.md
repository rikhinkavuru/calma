# Calma rebuild — Phase 0 de-risking spike

> Per the rebuild guide (`~/calma-strategy/CALMA-REBUILD-GUIDE-2026-06-27.md`) §9: **do this before the
> big build.** Measure the two riskiest assumptions — **reproduction success rate** and **input-binding
> accuracy** — and prove the franchise gate (**false-confirm = 0**) on real code, so a hopeless beachhead
> rate is learned in a week, not a quarter.

This is a clean-slate, self-contained harness. It does not import the old engine; it lifts only the *idea*
of independent recompute, re-implemented pure-stdlib. It is the seed of the eventual `packages/core`,
`packages/discovery`, and `packages/runner`.

## The loop (guide §3–§5)

```
ingest repo → discover claim (TDMR) → make-runnable → sandbox run (k×, recorded)
            → INSTRUMENT-CAPTURE the raw arrays passed to each metric   ← the key new capability (§4.2b)
            → independent recompute (trusted catalog, separate clean impl)
            → three-way diff → verdict → score vs hand-graded truth
```

The three-way diff (guide §4.4) is the whole game:

| comparison | mismatch ⇒ |
|---|---|
| **claimed** (README/results.json) vs **produced** (the value the repo computed at runtime) | **REFUTED** — misreported / hallucinated |
| **produced** vs **recomputed** (our trusted impl on the *same captured inputs*) | **INVALIDATED** — wrong / cheating formula |
| all three agree **+ deterministic + validity-clean** | **CONFIRMED** |

**Fail closed (§4.7):** inputs unbindable, metric unrecognised, recompute degenerate, or determinism
unproven → never CONFIRMED. We downgrade to `REPRODUCED-ONLY` / `NON-DETERMINISTIC` / `INCONCLUSIVE` and
say what blocked it. ~0 false-confirm is the entire franchise — the router refuses rather than guesses.

## Layout

```
core/        trusted recompute oracle (catalog.py), three-way diff (diff.py), verdict taxonomy
             (verdict.py), rounding-aware claim tolerance (tolerance.py), validity overlay (validity.py)
capture/     calma_capture.py — the instrumented-capture shim; sitecustomize.py auto-loads it on PYTHONPATH
discovery/   extract.py — claim discovery (TDMR): auto-extract (metric, value) from results.json + README + stdout
runner/      local_runner.py (host subprocess), e2b_runner.py (Firecracker microVM), build.py (make-runnable)
fixtures/    one synthetic repo per verdict path + a realistic sklearn repo (own requirements.txt)
tests/       293 checks — catalog validated vs sklearn/numpy (1e-9), the full loop per verdict, discovery
repos.yaml   the corpus: hand-specified claims + hand-graded `expect`, or `discover: true` (auto-find claims)
run_spike.py the loop + scoring + the go/no-go memo (results/SPIKE-REPORT.md)
```

## The web app (connect a repo → verify the numbers)

A local-first web product over the engine — the connect → scan → findings flow, Calma-branded.

```bash
./spike/web.sh           # or: ~/.calma/spike-venv/bin/python spike/server.py
# → open http://localhost:8787
```

Paste a GitHub repo (or pick one of your own — it lists them via `gh`), then:
- **Auto-discover** (default): clone + find every number the repo reports (results.json / **results.csv** /
  README / stdout) and list them — the static layer, lights up *any* repo, even when it can't be re-run.
- **Deep verify** (toggle + entrypoint): re-run the code, recompute each claim independently, three-way
  diff → CONFIRMED / REFUTED / INVALIDATED. The bundled example (`ml-in-10-lines`) catches a real
  version-drift REFUTED.

Backend: `server.py` (FastAPI) runs each repo as a durable background job over `core` + `runner` +
`discovery`. In-memory jobs, local-first; the same engine moves behind a hosted `apps/api` to deploy.

## Run the spike (CLI)

```bash
python3 -m venv ~/.calma/spike-venv
~/.calma/spike-venv/bin/pip install numpy scikit-learn pandas pyyaml e2b pytest

cd spike
~/.calma/spike-venv/bin/python -m pytest tests/ -q          # 289 checks
~/.calma/spike-venv/bin/python run_spike.py                 # writes results/SPIKE-REPORT.md
# subsets / knobs:
~/.calma/spike-venv/bin/python run_spike.py --only clean_eval,misreported --k 3
```

E2B needs `CALMA_E2B_API_KEY` (+ `CALMA_E2B_ENDPOINT`, `CALMA_E2B_TEMPLATE`); read from the repo `.env`.

## Go / no-go gates

| Gate | Target | Current (synthetic + realistic + E2B) |
|---|---|---|
| **False-confirm count** | **0** (the franchise) | **0** |
| Reproduction rate | ≥ 60% floor on self-contained repos | 100% (9/9) — *synthetic; real external repos pending* |
| Input-binding accuracy | high | 92% (the 1 miss is the intentionally-ambiguous claim → correctly INCONCLUSIVE) |
| Verdict accuracy (graded) | high | 100% (13/13) |
| Cost / latency per repo | low | ~1.5s local, ~2.5s E2B, ~25s with a fresh venv build |

The headline reproduction number is only meaningful on **real external repos** — that is the next curation
step (fill the `# real:` section of `repos.yaml` with ~15–20 self-contained CPU repos). The synthetic suite
proves the *machine routes every case correctly and never false-confirms*; the real corpus measures the
*rate*.

## Couldn't-reproduce taxonomy (guide §14 — each → a user action / upsell)

`run_spike.py` classifies a non-running repo from its stderr and routes it:

| signature | reason | action / upsell |
|---|---|---|
| `ModuleNotFoundError` | missing dependency | declare/scan requirements → agentic env build |
| `FileNotFoundError` / `No such file` | missing input/dataset | **connect your data** |
| `CUDA` | needs a GPU | **GPU tier** |
| `out of memory` | OOM | larger sandbox tier |
| `timeout` | over the time budget | raise timeout / scope the run |

This is what makes the static fallback feel helpful instead of a dead end, and routes the hard cases to
paid features.

## What this de-risks (and what it doesn't, yet)

**Proven here:** the instrumented-capture mechanism (auto sklearn sinks + targeted custom-function wrap +
explicit API) reliably captures the *actual inputs* to a metric; an independent pure-stdlib recompute
agrees with sklearn to 1e-9; the three-way diff + fail-closed verdict routes every path correctly with
**zero false-confirms**; both the host and the E2B-isolated runners drive the same loop; the build-runnable
(per-repo venv) path works.

**Claim discovery (TDMR) — first version built** (`discovery/extract.py`): a repo with `discover: true`
has its claims auto-extracted from `results.json` / README tables / stdout and verified with no
hand-specification (the free path). Demonstrated on `realistic_autodiscover` (3 claims found + CONFIRMED).
Metric-name → catalog mapping uses the alias table + keyword tokens + split-prefix hints; the value parser
is where SOTA is weakest, so it carries a confidence. **Auto-binding** (dataflow tracing to replace the
hand bind hints) is the remaining stubbed piece.

**Still to measure (the actual Phase-0 question):** the reproduction + binding *rate on real external
repos*. The harness is ready and proven on one real clone; the corpus is not yet curated (the `# real:`
section of `repos.yaml`). The synthetic suite proves the *machine routes every case correctly and never
false-confirms*; the real corpus measures the *rate*.
