#!/usr/bin/env python
"""Build a pre-warmed, multi-core E2B template for verification — the biggest lever on deep-verify latency.

Two wins over the generic "base" template we use today:
  1. MORE CORES. A verify re-runs the repo's own code; that runtime is the floor. gb_kmer is CPU-only
     LightGBM + k-mer featurization — embarrassingly parallel — so 8 cores instead of 2 cuts each run
     ~3-4x. `Sandbox.create` can't set cores (they're template-defined), so this is the ONLY way to get them.
  2. PRE-BAKED DEPS. The scientific + genomics stack is installed at BUILD time and captured in the snapshot,
     so a run starts warm: the residual `uv pip install` only resolves the few extras a repo pins, mostly
     from the warm uv cache. Install drops from ~24s toward ~0 for the common case.

Run it once (locally or in CI), then point the backend at the result:

    export CALMA_E2B_API_KEY=<your key>          # same key the backend uses (CALMA_E2B_* on Fly)
    python spike/e2b_template.py                 # builds "calma-verify" (override: CALMA_TEMPLATE_NAME)
    flyctl secrets set -a calma-engine CALMA_E2B_TEMPLATE=calma-verify   # then the backend uses it

Cores/RAM are env-tunable (CALMA_TEMPLATE_CPUS / CALMA_TEMPLATE_MEM_MB) — bigger = faster runs, more cost.
Rebuilding is cheap: E2B layer-caches, so re-running only rebuilds changed layers.
"""
from __future__ import annotations

import os
import sys

# The common heavy stack, pre-installed so it's resident at sandbox start (a repo's exact pins still install
# at runtime, but fast from the warm uv cache). CPU wheels only — verification is CPU-tier.
_ML = ["numpy", "scipy", "scikit-learn", "pandas", "matplotlib", "lightgbm", "xgboost", "statsmodels"]
_GENOMICS = ["biopython", "genomic-benchmarks", "pyjaspar", "pysam"]
_TORCH_CPU = ["torch", "--index-url", "https://download.pytorch.org/whl/cpu"]


def main() -> int:
    if not os.environ.get("CALMA_E2B_API_KEY"):
        print("set CALMA_E2B_API_KEY first (the same E2B key the backend uses)", file=sys.stderr)
        return 2
    # the SDK reads E2B_API_KEY; mirror our namespaced var onto it.
    os.environ.setdefault("E2B_API_KEY", os.environ["CALMA_E2B_API_KEY"])
    if os.environ.get("CALMA_E2B_ENDPOINT"):
        os.environ.setdefault("E2B_DOMAIN", os.environ["CALMA_E2B_ENDPOINT"])

    from e2b import Template, default_build_logger

    name = os.environ.get("CALMA_TEMPLATE_NAME", "calma-verify")
    cpus = int(os.environ.get("CALMA_TEMPLATE_CPUS", "8"))
    mem = int(os.environ.get("CALMA_TEMPLATE_MEM_MB", "8192"))
    py = os.environ.get("CALMA_TEMPLATE_PY", "3.11")

    t = Template()
    builder = (
        t.from_python_image(py)
        .apt_install(["git", "build-essential"])          # a few repos still compile a small wheel
        .pip_install(["uv"])                              # the fast installer, resident for runtime residuals
        .pip_install(_ML)
        .pip_install(_TORCH_CPU)                          # CPU torch (small) — covers the DL repos too
        .pip_install(_GENOMICS)
        # keep runtime installs deterministic + fast: prefer wheels, cache under a fixed dir.
        .set_envs({"PIP_PREFER_BINARY": "1", "UV_SYSTEM_PYTHON": "1", "UV_CACHE_DIR": "/root/.cache/uv"})
    )

    print("building E2B template %r — %d vCPU / %d MB, python %s" % (name, cpus, mem, py))
    print("pre-baking: %s" % " ".join(_ML + ["torch(cpu)"] + _GENOMICS))
    Template.build(builder, name=name, cpu_count=cpus, memory_mb=mem,
                   on_build_logs=default_build_logger())
    print("\n✓ built %r. Point the backend at it:" % name)
    print("  flyctl secrets set -a calma-engine CALMA_E2B_TEMPLATE=%s" % name)
    print("  (then the deep runs get %d cores + a warm dep cache — re-run gb_kmer to see the drop)" % cpus)
    return 0


if __name__ == "__main__":
    sys.exit(main())
