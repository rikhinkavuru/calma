"use client";

// The Overview is the console's home: a flat, mostly-monochrome dashboard. A
// get-started panel pairs with an activity bar-graph; the verdict history rolls
// up to inline figures (not boxed stat tiles); recent runs expand into the diff.
// Amber is the only accent. All derived from one list call.
import { useMemo, useState } from "react";
import Link from "next/link";
import { FiUploadCloud, FiTerminal, FiBookOpen, FiShield, FiArrowRight, FiPlay, FiFileText } from "react-icons/fi";
import type { Verification } from "@/lib/calma";
import { outcome } from "./outcome";
import { VerificationRows } from "./VerificationRows";
import styles from "./dashboard.module.css";

type RangeKey = "1d" | "7d" | "30d" | "all";
const RANGES: { key: RangeKey; label: string; days: number | null }[] = [
  { key: "1d", label: "24h", days: 1 },
  { key: "7d", label: "7d", days: 7 },
  { key: "30d", label: "30d", days: 30 },
  { key: "all", label: "All", days: null },
];

export function Overview({ items }: { items: Verification[] }) {
  const [range, setRange] = useState<RangeKey>("all");
  const rangeLabel = RANGES.find((r) => r.key === range)?.label ?? "All";

  const filtered = useMemo(() => {
    const days = RANGES.find((r) => r.key === range)?.days ?? null;
    if (days === null) return items;
    const cutoff = Date.now() - days * 86_400_000;
    return items.filter((v) => {
      const t = Date.parse(v.created_at);
      return Number.isNaN(t) ? true : t >= cutoff;
    });
  }, [items, range]);

  const stats = useMemo(() => {
    let ok = 0, bad = 0, idle = 0;
    for (const v of filtered) {
      const k = outcome(v.verdict || v.repo_verdict).key;
      if (k === "ok") ok++;
      else if (k === "bad") bad++;
      else idle++;
    }
    const total = filtered.length;
    return { total, ok, bad, idle, passRate: total ? Math.round((ok / total) * 100) : 0 };
  }, [filtered]);

  // bucket runs into bars: hourly over 24h, otherwise daily over the window.
  const chart = useMemo(() => buildChart(filtered, range), [filtered, range]);
  const recent = useMemo(() => filtered.slice(0, 8), [filtered]);

  return (
    <div className={styles.main}>
      <div className={styles.row}>
        <div>
          <h1 className={styles.h1}>Overview</h1>
          <p className={styles.sub}>Every result Calma re-executed and recomputed to ground truth.</p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div className={styles.rangetabs} role="tablist" aria-label="Time range">
            {RANGES.map((r) => (
              <button
                key={r.key}
                role="tab"
                aria-selected={range === r.key}
                className={`${styles.rangetab} ${range === r.key ? styles.rangetabOn : ""}`}
                onClick={() => setRange(r.key)}
              >
                {r.label}
              </button>
            ))}
          </div>
          <Link href="/dashboard/submit" className={styles.btn}>
            <FiUploadCloud /> New verification
          </Link>
        </div>
      </div>

      <div className={styles.panelGrid}>
        {/* get started */}
        <section className={styles.panel}>
          <div className={styles.getStartedHead}>
            <div className={styles.getStartedText}>
              <h2 className={styles.panelTitle}>Verify a result</h2>
              <p>Upload a result bundle and Calma re-runs it offline, recomputes the headline number from the raw outputs, then proves or breaks the claim.</p>
            </div>
            <div className={styles.getStartedCtas}>
              <Link href="/install" className={styles.btnGhost} style={ghostBtn}><FiFileText /> Docs</Link>
              <Link href="/dashboard/submit" className={styles.btn} style={ghostBtn}>New verification</Link>
            </div>
          </div>
          <Link href="/dashboard/v/demo" className={styles.dashedCta}>
            <FiPlay /> Run the sample demo
          </Link>
        </section>

        {/* activity */}
        <section className={styles.panel}>
          <div className={styles.activityHead}>
            <span className={styles.panelTitle} style={{ fontSize: 16 }}>Activity</span>
            <span className={styles.panelMeta}>{range === "all" ? "30 days" : `last ${rangeLabel}`}</span>
          </div>
          <div className={styles.chart} aria-hidden>
            {chart.bars.map((b, i) => (
              <div
                key={i}
                className={`${styles.chartBar} ${b.count > 0 ? styles.chartBarHit : ""}`}
                style={{ height: `${Math.max(2, (b.count / chart.max) * 100)}%` }}
                title={`${b.label}: ${b.count}`}
              />
            ))}
          </div>
          <div className={styles.chartAxis}>
            <span>{chart.startLabel}</span>
            <span>{chart.endLabel}</span>
          </div>
          <div className={styles.statline}>
            <StatItem num={stats.total} name="runs" />
            <StatItem num={stats.ok} name="confirmed" dot="ok" />
            <StatItem num={stats.bad} name="caught" dot="bad" />
            <StatItem num={`${stats.passRate}%`} name="pass rate" />
          </div>
        </section>
      </div>

      <p className={styles.sectionLabel}>Explore</p>
      <div className={styles.quickgrid}>
        <QuickAction href="/dashboard/submit" icon={<FiUploadCloud />}
          title="Run a verification" desc="Upload a result bundle and recompute its headline number." />
        <QuickAction href="/dashboard/v/demo" icon={<FiShield />}
          title="Open a sample proof" desc="A real signed run, replayed instantly — verifies in your browser." />
        <QuickAction href="/install" icon={<FiTerminal />}
          title="Wire the Stop-hook" desc="Zero-touch guardrail for Claude Code: verify on every agent stop." />
        <QuickAction href="/recipes" icon={<FiBookOpen />}
          title="Browse recipes" desc="628 metrics across trading, ML, stats, and engineering." />
      </div>

      <p className={styles.sectionLabel} style={{ marginTop: 36 }}>Recent runs</p>
      {recent.length > 0 ? (
        <VerificationRows items={recent} />
      ) : (
        <div className={styles.card}>
          <div className={styles.empty}>
            <h3>Nothing in this window</h3>
            <p>No verifications in the last {rangeLabel}. Widen the range or submit a result.</p>
          </div>
        </div>
      )}
    </div>
  );
}

