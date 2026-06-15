"""Autonomy modes: resolve_mode precedence (flag > env > config > default 'ask') and the action gate
(ask=skip, suggest=suggest, auto=execute). The gate governs follow-on ACTIONS only; outward actions
(publish/send) require an explicit standing opt-in even in auto. The verdict is never routed here.
Run: python3 test_autonomy.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.join(HERE, "..")
sys.path.insert(0, SCR)
import autonomy as AUT  # noqa: E402

checks = fails = 0


def ok(cond, msg):
    global checks, fails
    checks += 1
    if not cond:
        fails += 1
        print("  FAIL:", msg)


os.environ.pop("CALMA_MODE", None)

with tempfile.TemporaryDirectory() as base:
    ok(AUT.resolve_mode(None, base) == "ask", "default is ask")
    ok(AUT.resolve_mode("auto", base) == "auto", "cli mode wins")
    ok(AUT.resolve_mode("suggest", base) == "suggest", "cli suggest")
    ok(AUT.resolve_mode("BOGUS", base) == "ask", "invalid cli mode -> ask")
    os.environ["CALMA_MODE"] = "suggest"
    ok(AUT.resolve_mode(None, base) == "suggest", "env CALMA_MODE applies")
    ok(AUT.resolve_mode("auto", base) == "auto", "cli overrides env")
    os.environ.pop("CALMA_MODE", None)
    os.makedirs(os.path.join(base, ".calma"), exist_ok=True)
    json.dump({"mode": "auto"}, open(os.path.join(base, ".calma", "config.json"), "w"))
    ok(AUT.resolve_mode(None, base) == "auto", "config mode applies")
    os.environ["CALMA_MODE"] = "suggest"
    ok(AUT.resolve_mode(None, base) == "suggest", "env overrides config")
    os.environ.pop("CALMA_MODE", None)

# the gate (non-outward)
ok(AUT.gate("ask", "seal") == "skip", "ask -> skip")
ok(AUT.gate("suggest", "seal") == "suggest", "suggest -> suggest")
ok(AUT.gate("auto", "seal") == "execute", "auto non-outward -> execute")
ok(AUT.gate("nonsense", "seal") == "skip", "invalid mode -> skip (fail safe)")

# the gate (outward: needs an explicit standing opt-in even in auto)
ok(AUT.gate("auto", "publish", outward=True, config={}) == "suggest", "auto outward, no opt-in -> suggest")
ok(AUT.gate("auto", "publish", outward=True, config={"autonomy": {"auto_publish": True}}) == "execute",
   "auto outward + auto_publish -> execute")
ok(AUT.gate("auto", "publish", outward=True, config={"autonomy": {"allowlist": ["publish"]}}) == "execute",
   "auto outward + allowlist -> execute")
ok(AUT.gate("suggest", "publish", outward=True, config={"autonomy": {"auto_publish": True}}) == "suggest",
   "suggest never executes an outward action")

print("autonomy: %d checks, %d failures" % (checks, fails))
sys.exit(1 if fails else 0)
