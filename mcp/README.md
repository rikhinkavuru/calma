# calma-mcp — Calma's deterministic verifier, under every agent host

A host-agnostic [MCP](https://modelcontextprotocol.io) server that exposes Calma's **deterministic**
verifier to any MCP host (Claude Desktop, Cursor, Codex CLI, Windsurf, CI bots). The calling agent
*proposes* a number; Calma's engine *disposes* the verdict by re-executing the target to ground truth
and recomputing the headline metric.

**Transport only.** Every tool shells out to the shipped CLI and returns the engine's JSON verbatim.
The server never imports the verdict core (`verdict` / `ledger` / `compare` / `recompute` / `numeric`)
and never re-implements a verdict — enforced by `mcp/tests/test_firewall.py`. The pure-stdlib Calma
engine stays dependency-free; the only dependency here is the MCP SDK.

## Tools

| Tool | What it does | LLM? |
|------|--------------|------|
| `calma_verify(target, claim?, metric?, mode="ask", trust="own-code", isolation="auto", timeout=600, check_determinism=false)` | Re-execute `target` and recompute the headline number, then prove or break the claim. The agent guardrail — **works today**. | No (the engine is deterministic) |
| `calma_debug(target, claim?, metric?, trust="own-code", isolation="auto", timeout=600)` | Iterate mid-task: re-run + recompute + return the **binding, recomputed value, and gap** vs your claim, with **NO verdict and NO gate**. "What does the code actually compute, and how far off is my number?" Pair with `calma_verify` for the gating pass/fail. | No (recompute only) |
| `calma_verify_artifact(target, mode="flag")` | Verify *every* number in an artifact directory (notebook / PDF / CSV + the data it was computed from), each catch tied to its source span. Wraps the A1 claim-graph pipeline (`python -m edges.extract`). | Extraction only; the verdict is still deterministic |
| `calma_suggest(query, top=5)` | Rank the recipes a free-text description best matches (the shipped suggester). | No |

`calma_verify` is deterministic and makes **no** model call, so it needs no API key. Safety flags
(`--trust` / `--isolation` / `--timeout`) pass through to the engine unchanged — the server cannot
downgrade isolation or weaken a verdict. A target path that escapes the workspace
(`CALMA_MCP_WORKSPACE`, default: the server's cwd) is rejected before any subprocess runs.

## Resources (read-only)

- `calma://recipes` — the recipe catalog (coverage at a glance).
- `calma://catch-history` — the (Rekor-backed) catch-history registry summary, if configured.

## Install

```bash
pip install ./mcp                 # or:  pip install ./mcp[http]   for the streamable-HTTP transport
```

The server shells out to this repo's `calma.py`. When run from a checkout the path is auto-detected;
for an installed deployment, point it at the engine with two env vars:

```bash
export CALMA_HOME=/path/to/calma                                   # repo root (for python -m edges.extract)
export CALMA_SCRIPT=$CALMA_HOME/.claude/skills/calma/scripts/calma.py
export CALMA_MCP_WORKSPACE=/path/to/your/project                   # the path jail (default: cwd)
```

## Run

```bash
python -m calma_mcp           # stdio (default) — for desktop hosts
python -m calma_mcp --http --host 127.0.0.1 --port 8765   # streamable HTTP (needs the [http] extra)
```

## Host configuration

### Claude Desktop / Cursor / Windsurf (stdio)

`claude_desktop_config.json` (or the host's MCP config):

```json
{
  "mcpServers": {
    "calma": {
      "command": "python",
      "args": ["-m", "calma_mcp"],
      "env": {
        "CALMA_HOME": "/path/to/calma",
        "CALMA_SCRIPT": "/path/to/calma/.claude/skills/calma/scripts/calma.py",
        "CALMA_MCP_WORKSPACE": "/path/to/your/project"
      }
    }
  }
}
```

### Codex CLI (`~/.codex/config.toml`)

```toml
[mcp_servers.calma]
command = "python"
args = ["-m", "calma_mcp"]
env = { CALMA_HOME = "/path/to/calma", CALMA_MCP_WORKSPACE = "/path/to/your/project" }
```

### CI bot (streamable HTTP)

```bash
pip install ./mcp[http]
CALMA_MCP_WORKSPACE="$GITHUB_WORKSPACE" python -m calma_mcp --http --port 8765 &
# point your MCP-over-HTTP client at  http://127.0.0.1:8765/mcp
```

## Example

```jsonc
// call: calma_verify { "target": ".claude/skills/calma/assets/btc" }
// returns (verbatim engine JSON):
{ "verdict": "REFUTED", "claimed": 146.98, "recomputed": -0.316, "gate_exit": 1,
  "metric": "total_return", "run_dir": ".../.calma/run", "isolation_tier": "...", ... }
```

The agent claimed a +14,698 % return; Calma recomputed −31.6 % from the raw OOS series and **refuted**
it. The server added nothing — the verdict is the engine's.
