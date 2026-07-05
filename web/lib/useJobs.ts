"use client";

// Live job list for the console surfaces (Overview + Scans). Fetches /api/jobs and re-polls so a running
// deep verify updates in place — status, the "run 1/2 · Nm elapsed" progress line, and the verdict counts
// when it finishes — instead of the founder having to reload. Polls fast (every 4s) while anything is
// running/queued, and slowly (every 20s) otherwise so a scan started in another tab still shows up. The
// backend job list is durable now (server persists to a volume), so this reflects real history, not just the
// current instance's memory.
import { useEffect, useRef, useState } from "react";
import type { JobSummary } from "@/lib/verify";

const FAST_MS = 4000;
const SLOW_MS = 20000;

export function useJobs(): { jobs: JobSummary[] | null; err: string | null } {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let alive = true;

    const tick = async () => {
      try {
        const r = await fetch("/api/jobs", { cache: "no-store" });
        if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.error || `status ${r.status}`);
        const d = await r.json();
        if (!alive) return;
        const list: JobSummary[] = Array.isArray(d) ? d : [];
        setJobs(list);
        setErr(null);
        const active = list.some((j) => j.status === "running" || j.status === "queued");
        timer.current = setTimeout(tick, active ? FAST_MS : SLOW_MS);
      } catch (e) {
        if (!alive) return;
        setErr(e instanceof Error ? e.message : String(e));
        setJobs((prev) => prev ?? []);       // first load failed → empty; a later poll can still recover
        timer.current = setTimeout(tick, SLOW_MS);
      }
    };

    tick();
    return () => {
      alive = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  return { jobs, err };
}
