// Docs content — the single source of truth. Each page is authored in Markdown; the page renders it, the
// "Copy page" / "View as Markdown" actions serve it verbatim, and the "Open in ChatGPT/Claude/Perplexity"
// links point an LLM at /docs/<slug>.md. Keep it accurate to the real engine/CLI/MCP (calma-engine.fly.dev).

export const ENGINE = "https://calma-engine.fly.dev";
export const DASH = "https://calma1.vercel.app";

export type DocPage = { slug: string; title: string; description: string; group: string; markdown: string };

export const GROUPS = ["Getting started", "Surfaces", "CI & pull requests"] as const;

export const DOCS: DocPage[] = [
  {
    slug: "quickstart",
    title: "Quickstart",
    description: "Verify the numbers a repository reports — in one command.",
    group: "Getting started",
    markdown: `Calma **re-runs a repository, recomputes every number it reports from the raw outputs, and tells you which hold up** — a deterministic verdict, never an LLM guess. It is the correctness layer for benchmarks, evals, and reproducible research.

There are three ways to use it, depending on where you work:

| Surface | Best for |
| --- | --- |
| [Dashboard](${DASH}/dashboard) | Point-and-click: connect a repo, watch it verify |
| [CLI](/docs/cli) | Your terminal or a CI gate — \`pip install calma\` |
| [API](/docs/api) / [MCP](/docs/mcp) | Automation, agents, and integrations |

## 60-second start (CLI)

\`\`\`bash
pip install calma
export CALMA_API_KEY=calma_sk_...        # create one at ${DASH}/dashboard/keys

calma verify owner/repo --deep           # re-run + recompute every number
\`\`\`

That's it. Calma clones the repo into a network-isolated sandbox, re-runs it, recomputes each reported metric from the raw outputs, and prints a per-claim verdict.

## What a verdict means

Every reported number gets exactly one verdict — the label is derived by a single deterministic function, so it is reproducible and can never be a false confirm:

| Verdict | Meaning |
| --- | --- |
| **CONFIRMED** | The number reproduces from a re-run + independent recompute |
| **REFUTED** | The code does not produce the reported number |
| **INVALIDATED** | The number reproduces, but the method is invalid (e.g. data leakage) |
| **REPRODUCED_ONLY** | Regenerates deterministically, but correctness couldn't be independently confirmed |
| **INCONCLUSIVE** | Ran, but the number couldn't be bound to a computation (fail-closed) |
| **DISCOVERED** | Found in the repo, not deep-verified |

> Calma is **fail-closed**: when it cannot verify something, it says so — it never upgrades a doubt into a confirmation.

## Next steps

- [Authentication](/docs/authentication) — create and use an API key
- [CLI reference](/docs/cli) — every command and flag
- [Re-run the paper](/docs/api#artifact-reproduction) — verify committed result files regenerate
`,
  },
  {
    slug: "authentication",
    title: "Authentication",
    description: "Create an API key and authenticate the CLI, API, or MCP server.",
    group: "Getting started",
    markdown: `Programmatic access (the CLI, the API, the MCP server) authenticates with an **API key**. The dashboard uses your signed-in session, so you only need a key for automation.

## Create a key

1. Open [**Dashboard → API keys**](${DASH}/dashboard/keys).
2. Give it a label (e.g. \`laptop CLI\`, \`CI\`) and click **Create key**.
3. Copy the key **immediately** — it is shown once and only stored hashed. It looks like \`calma_sk_…\`.

You can list and revoke keys from the same page; a revoked key stops working instantly.

## Use a key

Set it as an environment variable (the CLI and MCP read it automatically):

\`\`\`bash
export CALMA_API_KEY=calma_sk_...
\`\`\`

Or send it as a bearer token when calling the API directly:

\`\`\`bash
curl ${ENGINE}/api/jobs \\
  -H "Authorization: Bearer $CALMA_API_KEY"
\`\`\`

## Scope & tiers

A key inherits the **tenant and plan** it was created under — every request is metered and rate-limited exactly like your dashboard. A key can only ever see or affect **your own** scans; it cannot mint or revoke keys (that stays in the dashboard, so a leaked key can't escalate).

| Variable | Default | Meaning |
| --- | --- | --- |
| \`CALMA_API_KEY\` | — | your API key (required) |
| \`CALMA_API_URL\` | \`${ENGINE}\` | API base URL |

> Treat a key like a password. If one leaks, revoke it in the dashboard and create a new one.
`,
  },
  {
    slug: "api",
    title: "API reference",
    description: "The REST API: submit a verification, poll it, read the verdicts.",
    group: "Surfaces",
    markdown: `The engine is a small REST API at \`${ENGINE}\`. Authenticate every request with a bearer [API key](/docs/authentication). Verification is **async**: you submit a repo, get a job id, and poll it.

## Submit a verification

\`\`\`bash
curl ${ENGINE}/api/verify \\
  -H "Authorization: Bearer $CALMA_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"repo":"owner/repo","deep":true}'
\`\`\`

**Body fields**

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| \`repo\` | string | — | \`owner/name\` or a GitHub URL |
| \`deep\` | bool | \`false\` | re-run the code (vs a fast, no-run validity check) |
| \`entry\` | string | auto | entrypoint override, e.g. \`run.py\` |
| \`pip_install\` | string[] | auto | extra dependencies |
| \`artifact_repro\` | bool | \`false\` | also verify committed result files regenerate (see below) |

Returns \`{ "id": "…", "tier": "pro", "deep": true }\`.

## Poll a job

\`\`\`bash
curl ${ENGINE}/api/jobs/<id> -H "Authorization: Bearer $CALMA_API_KEY"
\`\`\`

The job carries \`status\` (\`queued\` → \`running\` → \`done\`/\`error\`), a live \`progress\` line, per-claim \`claims\` (each with a \`verdict\`), and \`counts\`. List your recent scans with \`GET /api/jobs\`; get the full run log as plain text with \`GET /api/jobs/<id>/logs\`.

## Endpoints

| Method | Path | Returns |
| --- | --- | --- |
| \`POST\` | \`/api/verify\` | submit a scan → \`{id}\` |
| \`GET\` | \`/api/jobs\` | your recent scans (newest first) |
| \`GET\` | \`/api/jobs/{id}\` | one scan: claims + verdicts + counts |
| \`GET\` | \`/api/jobs/{id}/logs\` | the full run log (plain text) |
| \`GET\` | \`/api/usage\` | your live meter (scans, budget, tier) |

## Artifact reproduction

For a "reproduce the paper" repo — one that ships a repro script + committed result files (\`leaderboard.csv\`, \`metrics.json\`) whose numbers come from custom code — set \`"artifact_repro": true\`. Calma re-runs the repro entrypoint and **diffs the regenerated result files against the committed ones**, reporting how many committed numbers reproduce identically (and naming any that don't). It reports \`reproduced\` / \`not-reproduced\` / \`incomplete\` — never a false "reproduced".
`,
  },
  {
    slug: "cli",
    title: "CLI",
    description: "Verify repos from your terminal or a CI gate. Zero dependencies.",
    group: "Surfaces",
    markdown: `The \`calma\` CLI is a zero-dependency (stdlib-only) client for the engine.

\`\`\`bash
pip install calma
export CALMA_API_KEY=calma_sk_...        # from ${DASH}/dashboard/keys
\`\`\`

## Commands

\`\`\`bash
calma verify owner/repo --deep     # re-run + recompute every number
calma scans                        # your recent scans
calma get <scan-id>                # one scan's verdict summary
calma logs <scan-id>               # the full run log
\`\`\`

## \`calma verify\` flags

| Flag | Meaning |
| --- | --- |
| \`--deep\` | re-run the repo (vs a fast, no-run validity check) |
| \`--entry <cmd>\` | entrypoint override, e.g. \`run.py\` (auto-detected otherwise) |
| \`--pip <pkg>\` | extra dependency (repeatable) |
| \`--artifact-repro\` | verify committed result files regenerate ("re-run the paper") |
| \`--no-wait\` | submit and return immediately |
| \`--json\` | print the raw job JSON |

## Use it as a CI gate

\`calma verify … --deep\` **exits non-zero if any number fails to reproduce** (REFUTED / INVALIDATED), so it drops straight into CI:

\`\`\`yaml
# .github/workflows/verify.yml
- run: pip install calma
- run: calma verify \${{ github.repository }} --deep
  env:
    CALMA_API_KEY: \${{ secrets.CALMA_API_KEY }}
\`\`\`

Drop \`--deep\` for a fast, no-run validity check (leakage / trivial baseline / misreport). For the no-execution PR check, see the [GitHub Action](/docs/github-action).
`,
  },
  {
    slug: "mcp",
    title: "MCP server",
    description: "Give an AI agent a deterministic verify tool.",
    group: "Surfaces",
    markdown: `The Calma MCP server exposes verification as a tool for AI agents (Claude, and any MCP client) — *AI proposes a number, determinism disposes*. It is **transport-only**: every tool shells out to the CLI and returns the engine's verdict verbatim, never computing a verdict itself.

\`\`\`bash
pip install "calma[mcp]"
export CALMA_API_KEY=calma_sk_...
python -m calma_mcp        # stdio
\`\`\`

## Client config

Add to your MCP client (e.g. Claude Desktop's \`claude_desktop_config.json\`):

\`\`\`json
{
  "mcpServers": {
    "calma": {
      "command": "python",
      "args": ["-m", "calma_mcp"],
      "env": {
        "CALMA_API_KEY": "calma_sk_...",
        "CALMA_API_URL": "${ENGINE}"
      }
    }
  }
}
\`\`\`

## Tools

| Tool | What it does |
| --- | --- |
| \`calma_verify\` | Re-run a repo and return a per-claim verdict (\`repo\`, \`deep\`, \`entry\`) |
| \`calma_scans\` | List your recent scans and their verdict counts |

The agent gets a verdict it cannot fake — the result is always the engine's deterministic recompute, never the agent's own claim.
`,
  },
  {
    slug: "github-action",
    title: "GitHub Action",
    description: "A fail-closed validity check on every pull request. Free, no run.",
    group: "CI & pull requests",
    markdown: `The Calma GitHub Action runs a **no-execution validity check** on every PR: it recomputes committed numbers and catches data leakage, trivial/degenerate baselines, and misreports — without building or running the repo. It's free and fail-closed.

Add \`.github/workflows/calma.yml\`:

\`\`\`yaml
name: Calma validity check
on: [pull_request]
jobs:
  calma:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: rikhinkavuru/calma@v1
        with:
          fail-on: fail       # fail | incomplete | never
          comment: true       # post a report-card comment on the PR
\`\`\`

## Inputs

| Input | Default | Meaning |
| --- | --- | --- |
| \`path\` | \`.\` | subdirectory to scan |
| \`fail-on\` | \`fail\` | fail the check on a validity problem (\`fail\`), also when nothing is checkable (\`incomplete\`), or never (\`never\`) |
| \`comment\` | \`true\` | post/update a report-card comment on the PR |

The action outputs \`grade\` (\`PASS\` / \`FAIL\` / \`INCOMPLETE\`). For a full re-run + recompute in CI (not just the no-run validity check), use the [CLI](/docs/cli) as a step instead.
`,
  },
  {
    slug: "pr-check",
    title: "PR check",
    description: "Connect the GitHub App for a report-card comment on every PR.",
    group: "CI & pull requests",
    markdown: `Connect the Calma GitHub App and every pull request gets a **report-card comment** — the verdict on each reported number plus the leakage / trivial-baseline / misreport checks — so a wrong number is caught before it merges.

## Connect

1. Open [**Dashboard → Verify a repo**](${DASH}/dashboard/verify) and connect the GitHub App to the repos you want checked.
2. Calma then comments on new PRs automatically. Private repos are supported on paid tiers.

The PR check is the connected, zero-config version of the [GitHub Action](/docs/github-action): same validity engine, but installed once via the App instead of a workflow file — and it can post richer, deep-verify results on the repos you connect.

## What you get

- A verdict per reported number (CONFIRMED / REFUTED / INVALIDATED / …).
- The leakage, trivial-baseline, and misreport checks, graded.
- A link into the [dashboard](${DASH}/dashboard) for the full run log and receipts.
`,
  },
];

export function docBySlug(slug: string): DocPage | undefined {
  return DOCS.find((d) => d.slug === slug);
}

// Group → pages, in declaration order — drives the sidebar.
export function docsByGroup(): { group: string; pages: DocPage[] }[] {
  return GROUPS.map((group) => ({ group, pages: DOCS.filter((d) => d.group === group) }));
}

// ## headings → the right-rail "On this page" anchors.
export function headings(markdown: string): { id: string; text: string }[] {
  const out: { id: string; text: string }[] = [];
  for (const line of markdown.split("\n")) {
    const m = /^##\s+(.+?)\s*$/.exec(line);
    if (m) out.push({ id: slugify(m[1]), text: m[1] });
  }
  return out;
}

export function slugify(s: string): string {
  return s.toLowerCase().replace(/[^\w]+/g, "-").replace(/(^-|-$)/g, "");
}
