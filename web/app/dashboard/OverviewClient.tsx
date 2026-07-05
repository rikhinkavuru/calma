"use client";

// The console home: a quick read on the account's verification activity — how many scans, how many numbers
// confirmed, how many need a look — plus the most recent scans and a prominent way to start a new one. All
// derived from the tenant's own job list (/api/jobs); no verdict is computed here.
import Link from "next/link";
import { FiPlus, FiArrowRight, FiCheckCircle, FiAlertTriangle, FiActivity } from "react-icons/fi";
import { tierCounts } from "@/lib/verdict";
import { useJobs } from "@/lib/useJobs";
import { StatusPill, RunProgress, VerdictSummary, repoLabel, timeAgo } from "./scan-ui";
import dash from "./dashboard.module.css";

export function OverviewClient() {
  const { jobs, err } = useJobs();

  // aggregate the tenant's verdicts across all scans
  let confirmed = 0, toReview = 0, running = 0;
  for (const j of jobs || []) {
    const t = tierCounts(j.counts || {});
    confirmed += t.ok;
    toReview += t.bad + t.inv + t.neu;
    if (j.status === "running" || j.status === "queued") running += 1;
  }
  const recent = (jobs || []).slice(0, 6);

  return (
    <div className={dash.main}>
      <div className={dash.row}>
        <div>
          <h1 className={dash.h1}>Overview</h1>
          <p className={dash.sub}>Connect a repo and Calma re-runs it, recomputes every number it reports, and
            tells you which hold up. Here&apos;s what you&apos;ve verified so far.</p>
        </div>
        <Link href="/dashboard/verify" className={`${dash.btn} ${dash.btnAmber}`}>
          <FiPlus /> New scan
        </Link>
      </div>

      {jobs === null ? (
        <StatSkeleton />
      ) : (
        <div className={dash.statCards}>
          <StatCard icon={<FiActivity />} label="Total scans" value={jobs.length}
            sub={running ? `${running} running now` : "all complete"} />
          <StatCard icon={<FiCheckCircle />} label="Confirmed" value={confirmed} tone="ok"
            sub="numbers that hold up" />
          <StatCard icon={<FiAlertTriangle />} label="To review" value={toReview} tone={toReview ? "bad" : undefined}
            sub="misreported / invalid / unstable" />
        </div>
      )}

      <section className={dash.section}>
        <div className={dash.activityHead}>
          <div className={dash.sectionTitle} style={{ margin: 0 }}>Recent scans</div>
          {(jobs?.length ?? 0) > 0 && (
            <Link href="/dashboard/scans" className={dash.back}>View all <FiArrowRight /></Link>
          )}
        </div>

        {jobs === null ? (
          <div className={dash.card}><TableSkeleton /></div>
        ) : recent.length === 0 ? (
          <div className={`${dash.card} ${dash.empty}`}>
            <h3>No scans yet</h3>
            <p>Verify your first repository — Calma will re-run it and recompute every number it reports.</p>
            <div style={{ marginTop: 18 }}>
              <Link href="/dashboard/verify" className={`${dash.btn} ${dash.btnAmber}`}><FiPlus /> Verify a repo</Link>
            </div>
            {err && <p className={dash.muted} style={{ marginTop: 14, fontSize: 12 }}>({err})</p>}
          </div>
        ) : (
          <div className={dash.card}>
            <table className={dash.table}>
              <thead>
                <tr><th>Repository</th><th>Verdicts</th><th>Status</th><th>When</th></tr>
              </thead>
              <tbody>
                {recent.map((j) => (
                  <tr key={j.id}>
                    <td>
                      <Link href={`/dashboard/scans/${j.id}`} className={dash.rowlink}>
                        <b>{repoLabel(j.repo)}</b>
                      </Link>
                    </td>
                    <td><VerdictSummary counts={j.counts} nClaims={j.n_claims} /></td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      <StatusPill status={j.status} />
                      <RunProgress status={j.status} progress={j.progress} stage={j.stage} />
                    </td>
                    <td className={dash.muted}>{timeAgo(j.created)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function StatCard({ icon, label, value, sub, tone }:
  { icon: React.ReactNode; label: string; value: number; sub?: string; tone?: "ok" | "bad" }) {
  return (
    <div className={dash.statCard}>
      <div className={`${dash.statCardIcon} ${tone === "ok" ? dash.toneOk : tone === "bad" ? dash.toneBad : ""}`}>
        {icon}
      </div>
      <div className={dash.statCardValue}>{value}</div>
      <div className={dash.statCardLabel}>{label}</div>
      {sub && <div className={dash.statCardSub}>{sub}</div>}
    </div>
  );
}

function StatSkeleton() {
  return (
    <div className={dash.statCards}>
      {[0, 1, 2].map((i) => <div key={i} className={`${dash.skel} ${dash.skelPanel}`} style={{ height: 118 }} />)}
    </div>
  );
}

function TableSkeleton() {
  return (
    <div>
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className={dash.skelRow}>
          <div className={`${dash.skel} ${dash.skelCell}`} />
          <div className={`${dash.skel} ${dash.skelPill}`} />
          <div className={`${dash.skel} ${dash.skelCellSm}`} />
        </div>
      ))}
    </div>
  );
}
