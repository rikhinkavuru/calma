"use client";

// The live e2e log console — every step from clone → build → run → recompute, streamed as it happens. Shared
// by the verify page (live run) and the scan-detail page (replay/post-mortem). Auto-follows the tail unless
// the user has scrolled up, so they can read back without being yanked to the bottom on each poll.
import { useEffect, useRef } from "react";
import type { Job } from "@/lib/verify";
import s from "./verify.module.css";

export function LogConsole({ job }: { job: Pick<Job, "id" | "status" | "stage" | "logs"> }) {
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const follow = useRef(true);
  const logs = job.logs || [];
  const running = job.status === "running" || job.status === "queued";

  useEffect(() => {
    const el = bodyRef.current;
    if (el && follow.current) el.scrollTop = el.scrollHeight;
  }, [logs.length]);

  function onScroll() {
    const el = bodyRef.current;
    if (el) follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }

  const dotClass = running ? s.dotLive : job.status === "error" ? s.dotErr : s.dotDone;
  return (
    <div className={s.console}>
      <div className={s.consoleHead}>
        <span className={s.consoleHeadL}>
          <span className={`${s.dot} ${dotClass}`} />
          <span className={s.consoleStage}>{running ? `${job.stage}…` : job.status}</span>
        </span>
        <a className={s.consoleRaw} href={`/api/verify/${job.id}/logs`} target="_blank" rel="noreferrer">
          {logs.length} lines · raw ↗
        </a>
      </div>
      <div className={s.consoleBody} ref={bodyRef} onScroll={onScroll}>
        {logs.length === 0 ? (
          <div className={s.consoleEmpty}>starting…</div>
        ) : (
          logs.map((l, i) => <div key={i} className={logLineClass(l)}>{l}</div>)
        )}
      </div>
    </div>
  );
}

// tint by line kind: the run's own streamed stdout (`| `), pip/install output (`pip| ` / `! `), and the
// budget/kill/error lines that explain a stopped job.
export function logLineClass(l: string): string {
  if (/]\s+\|\s/.test(l)) return s.logStream;
  if (/]\s+(pip\||!\s)/.test(l)) return s.logPip;
  if (/(exceeded|killed|stopped|failed|error|crash)/i.test(l)) return s.logWarn;
  return "";
}
