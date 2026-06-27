"""A repo reporting a metric the trusted catalog does not (yet) recognise (a toy 'bleu'). We can reproduce
the reported number (and check determinism), but we have no independent oracle to recompute it -> the
fail-closed verdict REPRODUCED-ONLY, never CONFIRMED. (Coverage grows via the catalog flywheel, guide §10.)

Instrumented explicitly because there is no known sink to auto-hook — the repo hands us the inputs+value."""
import numpy as np

try:
    import calma_capture            # present on PYTHONPATH inside the spike sandbox
except Exception:                   # noqa: BLE001 — repo still runs outside the harness
    calma_capture = None


def toy_bleu(candidate, reference):
    # a deliberately simple stand-in for an unrecognised metric
    c, r = set(candidate), set(reference)
    return len(c & r) / max(1, len(c))


rng = np.random.default_rng(5)
cand = list(rng.integers(0, 50, 60))
ref = list(rng.integers(0, 50, 60))
score = toy_bleu(cand, ref)
if calma_capture:
    calma_capture.record("bleu", score, candidate=cand, reference=ref)
print(f"bleu={score:.4f}")
