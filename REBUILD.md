# Calma — the correctness layer · rebuild (in progress)

**Reframe (2026-06-27).** From a recipe-matching correctness tool → a web-native *"connect a repo → re-run
it → recompute every number it reports → CONFIRMED / REFUTED / INVALIDATED"* product. superagent.sh's
shape, but for **validity of computed results** instead of security. Source of truth for the design:
`~/calma-strategy/CALMA-REBUILD-GUIDE-2026-06-27.md`.

**One-liner:** *Calma re-runs your code and recomputes the numbers it reports — so you can trust the
result, not just the claim.*

---

## Where we are

**Phase 0 de-risking spike — built and green.** See [`spike/`](spike/) and
[`spike/results/SPIKE-REPORT.md`](spike/results/SPIKE-REPORT.md).

The spike proves the new core loop end to end — **instrument-capture the raw inputs to each metric →
recompute independently → three-way diff → fail-closed verdict** — on a synthetic suite (one repo per
verdict path), a realistic sklearn repo built from its own `requirements.txt`, and a real E2B Firecracker
microVM. Current gates: **false-confirm = 0**, 100% verdict accuracy (13/13), 92% binding (the one miss is
an intentionally-ambiguous claim → correctly INCONCLUSIVE), catalog validated vs sklearn to 1e-9 (324
tests). The remaining Phase-0 question — the reproduction + binding *rate on real external repos* — needs
the corpus curated (the harness is ready; fill the `# real:` section of `spike/repos.yaml`).

**Since the spike (product hardening, 2026-06-29):**
- The verify loop is one reusable module (`spike/pipeline.py`); the FastAPI server + tests share it.
- **Validity is wired into the per-claim verdict, not just a banner.** Dataset-level leakage (committed
  train/test splits, no re-run) is folded back onto every claim attributed to that dataset — a reproducible
  accuracy on a leaked split is now **INVALIDATED**, not CONFIRMED. Every claim record carries its validity
  findings. (This is the validity moat made real on the product surface.)
- Run failures surface the **actual exception** (e.g. `ModuleNotFoundError: No module named …`) instead of
  a generic "entrypoint failed to run".
- **Auth: "Verify a repo" routes through the WorkOS-gated Next dashboard** (`/dashboard/verify`), which
  proxies to the verification API server-side with a service token (`/api/verify[/id]`). The spike API
  (`/api/verify`, `/api/jobs`) is now token-gated — fail-closed when `CALMA_VERIFY_TOKEN` is set
  (first-party-only), open for the local-first operator when unset. Prod still needs the verification
  service deployed + `CALMA_VERIFY_API_URL` pointed at it (Vercel can't reach a laptop's localhost).

---

## Architecture decisions (this rebuild)

1. **Rebuild in-place, not a brand-new repo.** The guide floats a fresh repo; the live web deploy + domain
   + the landing-to-preserve make in-place reorganization the right call. New structure grows alongside the
   old code (which becomes reference); old dirs are archived once the new structure proves out. *No
   destructive moves until the spike → product transition.*
2. **Clean-slate architecture, lift only the math.** The only thing carried over is the *idea* of
   independent recompute, re-implemented pure-stdlib in `spike/core/catalog.py` (a genuinely independent
   oracle — zero shared code with the repo under test). The E2B SDK usage is lifted from the proven
   `run_hermetic._RealE2BSession`. **Cut:** the recipe-catalog / `verify.yaml` contract UX, the registry,
   the transparency-log / lineage, the CLI-first plumbing.
3. **Promise both, market as one** (§14.2): lead with reproducibility (universal), layer correctness where
   the metric is recognized.
4. **CPU-reproducible beachhead first** (§14.3): ML evals / notebooks / analytics. Dodge GPU initially.
5. **Async by design:** verification is a durable background job, never a synchronous request (next, in the
   product scaffold).
6. **Signing:** deferred (keep DSSE-on-reports only if an enterprise buyer asks).

## Target structure (guide §6) and how the spike seeds it

```
apps/web            ← web/            (live Next.js landing + dashboard; copy-only rewrite, §13)
apps/api            ← api/ + control_plane/   (durable jobs, sandbox orchestration, discovery, reports)
packages/core       ← spike/core/     (trusted recompute + validity; pure + tested) ✅ seeded
packages/runner     ← spike/runner/ + spike/capture/   (repo-to-runnable + sandbox + capture) ✅ seeded
packages/discovery  ← spike/discovery/  (claim extraction TDMR — first version) ✅ seeded
packages/sdk        ← (to build)      thin verify({repo}) client
apps/mcp            ← mcp/            (keep thin — the one client surface worth keeping)
```

## Next steps (in order)

1. **Curate the real corpus** — ✅ DONE (2026-06-29). 10 real repos run; **GO** memo at
   `spike/results/GO-NO-GO-corpus-2026-06-29.md`. Result: reproduction 80%, 11 auto-discovered claims,
   binding 58%, **false-confirm = 0**. Binding is the bottleneck (every miss fails closed) → step 3 is now
   the critical path. (More repos can still be added to lift the graded set above n=1.)
2. **Discovery (TDMR)** — ✅ first version built (`spike/discovery/extract.py`: results.json + README +
   stdout → claims, mapped to the catalog). Next: notebook outputs, wandb/mlflow logs, and invest in the
   VALUE parser (SOTA's weak spot). Free = auto-discover; paid = user states the claim.
3. **Build auto-binding** — ⭐ NOW THE CRITICAL PATH (the corpus proved it). Dataflow/provenance tracing to
   disambiguate multi-candidate cases (GridSearchCV's many accuracy calls, multi-model scripts → bind the
   held-out/test computation) + a value-recompute fallback for hand-rolled metrics with no library call to
   hook. Replaces the metric-identity + manual-hint binding today. Target: binding ≥ 85%.
4. **Grow the catalog** — port the proven metric corpus into `packages/core`; add the CEGIS synth-and-
   validate path for novel metrics.
5. **Product scaffold** — `apps/api` durable job model (`queued → mapping → triaging → verifying → done`),
   GitHub App connector (§7), dashboard tabs (Logs / Findings / Triage / Environment / Recordings),
   landing copy rewrite (§13).

## Landing page

**Keep the structure + brand** (dark Hero → light band → footer; Archivo; the lotus). **Copy only** changes
to the new positioning (§13). Not touched yet.
