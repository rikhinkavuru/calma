"""capture.seedinject — feature 15: force-seed all RNGs when CALMA_INJECT_SEED is set.

Used ONLY for the CHARACTERIZATION runs ("is the non-determinism seed-controlled?") — NEVER to produce a
claim's value. A run under an injected seed computes a DIFFERENT number than the author's (a different
split/init), so it can never confirm the claim; core.verdict hard-caps a seed_injected run at REPRODUCED-ONLY.
Seeds `random` at startup + PYTHONHASHSEED, and hooks numpy/torch to be seeded the moment they import (they
usually import AFTER this shim). Pure stdlib + duck-typed (never force-imports numpy/torch). Fail-soft.
"""
from __future__ import annotations

import os
import sys

_INSTALLED = [False]


def _int(raw, default=0):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _seed_loaded(seed: int):
    """Seed any RNG library ALREADY imported (never force-imports one)."""
    np = sys.modules.get("numpy")
    if np is not None:
        try:
            np.random.seed(seed)
        except Exception:  # noqa: BLE001
            pass
    torch = sys.modules.get("torch")
    if torch is not None:
        try:
            torch.manual_seed(seed)
            if hasattr(torch, "cuda") and torch.cuda.is_available():
                torch.cuda.manual_seed_all(seed)
        except Exception:  # noqa: BLE001
            pass


def _install_import_hook(seed: int):
    import builtins
    orig = builtins.__import__
    if getattr(orig, "__calma_seed_hook__", False):
        return

    def hooked(name, *a, **k):
        mod = orig(name, *a, **k)
        try:
            if name.split(".", 1)[0] in ("numpy", "torch"):
                _seed_loaded(seed)
        except Exception:  # noqa: BLE001
            pass
        return mod
    setattr(hooked, "__calma_seed_hook__", True)
    try:
        builtins.__import__ = hooked
    except Exception:  # noqa: BLE001
        pass


def seed_all(seed: int, hook: bool = False):
    """Seed `random` + any already-imported RNG lib. `hook=True` (production characterization runs only) also
    installs the import-time seeder for numpy/torch — kept off by default so a direct call doesn't leave a
    session-global __import__ wrapper behind (test hygiene)."""
    import random
    try:
        random.seed(seed)
    except Exception:  # noqa: BLE001
        pass
    _seed_loaded(seed)
    if hook:
        _install_import_hook(seed)


def install_seed_from_env():
    """If CALMA_INJECT_SEED is set, force-seed everything. Idempotent + fail-soft."""
    if _INSTALLED[0]:
        return
    raw = os.environ.get("CALMA_INJECT_SEED")
    if not raw:
        return
    _INSTALLED[0] = True
    os.environ.setdefault("PYTHONHASHSEED", raw)
    seed_all(_int(raw), hook=True)      # a real characterization run: also seed numpy/torch as they import
