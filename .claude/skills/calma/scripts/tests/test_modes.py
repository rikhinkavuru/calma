"""The `calma modes` command: show + choose the two autonomy axes (verify scope + action mode) without
editing JSON or knowing the env vars. Setting merges into .calma/config.json (other keys preserved);
showing resolves the EFFECTIVE state. The verdict is never affected by a mode. Pure stdlib, offline.
Run: python3 test_modes.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CALMA = os.path.join(HERE, "..", "calma.py")
_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def modes(workdir, *args):
    env = dict(os.environ)
    env.pop("CALMA_VERIFY", None)
    env.pop("CALMA_MODE", None)
    env.pop("CALMA_HOOK", None)
    p = subprocess.run([sys.executable, CALMA, "modes", "--dir", workdir, "--json", *args],
                       capture_output=True, text=True, env=env)
    try:
        return p.returncode, json.loads(p.stdout)
    except ValueError:
        return p.returncode, None


with tempfile.TemporaryDirectory() as d:
    # default state: headline + ask
    rc, j = modes(d)
    truth(rc == 0 and j and j["verify"] == "headline" and j["mode"] == "ask", "show: defaults headline/ask")
    truth(j["verify_choices"] == ["off", "headline", "all"] and j["mode_choices"] == ["ask", "suggest", "auto"],
          "show: lists the choices")

    # pre-existing config with a "hook" block must survive a set (merge, not overwrite)
    os.makedirs(os.path.join(d, ".calma"), exist_ok=True)
    json.dump({"hook": {"timeout_s": 20}}, open(os.path.join(d, ".calma", "config.json"), "w"))
    rc, j = modes(d, "--verify", "all", "--mode", "auto")
    truth(rc == 0 and j["verify"] == "all" and j["mode"] == "auto", "set: --verify all --mode auto applied")
    cfg = json.load(open(os.path.join(d, ".calma", "config.json")))
    truth(cfg.get("verify") == "all" and cfg.get("mode") == "auto", "set: written to config.json")
    truth(cfg.get("hook", {}).get("timeout_s") == 20, "set: preserved the pre-existing hook block")

    # re-show resolves to the set values
    rc, j = modes(d)
    truth(j["verify"] == "all" and j["mode"] == "auto", "show: resolves the set values")

    # setting one axis leaves the other untouched
    rc, j = modes(d, "--verify", "off")
    truth(j["verify"] == "off" and j["mode"] == "auto", "set: one axis at a time")

    # an invalid choice is rejected by the parser (exit 2), config unchanged
    p = subprocess.run([sys.executable, CALMA, "modes", "--dir", d, "--verify", "bogus"],
                       capture_output=True, text=True)
    truth(p.returncode == 2, "invalid --verify choice -> exit 2 (argparse rejects)")
    truth(json.load(open(os.path.join(d, ".calma", "config.json"))).get("verify") == "off",
          "invalid set did not corrupt the config")

print("modes: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
