"""Fixture callables for the feature 2/7/10 re-invocation tests. Pure stdlib so `capture.reinvoke` can
re-invoke them on synthetic inputs with no third-party deps. A mix of honest metrics and the three cheat
classes the un-foolability cluster must catch: a wrong formula (F2), an order-sensitive impostor (F7), and a
hard-coded constant (F10)."""
import statistics


def honest_accuracy(y_true, y_pred):
    return sum(1 for a, b in zip(y_true, y_pred) if a == b) / len(y_true)


def cheat_accuracy(y_true, y_pred):
    """F10 — fabrication: ignores its inputs entirely."""
    return 0.95


def wrong_accuracy(y_true, y_pred):
    """F2 — wrong formula: fraction predicted positive, not agreement. Diverges from accuracy on random data."""
    return sum(1 for p in y_pred if p) / len(y_pred)


def order_sensitive_accuracy(y_true, y_pred):
    """F7 — not the metric it claims: accuracy of only the first half, so it violates sample-order invariance."""
    h = max(1, len(y_true) // 2)
    return sum(1 for a, b in zip(y_true[:h], y_pred[:h]) if a == b) / h


def honest_sharpe(returns):
    m = sum(returns) / len(returns)
    s = statistics.stdev(returns)          # sample std (ddof=1) — the catalog default
    return m / s if s else 0.0


def honest_mean(values):
    return sum(values) / len(values)


def honest_mse(y_true, y_pred):
    return sum((a - b) ** 2 for a, b in zip(y_true, y_pred)) / len(y_true)


def honest_correlation(x, y):
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sx = sum((a - mx) ** 2 for a in x) ** 0.5
    sy = sum((b - my) ** 2 for b in y) ** 0.5
    return cov / (sx * sy) if sx and sy else 0.0


# convention-legitimate variants — a different but STANDARD convention (population std, ddof=0). The fuzz must
# NOT flag these: a cited convention reproduces them on every input, so they are metrics, not cheats.
def sharpe_ddof0(returns):
    m = sum(returns) / len(returns)
    s = statistics.pstdev(returns)         # population std (ddof=0) — numpy's default, a recognized convention
    return m / s if s else 0.0


# wrong-formula cheats (F2): depend on inputs but compute the wrong thing.
def scaled_sharpe(returns):
    return honest_sharpe(returns) * 1.3    # off by a constant factor — not the Sharpe ratio


def not_correlation(x, y):
    return sum(x) / len(x)                  # ignores y; not a correlation at all
