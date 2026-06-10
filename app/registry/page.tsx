import type { Metadata } from "next";
import fs from "node:fs";
import path from "node:path";

export const metadata: Metadata = {
  title: "The registry — Calma catch history",
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
      <header className="nav nav--bg">
        <div className="wrap">
          <a className="nav__brand" href="/">
            CALMA
          </a>
          <nav className="nav__links">
            <a href="/lab">The lab</a>
            <a href="/recipes">Recipes</a>
            <a className="nav__cta" href="/" style={{ display: "inline-block" }}>
              ← Back to Calma
            </a>
          </nav>
        </div>
      </header>

      <main className="rpage">
        <section className="sec rpage__head">
          <div className="wrap">
            <div className="sec__head">
              <span className="kicker">The registry — catch history</span>
              <h2 className="h2">Every engagement, on the record. Including the misses.</h2>
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
                        <span className={verdictClass(w.entry.verdict)}>{w.entry.verdict}</span>
                      </div>
                      {(w.entry.claim || w.entry.note) && (
                        <p className="reg__claim">{w.entry.claim ?? w.entry.note}</p>
                      )}
                      {w.entry.recomputed !== undefined && (
                        <p className="reg__gap mono">
                          claimed {String(w.entry.claimed)} → recomputed{" "}
                          {String(w.entry.recomputed)}
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
              SSHSIG. Sigstore-countersigned verdicts are additionally witnessed by the public
              Rekor transparency log. v2 adds a Merkle tree per the C2SP tlog-tiles spec —
              additive, the entries are already hash-addressed.
            </p>
          </div>
        </section>
      </main>
    </>
  );
}
