#!/usr/bin/env bash
# Boot the local Calma console in one command: the verifications API (:8000) and
# the web app (:3000) together, with a single Ctrl-C taking both down.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CPV="${CALMA_CP_VENV:-$HOME/.calma/cp-venv}"

if [ ! -x "$CPV/bin/uvicorn" ]; then
  echo "control-plane venv not found at $CPV" >&2
  echo "  one-time setup:  bash control_plane/setup-venv.sh" >&2
  exit 1
fi
if [ ! -d "$ROOT/web/node_modules" ]; then
  echo "web deps missing — installing..." >&2
  ( cd "$ROOT/web" && npm install )
fi

cd "$ROOT"
API_LOG="$(mktemp -t calma-api.XXXXXX.log)"
echo "→ API   http://localhost:8000   (control_plane.api.app · log: $API_LOG)"
"$CPV/bin/uvicorn" control_plane.api.app:app --port 8000 >"$API_LOG" 2>&1 &
API_PID=$!
trap 'kill "$API_PID" 2>/dev/null || true' EXIT INT TERM

# wait for the API to answer before starting the web app (cleaner first paint)
api_up=0
for _ in $(seq 1 20); do
  if curl -fsS -o /dev/null http://localhost:8000/healthz 2>/dev/null; then api_up=1; break; fi
  sleep 0.5
done
[ "$api_up" = 1 ] || echo "  ⚠ API did not answer on :8000 — see $API_LOG (the dashboard will show an API-unreachable card)" >&2

echo "→ web   http://localhost:3000   (dashboard at /dashboard)"
cd "$ROOT/web" && npm run dev
