"use client";

/* HeroConsole — interactive "verifier console" for the hero.
   Pick a strategy, toggle scope, watch it verify against a live equity curve.
   Plain-language verdicts; the claimed Sharpe counts down to the verified one. */
import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";

type Check = { name: string; result: "pass" | "fail"; note: string };
type Strategy = {
  id: string;
  file: string;
  claimed: string;
  verified: string;
  verdict: "pass" | "fail";
  plain: string;
  checks: Check[];
  detail: { tag: string; code: string } | null;
  vpath: string; // verified equity curve
};

// shared "claimed" curve — the seductive rising line every backtest shows
const CLAIMED_PATH = "M2,64 L38,55 L74,46 L110,33 L146,22 L182,11 L218,5";

const STRATEGIES: Strategy[] = [
  {
    id: "momentum",
    file: "momentum_reversal_v4.py",
    claimed: "2.81",
    verified: "0.31",
    verdict: "fail",
    plain: "Looks like Sharpe 2.81. It's really 0.31 — the model was reading tomorrow's price.",
    checks: [
      { name: "point-in-time provenance", result: "fail", note: "vol_zscore_20d reads close[t+1]" },
      { name: "independent recomputation", result: "pass", note: "reconciled to raw fills" },
      { name: "unseen-data re-run", result: "fail", note: "Sharpe collapses on holdout" },
      { name: "invariant assertion", result: "fail", note: "signal post-dates its fill" },
    ],
    detail: { tag: "look-ahead leak", code: "features.py:142 · close.shift(-1) reads t+1" },
    vpath: "M2,64 L38,63 L74,64 L110,61 L146,63 L182,62 L218,64",
  },
  {
    id: "pairs",
    file: "pairs_meanrev_v2.py",
    claimed: "1.42",
    verified: "1.39",
    verdict: "pass",
    plain: "Holds up. Returns reproduce from the raw trades and survive on data it never saw.",
    checks: [
      { name: "point-in-time provenance", result: "pass", note: "37 signals, all knowable at t" },
      { name: "independent recomputation", result: "pass", note: "Δ within 0.4% of claim" },
      { name: "unseen-data re-run", result: "pass", note: "1.39 on 2023Q4 holdout" },
      { name: "invariant assertion", result: "pass", note: "all identities hold" },
    ],
    detail: null,
    vpath: "M2,64 L38,56 L74,48 L110,36 L146,26 L182,16 L218,10",
  },
  {
    id: "earnings",
    file: "earnings_drift_v7.py",
    claimed: "2.05",
    verified: "0.44",
    verdict: "fail",
    plain: "The universe quietly dropped the names that went to zero. Survivors only.",
    checks: [
      { name: "point-in-time provenance", result: "pass", note: "no forward leakage" },
      { name: "independent recomputation", result: "pass", note: "reconciled to raw fills" },
      { name: "unseen-data re-run", result: "fail", note: "delisted names excluded" },
      { name: "invariant assertion", result: "pass", note: "all identities hold" },
    ],
    detail: { tag: "survivorship bias", code: "universe.py:61 · filters on is_active == True" },
    vpath: "M2,64 L38,55 L74,45 L110,38 L146,46 L182,57 L218,63",
  },
];

