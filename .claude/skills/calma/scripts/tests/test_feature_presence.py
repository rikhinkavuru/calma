"""H1: a blind merge that DROPS a feature must fail CI, not ship silently (the B1-was-dropped
incident). This asserts the user-visible SURFACE of every Phase 2-4 feature still exists - the CLI
flags/subcommands, the transport entrypoints, and the library hooks. It does not test behavior (the
per-feature suites do); it is a presence tripwire. Pure stdlib. Run: python3 test_feature_presence.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCR = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(SCR, "..", "..", "..", ".."))
sys.path.insert(0, SCR)
CALMA = os.path.join(SCR, "calma.py")

_n = _fail = 0


def truth(cond, label):
    global _n, _fail
    _n += 1
    if not cond:
        _fail += 1
        print("  FAIL [%s]" % label)


def cli(*args):
    r = subprocess.run([sys.executable, CALMA] + list(args), capture_output=True, text=True)
    return (r.stdout + r.stderr)


# --- CLI surface (the top-level subcommands) ---
top = cli("--help")
for cmd in ["verify", "init", "draft", "seal", "registry", "replay", "recipes", "suggest", "teardown"]:
    truth(cmd in top, "CLI exposes `%s`" % cmd)

# --- verify flags: C3 (--run-only), B2 (--cross-engine), M4 (--offline), C1 (--mode/timeout) ---
vh = cli("verify", "--help")
for flag in ["--run-only", "--cross-engine", "--offline", "--mode", "--timeout", "--check-determinism"]:
    truth(flag in vh, "verify exposes `%s`" % flag)

# --- C4: init <framework> + the M1 --list ---
ih = cli("init", "--help")
truth("--list" in ih, "init exposes `--list` (M1)")
truth("backtrader" in cli("init", "--list"), "init --list names frameworks (C4)")

# --- D1: registry site ---
truth("site" in cli("registry", "--help") or "site" in cli("registry"), "registry has `site` (D1)")

# --- B3: seal --evidence ---
truth("--evidence" in cli("seal", "--help"), "seal exposes `--evidence` (B3)")

# --- library hooks: B1 smells, B2 kernels, C1 coverage/timeout, CR1 near-miss ---
import plausibility_checks as PLC  # noqa: E402
for fn in ["check_regime_drift", "check_undeclared_split_leak", "check_train_test_loss_gap"]:
    truth(hasattr(PLC, fn), "B1 smell present: plausibility_checks.%s" % fn)
import cross_engine as CE  # noqa: E402
truth(len(CE._KERNELS) >= 7, "B2 cross-engine kernels present (%d)" % len(CE._KERNELS))
import hook_stop as HK  # noqa: E402
truth(hasattr(HK, "_coverage_line") and hasattr(HK, "_near_miss_line"),
      "C1 coverage line + CR1 near-miss line present")
import sniff_claims as SN  # noqa: E402
_c, _near = SN.sniff("the function return is 0.5", with_near=True)
truth(isinstance(_near, list), "CR1: sniff(with_near=True) returns near-misses")
import calma as C  # noqa: E402
truth(hasattr(C, "VerifyOptions"), "H2: VerifyOptions carrier present")

# --- transport entrypoints (firewalled features) ---
for rel in ["benchmark/run_agent.py", "pr/init.py", "mcp/calma_mcp/server.py"]:
    truth(os.path.isfile(os.path.join(ROOT, rel)), "transport entrypoint present: %s" % rel)
# C3 MCP debug tool
truth("calma_debug" in open(os.path.join(ROOT, "mcp/calma_mcp/server.py")).read(),
      "C3: the calma_debug MCP tool is registered")

# --- D3 assurance docs ---
truth(os.path.isfile(os.path.join(ROOT, "docs/assurance-roadmap.md")), "D3: assurance docs present")

print("feature-presence (H1): %d checks, %d failures" % (_n, _fail))
sys.exit(1 if _fail else 0)
