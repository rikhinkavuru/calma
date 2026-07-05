"use client";

// Integrations: every surface Calma runs on besides this dashboard — the CLI, the GitHub Action (validity
// check on a PR), the PR-comment connector, and the MCP server for AI agents. Mostly docs + copyable
// snippets; the API-key page is where you mint the credential the CLI/MCP use.
import { useState } from "react";
import Link from "next/link";
import { FiTerminal, FiGithub, FiGitPullRequest, FiCpu, FiCopy, FiCheck, FiArrowRight } from "react-icons/fi";
import { GITHUB_URL } from "../../components/contact";
import dash from "./dashboard.module.css";

const ENGINE = "https://calma-engine.fly.dev";

function Snippet({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div style={{ position: "relative" }}>
      <button
        className={dash.btn}
        style={{ position: "absolute", top: 8, right: 8, padding: "4px 10px", fontSize: 11 }}
        onClick={() => navigator.clipboard?.writeText(code).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1600); })}
      >
        {copied ? <><FiCheck /> Copied</> : <><FiCopy /> Copy</>}
      </button>
      <pre className={dash.codeblock} style={{ overflowX: "auto", paddingRight: 92 }}>{code}</pre>
    </div>
  );
}

function Card({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <section className={dash.section}>
      <div className={dash.sectionTitle} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        {icon} {title}
      </div>
      <div className={dash.card}>{children}</div>
    </section>
  );
}

export function IntegrationsClient() {
  return (
    <div className={dash.main}>
      <div className={dash.row}>
        <div>
          <h1 className={dash.h1}>Integrations</h1>
          <p className={dash.sub}>Run the same recompute-and-diff verification from the command line, in CI, on a
            pull request, or from an AI agent. The CLI and MCP authenticate with an{" "}
            <Link href="/dashboard/keys" className={dash.rowlink}>API key</Link>.</p>
        </div>
      </div>

      <Card icon={<FiTerminal />} title="CLI">
        <p className={dash.muted} style={{ marginTop: 0 }}>Verify a repo from your terminal — same engine as the
          dashboard, authenticated with your API key.</p>
        <Snippet code={`pip install calma
export CALMA_API_KEY=calma_sk_...        # create one under API keys

calma verify owner/repo --deep           # re-run + recompute every number
calma scans                              # your recent scans
calma logs <scan-id>                     # the full run log`} />
      </Card>

      <Card icon={<FiGithub />} title="GitHub Action — validity check">
        <p className={dash.muted} style={{ marginTop: 0 }}>A fail-closed validity check on every PR: leakage,
          trivial/degenerate baselines, and misreported numbers — recomputed from the raw outputs, no run
          required. Free. Add <code>.github/workflows/calma.yml</code>:</p>
        <Snippet code={`name: Calma validity check
on: [pull_request]
jobs:
  calma:
    runs-on: ubuntu-latest
    permissions: { contents: read, pull-requests: write }
    steps:
      - uses: actions/checkout@v4
      - uses: rikhinkavuru/calma@v1
        with:
          fail-on: fail       # fail | incomplete | never
          comment: true       # post a report-card comment on the PR`} />
      </Card>

      <Card icon={<FiGitPullRequest />} title="Pull-request check (GitHub App)">
        <p className={dash.muted} style={{ marginTop: 0 }}>Connect the GitHub App and Calma posts a report-card
          comment on each PR — the verdict on every reported number, plus the leakage / baseline checks — so a
          wrong number is caught before it merges.</p>
        <div style={{ marginTop: 12 }}>
          <Link href="/dashboard/verify" className={`${dash.btn} ${dash.btnAmber}`}>
            Connect a repo <FiArrowRight />
          </Link>
        </div>
      </Card>

      <Card icon={<FiCpu />} title="MCP server (AI agents)">
        <p className={dash.muted} style={{ marginTop: 0 }}>Give an AI agent (Claude, etc.) a{" "}
          <code>verify</code> tool that recomputes a repo&apos;s numbers. Add to your MCP client config:</p>
        <Snippet code={`{
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
}`} />
      </Card>

      <p className={dash.muted} style={{ fontSize: 12, marginTop: 8 }}>
        Full docs on <a href={GITHUB_URL} target="_blank" rel="noreferrer" className={dash.rowlink}>GitHub</a>.
      </p>
    </div>
  );
}