export function HeroConsole() {
  const reduced = useRef(
    typeof window !== "undefined" && window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches
  ).current;
  const [sel, setSel] = useState(0);
  const [phase, setPhase] = useState<"idle" | "running" | "done">("idle");
  const [step, setStep] = useState(0);
  const [scope, setScope] = useState({ holdout: true, costs: true });
  const [disp, setDisp] = useState<number | null>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const raf = useRef<number | null>(null);
  const strat = STRATEGIES[sel];

  const clearTimers = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  };

  const run = (idx?: number) => {
    const s = STRATEGIES[idx == null ? sel : idx];
    clearTimers();
    setDisp(null);
    setPhase("running");
    setStep(0);
    if (reduced) {
      setStep(s.checks.length);
      setPhase("done");
      return;
    }
    s.checks.forEach((_, i) => {
      timers.current.push(setTimeout(() => setStep(i + 1), 360 + i * 460));
    });
    timers.current.push(setTimeout(() => setPhase("done"), 360 + s.checks.length * 460 + 160));
  };

  const pick = (idx: number) => {
    setSel(idx);
    run(idx);
  };

  useEffect(() => {
    const t = setTimeout(() => run(0), reduced ? 0 : 650);
    return () => {
      clearTimeout(t);
      clearTimers();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const done = phase === "done";
  const running = phase === "running";

  // scope toggles re-derive the verdict from the live checks, so the stamp can
  // never contradict a SKIP'd check: any fail -> FAILED, any skip -> can't
  // confirm, otherwise VERIFIED.
  const effChecks = strat.checks.map((c) => {
    if (c.name.startsWith("unseen") && !scope.holdout) return { ...c, result: "skip" as const, note: "holdout disabled" };
    return c;
  });
  const anyFail = effChecks.some((c) => c.result === "fail");
  const anySkip = effChecks.some((c) => c.result === "skip");
  const effVerdict: "fail" | "pass" | "wait" = anyFail ? "fail" : anySkip ? "wait" : "pass";
  const decided = done && effVerdict !== "wait"; // a real, confirmable verdict
  const verdictClass = done ? effVerdict : "wait";

  // count the claimed Sharpe down (or up) to the verified figure once decided
  useEffect(() => {
    if (raf.current) cancelAnimationFrame(raf.current);
    if (!done) {
      setDisp(null);
      return;
    }
    const from = parseFloat(strat.claimed);
    const to = parseFloat(strat.verified);
    if (reduced) {
      setDisp(to);
      return;
    }
    const t0 = performance.now();
    const dur = 720;
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / dur);
      const e = 1 - Math.pow(1 - p, 3);
      setDisp(from + (to - from) * e);
      if (p < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [done, sel]);

  const verifiedStr = decided ? (disp == null ? strat.verified : disp.toFixed(2)) : "—";

  return (
    <div className="hc">
      <div className="hc__bar">
        <span className="hc__verb mono">verify</span>
        <div className="hc__files mono">
          {STRATEGIES.map((s, i) => (
            <button key={s.id} className={"hc__file" + (i === sel ? " is-sel" : "")} onClick={() => pick(i)}>
              <span className={"hc__fdot hc__fdot--" + s.verdict} />
              {s.file}
            </button>
          ))}
        </div>
        <motion.button className="hc__run" onClick={() => run()} whileTap={{ scale: 0.96 }}>
          {running ? <span className="hc__spin" /> : <span className="hc__play" />}
          {done ? "Re-verify" : running ? "Verifying" : "Verify"}
        </motion.button>
      </div>

      <div className="hc__body">
        <div className="hc__left">
          <div className="hc__sub mono">checks</div>
          <div className="hc__checks">
            {effChecks.map((c, i) => {
              const resolved = step > i;
              const state = c.result === "skip" ? "skip" : resolved ? c.result : running || done ? "run" : "idle";
              return (
                <div className={"hc__check hc__check--" + state} key={c.name}>
                  <span className="hc__cdot" />
                  <span className="hc__cname mono">{c.name}</span>
                  <span className="hc__cstat mono">
                    {state === "run" ? "···" : state === "pass" ? "PASS" : state === "fail" ? "FAIL" : state === "skip" ? "SKIP" : ""}
                  </span>
                </div>
              );
            })}
          </div>
          <div className="hc__sub mono" style={{ marginTop: 18 }}>
            scope · <span className="hc__hint">click to change</span>
          </div>
          <div className="hc__chips mono">
            <button className={"hc__chip" + (scope.holdout ? " is-on" : "")} onClick={() => setScope((s) => ({ ...s, holdout: !s.holdout }))}>
              holdout 2023Q4
            </button>
            <button className={"hc__chip" + (scope.costs ? " is-on" : "")} onClick={() => setScope((s) => ({ ...s, costs: !s.costs }))}>
              trading costs
            </button>
          </div>
        </div>

        <div className="hc__right">
          <div className={"hc__verdict hc__verdict--" + verdictClass}>
            <span className="hc__vstamp">
              {!done ? "verifying…" : effVerdict === "pass" ? "VERIFIED" : effVerdict === "fail" ? "FAILED" : "CAN'T CONFIRM"}
            </span>
            {done && (
              <p className="hc__plain">
                {effVerdict === "wait"
                  ? "Holdout disabled — Calma can't confirm this out-of-sample. Re-enable holdout to verify."
                  : strat.plain}
              </p>
            )}
          </div>

          <div className="hc__panel">
            <div className="hc__metrics">
              <div className="hc__m">
                <span className="hc__m-k mono">claimed</span>
                <span className="hc__m-v mono">
                  Sharpe <b>{strat.claimed}</b>
                </span>
              </div>
              <span className="hc__m-arrow mono" aria-hidden="true">
                →
              </span>
              <div className="hc__m">
                <span className="hc__m-k mono" style={{ color: decided ? (effVerdict === "pass" ? "var(--pass)" : "var(--fail)") : "var(--ink-3)" }}>
                  verified by calma
                </span>
                <span className="hc__m-v mono">
                  Sharpe <b className={decided ? (effVerdict === "pass" ? "hc__ok" : "hc__fail") : ""}>{verifiedStr}</b>
                </span>
              </div>
            </div>

            <div className={"hc__curve hc__curve--" + verdictClass + (decided ? " is-done" : "")} aria-hidden="true">
              <svg viewBox="0 0 220 70" width="100%" height="70" preserveAspectRatio="none">
                <path className="hc__cl" d={CLAIMED_PATH} vectorEffect="non-scaling-stroke" />
                <path className="hc__vf" d={strat.vpath} pathLength={1} vectorEffect="non-scaling-stroke" />
              </svg>
              <span className="hc__curve-k hc__curve-k--c mono">claimed</span>
              <span className="hc__curve-k hc__curve-k--v mono">verified</span>
            </div>
          </div>

          {decided && effVerdict === "fail" && strat.detail && (
            <div className="hc__leak mono show">
              <span className="hc__leak-tag">{strat.detail.tag}</span>
              <code>{strat.detail.code}</code>
            </div>
          )}
          {decided && effVerdict === "pass" && !strat.detail && (
            <div className="hc__clean mono show">
              <span className="hc__clean-tag">no issues found</span>
              <code>every signal knowable at t · returns reproduce · holds out-of-sample</code>
            </div>
          )}
          <a className="hc__more mono" href="#roadmap">
            this ships as an open-source skill <span aria-hidden="true">↓</span>
          </a>
        </div>
      </div>
    </div>
  );
}
