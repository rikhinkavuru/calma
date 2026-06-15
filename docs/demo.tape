# Source for docs/demo.gif + docs/demo.mp4 (the README + site demo).
# Regenerate from the repo root with:  vhs docs/demo.tape
# Requires: vhs + ttyd + ffmpeg  (brew install vhs ttyd ffmpeg)
#
# Records real `calma` runs end to end:
#   1. catch an inflated backtest                                     -> REFUTED
#   2. catch a number that reproduces but is invalid (validity layer) -> INVALIDATED
#   3. confirm an honest result                                       -> CONFIRMED
#   4. seal a signed, counterparty-checkable proof
# A bash function shims `calma` to the in-repo CLI; CALMA_INVOKED_AS makes the printed hints read
# `calma ...`. CALMA_TRACE is left at its TTY default, so the live re-execution trace shows.

Output "docs/demo.gif"
Output "docs/demo.mp4"

Require ffmpeg

Set Shell "bash"
Set FontSize 16
Set Width 1340
Set Height 840
Set Padding 28
Set Margin 44
Set MarginFill "#211c2e"
Set BorderRadius 12
Set WindowBar Colorful
Set TypingSpeed 45ms
Set LoopOffset 35%
Set Theme { "name": "Calma", "background": "#15131c", "foreground": "#e9ddc4", "black": "#2a2735", "red": "#ef7a6a", "green": "#5ec99a", "yellow": "#f0c074", "blue": "#7aa2f7", "magenta": "#c79bf0", "cyan": "#46c7c0", "white": "#e9ddc4", "brightBlack": "#5a5670", "brightRed": "#f29485", "brightGreen": "#74d7ad", "brightYellow": "#f4d08c", "brightBlue": "#9bb8ff", "brightMagenta": "#d4b3f5", "brightCyan": "#6fd6cf", "brightWhite": "#fbf3e2", "selection": "#3a3650", "cursor": "#f0a868" }

# --- setup (hidden): shim calma to the in-repo CLI, stage two demo results ---
Hide
Type `cd "$(mktemp -d)"; calma() { python3 ~/calma/.claude/skills/calma/scripts/calma.py "$@"; }; export CALMA_INVOKED_AS=calma; export PS1='$ '; D=~/calma/.claude/skills/calma/assets/demos; cp -r "$D/leakage-heldout" model; cp -r "$D/deflated-sharpe-survives" honest; clear`
Enter
Sleep 600ms
Show

# --- 1. catch a backtest that's too good to be true ---
Sleep 800ms
Type "# does this backtest actually hold up?"
Enter
Sleep 350ms
Type "calma demo"
Sleep 400ms
Enter
Wait+Screen /REFUTED/
Sleep 3s
Hide
Type "clear"
Enter
Show

# --- 2. a number can reproduce perfectly and still be invalid ---
Sleep 500ms
Type "# the AUC reproduces -- but is it really held out?"
Enter
Sleep 350ms
Type `calma verify model "AUC 1.0 on the held-out set" --metric auc`
Sleep 400ms
Enter
Wait+Screen /INVALIDATED/
Sleep 3s
Hide
Type "clear"
Enter
Show

# --- 3. ...and confirm an honest one (it isn't just a naysayer) ---
Sleep 500ms
Type "# a real edge should survive the correction"
Enter
Sleep 350ms
Type `calma verify honest "deflated sharpe 0.996, survives the 1000-config search" --metric deflated_sharpe`
Sleep 400ms
Enter
Wait+Screen /CONFIRMED/
Sleep 3s
Hide
Type "clear"
Enter
Show

# --- 4. hand over a signed proof a counterparty checks offline ---
Sleep 500ms
Type "# every verdict ships as a signed, replayable proof"
Enter
Sleep 350ms
Type "calma seal honest/.calma/run --no-timestamp"
Sleep 400ms
Enter
Wait+Screen /VERIFIED/
Sleep 4s
