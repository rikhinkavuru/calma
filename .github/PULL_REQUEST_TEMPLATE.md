<!-- Thanks for contributing to Calma. Keep PRs focused; one logical change where practical. -->

## What & why

<!-- What does this change, and why? Link any issue (Fixes #123). -->

## How it was tested

<!-- The commands you ran. The engine suite must stay green. -->

- [ ] `python3 .claude/skills/calma/scripts/tests/run_all.py` passes
- [ ] Added/updated a regression test for the behavior change
- [ ] Relevant package suite passes (`edges/` · `mcp/` · `pr/`) if touched
- [ ] `npm run build` passes (if the web app was touched)

## The verdict firewall

<!-- Required reading: CONTRIBUTING.md. Confirm the invariant still holds. -->

- [ ] No model client is imported by the engine (`.claude/skills/calma/scripts/`); any AI is in `edges/`
      and reached only via a subprocess seam
- [ ] `edges/tests/test_firewall.py` still passes (the AI layer can't import the verdict core)
