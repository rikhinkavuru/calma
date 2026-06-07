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

## Audit round 1 (adversarial, 2 auditors) - fixed

- **NaN-input propagation** (numeric.py): auc/accuracy/max_drawdown/DeLong now return NaN on NaN inputs
  so the recipe flags `degenerate` and the verdict degrades to INCONCLUSIVE (was: silently valid metric).
- **Path traversal** (recompute.py `_safe_join`): artifact paths that escape the contract base (abs / ..)
  are refused.
- **Determinism mis-detection** (run_hermetic.py): regex replaced with an AST scan that catches
  `import random as r`, `from random import ...`, `secrets`, `os.urandom`, numpy/torch aliases -> these
  are no longer mislabeled controlled-to-bit (closed a false-REFUTED soundness hole).
- **M2-gate soundness** (verdict.py): a REFUTED on a measured/uncontrolled BAND now requires M2
  calibration regardless of isolation tier (a container does not validate an uncalibrated band).
- **Sandbox read-scope** (run_hermetic.py): profile now denies ALL user homes (/Users) + system-secret
  dirs (keychains, /etc/ssh, /var/root), not just $HOME; `doctor` runs a probe BATTERY (raw-IP, DNS,
  curl egress + multiple secret reads) and stamps host-not-isolated on ANY leak. Honest stamp added:
  Seatbelt is host-kernel-shared, NOT escape-isolated (untrusted code still requires a container/VM,
  refused otherwise) - the process-escape-on-timeout limit is acknowledged, not hidden.
- All proxy env vars (incl no_proxy) cleared for the run phase.
- 20 new regression tests (test_audit.py). Total: 121 checks across 8 suites, all green.

## Audit round 2 (verification pass) - all round-1 fixes confirmed; 3 new fixed

- **Entrypoint path traversal** (run_hermetic.run): the entrypoint is now guarded by `_within(base,...)`
  exactly like artifact paths - an escaping entrypoint is refused (exit 2) and never read/executed on the
  host (closed a host-side read before sandboxing).
- **Dynamic-import / exec determinism evasion**: `_detect_determinism` now returns `uncontrolled` for
  `__import__`, `importlib.import_module`, `exec`/`eval`/`compile` - purity cannot be proven statically, so
  it fails safe (was: mislabeled controlled-to-bit).
- 7 new regression tests. Total: 128 checks across 8 suites, all green.

## Audit round 3 (convergence) - CONVERGED

Verdict: CONVERGED (no critical/major). Confirmed closed: entrypoint/artifact symlink-escape (realpath),
ledger REFUTED-cannot-be-clean invariant, orchestrator edge cases (no-contract / timeout / untrusted all
yield a coherent valid ledger, never a crash or exit-2). One honest tightening applied: importing a
stdlib source of run-to-run variation (time/datetime/uuid/socket/threading/multiprocessing) now downgrades
from controlled-to-bit to measured-band (fails safe). Total: 130 checks across 8 suites, all green.

## Status: M0 + M1 COMPLETE and audited. The closed build->audit->fix loop converged in 3 rounds.

Try it:  python3 .claude/skills/calma/scripts/calma.py verify .claude/skills/calma/assets/btc
Tests:   python3 .claude/skills/calma/scripts/tests/run_all.py
