# Calma FCR Bug Bounty

> The whole franchise is a single number: **FCR = 0** — the false-CONFIRM rate. This program pays for the one
> thing that can break it: a **wrong number that Calma reported as CONFIRMED**.

## Scope & severity

| Severity | What | Payout tier |
|---|---|---|
| **Critical** | A demonstrably WRONG number (misreported / fabricated / leaked / trivial / cheating-formula) that Calma returns as **CONFIRMED**. | The only Critical. |
| Low | A correct number wrongly REFUTED/INVALIDATED (a false-negative / trust cost, not an FCR breach). | Best-effort. |
| N/A | Any other verdict (REPRODUCED-ONLY, NON-DETERMINISTIC, INCONCLUSIVE, DISCOVERED). These are safe fail-closed outcomes and carry no positive commitment. | — |

Only the **CONFIRMED** verdict carries false-confirm risk, so only a false CONFIRMED is in Critical scope.

## What a valid submission looks like

A minimal, reproducible proof-of-concept: either

1. a **construct-only** case — a `{metric, claim, runs}` triple (the same shape as `optimize/redteam.py::attacks()`) where the claimed number is wrong yet Calma returns CONFIRMED; or
2. a **full repo** — a public repository + the exact claim, where deep verify returns CONFIRMED on a number that is actually wrong.

Triage runs your submission through `optimize/bounty.py::triage` (which calls `core.diff.diff_claim` /
`pipeline.verify_repo`). `is_false_confirm == True` → accepted.

## Rules of engagement / safe harbor

- Test only against your own repositories or the provided fixtures — never against third parties' private data.
- No stealth fixes: an accepted breach is disclosed **after** the fix ships and a regression fixture lands.
- No DoS, no attacks on infrastructure — this bounty is about the **verdict**, not the service.
- Duplicate submissions (same `dedup_key = metric × capability × transform`) collapse to the first report.

## What happens to an accepted breach

`promote_to_fixture` freezes it as a construct-only `redteam.attacks()` tuple or a `T4` `repos.yaml` stub with a
`capability:` tag. The standing CI gate (`optimize/redteam.py`, `test_optimize_gates.py`) then asserts
`adversarial_fcr == 0` forever — so the bug you found can never silently regress. That is the point: every
accepted counterexample makes FCR=0 *stronger*.
