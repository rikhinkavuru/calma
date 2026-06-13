# Source for docs/demo.gif (the README demo).
# Regenerate from the repo root with:  vhs docs/demo.tape
# Requires: vhs + ttyd + ffmpeg  (brew install vhs ttyd ffmpeg)
#
# Records the real `calma demo` (re-executes a bundled inflated BTC backtest and recomputes
# +14,698% -> -32.4%). A bash function shims `calma` to the in-repo CLI and CALMA_INVOKED_AS
# makes the printed reproduce/next-step hints read `calma ...` (copy-pasteable). CALMA_TRACE is
# left at its TTY default, so the live re-execution trace shows.

Output "docs/demo.gif"

Set Shell "bash"
Set FontSize 15
Set Width 1320
Set Height 600
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 55ms

Hide
Type `export TMPDIR=$(mktemp -d); export CALMA_INVOKED_AS=calma; calma() { python3 .claude/skills/calma/scripts/calma.py "$@"; }; export PS1='$ '; clear`
Enter
Sleep 400ms
Show

Sleep 800ms
Type "calma demo"
Sleep 500ms
Enter
Sleep 4s
