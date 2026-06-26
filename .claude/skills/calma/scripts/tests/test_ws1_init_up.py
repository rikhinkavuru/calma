"""WS1: calma.toml config + `calma init` (auto-detect) + `calma up` (verify-first) + bare `calma verify`
reading the committed config. Pure stdlib, offline for the config layer; the `up` integration re-executes
a tiny fixture in the sandbox. Run: python3 test_ws1_init_up.py
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import config_toml as CFG  # noqa: E402
import calma as C          # noqa: E402

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


# ============ config_toml: parse / round-trip / find ==============================================
# the flat minimal reader (exercised directly so 3.9/3.10 - where tomllib is absent - is covered).
flat = CFG._parse_minimal('# c\n[verify]\ntarget = "./eval"\nmetric = "accuracy"\nclaim = "accuracy=0.91"\n'
                          'tol = 0.005\nquiet = true\n')
truth(flat["verify"]["target"] == "./eval", "minimal: string value")
truth(flat["verify"]["tol"] == 0.005, "minimal: float value")
truth(flat["verify"]["quiet"] is True, "minimal: bool value")
truth(flat["verify"]["claim"] == "accuracy=0.91", "minimal: '=' inside a quoted value is preserved")
# an inline comment outside quotes is stripped; a '#' inside quotes is data.
hashy = CFG._parse_minimal('[verify]\nmetric = "accuracy"   # a comment\nclaim = "a#b"\n')
truth(hashy["verify"]["metric"] == "accuracy", "minimal: inline comment stripped")
truth(hashy["verify"]["claim"] == "a#b", "minimal: '#' inside quotes kept")
# loads() agrees with the minimal reader on the flat subset (tomllib path when present).
viatoml = CFG.loads('[verify]\ntarget = "."\nmetric = "sharpe"\n')
truth(viatoml["verify"]["metric"] == "sharpe", "loads(): flat subset parses under tomllib or fallback")
# dump_verify round-trips through loads().
rt = CFG.loads(CFG.dump_verify(target=".", metric="rmse", claim="rmse=0.2", tol=0.01))
truth(rt["verify"] == {"target": ".", "metric": "rmse", "claim": "rmse=0.2", "tol": 0.01},
      "dump_verify -> loads round-trips every field")
rt2 = CFG.loads(CFG.dump_verify(target="./out", metric="accuracy"))
truth("claim" not in rt2["verify"], "dump_verify omits claim when none given (reproduction-only)")

# find(): walks up, stops at the repo root (.git), never escapes into an unrelated parent.
tmp = tempfile.mkdtemp(prefix="calma-ws1-")
try:
    repo = os.path.join(tmp, "repo")
    sub = os.path.join(repo, "a", "b")
    os.makedirs(sub)
    os.makedirs(os.path.join(repo, ".git"))
    truth(CFG.find(sub) is None, "find: none when no calma.toml anywhere")
    CFG.write(repo, target=".", metric="accuracy")
    found = CFG.find(sub)
    truth(found == os.path.join(repo, "calma.toml"), "find: discovers calma.toml at the repo root from a subdir")
    # a calma.toml ABOVE the repo root (outside .git) must NOT be picked up.
    CFG.write(tmp, target=".", metric="leak")
    truth(CFG.find(sub) == os.path.join(repo, "calma.toml"),
          "find: stops at the repo root - never reads an unrelated parent's calma.toml")
    # verify_config resolves target RELATIVE TO the calma.toml dir, from any subdir.
    cfg = CFG.verify_config(sub)
    truth(cfg and cfg["target"] == os.path.realpath(repo) or cfg["target"] == repo,
          "verify_config: target resolved relative to the calma.toml dir")
    truth(cfg.get("metric") == "accuracy", "verify_config: carries the metric")

    # the stray parent calma.toml above was only for the boundary assertion; remove it so the isolated
    # project fixtures below (each its own repo, with a .git boundary) can't pick it up.
    os.remove(os.path.join(tmp, "calma.toml"))

    # ======== `calma init` (auto-detect) writes calma.toml from an EXISTING output ================
    proj = os.path.join(tmp, "proj")
    os.makedirs(os.path.join(proj, ".git"))   # an isolated repo (find() stops at this boundary)
    with open(os.path.join(proj, "preds.csv"), "w") as fh:
        fh.write("y_true,y_pred\n1,1\n0,0\n1,0\n0,0\n1,1\n")
    rc = C.init_detect_cmd(proj, yes=True)
    truth(rc == 0, "init --yes: exits 0 when it detects a recomputable artifact")
    truth(os.path.isfile(os.path.join(proj, "calma.toml")), "init: writes calma.toml")
    cfg2 = CFG.verify_config(proj)
    truth(cfg2 and cfg2.get("metric"), "init: the written calma.toml pins a metric")
    # idempotent: a second init without --force does not clobber and exits 0.
    rc2 = C.init_detect_cmd(proj, yes=True)
    truth(rc2 == 0, "init: re-run without --force is a no-op exit 0 (doesn't clobber)")

    # ======== `calma up` on a FRESH repo: execute -> detect -> verify -> persist ===================
    fresh = os.path.join(tmp, "fresh")
    os.makedirs(os.path.join(fresh, ".git"))   # an isolated repo
    with open(os.path.join(fresh, "main.py"), "w") as fh:
        fh.write("import csv\n"
                 "rows=[('y_true','y_pred')]+[(i%2, i%2) for i in range(20)]\n"
                 "open('out.csv','w').write('\\n'.join('%s,%s'%r for r in rows))\n"
                 "print('accuracy', 1.0)\n")
    rc3 = C.up_cmd(fresh, yes=True)
    truth(rc3 == 0, "up: fresh repo executes + recomputes + exits clean (got %s)" % rc3)
    truth(os.path.isfile(os.path.join(fresh, "calma.toml")),
          "up: persists calma.toml on the first run so the next verify is bare")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("ws1-init-up: %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
