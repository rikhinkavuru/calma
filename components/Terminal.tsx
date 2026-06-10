"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/* The hero demo: real Calma output, auto-typed. Three scenarios (REFUTED / CONFIRMED /
   CAN'T-CONFIRM) cycle automatically; tabs jump directly. All output text is verbatim
   from actual runs of the shipped engine. */

type Scene = {
  key: "fail" | "pass" | "warn";
  tab: string;
  cmd: string;
  out: ReactNode;
};

const SCENES: Scene[] = [
  {
    key: "fail",
    tab: "REFUTED",
    cmd: 'calma verify ./btc-backtest "+14,698% backtest"',
    out: (
      <>
        {"\n"}
        <span className="v-fail">REFUTED</span>
        <span className="dim">  (confidence 98/100)</span>  -  the result does not hold{"\n"}
        {"  "}<span className="dim">- also: strategy underperforms the trivial baseline (edge -0.7422 &lt;= 0)</span>{"\n"}
        {"  "}claimed <b style={{ color: "var(--ink)" }}>+14,698%</b>  →  recomputed{" "}
        <span className="v-fail">-32.4%</span>{"\n"}
        {"  "}reproduce: <span className="dim">calma replay ./btc-backtest/.calma/run</span>{"\n"}
        {"  "}<span className="dim">scope: reproducibility, recomputation, baseline | isolation: seatbelt-verified</span>{"\n"}
        {"\n"}
        <span className="dim">[gate exit 1 - re-ran the code on the held-out data. The claim was best-of-100 in-sample tries.]</span>
      </>
    ),
  },
  {
    key: "pass",
    tab: "CONFIRMED",
    cmd: 'calma verify . "accuracy 0.87"',
    out: (
      <>
        {"\n"}
        <span className="v-pass">CONFIRMED</span>
        <span className="dim">  (confidence 95/100)</span>  -  reproduces and recomputes to the claim{"\n"}
        {"  "}<span className="dim">- recomputed value matches the claim within the calibrated budget</span>{"\n"}
        {"  "}<span className="dim">scope: reproducibility, recomputation | determinism: controlled-to-bit</span>{"\n"}
        {"\n"}
        <span className="dim">[gate exit 0 - the number was rebuilt from predictions.csv, not read from the claim]</span>
      </>
    ),
  },
  {
    key: "warn",
    tab: "CAN'T-CONFIRM",
    cmd: 'calma verify ./sim "mean 50.0"',
    out: (
      <>
        {"\n"}
        <span className="v-warn">CAN&apos;T-CONFIRM</span>  -  not verifiable yet{"\n"}
        {"  "}<span className="dim">- determinism is measured-band: unseeded randomness in main.py</span>{"\n"}
        {"  "}<span className="v-warn">fix:</span> set a fixed seed and write outputs deterministically, then re-run{"\n"}
        {"  "}<span className="dim">scope: reproducibility, recomputation | determinism: measured-band</span>{"\n"}
        {"\n"}
        <span className="dim">[gate exit 1 - Calma names the exact unblock instead of guessing. It never cries wolf.]</span>
      </>
    ),
  },
];

const TYPE_MS = 26;
const HOLD_MS = 5200;

export function Terminal() {
  const [scene, setScene] = useState(0);
  const [typed, setTyped] = useState(0);
  const [done, setDone] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reduced = useRef(false);

  useEffect(() => {
    reduced.current = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }, []);

  useEffect(() => {
    const s = SCENES[scene];
    if (reduced.current) {
      setTyped(s.cmd.length);
      setDone(true);
      return;
    }
    if (typed < s.cmd.length) {
      timer.current = setTimeout(() => setTyped((n) => n + 1), TYPE_MS);
    } else if (!done) {
      timer.current = setTimeout(() => setDone(true), 360);
    } else {
      timer.current = setTimeout(() => {
        setScene((n) => (n + 1) % SCENES.length);
        setTyped(0);
        setDone(false);
      }, HOLD_MS);
    }
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [scene, typed, done]);

  const s = SCENES[scene];
  return (
    <div className="term" role="img" aria-label="Calma terminal demo: verify a claim, get a deterministic verdict">
      <div className="term__bar">
        <span className="term__dot" />
        <span className="term__dot" />
        <span className="term__dot" />
        <span className="term__title">calma — verification by re-execution</span>
        <div className="term__tabs">
          {SCENES.map((sc, i) => (
            <button
              key={sc.key}
              className={
                "term__tab" + (i === scene ? ` term__tab--on t-${sc.key}` : "")
              }
              onClick={() => {
                setScene(i);
                setTyped(0);
                setDone(false);
              }}
            >
              {sc.tab}
            </button>
          ))}
        </div>
      </div>
      <div className="term__body">
        <span className="term__prompt">$ </span>
        <span className="term__cmd">{s.cmd.slice(0, typed)}</span>
        {!done && <span className="term__caret" />}
        {done && <span className="term__out">{s.out}</span>}
      </div>
    </div>
  );
}
