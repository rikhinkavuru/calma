"""pytest configuration for the edges suite.

Default the LLM client to REPLAY mode (CALMA_EDGES_RECORD off) so the suite never makes a live
Anthropic call and stays green with no ANTHROPIC_API_KEY. record.replay() only forces a live call
when CALMA_EDGES_RECORD == "1"; clearing it here makes "off" the default regardless of the caller's
environment. Replays come from edges/tests/fixtures/.
"""
import os

os.environ.pop("CALMA_EDGES_RECORD", None)   # off => replay from fixtures; never record under test

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
os.makedirs(FIXTURES, exist_ok=True)
