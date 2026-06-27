"""The lifted 626-recipe catalog, exposed through recompute_any via the input-binding adapter. Validates a
sample against sklearn and confirms recompute_any routes unknown-to-the-new-catalog metrics to a recipe."""
import random

from recipes import adapter as RA
from synth import formula as F


def test_recipe_catalog_lifted():
    assert RA.count() >= 600


def test_brier_and_logloss_match_sklearn():
    from sklearn.metrics import brier_score_loss, log_loss
    rng = random.Random(1)
    yt = [rng.randint(0, 1) for _ in range(150)]
    ys = [min(max(rng.random(), 0.02), 0.98) for _ in range(150)]
    rb = F.recompute_any("brier_score_loss", {"y_true": yt, "y_score": ys}, {})
    assert rb["provenance"] == "recipe" and abs(rb["value"] - brier_score_loss(yt, ys)) < 1e-9
    rl = F.recompute_any("log_loss", {"y_true": yt, "y_score": ys}, {})
    assert rl["provenance"] == "recipe" and abs(rl["value"] - log_loss(yt, ys)) < 1e-6


def test_finance_recipe_resolves():
    rng = random.Random(2)
    r = F.recompute_any("sortino", {"returns": [rng.gauss(0.001, 0.02) for _ in range(200)]}, {})
    assert r["provenance"] == "recipe" and r["value"] == r["value"]   # finite


def test_unbindable_recipe_falls_through():
    # a recipe whose required tags we can't fill from the captured inputs -> None (recompute_any continues)
    assert RA.recompute_recipe("sharpe", {"y_true": [0, 1]}, {}) is None     # no 'return' input
    # a metric that is in neither catalog nor recipes nor synth -> fail-closed degenerate
    r = F.recompute_any("totally_made_up_metric_xyz", {"values": [1, 2, 3]}, {})
    assert r["degenerate"] and r["provenance"] == "none"
