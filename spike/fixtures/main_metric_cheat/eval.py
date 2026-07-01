"""A __main__-defined metric that CHEATS: it ignores y_true and compares y_pred to itself → always 1.0. It
re-runs to 1.0 every time (looks perfect + deterministic), but Tier 1 captures the REAL (y_true, y_pred)
it received, and an independent recompute over those inputs (≈0.8) catches it → INVALIDATED. The proof that
capturing a __main__ metric's inputs (guide §B.1 P1.3) turns an un-verifiable claim into a caught one."""
import random


def my_accuracy(y_true, y_pred):        # cheat: ignores y_true, compares y_pred to itself
    return sum(1 for a, b in zip(y_pred, y_pred) if a == b) / len(y_pred)


rng = random.Random(2026)
n = 300
y_true = [rng.randint(0, 1) for _ in range(n)]
y_pred = [yt if rng.random() < 0.8 else 1 - yt for yt in y_true]   # true accuracy ≈ 0.8

acc = my_accuracy(y_true, y_pred)
print(f"accuracy={acc:.4f}")          # reports a perfect 1.0000
