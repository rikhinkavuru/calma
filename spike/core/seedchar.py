"""calma.spike.core.seedchar — seed characterization (feature 15).

The DELICATE feature. Seeding is not a free determinism fix: the seed is an INPUT to the computation (it
selects the split/init/shuffle), so a run with an injected seed computes a DIFFERENT number than the author
reported. Therefore seed injection may only CHARACTERIZE non-determinism — answer "is the unseededness the only
source of spread?" — it may NEVER manufacture a point confirm. Nothing here feeds a claim's `produced`; the
verdict stays NON-DETERMINISTIC (with a better explanation), and `core.verdict` independently hard-caps any
seed_injected run below CONFIRMED. Pure orchestration over an injected run_fn (fully testable, no sandbox).
"""
from __future__ import annotations


def _spread(values):
    vals = [float(v) for v in (values or []) if isinstance(v, (int, float)) and v == v]
    return (max(vals) - min(vals)) if len(vals) >= 2 else 0.0


def characterize_seed(run_fn, seed: int = 1234, tol: float = 1e-9) -> dict:
    """`run_fn(env_extra) -> [produced values across runs]`. Runs the repo unseeded, then with an injected
    seed, and reports whether the seed controls the spread. Returns a CHARACTERIZATION only — never a value to
    confirm against.

    seed_controls_spread=True means: the repo is irreproducible unseeded but stable once seeded, i.e. "the
    author's number depends on their unshared seed" — an honest NON-DETERMINISTIC explanation, not a confirm.
    """
    unseeded = run_fn(None)
    seeded = run_fn({"CALMA_INJECT_SEED": str(seed)})
    us, ss = _spread(unseeded), _spread(seeded)
    seeded_stable = ss <= tol
    return {"unseeded_spread": us, "seeded_spread": ss, "seeded_stable": seeded_stable,
            "seed_controls_spread": bool(us > tol and seeded_stable),
            "irreducibly_random": bool(us > tol and not seeded_stable),
            "explanation": ("non-determinism is seed-controlled; the author's number depends on their unshared "
                            "seed" if (us > tol and seeded_stable) else
                            ("irreducibly non-deterministic even with a fixed seed" if us > tol else
                             "deterministic across runs"))}
