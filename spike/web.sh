#!/usr/bin/env bash
# Launch the Calma web app (connect a repo → verify the numbers). Open http://localhost:8787
set -e
VENV="$HOME/.calma/spike-venv"
[ -x "$VENV/bin/python" ] || { echo "spike venv missing — see spike/README.md"; exit 1; }
# load local config/secrets (GitHub App, etc.) if present — kept outside the repo
[ -f "$HOME/.calma/calma.env" ] && { set -a; . "$HOME/.calma/calma.env"; set +a; }
exec "$VENV/bin/python" "$(cd "$(dirname "$0")" && pwd)/server.py"
