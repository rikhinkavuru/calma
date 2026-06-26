// WS5 — the shareable proof permalink page (the npm-package-page analog for a verification). Renders
// from query params so a `calma seal` / dashboard link is self-contained and public (no auth): the
// claim, the recomputed value, the diff, the verdict + the data-authenticity ceiling, the signing key,
// and a "Re-verify offline" panel a skeptic runs without trusting Calma's servers.
import type { Metadata } from "next";

export const dynamic = "force-static";

type SP = Record<string, string | string[] | undefined>;

const GLYPH: Record<string, string> = { Confirmed: "✓", Caught: "✗", "Can't tell": "?" };
const COLOR: Record<string, string> = {
  Confirmed: "#3fb56b",
  Caught: "#e0564f",
  "Can't tell": "#9aa0a8",
  Pending: "#9aa0a8",
};

function one(v: string | string[] | undefined): string | undefined {
  return Array.isArray(v) ? v[0] : v;
}

export async function generateMetadata({
  searchParams,
}: {
  searchParams: Promise<SP>;
}): Promise<Metadata> {
  const sp = await searchParams;
  const outcome = one(sp.outcome) || one(sp.verdict) || "Pending";
  const metric = one(sp.metric) || "a result";
  return {
    title: `${outcome}: ${metric} — verified by Calma`,
    description: "An offline-re-verifiable proof: Calma re-executed the work and recomputed the number.",
  };
}

export default async function ProofPage({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const outcome = one(sp.outcome) || one(sp.verdict) || "Pending";
  const metric = one(sp.metric) || "";
  const claimed = one(sp.claimed);
  const recomputed = one(sp.recomputed);
  const delta = one(sp.delta);
  const keyid = one(sp.keyid);
  const color = COLOR[outcome] || COLOR.Pending;
  const glyph = GLYPH[outcome] || "·";

  const label = (metric + (recomputed ? ` ${recomputed}` : "")).trim() || outcome;
  const badgeUrl = `/badge?outcome=${encodeURIComponent(outcome)}&label=${encodeURIComponent(label)}`;
  const badgeMd = `![verified by calma](https://trycalma.ai${badgeUrl})`;

  const mono = "ui-monospace, SFMono-Regular, Menlo, monospace";
  const card: React.CSSProperties = {
    background: "rgba(255,255,255,0.03)",
    border: "1px solid rgba(255,255,255,0.10)",
    borderRadius: 12,
    padding: "20px 22px",
    margin: "14px 0",
  };

  return (
    <main
      style={{
        maxWidth: 720,
        margin: "0 auto",
        padding: "56px 24px 80px",
        color: "var(--paper, #ece7df)",
        fontFamily: "Archivo, system-ui, sans-serif",
      }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={badgeUrl} alt={`verified by calma: ${outcome}`} height={28} style={{ display: "block" }} />

      <h1 style={{ fontSize: 30, margin: "22px 0 4px", letterSpacing: -0.5 }}>
        <span style={{ color, fontFamily: mono }}>{glyph}</span>{" "}
        <span style={{ color }}>{outcome}</span>{" "}
        {metric && <span style={{ color: "var(--paper)" }}>{metric}</span>}{" "}
        {recomputed && <span style={{ fontFamily: mono }}>{recomputed}</span>}
      </h1>
      <p style={{ color: "rgba(236,231,223,0.55)", margin: "0 0 8px", fontSize: 14 }}>
        Calma re-executed the work in a network-off sandbox and recomputed the headline number from the
        raw output files — never the reported number.
      </p>

      <div style={card}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          <Field k="claimed" v={claimed ?? "— (reproduction)"} mono={mono} />
          <Field k="recomputed" v={recomputed ?? "—"} mono={mono} />
          {delta && <Field k="Δ (recomputed − claimed)" v={delta} mono={mono} />}
          {metric && <Field k="metric" v={metric} mono={mono} />}
        </div>
      </div>

      <div style={card}>
        <Label>data-authenticity ceiling</Label>
        <p style={{ margin: "6px 0 0", fontSize: 14, lineHeight: 1.5 }}>
          This proof attests that the <em>recompute</em> matches (or breaks) the claim. It does{" "}
          <strong>not</strong> attest that the upstream input data is authentic/untampered, or that the
          result is semantically correct. The verdict comes from deterministic scripts, not a model.
        </p>
      </div>

      <div style={card}>
        <Label>re-verify offline</Label>
        <p style={{ margin: "6px 0 10px", fontSize: 14, color: "rgba(236,231,223,0.6)" }}>
          A counterparty re-checks this without trusting Calma&apos;s servers — zero network:
        </p>
        <pre style={preStyle(mono)}>calma proof verify proof.json</pre>
        {keyid && (
          <p style={{ margin: "10px 0 0", fontSize: 13, color: "rgba(236,231,223,0.55)" }}>
            signed by <span style={{ fontFamily: mono }}>{keyid.slice(0, 24)}…</span> (DSSE + SSHSIG;
            also checkable with stock <code>ssh-keygen -Y verify</code>)
          </p>
        )}
      </div>

      <div style={card}>
        <Label>embed this badge</Label>
        <pre style={preStyle(mono)}>{badgeMd}</pre>
      </div>

      <p style={{ marginTop: 28, fontSize: 13, color: "rgba(236,231,223,0.4)" }}>
        <a href="/" style={{ color: "var(--amber, #eec88c)" }}>
          trycalma.ai
        </a>{" "}
        — catch your own wrong number before it ships.
      </p>
    </main>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 11,
        textTransform: "uppercase",
        letterSpacing: 1.5,
        color: "rgba(236,231,223,0.45)",
      }}
    >
      {children}
    </div>
  );
}

function Field({ k, v, mono }: { k: string; v: string; mono: string }) {
  return (
    <div>
      <Label>{k}</Label>
      <div style={{ fontFamily: mono, fontSize: 18, marginTop: 4 }}>{v}</div>
    </div>
  );
}

function preStyle(mono: string): React.CSSProperties {
  return {
    background: "rgba(0,0,0,0.35)",
    border: "1px solid rgba(255,255,255,0.08)",
    borderRadius: 8,
    padding: "12px 14px",
    fontFamily: mono,
    fontSize: 13,
    overflowX: "auto",
    margin: 0,
    whiteSpace: "pre-wrap",
    wordBreak: "break-all",
  };
}
