# calma — CLI for the Calma verification engine

Connect a repo, re-run it, recompute every number it reports, and get a per-claim verdict — from your
terminal or CI. Zero dependencies (stdlib only).

```bash
pip install calma
export CALMA_API_KEY=calma_sk_...        # create one at https://calma1.vercel.app/dashboard/keys

calma verify owner/repo --deep           # re-run + recompute every number
calma scans                              # your recent scans
calma get <scan-id>                      # one scan's verdict summary
calma logs <scan-id>                     # the full run log
```

`calma verify … --deep` exits non-zero if any number fails to reproduce (REFUTED / INVALIDATED) — so it
works as a CI gate. Drop `--deep` for a fast, no-run validity check (leakage / trivial baseline / misreport).

## Config

| env | default | meaning |
|---|---|---|
| `CALMA_API_KEY` | — | your API key (required for the hosted engine) |
| `CALMA_API_URL` | `https://calma-engine.fly.dev` | engine base URL |

## MCP server (AI agents)

```bash
pip install "calma[mcp]"
python -m calma_mcp        # stdio; exposes calma_verify + calma_scans tools
```

See <https://calma1.vercel.app/dashboard/integrations> for the GitHub Action and PR-check surfaces.
