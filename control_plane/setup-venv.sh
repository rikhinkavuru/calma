#!/usr/bin/env bash
# Create the control-plane venv (~/.calma/cp-venv) and install its deps. Mirrors the repo's other
# ~/.calma/*-venv conventions (eval-venv, mcp-venv, ...). The engine stays pure-stdlib; this is separate.
set -euo pipefail
VENV="${CALMA_CP_VENV:-$HOME/.calma/cp-venv}"
PY="${PYTHON:-/usr/bin/python3}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$PY" -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$HERE/requirements.txt"
echo "cp-venv ready: $VENV"
"$VENV/bin/python" -c "import psycopg; print('psycopg', psycopg.__version__)"
