# Contributing to Calma

Thanks for your interest in making Calma better. Calma is an open-source verifier for AI-computed
numbers: it re-runs the code and recomputes the headline metric from raw outputs, then proves or breaks
the claim. This guide covers the one rule that matters, how to run the suites, and how to add a recipe.

## The one rule: the verdict is deterministic, never a model

Calma's whole value is that **the verdict is computed by a single deterministic function, not a language
model** — so it can't be talked past, even when checking an agent's own work. This is enforced
structurally, and a contribution that breaks it won't be merged:

- The **engine** (`.claude/skills/calma/scripts/`) is **pure Python stdlib** and AI-free. No `import`
  of any model client, ever. The verdict, every statistic, and every validity flag come from code here.
- AI lives **only** in the `edges/` package ("AI proposes, determinism disposes"): extracting claims,
  drafting contracts, synthesizing recipes, repairing broken results. A CI **firewall test**
  (`edges/tests/test_firewall.py`) blocks `edges/` from importing the verdict core
  (`verdict`/`recompute`/`compare`/`ledger`/`numeric`). The engine reaches the model only as a
  subprocess, never an import.

If you're adding an AI-assisted feature, it goes in `edges/` and is reached via a subprocess seam (see
`calma draft --ai`, `calma onboard`, `calma repair`).

## Running the tests

The engine is dependency-free, so its suite runs on a clean Python 3.9+ with no install:

```bash
# the full engine suite (pure stdlib — no deps, no venv)
python3 .claude/skills/calma/scripts/tests/run_all.py

# prove the sandbox actually isolates on your host
python3 .claude/skills/calma/scripts/run_hermetic.py doctor

# everything (engine + mcp + pr) in one command
make test-all
```

The `edges/`, `mcp/`, and `pr/` packages have their own deps; install them into a venv before running
those suites:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ./mcp pytest numpy "anthropic>=0.40,<2" "jsonschema>=4.18,<5"
pytest -q edges/tests mcp/tests pr/tests   # edges tests REPLAY recorded fixtures — no API key needed
```

The web app (the marketing site + dashboard) is a separate Next.js project:

```bash
npm install && npm run build      # tsc + production build
```

Every PR must keep the engine suite green and the firewall test passing.

## Repository layout

| Path | What |
|---|---|
| `.claude/skills/calma/` | the pure-stdlib **engine** + the `calma` CLI/skill (the product) |
| `src/calma/` | the pip-installable facade + the OTel wedge |
| `edges/` | the AI edges (extract / draft / synth / repair) — firewalled from the core |
| `mcp/`, `pr/`, `github_app/` | the transports (MCP server, PR-review bot, GitHub App) |
| `control_plane/`, `api/` | the hosted control-plane API (FastAPI + the Vercel entry) |
| `app/`, `components/` | the Next.js marketing site + logged-in dashboard |
| `benchmark/` | the reproducible head-to-head corpus |
| `docs/` | user + operator docs |

## Adding a metric recipe

Recipes are deterministic, total programs in a constrained DSL — no loops, no I/O, terminating by
construction. A new recipe is admitted only when it reproduces the published reference implementation to
tolerance and holds its metamorphic properties (the same gate every built-in recipe clears). Start from
[`docs/extending.md`](docs/extending.md) and the existing recipes in
`.claude/skills/calma/scripts/recipes.py`. For a metric with no published oracle (a firm's bespoke
metric), `calma onboard` drives a CEGIS synthesis loop gated by the deterministic admission test.

## Pull requests

1. Branch off `main`.
2. Keep changes focused; one logical change per PR where practical.
3. Add a regression test for any behavior change.
4. Run `python3 .claude/skills/calma/scripts/tests/run_all.py` (and the relevant package suites).
5. Open the PR — CI runs the engine suite on macOS + Linux, the MCP/PR transports, SCA, and CodeQL.

## Reporting bugs and security issues

Open a bug via the issue templates. For security vulnerabilities, **do not open a public issue** —
follow [`SECURITY.md`](SECURITY.md).

## License

By contributing, you agree your contributions are licensed under the repository's [MIT License](LICENSE).
