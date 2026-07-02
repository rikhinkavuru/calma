// A REAL, recorded run of demo-repo/ against the actual deployed engine (captured 2026-07-02, backend
// commit with the discovery/target-scoping + demo-tier fixes). The demo replays this instead of running the
// pipeline live on every page view: a live run needs an E2B sandbox boot + clone + install + 2 runs
// (~20s, real compute cost, and a real chance of a slow/timed-out sandbox on a landing-page visitor) for a
// result that's IDENTICAL every time anyway — demo-repo/eval.py is fully seeded, so re-running it live buys
// nothing but latency and cost. This is not fabricated data: it's the actual logs/claims/verdicts from one
// genuine verify job, replayed with compressed timing. The backend demo API (app/api/demo/verify) still
// exists and works — it's just no longer called by the client. Re-record by POSTing to it directly, polling
// /api/demo/verify/{id} until status=done, and pasting the returned logs/claims/run back in here.
import type { Claim, Job } from "@/lib/verify";

export const RECORDED_LOGS: string[] = [
  "[+   0.0s] cloning rikhinkavuru/calma",
  "[+   2.5s] isolating verification in a resource-capped child (mem≤700MB, cpu≤1740s, wall≤1740s)",
  "[+   2.6s] starting verification",
  "[+   2.6s] planning the run (concurrent with sandbox boot)",
  "[+   2.8s] determinism not statically proven (uses tensorflow without a fixed seed; numpy default_rng() with no seed; reads a nondeterministic source (time.time)) → keeping the empirical k=2 check",
  "[+   2.8s] preparing runnable environment",
  "[+   2.8s] running in E2B microVM",
  "[+   2.8s] E2B: creating microVM (lifetime 36m)…",
  "[+   4.4s] E2B: microVM up (1.6s) — uploading repo + capture shim",
  "[+   6.6s] E2B: staged 322 file(s) as one 10.9MB archive",
  "[+  12.4s] AI plan (40% conf): This repo is the Calma verification engine itself; its headline number ('293 checks') is the pass count of its own pytest suite under spike/",
  "[+  14.9s] installer: uv (fast)",
  "[+  14.9s] E2B: installing 1 dep(s) — scikit-learn",
  "[+  15.0s] E2B: environment ready (12s total)",
  "[+  15.0s] E2B: running `demo-repo/eval.py` (run 1/2)…",
  "[+  17.5s] … still working — 15s elapsed / 1740s budget · child 80MB/700MB",
  "[+  18.8s]   | Test accuracy: 73.3%",
  "[+  19.0s] E2B: run 1/2 done — 4s, exit 0, 1 computation(s) captured",
  "[+  19.0s] E2B: running `demo-repo/eval.py` (run 2/2)…",
  "[+  20.1s]   | Test accuracy: 73.3%",
  "[+  20.3s] E2B: run 2/2 done — 1s, exit 0, 1 computation(s) captured",
  "[+  20.3s] captured 2 computation(s)",
  "[+  20.3s] sandbox: 17.5s (build 12.2s + 2 run(s)) — one sandbox reused",
  "[+  20.3s] discovering reported numbers",
  "[+  20.3s] discovered 2 claim(s)",
  "[+  20.3s] top claim by salience: accuracy=94.2% (0.73)",
  "[+  20.3s] checking committed splits and prediction artifacts",
  "[+  20.3s] comparing claimed vs produced vs recomputed",
  "[+  20.3s] verification complete",
  "[+  20.5s] done — REFUTED:1, CONFIRMED:1",
];

export const RECORDED_CLAIMS: Claim[] = [
  {
    id: "d0_accuracy",
    metric: "accuracy",
    claimed: "94.2%",
    context: "",
    location: "README.md",
    source: "text",
    verdict: "REFUTED",
    reason: "the reported value '94.2%' is not what the code produced (0.733333); Δ=0.209",
    diff: { claimed: "94.2%", produced: 0.7333333333333333, recomputed: 0.7333333333333333 },
    provenance: null,
    validity: { invalidating: [], advisory: [] },
  },
  {
    id: "d1_accuracy",
    metric: "accuracy",
    claimed: "73.3%",
    context: "",
    location: "stdout",
    source: "text",
    verdict: "CONFIRMED",
    reason: "claim == runtime value == independent recompute, deterministic",
    diff: { claimed: "73.3%", produced: 0.7333333333333333, recomputed: 0.7333333333333333 },
    provenance: null,
    validity: { invalidating: [], advisory: [] },
  },
];

export const RECORDED_RUN: Job["run"] = {
  ran: true,
  calls: 2,
  entry: "demo-repo/eval.py",
  error: "",
};

// (timestamp_seconds, isPipelineStep) parsed once — used to schedule the replay.
export function parsedLogTimes(): number[] {
  return RECORDED_LOGS.map((l) => {
    const m = l.match(/^\[\+\s*([\d.]+)s\]/);
    return m ? parseFloat(m[1]) : 0;
  });
}
