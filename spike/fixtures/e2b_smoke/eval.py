"""Stdlib-only fixture for the E2B isolation smoke test — runs on any base template (no numpy/sklearn).
Records a 'mean' explicitly so the harness can recompute it independently and three-way-diff -> CONFIRMED,
proving capture works inside a real Firecracker microVM."""
import calma_capture

vals = [0.10, 0.20, 0.30, 0.40, 0.50]
m = sum(vals) / len(vals)
calma_capture.record("mean", m, values=vals)
print(f"mean={m:.4f}")
