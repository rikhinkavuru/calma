"""A repo whose custom metric is defined AND called in __main__ itself (run as `python eval.py`). The
import-patch tier CANNOT wrap it — import_module('eval') returns a different object than the running
__main__ — so ONLY sys.monitoring (Tier 1, guide §B.1) captures its inputs. A hand-rolled accuracy the
catalog then recomputes independently → a real CONFIRMED (the digits-softmax value-recompute case). Seeded."""
import random


def my_accuracy(y_true, y_pred):        # defined in __main__ — the capture gap Tier 1 closes
    correct = sum(1 for a, b in zip(y_true, y_pred) if a == b)
    return correct / len(y_true)


rng = random.Random(2026)
n = 300
y_true = [rng.randint(0, 1) for _ in range(n)]
y_pred = [yt if rng.random() < 0.8 else 1 - yt for yt in y_true]   # ~80% correct

acc = my_accuracy(y_true, y_pred)
print(f"accuracy={acc:.4f}")
