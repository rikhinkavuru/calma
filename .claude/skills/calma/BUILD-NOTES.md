# Calma build notes

Living record of what shipped, what's in progress, decisions, and open questions. Per the runbook, the
repo stays green and runnable at every commit. Phase A (M0+M1) is buildable on this M4; M2+ needs the
repo corpus (see `docs/BUILD-REVIEW.md`).

## Status

| Milestone | State | Notes |
|---|---|---|
| M0.0 verdict.py | **DONE, tested (27/0)** | Total pure `verdict()` over the full vector; conservative defaults; ordered false-REFUTED guards; M2-gate + controlled-to-bit carve-out. |
| M0.1 ledger + gate | **DONE, tested (12/0)** | schema + semantic `_validate()` (byte-re-derivation), strict-lattice gate, FP-aware repo verdict. BTC ledger fixture -> REFUTED / exit 1. |
| M0.2 SKILL.md + invariants | **DONE** | TOC body, version-gated description (M1 = recompute-and-diff + baseline; rest named as roadmap), 7 machine-enforced invariants. |
| M1.1 verify.yaml + draft_contract + recipes | **DONE, tested** | verify.schema.json; draft_contract.py (tag inference + graded binding); recipes: quant (Sharpe, total_return, max-drawdown) + general (accuracy, AUC-DeLong). |
| M1.2 run_hermetic | **DONE, tested** | verified Seatbelt tier with `calma doctor` positive-control (secret-read + egress BOTH blocked); process-group kill on timeout; untrusted-third-party refused (no container). |
| M1.3 recompute + compare + attest | **DONE, tested** | reference-deterministic recompute (fsum/pairwise-product/sqrt, NO transcendental/numpy); calibrated budget; shared verdict(); SBOM manifest. |
| M1.x orchestrator + report | **DONE, tested** | `calma.py verify` chains draft->run_hermetic->recompute->compare->ledger/gate->attest->progressive report. BTC -> REFUTED, honest claim -> CONFIRMED, end-to-end. 101 tests across 7 suites. |
| M2 calibration lock-gates | **deferred (infra)** | self-calibrating on this M4 per blueprint, but needs a 3-5 repo x language corpus. REFUTED-without-container disabled for MEASURED-BAND until passed; CONTROLLED-TO-BIT exempt. |
| M3 five-family + stats_engine | **deferred** | DSR/PBO validatable vs mlfinlab/pypbo vectors w/o new infra; leakage re-run + domain breadth need the corpus. |
| M4 breadth + contamination + signing | **deferred** | |

## Key decisions

- **Generalizable skill -> deep-quant CLI** (founder-confirmed). Breadth = the recompute-and-diff spine +
  trivial general recipes; DEPTH (DSR, leakage, realism) stays quant-only and becomes the CLI's core.
- **Reference transcendentals via `mpmath` at fixed precision** (correctly-rounded path) rather than
  vendoring crlibm for M1 - same guarantee class, far less build risk. Recorded as the pinned-libm choice.
- **Isolation on macOS = Tier-0 native sandbox + a verified `sandbox-exec` Seatbelt profile** with a
  positive-control credential-read self-test (`calma doctor`). Container/VM tier for untrusted third-party
  code requires a daemon (colima/Docker) not up on this host -> untrusted falls to static-only INCONCLUSIVE.
- **Tier-0 counts as a verified isolation tier** for the "REFUTED-without-a-container" rule; that rule gates
  MEASURED-BAND (nondeterministic) runs only - CONTROLLED-TO-BIT runs (the pure-stdlib BTC fixture) REFUTE.

## Open questions (-> Validation Plan blueprint S16)

- Tolerance-model constants (per-metric floors, fraud-multiple M) are placeholders until the M2 corpus
  calibrates them. Until then REFUTED only fires on CONTROLLED-TO-BIT runs with astronomic gaps (the BTC
  case). Do NOT ship measured-band REFUTED before M2.

## Test entrypoint

`python3 .claude/skills/calma/scripts/tests/run_all.py` runs every suite (pure stdlib; no pytest/numpy).
