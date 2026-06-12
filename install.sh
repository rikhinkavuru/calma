#!/usr/bin/env bash
# Put `calma` on your PATH. Pure-stdlib: no pip, no deps - just a symlink to bin/calma.
# Usage:  ./install.sh            # installs to ~/.local/bin (or /usr/local/bin)
#         ./install.sh <dir>      # installs to <dir>
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$REPO/bin/calma"
chmod +x "$SRC"

DEST="${1:-}"
if [ -z "$DEST" ]; then
  if echo ":$PATH:" | grep -q ":$HOME/.local/bin:"; then DEST="$HOME/.local/bin"
  elif [ -w "/usr/local/bin" ]; then DEST="/usr/local/bin"
  else DEST="$HOME/.local/bin"; fi
fi
mkdir -p "$DEST"
ln -sf "$SRC" "$DEST/calma"
echo "linked: $DEST/calma -> $SRC"

if ! echo ":$PATH:" | grep -q ":$DEST:"; then
  echo "NOTE: $DEST is not on your PATH. Add it, e.g.:"
  echo "  echo 'export PATH=\"$DEST:\$PATH\"' >> ~/.zshrc && source ~/.zshrc"
fi
echo "try:  calma demo"
