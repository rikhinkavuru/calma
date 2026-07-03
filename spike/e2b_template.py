#!/usr/bin/env python
"""Build the pre-warmed E2B verification templates — the biggest lever on deep-verify latency AND the single
image-build that unlocks THREE capabilities (notebooks + conda + non-Python-run).

Two wins over the generic "base" template we use today:
  1. MORE CORES. A verify re-runs the repo's own code; that runtime is the floor. gb_kmer is CPU-only
     LightGBM + k-mer featurization — embarrassingly parallel — so 8 cores instead of 2 cuts each run
     ~3-4x. `Sandbox.create` can't set cores (they're template-defined), so this is the ONLY way to get them.
  2. PRE-BAKED DEPS + TOOLING. The scientific + genomics stack, the notebook runtime (nbclient/nbformat/
     ipykernel/papermill), and the micromamba binary are installed at BUILD time and captured in the snapshot,
     so a run starts warm: the residual `uv pip install` only resolves the few extras a repo pins, mostly from
     the warm uv cache. Install drops from ~24s toward ~0 for the common case.

The "one image unlocks three" reframe (see docs/FOUR-UNLOCKS-BUILD-PLAN.md §0): the notebook runner
(orchestrator.tools_exec.run_notebook), the conda builder (build_conda → micromamba), and the R/Julia runner
(run_lang) all already exist in code — they were only ever blocked on the E2B image lacking the runtime. This
script adds that runtime. GPU is deliberately NOT here: E2B's Firecracker microVMs cannot do GPU passthrough,
so GPU verification routes to a separate Modal backend (runner/modal_runner.py), never an E2B template.

Two templates, one script (keep the base lean — R/Julia bloat cold-start for the 95% Python case):
  * calma-verify            (default)   ML + genomics + notebooks + micromamba
  * calma-verify-polyglot   (variant)   the above + R (r-base) + Julia, for run_lang entries

Build them (locally or in CI), then point the backend at the result:

    export CALMA_E2B_API_KEY=<your key>              # same key the backend uses (CALMA_E2B_* on Fly)
    python spike/e2b_template.py                      # builds "calma-verify" (nb + conda)
    CALMA_TEMPLATE_VARIANT=polyglot CALMA_TEMPLATE_NAME=calma-verify-polyglot python spike/e2b_template.py
    flyctl secrets set -a calma-engine \
        CALMA_E2B_TEMPLATE=calma-verify \
        CALMA_E2B_TEMPLATE_POLYGLOT=calma-verify-polyglot

Rollout safety: don't overwrite the LIVE template name in place — build under a new suffix (e.g. calma-verify-v2),
flip the Fly secret, and keep the prior template for instant rollback. E2B layer-caches, so re-running only
rebuilds changed layers.

Cores/RAM are env-tunable (CALMA_TEMPLATE_CPUS / CALMA_TEMPLATE_MEM_MB) — bigger = faster runs, more cost.
"""
from __future__ import annotations

import os
import sys

# The common heavy stack, pre-installed so it's resident at sandbox start (a repo's exact pins still install
# at runtime, but fast from the warm uv cache). CPU wheels only — verification is CPU-tier.
# pyarrow is bundled because parquet is ubiquitous in genomics/DS pipelines (pandas needs it for read_parquet,
# and it's an OPTIONAL pandas extra that dep-inference never sees — a repo's `pd.read_parquet` crashes without it).
_ML = ["numpy", "scipy", "scikit-learn", "pandas", "pyarrow", "matplotlib", "lightgbm", "xgboost", "statsmodels"]
_GENOMICS = ["biopython", "genomic-benchmarks", "pyjaspar", "pysam"]
_TORCH_CPU = ["torch", "--index-url", "https://download.pytorch.org/whl/cpu"]
# The notebook runtime (A1): run_notebook uses nbclient+nbformat with a kernel-armed capture env; ipykernel
# supplies the pinned `python3` kernel; papermill is the human-facing launch_command shape. These are absent
# from the local dev venv on purpose — they ship HERE so notebook verification works inside the microVM.
_NOTEBOOK = ["nbclient", "nbformat", "ipykernel", "jupyter-client", "papermill"]

# micromamba: a ~5MB static binary (not a pip package) — the conda builder (build_conda / pkg_manager=conda)
# routes to it. Installed to /usr/local/bin so `shutil.which("micromamba")` resolves it. No solver runs at
# image-build time; the repo's environment.yml is solved per-run inside the sandbox.
_MICROMAMBA_INSTALL = ("curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest "
                       "| tar -xj -C /usr/local/bin --strip-components=1 bin/micromamba "
                       "&& chmod +x /usr/local/bin/micromamba && micromamba --version")

