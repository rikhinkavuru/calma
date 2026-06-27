# Calma — the correctness layer

> *AI did the work. Calma checks it.*
>
> Connect a repo. Calma finds the numbers it reports, re-runs the work, and **recomputes each one from the
> raw outputs — not the value that was reported** — then tells you which hold up: **CONFIRMED / REFUTED /
> INVALIDATED**.

Every agent and analysis now ships *numbers* — a Sharpe, an AUC, "tests pass", "2.3× faster". People trust
the reported number; they read the diff, not the data. Code is buggy, agents hallucinate, results leak and
overfit, and the wrong number ships. Calma re-executes and independently recomputes, deterministically — so
you can trust the result, not just the claim.

## Repo layout

```
spike/     the engine + the web product
           ├─ core/        trusted recompute oracle + three-way diff + fail-closed verdicts (pure-stdlib)
           ├─ capture/     instrumented capture — intercepts the raw arrays passed to each metric
           ├─ runner/      repo-to-runnable + sandbox (host / E2B Firecracker)
           ├─ discovery/   claim discovery (TDMR) from results.json / results.csv / README / stdout
           ├─ server.py    the verify API (durable jobs over the engine)
           └─ web/         the dashboard: connect a repo → verify → findings
web/       the marketing landing (Next.js; dark hero, the lotus) — the brand
legacy/    the previous build (the 628-recipe CLI engine), archived for reference
REBUILD.md the architecture, decisions, and roadmap for the rebuild
```

The rebuild replaced ~74k LOC of recipe-matching engine with a ~3k-LOC blackbox **capture-and-recompute**
loop. How it works, the de-risking results, and the design decisions are in **[REBUILD.md](REBUILD.md)**.

## Try it

```bash
# the verification engine + tests
python3 -m venv ~/.calma/spike-venv
~/.calma/spike-venv/bin/pip install numpy scikit-learn pandas pyyaml e2b pytest fastapi "uvicorn[standard]"
~/.calma/spike-venv/bin/python -m pytest spike/tests -q          # 293 checks

# the web product — connect a repo, verify the numbers
./spike/web.sh                                                   # → http://localhost:8787

# the landing
cd web && npm run dev                                            # → http://localhost:3000
```

## How it catches a wrong number

1. **Discover** every number the repo reports (the static layer — works on *any* repo).
2. **Re-run** the code in an isolated sandbox and **capture the actual inputs** to each metric.
3. **Recompute** each metric independently with a trusted implementation (zero shared code with the repo).
4. **Three-way diff** — claimed vs repo-produced vs independent-recompute:
   - claimed ≠ produced → **REFUTED** (misreported)
   - produced ≠ recomputed → **INVALIDATED** (wrong/cheating formula)
   - all agree + deterministic + valid → **CONFIRMED**
5. **Fail closed** — unbindable, unrecognized, or non-deterministic → never CONFIRMED. ~0 false-confirm.
