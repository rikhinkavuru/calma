#!/usr/bin/env bash
# Calma — PostToolUse reminder: keep docs/competitive-landscape.md in sync with engine/product changes.
# Reads the hook JSON on stdin; if the edited file is engine/product-relevant, emits a reminder
# (additionalContext to the model + a systemMessage to the user). Fail-open: any error => silent exit 0.
input="$(cat 2>/dev/null || true)"
f="$(printf '%s' "$input" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin); ti = d.get("tool_input", {}) or {}
    print(ti.get("file_path") or ti.get("filePath") or "")
except Exception:
    print("")
' 2>/dev/null || true)"
[ -z "$f" ] && exit 0
case "$f" in */node_modules/*|*/docs/competitive-landscape.md) exit 0 ;; esac
case "$f" in
  *.claude/skills/calma/scripts/*|*.claude/skills/calma/SKILL.md|*/benchmark/*|*/README.md|README.md|*/CHANGELOG.md|CHANGELOG.md|*.claude-plugin/plugin.json|*.claude-plugin/marketplace.json)
    cat <<EOF
{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"[doc-sync] Engine/product file changed: $f . If this changed WHAT CALMA IS OR DOES (engine pipeline, verdict logic, the validity families, recipe count/families, isolation/attestation, the benchmark, or the version), update ~/calma-strategy/competitive-landscape.md -- at minimum 'Part 1 -- What Calma is' and the 'Last updated' line -- and re-check whether any competitive delta changed."},"systemMessage":"doc-sync: engine/product file changed -- update ~/calma-strategy/competitive-landscape.md (Part 1 + Last-updated) if behavior changed."}
EOF
    ;;
esac
exit 0
