"""A repo reporting a LEARNED / embedding metric (BERTScore). We can reproduce the reported number and
check determinism, but there is NO independent recompute of a neural metric — reproducing it would mean
re-running the same checkpoint, which is the thing under test, not an independent oracle. So the honest,
fail-closed verdict is REPRODUCED-ONLY, never CONFIRMED (guide §B.3 (c)).

Instrumented explicitly because there is no known sink to auto-hook — the repo hands us the inputs+value."""
try:
    import calma_capture            # present on PYTHONPATH inside the spike sandbox
except Exception:                   # noqa: BLE001 — repo still runs outside the harness
    calma_capture = None


def neural_score(candidate, reference):
    # stand-in for a BERTScore-style learned metric (the real one runs a BERT checkpoint). Deterministic
    # value — the point is that it is NOT independently recomputable, not how it's produced.
    cand, ref = candidate.split(), reference.split()
    overlap = len(set(cand) & set(ref)) / max(1, len(set(cand) | set(ref)))
    return 0.85 + 0.1 * overlap


cand = "the quick brown fox jumped over the lazy dog"
ref = "a quick brown fox leaps over a sleepy dog"
score = neural_score(cand, ref)
if calma_capture:
    calma_capture.record("bertscore", score, candidate=cand, reference=ref)
print(f"bertscore={score:.4f}")
