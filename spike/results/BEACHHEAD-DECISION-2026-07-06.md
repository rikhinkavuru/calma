# Beachhead decision — go all in on AI-eval / benchmark integrity

Grounded in (a) the 60-repo eval that mapped what Calma verifies well, and (b) 2026 market data on where the
money and the pain are. This is the "pick the niche and go all in, weighed against market size" call.

## The decision

**Position Calma as the neutral third-party auditor for AI benchmarks and evals: "recompute the number,
catch the contamination — deterministic, never a false confirm."** Monetize on AI labs + enterprises +
compliance. Use reproducible-research (academic artifact badges) as a free credibility/adoption wedge, not the
revenue.

## Why this niche (market data, 2026)

- **It's exploding and it pays.** Arena/LMArena went **$30M → $100M ARR in 8 months** on a paid Evaluations
  product, at a **$1.7B** valuation. LLM-eval-as-a-service is **$2.25B (2026) → $6.31B (2030), 29.5% CAGR**;
  the broader AI-evaluation category is credibly $10B+ within the decade. Forecast growth drivers named
  explicitly: **continuous evaluation in CI/CD** and **compliance-ready reporting** — both squarely Calma.
- **The pain is Calma's thesis, verbatim.** The industry's "**grading your own homework**" problem hit a
  breaking point: enterprise procurement now **refuses to rely on vendor-reported benchmarks** and wants
  "third-party verification with the same rigor as financial auditors." Every static benchmark is
  contaminated; identical weights score 10-20 pts apart by harness; leaderboard numbers are "trivially
  gameable." SWE-ReBench-style decontamination exposed memorization-driven scores.
- **Neutrality is the moat — and the window is closing.** As foundation labs acquire the evaluation companies,
  the pool of genuinely neutral assessors shrinks; buyers are told to "establish relationships with
  independent providers now." Calma is neutral **by construction** (a deterministic recompute, no conflict of
  interest, no data retention) — a structural advantage a lab-owned evaluator cannot claim.
- **Regulatory tailwind.** NIST AI TEVV + the EU AI Act push toward mandatory AI evaluation → compliance spend
  that flows to auditable, standardized assessment.

## Why Calma fits it exactly (already shipped)

| Buyer pain | Calma capability (built + deployed) |
| --- | --- |
| "Does this benchmark's leaderboard actually reproduce?" | **artifact-reproduction** — re-run the repro, diff regenerated vs committed result files (meta: 983/983 cells; catches a non-reproducing number, names the cell) |
| "Is this benchmark contaminated / leaked?" | **leakage detection** — verbatim + homology train/test overlap, fail-closed |
| "Is the reported metric even computed right?" | **recompute-and-diff** — independent recompute of the standard metric from raw outputs → CONFIRMED / REFUTED / INVALIDATED |
| "I can't trust a self-graded score." | **deterministic verdict, never a false confirm** — the whole trust model, plus signed replayable receipts |
| "Gate it in CI." | **`calma verify --deep`** exits non-zero on REFUTED/INVALIDATED; GitHub Action + PR check |

The 60-repo eval confirmed the limits too: Calma lands clean verdicts when a repo has **one hookable/committed
headline number + a runnable entrypoint** — exactly the shape of a benchmark/eval submission, and the reason to
target that segment rather than arbitrary ML repos.

## GTM

1. **Wedge (free, for credibility):** the no-run validity check + artifact-repro on public benchmark repos and
   paper artifacts. Ride the academic reproducibility mandates (ACM "Results Reproduced" badges, NeurIPS MLRC,
   PLOS code-sharing-mandatory-2027) — free, builds the neutral-auditor brand, seeds the funnel.
2. **Land (paid):** benchmark maintainers, eval vendors, and enterprises standardizing on a model — "we
   independently verify your leaderboard reproduces + is decontaminated, and issue a signed report." Sell the
   auditor relationship *now*, while independent neutrality is scarce and being acquired away.
3. **Expand:** continuous verification in CI (the agent-CI angle) + compliance-ready reports for NIST TEVV /
   EU AI Act. Consumption or per-benchmark-audit pricing (mirrors Arena's model that hit $100M ARR).

## What to sharpen next (product)

The engine is there; the gaps are positioning + two demos, not new verdict logic:
- A **"verify this leaderboard"** flow: point Calma at a benchmark repo (committed predictions + leaderboard) →
  one report card of which cells reproduce + any contamination. (artifact-repro + leakage already do this.)
- A **decontamination report** as a first-class output (leakage detection reframed as "benchmark contamination
  audit").
- Keep widening make-runnable coverage (6 fixes shipped this session) — every benchmark repo that now runs is a
  verifiable customer artifact.

## Refinement — where the recompute actually bites (GT is usually hidden)

Scouting real benchmark repos surfaced a constraint: **live competition leaderboards hide the ground-truth
labels** (to stop gaming), so you often cannot recompute their headline metric from what's committed. The
recompute-from-committed-predictions path therefore bites hardest on **reproducibility artifacts** — the
predictions + labels + scorer a paper/challenge commits *for peer/artifact review* (e.g. PhysioNet's
`evaluate_model.py -d labels.csv -o predictions.csv`, PTB-XL's `preds_x.npy`/`targs_x.npy`, per-run result
CSVs). This is the concrete paid entry point: **the artifact-evaluation / reproducibility-review step**
(ACM/NeurIPS/IEEE artifact committees, journal code-review, a lab's internal "did this eval reproduce before we
publish it" gate) — a place that both needs auditor-grade verification AND has committed both sides. Two
verifiable modes to lead with:
1. **Committed predictions + labels + a reported score** → recompute the standard metric → CONFIRMED / REFUTED.
2. **A repro script + committed result files** → artifact-reproduction (already shipped; meta 983/983).

## What NOT to do

Do not chase the generic "point Calma at any ML repo" funnel (low CONFIRM-rate: multi-value binding wall,
repos that don't run) or build for the academic segment's willingness-to-pay (mandate-driven but
volunteer/APC-funded). Both are wedges, not the business.
