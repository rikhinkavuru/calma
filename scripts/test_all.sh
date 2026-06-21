#!/usr/bin/env bash
# T1: run EVERY Calma test layer with the right interpreter, in one command.
#   core (pure stdlib)  -> system python3            -> .../scripts/tests/run_all.py
#   mcp  (transport)    -> ~/.calma/mcp-venv  (mcp SDK + pytest)
#   pr   (transport)    -> ~/.calma/ref-venv  (pytest + numpy)
# Exits non-zero if ANY layer fails - no more "out of band" blind spot where `make test` reads 48/0
# while 39 transport tests never ran. Bootstraps the venvs if missing (needs network that once).
#
# Override interpreters: CALMA_MCP_VENV / CALMA_REF_VENV (point at an existing venv dir).
# Skip a layer: CALMA_SKIP_MCP=1 / CALMA_SKIP_PR=1 (e.g. offline CI without the SDK).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
CORE="$ROOT/.claude/skills/calma/scripts/tests/run_all.py"
MCP_VENV="${CALMA_MCP_VENV:-$HOME/.calma/mcp-venv}"
REF_VENV="${CALMA_REF_VENV:-$HOME/.calma/ref-venv}"

fails=0
declare -a summary

run_layer() {  # name, command...
  local name="$1"; shift
  echo "── $name ─────────────────────────────────────────────"
  if "$@"; then summary+=("  PASS  $name")
  else fails=$((fails+1)); summary+=("  FAIL  $name"); fi
  echo
}

ensure_venv() {  # venv_dir, pip-args...
  local venv="$1"; shift
  local py="$venv/bin/python"
  if [ ! -x "$py" ]; then
    echo "bootstrapping venv at $venv ..."
    python3 -m venv "$venv" || return 1
    "$py" -m pip install --quiet --upgrade pip || return 1
  fi
  if ! "$py" -c "import pytest" 2>/dev/null; then
    echo "installing test deps into $venv ..."
    "$py" -m pip install --quiet "$@" || return 1
  fi
  echo "$py"
}

# 1) core ------------------------------------------------------------------
run_layer "core (system python3)" python3 "$CORE"

# 2) mcp -------------------------------------------------------------------
if [ "${CALMA_SKIP_MCP:-0}" = "1" ]; then
  summary+=("  SKIP  mcp (CALMA_SKIP_MCP=1)")
else
  if MCP_PY="$(ensure_venv "$MCP_VENV" pytest numpy -e ./mcp)"; then
    MCP_PY="$(printf '%s\n' "$MCP_PY" | tail -1)"
    run_layer "mcp (mcp-venv)" env PYTHONPATH="$ROOT/mcp" "$MCP_PY" -m pytest -q mcp/tests
  else
    fails=$((fails+1)); summary+=("  FAIL  mcp (venv bootstrap failed)")
  fi
fi

# 3) pr --------------------------------------------------------------------
if [ "${CALMA_SKIP_PR:-0}" = "1" ]; then
  summary+=("  SKIP  pr (CALMA_SKIP_PR=1)")
else
  if REF_PY="$(ensure_venv "$REF_VENV" pytest numpy)"; then
    REF_PY="$(printf '%s\n' "$REF_PY" | tail -1)"
    run_layer "pr (ref-venv)" "$REF_PY" -m pytest -q pr/tests
  else
    fails=$((fails+1)); summary+=("  FAIL  pr (venv bootstrap failed)")
  fi
fi

echo "═══════════════════════ test-all summary ═══════════════════════"
printf '%s\n' "${summary[@]}"
echo "════════════════════════════════════════════════════════════════"
[ "$fails" -eq 0 ] && echo "all layers green" || echo "$fails layer(s) FAILED"
exit $((fails > 0 ? 1 : 0))
