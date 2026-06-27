#!/usr/bin/env bash
# Launch the Calma web app (connect a repo → verify the numbers). Open http://localhost:8787
set -e
VENV="$HOME/.calma/spike-venv"
[ -x "$VENV/bin/python" ] || { echo "spike venv missing — see spike/README.md"; exit 1; }
exec "$VENV/bin/python" "$(cd "$(dirname "$0")" && pwd)/server.py"
