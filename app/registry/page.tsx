import type { Metadata } from "next";
import fs from "node:fs";
import path from "node:path";
import { SubNav } from "../../components/chrome";
import { GITHUB_URL } from "../../components/contact";

export const metadata: Metadata = {
  title: "The registry — catch history",
  description:
    "An append-only, hash-chained, signed public log of verification outcomes — including " +
    "engagements that were withdrawn or refuted. Clinical-trial style: a missing outcome is " +
    "itself visible.",
};

type RegistryEntry = {
  schema: string;
  seq: number;
  prev: string | null;
  kind: "verification" | "engagement-opened" | "engagement-outcome";
  date: string;
  target?: string;
  claim?: string;
  metric?: string;
  claimed?: number;
  recomputed?: number;
  verdict: string;
  engagement?: string;
  note?: string;
  manifest_sha256?: string;
  ledger_sha256?: string;
  keyid?: string;
};

type Wrapper = { entry: RegistryEntry; id: string };

function loadRegistry(): { entries: Wrapper[]; headId: string | null } {
  const dir = path.join(process.cwd(), "registry", "entries");
  let entries: Wrapper[] = [];
  try {
    entries = fs
      .readdirSync(dir)
      .filter((n) => n.endsWith(".json"))
      .sort()
      .map((n) => JSON.parse(fs.readFileSync(path.join(dir, n), "utf8")) as Wrapper);
  } catch {
    entries = [];
  }
  let headId: string | null = null;
  try {
    headId = JSON.parse(
      fs.readFileSync(path.join(process.cwd(), "registry", "HEAD.json"), "utf8"),
    ).id;
  } catch {
    headId = null;
  }
  return { entries, headId };
}

/* Render raw registry floats for humans: 4 significant figures, and for
   ratio-style return metrics a percent reading alongside. */
function fmtNum(v: number | undefined): string {
  if (v === undefined || !Number.isFinite(v)) return String(v);
  const abs = Math.abs(v);
  if (abs !== 0 && (abs >= 1e6 || abs < 1e-4)) return v.toExponential(3);
  return String(Number(v.toPrecision(4)));
}

const PERCENT_METRICS = /(_return|^return|cagr|drawdown|growth)/;

function fmtMetricValue(metric: string | undefined, v: number | undefined): string {
  const base = fmtNum(v);
  if (v === undefined || !Number.isFinite(v) || !metric || !PERCENT_METRICS.test(metric)) return base;
  const pct = v * 100;
  const sign = pct > 0 ? "+" : "";
  return `${base} (${sign}${pct.toLocaleString("en-US", { maximumFractionDigits: 1 })}%)`;
}

function verdictClass(v: string): string {
  if (v === "REFUTED" || v === "MIXED") return "reg__verdict reg__verdict--refuted";
  if (v === "CONFIRMED" || v === "CONFIRMED-WITH-CAVEATS")
    return "reg__verdict reg__verdict--confirmed";
  if (v === "PENDING") return "reg__verdict reg__verdict--pending";
  return "reg__verdict";
}

function kindLabel(k: RegistryEntry["kind"]): string {
  if (k === "engagement-opened") return "engagement opened";
  if (k === "engagement-outcome") return "engagement outcome";
  return "verification";
}

