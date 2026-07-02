"use client";

// The no-signup demo: ONE button, ONE fixed sample repo (demo-repo/ in this monorepo). Replays a REAL,
// recorded run (recording.ts) instead of executing the pipeline live on every page view — demo-repo/eval.py
// is fully seeded, so a live re-run is guaranteed to reproduce the exact same numbers every time; running it
// live bought nothing but ~20s of E2B sandbox latency, real compute cost per visitor, and a real chance of a
// slow/timed-out sandbox on a landing page. The log lines, claims, and verdicts below are all genuine —
// captured from one real verify job — just replayed with compressed timing instead of re-executed.
import { useEffect, useRef, useState } from "react";
import type { Claim } from "@/lib/verify";
import { ORDER, pillTier, verdictLabel } from "@/lib/verdict";
import { RECORDED_CLAIMS, RECORDED_LOGS, parsedLogTimes } from "./recording";
import s from "../dashboard/verify.module.css";

function pillClass(verdict: string): string {
  return s[pillTier(verdict)];
}

function num(x: unknown): string {
  return typeof x === "number" && Number.isFinite(x) ? Number(x).toPrecision(5) : "—";
}

// Real elapsed was ~20.5s; replay compresses that into ~5.5s (scale ~0.27) so the demo stays snappy while
// still reading as "things are actually happening in sequence," not an instant jump-cut. Never faster than
// 90ms between lines (still readable) or slower than 700ms (never drags).
const SCALE = 0.27;
const MIN_GAP_MS = 90;
const MAX_GAP_MS = 700;
const TIMES = parsedLogTimes();

function logLineClass(l: string): string {
  if (/]\s+\|\s/.test(l)) return s.logStream;
  if (/]\s+(pip\||installer:|E2B: installing)/.test(l)) return s.logPip;
  if (/(exceeded|killed|stopped|failed|error|crash)/i.test(l)) return s.logWarn;
  return "";
}

export function DemoClient() {
  const [visibleLines, setVisibleLines] = useState(0);
  const [done, setDone] = useState(false);
  const [running, setRunning] = useState(false);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const bodyRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [visibleLines]);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  function run() {
    if (running) return;
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setDone(false);
    setVisibleLines(0);
    setRunning(true);
    let at = 0;
    for (let i = 0; i < RECORDED_LOGS.length; i++) {
      const gapS = i === 0 ? 0 : TIMES[i] - TIMES[i - 1];
      at += Math.min(MAX_GAP_MS, Math.max(MIN_GAP_MS, gapS * 1000 * SCALE));
      timers.current.push(setTimeout(() => setVisibleLines(i + 1), at));
    }
    timers.current.push(setTimeout(() => { setRunning(false); setDone(true); }, at + 250));
  }

  const claims: Claim[] = RECORDED_CLAIMS.slice().sort(
    (a, b) => ORDER.indexOf(a.verdict) - ORDER.indexOf(b.verdict),
  );
  const shown = RECORDED_LOGS.slice(0, visibleLines);

  return (
    <div>
      <button className="btn-primary" onClick={run} disabled={running} type="button">
        {running ? "verifying…" : done ? "Run it again" : "Run the demo"}
        {!running && <span className="arrow" aria-hidden="true"> →</span>}
      </button>
      <p className="micro" style={{ marginTop: 10 }}>
        Runs a tiny seeded sklearn classifier (
        <a href="https://github.com/rikhinkavuru/calma/tree/main/demo-repo" target="_blank" rel="noreferrer">
          demo-repo
        </a>
        ) that claims 94.2% accuracy in its README. Watch what Calma actually recomputes — a real recorded
        run, replayed (demo-repo is fully seeded, so re-running it live reproduces the exact same numbers).
      </p>

      {(running || visibleLines > 0) && (
        <div className={s.console} style={{ marginTop: 14 }}>
          <div className={s.consoleHead}>
            <span className={s.consoleHeadL}>
              <span className={`${s.dot} ${running ? s.dotLive : s.dotDone}`} />
              <span className={s.consoleStage}>{running ? "verifying…" : "done"}</span>
            </span>
          </div>
          <div className={s.consoleBody} ref={bodyRef}>
            {shown.map((l, i) => <div key={i} className={logLineClass(l)}>{l}</div>)}
          </div>
        </div>
      )}

      {done && (
        <table className={s.table} style={{ marginTop: 18 }}>
          <thead>
            <tr>
              <th>Metric</th><th>Claimed</th><th>Recomputed</th><th>Verdict</th><th>Where</th><th>Why</th>
            </tr>
          </thead>
          <tbody>
            {claims.map((c) => {
              const d = c.diff || {};
              const recomp = d.recomputed != null ? num(d.recomputed) : num(d.produced);
              return (
                <tr key={c.id}>
                  <td><b>{c.metric}</b></td>
                  <td className={s.mono}>{c.claimed}</td>
                  <td className={s.mono}>{recomp}</td>
                  <td><span className={`${s.pill} ${pillClass(c.verdict)}`}>{verdictLabel(c.verdict)}</span></td>
                  <td className={s.where}>{(c.context || c.location || c.source || "").slice(0, 90)}</td>
                  <td className={s.why}>{c.reason}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default DemoClient;
