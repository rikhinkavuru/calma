"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useInView } from "./chrome";

/* The demo: one verification, typed out like a real terminal session.
   As each step of the pipeline prints, a connector draws out to a small
   box that shows what actually happened inside that step. */

type Line = { text: string; cls: string; typed?: boolean; pause: number; step?: number };

const SCRIPT: Line[] = [
  { text: '$ calma verify . "the model is 87% accurate"', cls: "p", typed: true, pause: 600 },
  { text: "  re-running the work in a sandbox ......... done", cls: "out", pause: 1500, step: 0 },
  { text: "  rebuilding the number from raw outputs ... 0.84", cls: "out", pause: 1500, step: 1 },
  { text: "  comparing  reported 0.87  vs  rebuilt 0.84", cls: "out", pause: 1700, step: 2 },
  { text: "", cls: "out", pause: 100 },
  { text: "  VERDICT: REFUTED — the real number is 0.84", cls: "verdict", pause: 600, step: 3 },
];

const STEPS: { kicker: string; body: ReactNode }[] = [
  {
    kicker: "Re-run",
    body: <>The sandbox proves itself before it&apos;s trusted — network blocked, secrets unreadable. Then the work runs again from scratch.</>,
  },
  {
    kicker: "Recompute",
    body: <>The number is rebuilt from the raw output files. The AI&apos;s report is never trusted — or even read.</>,
  },
  {
    kicker: "Compare",
    body: <>0.87 vs 0.84 is outside the calibrated tolerance — a real break, not hardware noise. Calma never cries wolf.</>,
  },
  {
    kicker: "Verdict",
    body: <>Decided by a deterministic script, not a model&apos;s opinion. Anyone can replay the whole check with one command.</>,
  },
];

export function Demo() {
  const [ref, seen] = useInView<HTMLDivElement>(0.35);
  const [run, setRun] = useState(0);
  const [lines, setLines] = useState<{ text: string; cls: string }[]>([]);
  const [active, setActive] = useState(0);
  const [done, setDone] = useState(false);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    if (!seen) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setDone(false);

    if (reduced) {
      setLines(SCRIPT.map(({ text, cls }) => ({ text, cls })));
      setActive(STEPS.length);
      setDone(true);
      return;
    }

    setLines([]);
    setActive(0);
    let at = 400;
    const later = (fn: () => void, ms: number) => {
      timers.current.push(setTimeout(fn, ms));
    };

    SCRIPT.forEach((line, i) => {
      if (line.typed) {
        for (let c = 1; c <= line.text.length; c++) {
          const part = line.text.slice(0, c);
          later(() => {
            setLines((prev) => {
              const next = prev.slice(0, i);
              next[i] = { text: part, cls: line.cls };
              return next;
            });
          }, at);
          at += 28;
        }
      } else {
        const full = line.text;
        later(() => {
          setLines((prev) => {
            const next = prev.slice(0, i);
            next[i] = { text: full, cls: line.cls };
            return next;
          });
        }, at);
      }
      if (line.step !== undefined) {
        const upto = line.step + 1;
        later(() => setActive((a) => Math.max(a, upto)), at + 450);
      }
      at += line.pause;
    });
    later(() => setDone(true), at);

    return () => {
      timers.current.forEach(clearTimeout);
      timers.current = [];
    };
  }, [seen, run]);

  return (
    <div className="demo" ref={ref}>
      <div className="term" aria-label="Demo: calma verifies a claimed number and refutes it">
        <div className="term__bar">
          <span className="term__dots" aria-hidden="true"><i /><i /><i /></span>
          <span className="term__title">calma — one check, start to finish</span>
          <button className="term__replay" onClick={() => setRun((n) => n + 1)} disabled={!done}>
            replay ↺
          </button>
        </div>
        <div className="term__body" aria-live="off">
          {lines.map((l, i) => (
            <div key={i} className={l.cls}>
              {l.text || " "}
              {i === lines.length - 1 && !done && <span className="term__caret" />}
            </div>
          ))}
          {done && (
            <div>
              <span className="p">$ </span>
              <span className="term__caret" />
            </div>
          )}
        </div>
      </div>

      <div className="dsteps" aria-label="What happens inside each step">
        {STEPS.map((s, i) => (
          <div
            key={s.kicker}
            className={
              "dstep" +
              (i < active ? " in" : "") +
              (i === STEPS.length - 1 ? " dstep--verdict" : "")
            }
          >
            <span className="dstep__k">{`0${i + 1} — ${s.kicker}`}</span>
            <p>{s.body}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