const ghostBtn: React.CSSProperties = { fontSize: 13, padding: "8px 13px" };

function StatItem({ num, name, dot }: { num: number | string; name: string; dot?: "ok" | "bad" }) {
  const dotCls = dot === "ok" ? styles.vdotOk : dot === "bad" ? styles.vdotBad : null;
  return (
    <div className={styles.statItem}>
      <span className={styles.statNum}>{num}</span>
      <span className={styles.statName}>{dotCls && <i className={`${styles.vdot} ${dotCls}`} />}{name}</span>
    </div>
  );
}

function QuickAction({
  href, icon, title, desc,
}: { href: string; icon: React.ReactNode; title: string; desc: string }) {
  return (
    <Link href={href} className={styles.quick}>
      <span className={styles.quickIcon}>{icon}</span>
      <span className={styles.quickTitle}>{title} <FiArrowRight className={styles.quickArrow} /></span>
      <span className={styles.quickDesc}>{desc}</span>
    </Link>
  );
}

// Build the activity bars: 24 hourly buckets for the 24h range, otherwise daily
// buckets across the window (capped at 30 bars for "all").
function buildChart(items: Verification[], range: RangeKey) {
  const now = Date.now();
  const hourly = range === "1d";
  const n = hourly ? 24 : range === "7d" ? 7 : 30;
  const sizeMs = hourly ? 3_600_000 : 86_400_000;
  const start = now - n * sizeMs;
  const bars = Array.from({ length: n }, (_, i) => ({ count: 0, label: "", ts: start + i * sizeMs }));
  for (const v of items) {
    const t = Date.parse(v.created_at);
    if (Number.isNaN(t)) continue;
    const idx = Math.floor((t - start) / sizeMs);
    if (idx >= 0 && idx < n) bars[idx].count++;
  }
  const fmt = (ts: number) =>
    hourly
      ? new Date(ts).toLocaleTimeString([], { hour: "numeric" })
      : new Date(ts).toLocaleDateString([], { month: "numeric", day: "numeric" });
  bars.forEach((b) => (b.label = fmt(b.ts)));
  const max = Math.max(1, ...bars.map((b) => b.count));
  return { bars, max, startLabel: fmt(start), endLabel: fmt(now) };
}
