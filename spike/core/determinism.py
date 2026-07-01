"""calma.spike.core.determinism — static proof that a repo's run is deterministic BY CONSTRUCTION, so a
SINGLE run can be trusted (adaptive-k). This is the safe way to spend one run instead of two: the research is
unambiguous that a lone run has ZERO power to detect run-to-run nondeterminism (unseeded RNG, data shuffle) —
the dominant, pervasive ML failure mode — so we only drop to k=1 when we can PROVE that class away without
running twice.

Conservative by construction. It returns "deterministic" ONLY when every stochastic library the code touches
is explicitly seeded and no unseeded-random red flag is present. Any doubt → "at_risk" → the caller keeps
k≥2 (the empirical determinism check). The asymmetry is deliberate and load-bearing:

    false "at_risk"      → one wasted extra run (harmless, just slower)
    false "deterministic" → a possible CONFIRM of a flaky number (the cardinal sin)

so the bar is set to avoid the second at the cost of the first. Regex over the repo's Python (bounded).
Pure stdlib.
"""
from __future__ import annotations

import os
import re

DETERMINISTIC = "deterministic"
AT_RISK = "at_risk"
UNKNOWN = "unknown"

# Each stochastic family: (USE — does the code draw randomness from it?, SEED — does it fix that RNG?).
# A family is "controlled" iff it isn't used, or it's used AND seeded. `import torch` counts as USE on its own
# (models randomly initialise / dropout even without an explicit torch.rand), so a torch repo with no
# manual_seed is at_risk — the safe call.
_FAMILIES = {
    "numpy": (
        re.compile(r"np\.random\.(rand|randn|randint|random|ranf|random_sample|choice|shuffle|permutation|"
                   r"normal|uniform|standard_normal|multivariate_normal|multinomial|poisson|beta|gamma|"
                   r"binomial|bytes|geometric|exponential|dirichlet|laplace|logistic)\b"
                   r"|numpy\.random\.|default_rng\s*\(|RandomState\s*\("),
        re.compile(r"np\.random\.seed\s*\(|numpy\.random\.seed\s*\("
                   r"|default_rng\s*\(\s*[^)\s]|RandomState\s*\(\s*[^)\s]"
                   r"|seed_everything\s*\(|set_seed\s*\(|set_random_seed\s*\("),
    ),
    "random": (
        re.compile(r"(?<![\w.])random\.(random|randint|randrange|shuffle|sample|choice|choices|uniform|"
                   r"gauss|normalvariate|getrandbits|betavariate|expovariate|triangular)\s*\("),
        re.compile(r"(?<![\w.])random\.seed\s*\(|seed_everything\s*\(|set_seed\s*\("),
    ),
    "torch": (
        re.compile(r"(?<![\w.])import\s+torch\b|(?<![\w.])torch\.|from\s+torch\b"),
        re.compile(r"torch\.manual_seed\s*\(|torch\.cuda\.manual_seed(_all)?\s*\("
                   r"|(?<![\w.])manual_seed\s*\(|seed_everything\s*\(|pl\.seed_everything\s*\("),
    ),
    "tensorflow": (
        re.compile(r"(?<![\w.])import\s+tensorflow\b|(?<![\w.])tf\.|from\s+tensorflow\b|(?<![\w.])keras\b"),
        re.compile(r"tf\.random\.set_seed\s*\(|tf\.set_random_seed\s*\(|set_seed\s*\(|set_random_seed\s*\("),
    ),
    # sklearn / lightgbm / xgboost estimators + splitters that are stochastic unless given a seed/random_state
    "sklearn_like": (
        re.compile(r"train_test_split\s*\(|StratifiedKFold\s*\(|(?<![\w])KFold\s*\(|ShuffleSplit\s*\("
                   r"|RandomForest\w*\s*\(|ExtraTrees\w*\s*\(|SGD\w*\s*\(|GradientBoosting\w*\s*\("
                   r"|LGBM\w*\s*\(|XGB\w*\s*\(|CatBoost\w*\s*\(|\bshuffle\s*=\s*True"),
        re.compile(r"random_state\s*=\s*(?!None)[\w.]|(?<![\w])seed\s*=\s*(?!None)[\w.]"),
    ),
}

# Hard red flags: even if a seed appears somewhere, these specific unseeded draws are the classic
# forgotten-seed leaks, so their presence forces at_risk.
_RED_FLAGS = [
    (re.compile(r"default_rng\s*\(\s*\)"), "numpy default_rng() with no seed"),
    (re.compile(r"np\.random\.(rand|randn|randint|choice|shuffle|permutation|normal|uniform)\b"),
     "np.random draw"),   # only a red flag when numpy is also unseeded (checked below)
]

