# Calma teardown tests (demand + tech signal)

Manual runs of the Calma loop on real public claims. Goal: (1) tech signal — does it catch real lies or land INCONCLUSIVE? (2) demand signal — does a damning teardown pull inbound "run it on mine"?

---

## Teardown #1 — "3000%+ profit" crypto bot (Medium, public, code provided)

**Claim:** "3000+% profit in backtesting" (sister editions claim 4450%, 6204%, 10,000%+). BTC/USDT, 15m/1h, RSI+Bollinger+MACD, Python/Hyperopt.

**Calma loop, static pillars (no execution yet):**

```
  REFUTED (as evidence of a tradeable edge)   · true net return: INCONCLUSIVE (needs re-run)

  • OVERFITTING [critical]: parameters (take-profit, stop-loss, leverage) tuned with
    Hyperopt/TPE for 55–150 epochs, optimized directly on the SAME data the 3000% is
    reported on. Multiple "bots" tested; only the WINNERS published (3000/4450/10000%).
    No out-of-sample period. No deflated Sharpe. No trial-count N. → the number is the
    max of a noisy search, not an edge.
  • REALISM [high]: fee 0.05% modeled, but 1–10x leverage with ZERO slippage, no funding
    cost on perps, no liquidation, perfect TP/SL fills. At 10x, a tiny overfit edge is
    amplified into a fake 3000%.
  • LEAKAGE [medium]: in-sample optimization = data snooping; no train/test split shown.
  • DATA [medium]: single pair, single window, no walk-forward.

  scope: read methodology + code description · did NOT re-run · corrected number pending execution
  what would change this: an out-of-sample / walk-forward result with costs at the stated leverage
```

**Signal:** the lie-hunt fired hard and correctly from the *methodology alone*. The honest limit: Calma can say "this is overfit" with high confidence, but can't yet say "it's really +40%, not +3000%" without executing — that half is INCONCLUSIVE pending a re-run. Exactly the predicted split.

---

## Teardown #2 — civil-war prediction ML papers (arXiv 2207.07048 documents them)

**Claim:** complex ML models beat logistic regression at predicting civil war; reported AUC ~0.85; ML advantage over LR = 0.14 AUC.

**Calma loop verdict (recompute is published, so this one completes):**

```
  REFUTED — claimed ML>>LR by 0.14 AUC; after removing leakage, advantage = 0.01 (i.e. ~none)

  • LEAKAGE [critical]: each of 4 papers had a distinct leakage form; correcting it collapses
    the ML-over-LR edge from 0.14 → 0.01. Decades-old logistic regression is as good.
  • OVERFITTING/UNCERTAINTY [high]: reported smoothed AUC 0.85, but bootstrapped 95% CI is
    0.66–0.95 — the headline point estimate hides huge uncertainty.

  reproduce: Kapoor & Narayanan, "Leakage and the Reproducibility Crisis in ML-based Science"
  scope: corrected numbers from the published re-analysis (recompute completed)
```

**Signal:** clean, falsifiable number-collapse — the exact shape of a Calma REFUTED. Honest caveat: this case was *pre-debunked*, so it tests the loop's reasoning/verdict format, not fresh discovery.

---

## Honest tech-signal readout

- **Catches lies: YES, reliably, on the static pillars** (overfitting-from-methodology, realism gaps, in-sample/no-OOS). Both targets are REFUTED/CAVEAT on reading alone. A large share of real-world inflated results die here — cheap, no execution.
- **Produces the corrected number: HARD.** That needs faithful re-execution, and that's where the ~21% reproduction ceiling and INCONCLUSIVE outcomes live. #1 stays INCONCLUSIVE on the true number until run; #2 only completes because someone already published the corrected figure.
- **Implication:** the shippable, defensible core is the **adversarial lie-hunt + calibrated verdict** (catches + caveats), NOT a promise to always recompute the exact true number. That matches the market verdict: lead with the teardown, lean on INCONCLUSIVE, always show scope.

## Teardown #3 — EXECUTION teardown on real BTC-USD data (number-complete)

Not a static read — an actual run. Reproduces the exact lie pattern of the "3000%" bot (in-sample
parameter mining + leverage, no out-of-sample, no costs) on **real Coinbase BTC-USD daily data**
(3000 bars, 2018–2026), then runs Calma's recompute pillar: the *same* params, out-of-sample,
with real fees + slippage. No lookahead — the collapse is purely overfit + costs.
Reproducible: `scripts/teardowns/btc_overfit_teardown.py` (pure stdlib).

```
  REFUTED — claimed +14,698% is really −32.4% out-of-sample, net of costs

  CLAIMED (in-sample, best of N=100 param combos):  +14,698%   Sharpe 1.32
  CALMA   (same params, out-of-sample, real costs):    −32.4%   Sharpe 0.19
  buy & hold over the same out-of-sample window:        +40.4%   Sharpe 0.53

  • OVERFITTING [critical]: the winner of 100 param combos, picked on the same data it reports.
    In-sample Sharpe 1.32 -> out-of-sample 0.19.
  • REALISM [high]: 3x leverage; costs alone drag OOS from −27.4% to −32.4%.
  • BENCHMARK [critical]: loses money AND underperforms doing nothing (−32% vs +40%).
  scope: real BTC-USD daily · no-lookahead · recompute completed (NOT inconclusive).
```

**Signal:** when the work is *runnable*, the recompute pillar produces the killer number — +14,698%
to −32%. This is the strongest possible demand ammo, and it's reproducible by anyone in ~20s.

---

## Demand probe (post this; measure inbound)

> I took the exact recipe behind those **"+14,000% backtest"** crypto bots — grid-search the
> parameters on the same data you report, add leverage, skip out-of-sample, skip costs — and ran it
> on real BTC. In-sample: **+14,698%**. Same strategy walked forward with real fees: **−32%** — worse
> than just holding (+40%). The backtest number isn't an edge, it's the max of a noisy search.
> Reply if you want me to run this teardown on a strategy you're about to put money behind.

The only demand signal that counts: someone replies **"can you run it on mine?"**
