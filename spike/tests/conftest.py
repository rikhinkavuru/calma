import os
import sys

import pytest

# make `core`, `capture` importable as top-level packages from the spike root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "capture"))


@pytest.fixture(autouse=True)
def _hermetic_planner(monkeypatch):
    """Keep the suite hermetic: with ANTHROPIC_API_KEY set in the dev's env, any test that runs
    verify_repo(plan=True) would make a REAL Sonnet 5 call (slow, flaky, costs money, and can change a run's
    entrypoint/deps out from under a test). Drop the key so the planner no-ops to heuristics by default. Tests
    that exercise the planner stub PLAN.plan_repo / PLAN._call_model directly, so they're unaffected."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
