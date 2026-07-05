"use client";

// One scan, in full: the three-way verdict on every number, grouped counts, the data-leakage check, and the
// complete run log. Polls the same authed job endpoint the live verify page uses, so an in-flight scan opened
// from the Scans list keeps updating until it finishes. Read-only — it renders verdicts the engine decided.
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { FiArrowLeft, FiRefreshCw } from "react-icons/fi";
import type { Claim, Job } from "@/lib/verify";
import { ISSUE_TIERS, ORDER, TIER_META, pillTier, tierCounts, verdictLabel, type PillTier } from "@/lib/verdict";
import { LogConsole } from "./LogConsole";
import { repoLabel } from "./scan-ui";
import ValidityCard from "@/components/ValidityCard";
import dash from "./dashboard.module.css";
import s from "./verify.module.css";

function num(x: unknown): string {
  return typeof x === "number" && Number.isFinite(x) ? Number(x).toPrecision(5) : "—";
}

export function ScanDetailClient({ id }: { id: string }) {
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [visibleTiers, setVisibleTiers] = useState<Set<PillTier>>(new Set(ISSUE_TIERS));
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const poll = useCallback(async (jid: string) => {
    try {
      const res = await fetch(`/api/verify/${jid}`, { cache: "no-store" });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.error || `status ${res.status}`);
      setJob(data as Job);
      if (data.status === "done" || data.status === "error") return;
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      return;
    }
    timer.current = setTimeout(() => poll(jid), 1500);
  }, []);

  useEffect(() => {
    poll(id);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [id, poll]);

  if (err) {
    return (
      <div className={dash.main}>
        <Link href="/dashboard/scans" className={dash.back}><FiArrowLeft /> Scans</Link>
        <div className={`${dash.notice} ${dash.noticeErr}`} style={{ marginTop: 18 }}>
          Couldn&apos;t load this scan — {err}. It may have expired (scan history is kept for a limited window).
        </div>
      </div>
    );
  }

  if (!job) {
    return (
      <div className={dash.main}>
        <Link href="/dashboard/scans" className={dash.back}><FiArrowLeft /> Scans</Link>
        <div className={`${dash.skel} ${dash.skelTitle}`} style={{ marginTop: 18 }} />
        <div className={`${dash.skel} ${dash.skelSub}`} />
        <div className={`${dash.skel} ${dash.skelPanel}`} style={{ marginTop: 22 }} />
      </div>
    );
  }

  const t = tierCounts(job.counts || {});
  const issues = t.bad + t.inv + t.neu;
  const ran = job.run?.ran;
  const running = job.status === "running" || job.status === "queued";
  const failed = job.status === "error" || (job.run && !ran);

  // headline tone for the hero
  const tone: "ok" | "bad" | "idle" =
    failed ? "idle" : issues > 0 ? "bad" : t.ok > 0 ? "ok" : "idle";
  const heroClass =
    tone === "ok" ? dash.verdictHeroOk : tone === "bad" ? dash.verdictHeroBad : dash.verdictHeroIdle;
  const glyph = tone === "ok" ? "✓" : tone === "bad" ? "!" : "·";
  const glyphStyle =
    tone === "ok" ? { background: "var(--ok-bg)", color: "var(--ok-fg)" }
      : tone === "bad" ? { background: "var(--bad-bg)", color: "var(--bad-fg)" }
        : { background: "var(--idle-bg)", color: "var(--idle-fg)" };
  const headline =
    running ? "Verifying…"
      : job.status === "error" ? "Scan failed"
        : issues > 0 ? `${issues} number${issues === 1 ? "" : "s"} need review`
          : t.ok > 0 ? `All ${t.ok} confirmed`
            : ran ? "Reproduced — nothing to confirm" : "No numbers verified";

  function toggleTier(tier: PillTier) {
    setVisibleTiers((prev) => {
      const next = new Set(prev);
      if (next.has(tier)) next.delete(tier); else next.add(tier);
      return next;
    });
  }

  const claims: Claim[] = (job.claims || [])
    .filter((c) => visibleTiers.has(pillTier(c.verdict)))
    .slice()
    .sort((a, b) => ORDER.indexOf(a.verdict) - ORDER.indexOf(b.verdict))
    .slice(0, 300);
  const leak = job.leakage || [];

  return (
    <div className={dash.main}>
      <div className={dash.row} style={{ marginBottom: 0 }}>
        <Link href="/dashboard/scans" className={dash.back}><FiArrowLeft /> Scans</Link>
        <Link href={`/dashboard/verify?repo=${encodeURIComponent(job.repo)}`} className={`${dash.btn} ${dash.btnGhost}`}>
          <FiRefreshCw /> Re-run
        </Link>
      </div>

      <div className={`${dash.verdictHero} ${heroClass}`}>
        <div className={dash.verdictGlyph} style={glyphStyle}>{glyph}</div>
        <div className={dash.verdictMeta}>
          <div className={dash.idMono}>{repoLabel(job.repo)}</div>
          <h1 className={dash.verdictTitle}>{headline}</h1>
          <p className={dash.verdictGloss}>
            {running ? `${job.progress?.trim() || job.stage}…`
              : ran ? <>Re-ran <code>{job.run?.entry}</code> and recomputed {job.run?.calls} computation(s) from the raw outputs.</>
                : job.run?.failure?.hint ? job.run.failure.hint
                  : "The entrypoint didn't produce a usable result — showing the numbers Calma found."}
          </p>
        </div>
      </div>

      {!running && (
        <div className={dash.detailGrid}>
          <Kv label="Confirmed" value={t.ok} />
          <Kv label="To review" value={issues} />
          <Kv label="Unverified" value={t.warn} />
          <Kv label="Discovered" value={t.idle} />
        </div>
      )}

      {leak.length > 0 && (
        <div className={`${s.banner} ${s.bannerBad}`}>
          <b>⚠ Data leakage — {leak.length} dataset(s) contaminated.</b> A leaked train/test split makes the
          held-out numbers invalid, even when they recompute perfectly.
          {leak.map((d) => (
            <div key={d.dataset} style={{ marginTop: 6 }}>
              <b>{d.dataset}</b>{" "}
              {d.findings.map((f, i) => (
                <span key={i} className={`${s.pill} ${s.bad}`} style={{ marginRight: 6 }}>
                  {f.kind} {Math.round(100 * f.magnitude)}%
                </span>
              ))}
            </div>
          ))}
        </div>
      )}

      {(running || (job.logs?.length ?? 0) > 0) && (
        <div className={dash.section}>
          <div className={dash.sectionTitle}>Run log</div>
          <LogConsole job={job} />
        </div>
      )}

      {job.status === "done" && job.validity_card && (
        <div className={dash.section} style={{ marginTop: 4 }}>
          <ValidityCard card={job.validity_card} />
        </div>
      )}

      {job.status === "done" && job.n_claims > 0 && (
        <div className={dash.section}>
          <div className={dash.sectionTitle}>Claims ({job.n_claims})</div>
          <div className={s.filters}>
            {TIER_META.map(({ tier, label }) => {
              const n = t[tier];
              const on = visibleTiers.has(tier);
              return (
                <button key={tier} type="button" className={`${s.filter} ${on ? s.filterOn : ""}`}
                  onClick={() => toggleTier(tier)} disabled={n === 0}>
                  <span className={`${s.pill} ${s[tier]}`} style={{ marginRight: 6 }}>{n}</span>{label}
                </button>
              );
            })}
            {visibleTiers.size < TIER_META.length && (
              <button type="button" className={s.filter} onClick={() => setVisibleTiers(new Set(TIER_META.map((m) => m.tier)))}>
                show all ({job.n_claims})
              </button>
            )}
          </div>
          {claims.length === 0 ? (
            <p className={dash.muted}>Nothing in the selected tiers — click one above to show its rows.</p>
          ) : (
            <div className={dash.card}>
              <table className={s.table}>
                <thead>
                  <tr><th>Metric</th><th>Claimed</th><th>Recomputed</th><th>Verdict</th><th>Where</th><th>Why</th></tr>
                </thead>
                <tbody>
                  {claims.map((c) => {
                    const d = c.diff || {};
                    const recomp = d.recomputed != null ? num(d.recomputed) : num(d.produced);
                    const adv = c.validity?.advisory || [];
                    return (
                      <tr key={c.id}>
                        <td><b>{c.metric}</b></td>
                        <td className={s.mono}>{c.claimed}</td>
                        <td className={s.mono}>{recomp}</td>
                        <td><span className={`${s.pill} ${s[pillTier(c.verdict)]}`}>{verdictLabel(c.verdict)}</span></td>
                        <td className={s.where}>{(c.context || c.location || c.source || "").slice(0, 90)}</td>
                        <td className={s.why}>
                          {c.reason}
                          {adv.length > 0 && <div className={s.adv}>⚠ validity: {adv.join("; ")}</div>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {job.status === "done" && job.n_claims === 0 && (
        <p className={dash.muted}>No reported numbers found in this repo.</p>
      )}
    </div>
  );
}

function Kv({ label, value }: { label: string; value: number }) {
  return (
    <div className={dash.kv}>
      <div className={dash.kvLabel}>{label}</div>
      <div className={dash.kvValue}>{value}</div>
    </div>
  );
}