# Julia (polyglot variant only): the official static tarball, symlinked onto PATH so `shutil.which("julia")`
# resolves it for run_lang. Pinned to an LTS for reproducibility.
_JULIA_VERSION = os.environ.get("CALMA_TEMPLATE_JULIA", "1.10.4")
_JULIA_INSTALL = (
    "curl -Ls https://julialang-s3.julialang.org/bin/linux/x64/%s/julia-%s-linux-x86_64.tar.gz "
    "| tar -xz -C /opt && ln -sf /opt/julia-%s/bin/julia /usr/local/bin/julia && julia --version"
    % (_JULIA_VERSION.rsplit(".", 1)[0], _JULIA_VERSION, _JULIA_VERSION)
)


def main() -> int:
    if not os.environ.get("CALMA_E2B_API_KEY"):
        print("set CALMA_E2B_API_KEY first (the same E2B key the backend uses)", file=sys.stderr)
        return 2
    # the SDK reads E2B_API_KEY; mirror our namespaced var onto it.
    os.environ.setdefault("E2B_API_KEY", os.environ["CALMA_E2B_API_KEY"])
    if os.environ.get("CALMA_E2B_ENDPOINT"):
        os.environ.setdefault("E2B_DOMAIN", os.environ["CALMA_E2B_ENDPOINT"])

    from e2b import Template, default_build_logger

    variant = (os.environ.get("CALMA_TEMPLATE_VARIANT") or "").strip().lower()
    polyglot = variant == "polyglot"
    default_name = "calma-verify-polyglot" if polyglot else "calma-verify"
    name = os.environ.get("CALMA_TEMPLATE_NAME", default_name)
    cpus = int(os.environ.get("CALMA_TEMPLATE_CPUS", "8"))
    mem = int(os.environ.get("CALMA_TEMPLATE_MEM_MB", "8192"))
    py = os.environ.get("CALMA_TEMPLATE_PY", "3.12")   # 3.12 so 2026-era wheels (numpy>=2.5 needs 3.12) install

    t = Template()
    builder = (
        t.from_python_image(py)
        # curl/bzip2/ca-certificates are needed to fetch the micromamba (+ Julia) static binaries.
        .apt_install(["git", "build-essential", "curl", "bzip2", "ca-certificates"])
        .pip_install(["uv"])                              # the fast installer, resident for runtime residuals
        .pip_install(_ML)
        .pip_install(_TORCH_CPU)                          # CPU torch (small) — covers the DL repos too
        .pip_install(_GENOMICS)
        .pip_install(_NOTEBOOK)                           # A1: notebook runtime (nbclient/nbformat/ipykernel/papermill)
        .run_cmd(_MICROMAMBA_INSTALL)                     # B2: conda via micromamba (static binary)
        .run_cmd("python -m ipykernel install --name python3 --sys-prefix")  # pin the `python3` kernelspec
    )
    if polyglot:
        # A3 long-tail (run_lang): R + Julia so non-Python entrypoints run. The metric is still recomputed in
        # Python from the committed/emitted predictions (core.artifacts) — the capture shim is Python-only.
        builder = builder.apt_install(["r-base"]).run_cmd(_JULIA_INSTALL)
    builder = builder.set_envs({
        "PIP_PREFER_BINARY": "1",
        "UV_SYSTEM_PYTHON": "1",
        "UV_CACHE_DIR": "/root/.cache/uv",
        "MAMBA_ROOT_PREFIX": "/opt/micromamba",           # micromamba's env root (conda envs land here)
        "MPLBACKEND": "Agg",                              # headless matplotlib (notebook cells that plot won't hang)
    })

    baked = _ML + ["torch(cpu)"] + _GENOMICS + _NOTEBOOK + ["micromamba"]
    if polyglot:
        baked += ["r-base", "julia %s" % _JULIA_VERSION]
    print("building E2B template %r%s — %d vCPU / %d MB, python %s"
          % (name, " [polyglot: R+Julia]" if polyglot else "", cpus, mem, py))
    print("pre-baking: %s" % " ".join(baked))
    Template.build(builder, name=name, cpu_count=cpus, memory_mb=mem,
                   on_build_logs=default_build_logger())
    print("\n✓ built %r. Point the backend at it:" % name)
    if polyglot:
        print("  flyctl secrets set -a calma-engine CALMA_E2B_TEMPLATE_POLYGLOT=%s" % name)
    else:
        print("  flyctl secrets set -a calma-engine CALMA_E2B_TEMPLATE=%s" % name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
