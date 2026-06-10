"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/* The bench: verification happening in front of you. Three real specimens — the visitor
   presses RE-RUN and watches the engine's actual output sequence land a verdict.
   Show, don't tell: every line below is verbatim from the shipped engine. */

type Specimen = {
  label: string;
  claimKind: string;
  claimed: string;
  recomputed: string;
  sub: string;
  cmd: string;
  steps: { t: string; ok: boolean }[];
  verdict: "fail" | "pass" | "warn";
  stamp: string;
  fix?: string;
  strike: boolean;
};

const SPECIMENS: Specimen[] = [
  {
    label: "SPECIMEN 01 / BTC-BACKTEST",
    claimKind: "Claimed — annual return",
    claimed: "+14,698%",
    recomputed: "−32.4%",
    sub: "Submitted by an agent. Best of 100 in-sample tries; the survivor was reported.",
    cmd: '$ calma verify ./btc-backtest "+14,698% backtest"',
    steps: [
      { t: "re-executing in sandbox · network off", ok: true },
      { t: "recomputing from runs/oos/returns.csv", ok: true },
      { t: "diff: gap 147.30  »  budget 1e-9", ok: false },
      { t: "baseline: loses to buy-and-hold (edge −0.74)", ok: false },
    ],
    verdict: "fail",
    stamp: "Refuted",
    strike: true,
  },
  {
    label: "SPECIMEN 02 / CLASSIFIER",
    claimKind: "Claimed — accuracy",
    claimed: "0.87",
    recomputed: "0.87",
    sub: "An agent's model eval. The number was rebuilt from predictions.csv, not read from the claim.",
    cmd: '$ calma verify . "accuracy 0.87"',
    steps: [
      { t: "re-executing in sandbox · network off", ok: true },
      { t: "recomputing from predictions.csv", ok: true },
      { t: "diff: within calibrated budget", ok: true },
      { t: "determinism: controlled-to-bit", ok: true },
    ],
    verdict: "pass",
    stamp: "Confirmed",
    strike: false,
  },
  {
    label: "SPECIMEN 03 / SIMULATION",
    claimKind: "Claimed — mean",
    claimed: "50.0",
    recomputed: "—",
    sub: "Unseeded randomness: two identical runs disagree. Nothing flaky can confirm anything.",
    cmd: '$ calma verify ./sim "mean 50.0" --check-determinism',
    steps: [
      { t: "re-executing in sandbox · run 1 of 2", ok: true },
      { t: "re-executing in sandbox · run 2 of 2", ok: true },
      { t: "artifacts differ across identical re-runs", ok: false },
    ],
    verdict: "warn",
    stamp: "Can't confirm",
    fix: "fix: set a fixed seed, then re-run",
    strike: false,
  },
];

const STEP_MS = 850;

export function Bench() {
  const [idx, setIdx] = useState(0);
  const [phase, setPhase] = useState(0); // 0..steps.length = log lines, +1 = verdict
  const [running, setRunning] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const started = useRef(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  const s = SPECIMENS[idx];
  const total = s.steps.length + 1;

  const run = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    setPhase(0);
    setRunning(true);
  }, []);

  const pick = useCallback(
    (i: number) => {
      if (timer.current) clearTimeout(timer.current);
      setIdx(i);
      setPhase(0);
      setRunning(true);
    },
    []
  );

  // advance the run one beat at a time
  useEffect(() => {
    if (!running) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      setPhase(total);
      setRunning(false);
      return;
    }
    if (phase < total) {
      timer.current = setTimeout(() => setPhase((p) => p + 1), STEP_MS);
    } else {
      setRunning(false);
    }
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [running, phase, total]);

  // auto-run once, when the bench scrolls into view
  useEffect(() => {
    const el = rootRef.current;
    if (!el || started.current) return;
    const io = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting && !started.current) {
          started.current = true;
          run();
          io.disconnect();
        }
      },
      { threshold: 0.35 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [run]);

  const verdictShown = phase >= total;

  return (
    <div className="bench" ref={rootRef}>
      <div className="bench-top">
        <span className="u-label">{s.label}</span>
        <div className="dots" role="tablist" aria-label="Specimens">
          {SPECIMENS.map((sp, i) => (
            <button
              key={sp.label}
              className={i === idx ? "on" : ""}
              role="tab"
              aria-selected={i === idx}
              aria-label={sp.label}
              onClick={() => pick(i)}
            />
          ))}
        </div>
      </div>

      <div className="bench-body">
        <div className="bench-claim">
          <div className="k">{s.claimKind}</div>
          <div className={"n" + (verdictShown && s.strike ? " struck" : "")}>{s.claimed}</div>
          <p className="sub">{s.sub}</p>
          <div className="re">
            <div className="k2">Recomputed — from raw outputs</div>
            <div className="n2" style={{ color: verdictShown && s.verdict === "fail" ? "var(--vermilion)" : "var(--ink)" }}>
              {verdictShown ? s.recomputed : "· · ·"}
            </div>
          </div>
        </div>

        <div className="bench-run">
          <div className="bench-log" aria-live="polite">
            <div className="cmd">{s.cmd}</div>
            {s.steps.map(
              (line, i) =>
                phase > i && (
                  <div key={i} className={line.ok ? "ok" : ""}>
                    {line.t}
                  </div>
                )
            )}
          </div>
          <div>
            <span className={"stamp " + s.verdict + (verdictShown ? " show" : "")}>{s.stamp}</span>
            {verdictShown && s.fix && <div className="bench-fix">{s.fix}</div>}
          </div>
          <div className="bench-foot">
            <button className="tile" onClick={run} aria-label="Re-run this verification" disabled={running}>
              <svg viewBox="0 0 24 24">
                <path d="M20 11a8 8 0 1 0-2.3 6.3M20 5v6h-6" />
              </svg>
            </button>
            <span className="u-label" style={{ color: "var(--ash)" }}>
              {running ? "Re-running" : "Re-run"}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