# NON-RNG nondeterminism: wall-clock, OS entropy, and the harness's own per-run counter. A seed can't control
# these, and "no RNG detected" does NOT mean deterministic if the result can depend on the clock or urandom —
# so their presence forces at_risk regardless of seeding. Conservative on purpose: a repo that merely TIMES
# itself (perf_counter) is treated as at_risk (→ k≥2), because we can't statically prove the clock doesn't
# feed a reported number. (This is why gb_kmer, which prints fit-times, stays on the empirical k=2 path.)
_ENTROPY = re.compile(
    r"os\.urandom\s*\(|(?<![\w.])secrets\.\w|uuid\.(uuid1|uuid4)\s*\(|SystemRandom\s*\("
    r"|time\.(time|time_ns|perf_counter|perf_counter_ns|monotonic|monotonic_ns|process_time|clock)\s*\("
    r"|datetime\.(now|today|utcnow)\s*\(|(?<![\w.])CALMA_RUN_INDEX")

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "env", "site-packages"}


def _gather_source(repo_dir: str, max_files: int = 200, max_bytes: int = 2_000_000) -> str:
    """Concatenate the repo's Python source (bounded) — RNG use and its seeding often live in different files
    (a worker cell vs a `set_seed` util), so we scan the whole tree, not just the entrypoint."""
    chunks: list[str] = []
    total = 0
    n = 0
    if not os.path.isdir(repo_dir):
        return ""
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fn in sorted(files):
            if not (fn.endswith(".py") or fn.endswith(".ipynb")):
                continue
            n += 1
            if n > max_files or total > max_bytes:
                return "\n".join(chunks)
            try:
                with open(os.path.join(root, fn), errors="replace") as fh:
                    s = fh.read(max_bytes - total)
            except OSError:
                continue
            chunks.append(s)
            total += len(s)
    return "\n".join(chunks)


def analyze(repo_dir: str) -> dict:
    """Static determinism verdict for a repo. Returns
        {"level": "deterministic"|"at_risk"|"unknown", "seeded": [...], "uncontrolled": [...], "detail": str}
    Only "deterministic" licenses k=1; everything else keeps the empirical k≥2 check."""
    src = _gather_source(repo_dir)
    if not src.strip():
        return {"level": UNKNOWN, "seeded": [], "uncontrolled": [], "detail": "no Python source to analyze"}

    seeded, used_unseeded = [], []
    for name, (use_re, seed_re) in _FAMILIES.items():
        if not use_re.search(src):
            continue                                  # family not used → nothing to control
        if seed_re.search(src):
            seeded.append(name)
        else:
            used_unseeded.append(name)

    # red flags that force at_risk (an explicit unseeded draw), gated so they only bite when the relevant
    # family is actually uncontrolled.
    red = []
    if _RED_FLAGS[0][0].search(src):
        red.append(_RED_FLAGS[0][1])
    if "numpy" in used_unseeded and _RED_FLAGS[1][0].search(src):
        red.append(_RED_FLAGS[1][1])

    entropy = _ENTROPY.search(src)                    # wall-clock / urandom / harness run-counter → uncontrollable
    if used_unseeded or red or entropy:
        why = []
        if used_unseeded:
            why.append("uses %s without a fixed seed" % ", ".join(used_unseeded))
        why.extend(red)
        if entropy:
            why.append("reads a nondeterministic source (%s)" % entropy.group(0).rstrip("("))
        return {"level": AT_RISK, "seeded": seeded, "uncontrolled": used_unseeded,
                "detail": "; ".join(why)}

    if seeded:
        return {"level": DETERMINISTIC, "seeded": seeded, "uncontrolled": [],
                "detail": "all randomness is explicitly seeded (%s)" % ", ".join(seeded)}
    # no stochastic library detected at all → a pure computation (deterministic under the enforced env).
    return {"level": DETERMINISTIC, "seeded": [], "uncontrolled": [],
            "detail": "no stochastic library detected — pure computation"}


# a fixed build/mtime clock for the shim tier (feature 20): 2023-11-14T22:13:20Z. Any fixed value works; it
# only needs to be STABLE across runs so SOURCE_DATE_EPOCH-aware code produces the same output each time.
_SHIM_EPOCH = "1700000000"


def enforced_env(shim: bool = False) -> dict:
    """The determinism-enforcing env applied to EVERY verification run (independent of adaptive-k): freeze the
    hash seed (dict/set iteration order) and the timezone. This is a strict quality win — it removes the
    controllable, output-affecting nondeterminism sources so a repo that IS deterministic-by-construction
    isn't spuriously flagged NON-DETERMINISTIC over dict ordering. We deliberately do NOT pin BLAS threads:
    that would negate the multi-core template, and the residual ~1e-6 thread-reduction wobble is far below any
    reported-metric tolerance. (Set-before-interpreter-start vars like PYTHONHASHSEED are read by the child
    python at launch.)

    `shim=True` adds the feature-20 shim tier (the DebuggAI/libfate 80/20 of rr): pin the build/mtime clock
    via SOURCE_DATE_EPOCH. It only REMOVES clock-derived noise — same category as PYTHONHASHSEED/TZ — so it can
    only turn a spurious NON-DETERMINISTIC into a clean verdict, never manufacture agreement."""
    env = {"PYTHONHASHSEED": "0", "TZ": "UTC"}
    if shim:
        env["SOURCE_DATE_EPOCH"] = _SHIM_EPOCH
    return env