export default function RegistryPage() {
  const { entries, headId } = loadRegistry();
  const opened = new Set(
    entries
      .filter((w) => w.entry.kind === "engagement-opened")
      .map((w) => w.entry.engagement),
  );
  const closed = new Set(
    entries
      .filter((w) => w.entry.kind === "engagement-outcome")
      .map((w) => w.entry.engagement),
  );
  const stillOpen = [...opened].filter((e) => e && !closed.has(e));

  return (
    <>
      <div className="grain" aria-hidden="true"></div>
      <SubNav
        links={[
          { href: "/", label: "Home" },
          { href: "/lab", label: "The lab" },
          { href: "/recipes", label: "Recipes" },
        ]}
        ctaHref="/lab"
        ctaLabel="Request verification"
      />

      <main className="rpage">
        <section className="sec rpage__head">
          <div className="wrap">
            <div className="sec__head">
              <span className="kicker">The registry — catch history</span>
              <h1 className="h2">Every engagement, on the record. Including the misses.</h1>
              <p className="lead">
                An append-only, hash-chained log of verification outcomes, clinical-trial style:
                an engagement is logged when it <b>opens</b>, so a missing outcome is itself
                visible. Entries are <b>redacted by construction</b> — claim, metric, claimed vs
                recomputed, verdict, and content hashes; never code, never data. Each entry
                embeds the SHA-256 of the previous one and is signed with the lab key; the chain
                audits offline with one command, or any single entry with stock OpenSSH.
              </p>
              <p className="rpage__legend micro mono">
                audit: python3 scripts/calma.py registry verify registry/
              </p>
              <p className="rpage__verify">
                Don&apos;t take this page&apos;s word for it:{" "}
                <a href={`${GITHUB_URL}/tree/main/registry`} target="_blank" rel="noreferrer">
                  the raw entries
                </a>
                ,{" "}
                <a href={`${GITHUB_URL}/blob/main/registry/README.md`} target="_blank" rel="noreferrer">
                  the lab&apos;s public key
                </a>
                , and the audit command above let anyone re-verify the whole chain offline — or any
                single entry with stock <span className="mono">ssh-keygen</span>.
              </p>
            </div>
          </div>
        </section>

        <section className="sec rfam">
          <div className="wrap">
            <div className="rfam__head">
              <span className="kicker">The chain</span>
              <span className="rfam__count mono">
                {entries.length} entr{entries.length === 1 ? "y" : "ies"}
                {headId ? ` · head ${headId.slice(0, 12)}` : ""}
              </span>
            </div>
            {stillOpen.length > 0 && (
              <p className="rfam__blurb">
                Open engagements awaiting an outcome:{" "}
                <span className="mono">{stillOpen.join(", ")}</span>
              </p>
            )}

            {entries.length > 0 && opened.size === 0 && (
              <p className="rfam__blurb">
                No client engagements have been logged yet — the chain below opens with the
                lab&apos;s own demonstration catch. From the first engagement on, every outcome —
                confirmed, refuted, withdrawn — appends here permanently. A registry that only
                showed wins would be worthless; this one can&apos;t.
              </p>
            )}

            {entries.length === 0 ? (
              <div className="reg__empty">
                <p>
                  The chain opens with the first engagement. From then on, every outcome —
                  confirmed, refuted, withdrawn — appends here permanently. A registry that only
                  showed wins would be worthless; this one can&apos;t.
                </p>
              </div>
            ) : (
              <div className="reg">
                {entries
                  .slice()
                  .reverse()
                  .map((w) => (
                    <article className="reg__row" key={w.id}>
                      <div className="reg__line1">
                        <span className="reg__seq mono">
                          #{String(w.entry.seq).padStart(5, "0")}
                        </span>
                        <span className="reg__date mono">{w.entry.date}</span>
                        <span className="reg__kind mono">{kindLabel(w.entry.kind)}</span>
                        {w.entry.engagement && (
                          <span className="reg__eng mono">{w.entry.engagement}</span>
                        )}
                        {w.entry.seq === 1 && (
                          <span className="reg__badge mono">self-test · demonstration</span>
                        )}
                        <span className={verdictClass(w.entry.verdict)}>{w.entry.verdict}</span>
                      </div>
                      {(w.entry.claim || w.entry.note) && (
                        <p className="reg__claim">{w.entry.claim ?? w.entry.note}</p>
                      )}
                      {w.entry.recomputed !== undefined && (
                        <p className="reg__gap mono">
                          claimed {fmtMetricValue(w.entry.metric, w.entry.claimed)} → recomputed{" "}
                          {fmtMetricValue(w.entry.metric, w.entry.recomputed)}
                        </p>
                      )}
                      <p className="reg__hash mono">
                        {w.id.slice(0, 16)}
                        {w.entry.prev ? ` ← ${w.entry.prev.slice(0, 16)}` : " · genesis"}
                      </p>
                    </article>
                  ))}
              </div>
            )}
          </div>
        </section>

        <section className="sec rpage__foot">
          <div className="wrap">
            <p className="micro">
              Entry format: in-toto/DSSE attestation bundle → redacted whitelist → hash chain →
              SSHSIG. Verdicts can additionally be Sigstore-countersigned and witnessed by the
              public Rekor transparency log, offered per engagement. v2 adds a Merkle tree per
              the C2SP tlog-tiles spec — additive, the entries are already hash-addressed.
            </p>
            <p className="rpage__verify">
              Questions about an entry, or a number you need verified?{" "}
              <a href="/lab">How the lab works</a>
            </p>
          </div>
        </section>
      </main>
    </>
  );
}
