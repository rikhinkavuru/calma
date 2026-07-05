"use client";

// API keys: create / list / revoke the credentials the `calma` CLI, a CI step, or the MCP server use to call
// the verification API directly (as your tenant + tier). The plaintext is shown ONCE at creation — the
// backend only stores a hash — so we surface it in a copy-once banner and never again.
import { useEffect, useState } from "react";
import { FiPlus, FiKey, FiCopy, FiCheck, FiTrash2, FiAlertTriangle } from "react-icons/fi";
import type { ApiKey, NewApiKey } from "@/lib/verify";
import { timeAgo } from "./scan-ui";
import dash from "./dashboard.module.css";

const ENGINE = "https://calma-engine.fly.dev";

export function ApiKeysClient() {
  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [fresh, setFresh] = useState<NewApiKey | null>(null);   // the just-minted plaintext (show once)
  const [copied, setCopied] = useState(false);

  const load = async () => {
    try {
      const r = await fetch("/api/keys", { cache: "no-store" });
      if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.error || `status ${r.status}`);
      const d = await r.json();
      setKeys(Array.isArray(d?.keys) ? d.keys : []);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setKeys([]);
    }
  };
  useEffect(() => { load(); }, []);

  const create = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch("/api/keys", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d?.error || `status ${r.status}`);
      setFresh(d as NewApiKey);
      setName("");
      setCopied(false);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (id: string) => {
    setErr(null);
    try {
      const r = await fetch(`/api/keys/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.error || `status ${r.status}`);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const copy = (text: string) => {
    navigator.clipboard?.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1800); });
  };

  return (
    <div className={dash.main}>
      <div className={dash.row}>
        <div>
          <h1 className={dash.h1}>API keys</h1>
          <p className={dash.sub}>Keys let the <code>calma</code> CLI, a CI step, or the MCP server verify repos
            from the command line — authenticated as your account, metered against your plan. Keep them secret;
            treat a key like a password.</p>
        </div>
      </div>

      {fresh && (
        <div className={`${dash.card}`} style={{ borderLeft: "3px solid var(--amber, #d98a00)", marginBottom: 18 }}>
          <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
            <FiAlertTriangle style={{ marginTop: 3, flexShrink: 0 }} />
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>Copy your new key now — it won&apos;t be shown again.</div>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <code className={dash.idMono} style={{ wordBreak: "break-all", flex: 1, minWidth: 220 }}>{fresh.key}</code>
                <button className={dash.btn} onClick={() => copy(fresh.key)}>
                  {copied ? <><FiCheck /> Copied</> : <><FiCopy /> Copy</>}
                </button>
                <button className={dash.btn} onClick={() => setFresh(null)}>Done</button>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className={dash.card}>
        <div className={dash.cardHead}>
          <span className={dash.cardHeadTitle}>Create a key</span>
        </div>
        <div style={{ display: "flex", gap: 8, padding: "4px 2px", flexWrap: "wrap" }}>
          <input
            className={dash.input}
            placeholder="Label (e.g. laptop CLI, CI)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={80}
            style={{ flex: 1, minWidth: 200 }}
          />
          <button className={`${dash.btn} ${dash.btnAmber}`} onClick={create} disabled={busy}>
            <FiPlus /> {busy ? "Creating…" : "Create key"}
          </button>
        </div>
      </div>

      <section className={dash.section}>
        <div className={dash.sectionTitle} style={{ marginBottom: 10 }}>Your keys</div>
        {keys === null ? (
          <div className={dash.card}><p className={dash.muted}>Loading…</p></div>
        ) : keys.length === 0 ? (
          <div className={`${dash.card} ${dash.empty}`}>
            <FiKey style={{ fontSize: 22, opacity: 0.5 }} />
            <h3>No keys yet</h3>
            <p>Create one above to use Calma from the CLI, CI, or an MCP client.</p>
            {err && <p className={dash.muted} style={{ marginTop: 12, fontSize: 12 }}>({err})</p>}
          </div>
        ) : (
          <div className={dash.card}>
            <table className={dash.table}>
              <thead>
                <tr><th>Label</th><th>Key</th><th>Plan</th><th>Created</th><th>Last used</th><th /></tr>
              </thead>
              <tbody>
                {keys.map((k) => (
                  <tr key={k.id}>
                    <td><b>{k.name || "—"}</b></td>
                    <td><code className={dash.idMono}>{k.display}</code></td>
                    <td className={dash.muted}>{k.tier}</td>
                    <td className={dash.muted}>{timeAgo(k.created)}</td>
                    <td className={dash.muted}>{k.last_used ? timeAgo(k.last_used) : "never"}</td>
                    <td style={{ textAlign: "right" }}>
                      <button className={dash.btn} onClick={() => revoke(k.id)} title="Revoke this key">
                        <FiTrash2 /> Revoke
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className={dash.section}>
        <div className={dash.sectionTitle} style={{ marginBottom: 10 }}>Using your key</div>
        <div className={dash.card}>
          <p className={dash.muted} style={{ marginTop: 0 }}>Set the key as an environment variable, then use the
            CLI or call the API directly. The API base is <code>{ENGINE}</code>.</p>
          <pre className={dash.codeblock} style={{ overflowX: "auto" }}>{`# CLI
pip install calma
export CALMA_API_KEY=calma_sk_...
calma verify owner/repo --deep

# or call the API directly
curl -s ${ENGINE}/api/verify \\
  -H "Authorization: Bearer $CALMA_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"repo":"owner/repo","deep":true}'`}</pre>
        </div>
      </section>
    </div>
  );
}
