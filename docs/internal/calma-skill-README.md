# Calma

**The trust layer for agentic work.** Your AI agents produce results that *look* right. Calma re-runs them and tells you whether they're actually real.

Drop it into Claude Code. Point it at what an agent just built — or have your agent call it as it works. Calma re-executes the code, **recomputes the headline number from the raw outputs** (it never trusts the number the agent reported), and returns a verdict you can act on — with a reproduction.

```
$ /calma verify ./btc-backtest  "+14,698% backtest"

  FAIL — claimed +14,698% is really −32% out-of-sample, net of costs
  • overfitting: the winner of 100 in-sample param combos, scored on the same data it reports
  • realism: 3× leverage, zero costs modeled — real fees flip it negative
  • benchmark: loses money AND underperforms buy-and-hold (−32% vs +40%)
  • reproduce: calma replay ./.calma/run-3f9
  scope: re-ran the code · recomputed from the out-of-sample trade log · real BTC-USD daily
```

<sub>Real, reproducible numbers — `scripts/teardowns/btc_overfit_teardown.py` on a vendored BTC snapshot (~0.2s, no network). The skill reproduces them through its own pipeline at M1. This is the fixture's actual failure mode — overfitting + realism + baseline; leakage / DSR land in later milestones.</sub>

## Why

AI agents generate a flood of plausible results — a metric, a backtest, a cleaned dataset, a “tests pass.” Usually it's fine. When it isn't, the failure is **silent**: a number that doesn't reproduce, a leak in a join you trusted, an overfit that only shows up in production. You can't catch that by asking another model *“does this look right?”* — that's just a second opinion. **Calma re-executes to ground truth** — the data, the raw outputs, the actually-recomputed number — and proves it, or breaks it.

And because the **agent** produced it, a FAIL isn't a knock on you — it's Calma catching the agent's mistake before you ship it.

## What it checks — any language, any domain

- **Reproduces?** Re-run → same number, or it isn't a result. (Only ~35% of real notebooks do.)
- **Recomputes?** The headline metric, rebuilt from the raw outputs — never the reported value.
- **Leakage / look-ahead?** Future or out-of-fold information sneaking in.
- **Holds on unseen data?** Re-run on data withheld from training — overfitting collapses.
- **Invariants hold?** The identities that must be true for an honest result.

No number to check against? It still works — it verifies properties, invariants, and reproducibility directly.

## Two ways to use it

- **After** — an agent finishes; you run `/calma` to verify what it produced.
- **During** — your agent calls Calma as a guardrail while it works, so results stay accurate as it changes things. (Fast: it only re-checks what changed.)

## What makes it trustworthy

The verdict is **computed by code, not by a model's opinion.** Every number — and the verdict itself — comes from deterministic scripts, so **even the agent that wrote the code can't talk Calma out of a FAIL.** That's the line between verification and a second opinion.

## Honest about limits

Calma proves a result is **real and reproduces** — not that the agent solved the *right problem*. When it can't fully verify (nondeterminism, a missing seed, outputs not emitted), it returns **CAN'T-CONFIRM** and tells you the exact fix to make it verifiable. It never cries wolf.

---

Open source. Runs on your machine — your code never leaves. *Quant & DS teams: the focused verification CLI is the next step.*
