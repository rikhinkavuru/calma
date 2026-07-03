"""runner.gpu — decide whether a repo needs a GPU, and which backend serves it.

The four-unlocks plan (§7): E2B's Firecracker microVMs cannot do GPU passthrough, so a GPU verify routes to a
SEPARATE backend (Modal — the only mature sandbox with a GPU inside the isolation boundary). This module is the
pure decision layer, kept out of the transport so it's testable without any SDK:

  * REACTIVE (primary) — a CPU run that fails with a `needs-gpu` signature (runner.build.classify_failure) is
    the strongest evidence the code truly needs a GPU. Try cheap CPU first, escalate only on that failure.
  * PROACTIVE (a cheap hint) — a static scan for CUDA-shaped imports/calls. A HINT only: it raises a GPU
    approach's rank but never forces one, so a CPU repo is never billed for a GPU it didn't need.

FCR-safe: routing to a GPU changes only WHERE the code runs, never the verdict. A misroute yields a
failed/empty run → DISCOVERED, never a false CONFIRM.
"""
from __future__ import annotations

import os
import re

# Static CUDA signatures. Deliberately conservative — each is a strong, low-false-positive signal that the code
# reaches for a GPU. `torch.cuda`, an explicit cuda device, or a CUDA-only library import.
_CUDA_PATTERNS = [
    re.compile(r"\.cuda\s*\("),                          # tensor.cuda()
    re.compile(r"""\.to\(\s*['"]cuda""", re.I),         # .to("cuda")
    re.compile(r"""device\s*=\s*['"]cuda""", re.I),     # device="cuda"
    re.compile(r"torch\.cuda\.", ),                      # torch.cuda.is_available()/set_device/…
    re.compile(r"\bimport\s+cupy\b"),
    re.compile(r"\bfrom\s+cupy\b"),
    re.compile(r"\bimport\s+pycuda\b"),
    re.compile(r"\bimport\s+bitsandbytes\b"),
]
# requirements-file tokens that pin a CUDA build (the repo declares a GPU dep outright).
_CUDA_REQ_TOKENS = ("tensorflow-gpu", "cupy-cuda", "+cu11", "+cu12", "nvidia-cuda", "cudf", "cuml",
                    "faiss-gpu", "onnxruntime-gpu", "jax[cuda", "vllm", "flash-attn", "deepspeed")

_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "env", ".venvs", "node_modules"}


def needs_gpu_from_failure(stderr: str) -> bool:
    """True when a run's stderr carries a GPU-required signature (delegates to the single failure taxonomy in
    runner.build so the two never drift)."""
    from . import build
    return build.classify_failure(stderr or "").get("kind") == "needs-gpu"


def scan_repo_for_gpu(repo_dir: str, max_files: int = 400, max_bytes: int = 400_000) -> dict:
    """Cheap static scan → {"needs_gpu": bool, "signals": [str]}. A HINT, not a gate. Bounded (file + byte
    caps) so a huge monorepo can't turn this into a stall. Reads .py sources + requirement manifests."""
    signals: list[str] = []
    seen = 0
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for fn in files:
            low = fn.lower()
            is_py = low.endswith(".py")
            is_req = low in ("requirements.txt", "pyproject.toml", "environment.yml", "setup.py") or "require" in low
            if not (is_py or is_req):
                continue
            if seen >= max_files:
                break
            seen += 1
            try:
                with open(os.path.join(root, fn), "r", errors="replace") as fh:
                    text = fh.read(max_bytes)
            except OSError:
                continue
            if is_req:
                low_text = text.lower()
                for tok in _CUDA_REQ_TOKENS:
                    if tok in low_text:
                        signals.append("%s declares %s" % (fn, tok))
            if is_py:
                for pat in _CUDA_PATTERNS:
                    if pat.search(text):
                        signals.append("%s: %s" % (os.path.basename(fn), pat.pattern))
                        break
        if seen >= max_files:
            break
    # de-dup, keep order, cap the list for a tidy report
    uniq: list[str] = []
    for s in signals:
        if s not in uniq:
            uniq.append(s)
    return {"needs_gpu": bool(uniq), "signals": uniq[:12]}
