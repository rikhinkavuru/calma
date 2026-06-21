#!/usr/bin/env bash
# `make eval` - the standing eval net (roadmap Phase 0 / pillar 2). Every change runs this; it is the
# safety net that makes fast change safe. Four gates, all pure-stdlib (no venv, no network, no heavy deps):
#   [1] core suite        - the 61 in-repo suites (recipes, validity families, report, verdict, ...)
#   [2] framework vectors - Calma's recompute == frozen golden == an INDEPENDENT pure-python reference
#                           (offline; --check-live in CI adds golden == the live framework)
#   [3] recompute-only    - the validity-gap baseline (a recompute-only verifier MISSES the validity cut)
#   [4] determinism       - the recompute path is byte-identical across runs with k_spread==0
# Any non-zero gate fails the whole target (set -e). Wired into CI on every push (.github/workflows).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"

echo "== [1/4] core suite =================================================="
"$PY" .claude/skills/calma/scripts/tests/run_all.py

echo ""
echo "== [2/4] framework golden vectors (Calma == golden == independent ref) =="
"$PY" benchmark/gen_framework_vectors.py

echo ""
echo "== [3/4] recompute-only validity-gap baseline ======================="
"$PY" benchmark/recompute_only.py

echo ""
echo "== [4/4] determinism (byte-identical recompute, k_spread==0) ========="
"$PY" benchmark/determinism_check.py

echo ""
echo "OK: make eval green (core + framework-vectors + recompute-baseline + determinism)"
