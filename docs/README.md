# Docs

## Start here (Diátaxis)

- **Tutorial — [Catch your first wrong number in 5 minutes](tutorial-catch-your-first-wrong-number.md):**
  one linear, copy-paste flow: install → `calma demo` → `calma up` on a tiny example → read the proof.
- **[How-to guides](how-to.md):** install the Claude Code Stop hook, wire a CI / PR gate, verify a proof
  offline, commit a `calma.toml`, run non-interactively in CI, add a custom recipe.
- **[Reference](reference.md):** every command + flag (from `calma schema`), the outcome/verdict roll-up,
  exit codes, the `calma.toml` schema, and the proof-bundle fields.
- **[Explanation](explanation.md):** why recompute beats re-reading the number, the validity families, the
  data-authenticity ceiling, and the threat model.
- **[`llms.txt`](llms.txt):** an AI-ingestible index of all of the above.

## Setup & operations

- **Install & run:** [`install.md`](install.md) — pip / symlink / Docker / Claude-plugin paths to a first verdict.
- **Supported frameworks:** [`frameworks.md`](frameworks.md) — the `calma init <framework>` starters.
- **PR / merge gate:** [`pr-bot.md`](pr-bot.md) and the hosted [GitHub App](../github_app/README.md).
- **Hosted console & auth:** [`DASHBOARD.md`](DASHBOARD.md).
- **Extending the engine:** [`extending.md`](extending.md) — add a recipe or a validity family (eval-gated).

## Trust & internals

- **Trust & data-flow:** [`TRUST.md`](TRUST.md) — where the bytes go (and don't), the four runnable SOC 2
  controls (`make controls`), what a security questionnaire answers trivially, and the limits we never claim away.
- **Using the skill:** see the top-level [`README.md`](../README.md) and `.claude/skills/calma/SKILL.md`.
- **Calibration & vendoring:** `.claude/skills/calma/calibration/CALIBRATION.md`, `VENDORING.md`.
- `internal/` — project planning, design specs, and market notes (not needed to use the skill).
