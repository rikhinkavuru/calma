"""WS2: tame the surface - `calma recipes search <term>` (semantic find) + `calma schema` (the
machine-readable CLI spec agents read instead of parsing --help). Pure stdlib, offline.
Run: python3 test_ws2_surface.py
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CAL = os.path.join(HERE, "..", "calma.py")
_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def run(*args):
    return subprocess.run([sys.executable, CAL, *args], capture_output=True, text=True)


# ---- recipes search ----
r = run("recipes", "search", "sharpe", "ratio")
truth(r.returncode == 0 and "sharpe" in r.stdout and "matching" in r.stdout,
      "recipes search ranks a match for 'sharpe ratio'")
truth("--metric" in r.stdout, "recipes search points to the next command (--metric)")
r = run("recipes", "search", "area", "under", "curve")
truth(r.returncode == 0 and "auc" in r.stdout, "recipes search finds 'auc' from a natural-language query")
r = run("recipes", "search", "zzqqxxnope")
truth(r.returncode == 1 and "no recipe matches" in r.stdout, "recipes search: a clean miss (exit 1, guidance)")
r = run("recipes", "search", "sharpe", "--json")
j = json.loads(r.stdout)
truth(j["query"] == "sharpe" and j["matches"] and j["matches"][0]["metric_id"],
      "recipes search --json is structured")
# bare `recipes` still lists by family + points at search.
r = run("recipes")
truth(r.returncode == 0 and "search" in r.stdout, "bare recipes lists + advertises search")

# ---- schema ----
r = run("schema")
truth(r.returncode == 0, "schema exits 0")
d = json.loads(r.stdout)
truth(d["tool"] == "calma" and d.get("version"), "schema names the tool + version")
truth(d["outcomes"] == ["Confirmed", "Caught", "Can't tell"], "schema publishes the 3 outcomes")
truth(set(d["exit_codes"]) == {"0", "1", "2", "3", "4"}, "schema documents the exit-code contract")
truth(d["config_file"] == "calma.toml", "schema names the config file")
cmds = d["commands"]
truth({"verify", "up", "init", "status", "doctor", "recipes", "schema"} <= set(cmds),
      "schema enumerates the key commands (verify/up/init/status/doctor/recipes/schema)")
# the verify command's flags are introspected, incl. the new --fail-on=caveats choice.
vf = {a["dest"]: a for a in cmds["verify"]["args"]}
truth("claim" in vf and "metric" in vf and "why" in vf, "schema lists verify's common flags")
truth("caveats" in (vf["fail_on"]["choices"] or []), "schema carries --fail-on's caveats choice")
truth(vf["target"]["positional"] is True, "schema marks positionals")
# a nested-subcommand command (attest) exposes its subcommands.
if "attest" in cmds:
    sub = next((a for a in cmds["attest"]["args"] if a.get("subcommands")), None)
    truth(sub is not None and "verify" in sub["subcommands"], "schema surfaces nested subcommands (attest verify)")

print("ws2-surface: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
