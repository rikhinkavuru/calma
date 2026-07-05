#!/bin/sh -l
# Calma validity-check action entrypoint. Runs the no-run validity scan on the checked-out repo, writes a
# job summary, posts/updates a PR report-card comment, and exits non-zero per --fail-on (fails the check).
SCAN_PATH="${1:-.}"
FAIL_ON="${2:-fail}"
COMMENT="${3:-true}"
TARGET="${GITHUB_WORKSPACE:-.}/${SCAN_PATH}"

python /calma/spike/validity_scan.py "$TARGET" \
  --format md \
  --out /tmp/calma_card.json \
  --summary-file "${GITHUB_STEP_SUMMARY:-/dev/null}" \
  --fail-on "$FAIL_ON" > /tmp/calma_card.md
CODE=$?
cat /tmp/calma_card.md

# exit 2 = the SCANNER itself errored (not a validity FAIL, which is exit 1). Surface it distinctly so a broken
# invocation isn't misread as "your numbers are invalid" — and don't block on it if the user asked report-only.
if [ "$CODE" = "2" ]; then
  echo "::warning title=Calma::the validity scanner could not run (config/path error), not a validity failure"
  [ "$FAIL_ON" = "never" ] && CODE=0
fi

GRADE=$(python -c "import json;print(json.load(open('/tmp/calma_card.json'))['grade'])" 2>/dev/null || echo UNKNOWN)
if [ -n "$GITHUB_OUTPUT" ]; then
  echo "grade=$GRADE" >> "$GITHUB_OUTPUT"
fi

if [ "$COMMENT" = "true" ] && [ -n "$GITHUB_TOKEN" ]; then
  python /calma/action/pr_comment.py /tmp/calma_card.md || echo "calma: PR comment skipped (no PR / token)"
fi

exit $CODE
