"use client";

import { useEffect, useRef, useState } from "react";
import { useInView } from "./chrome";

/* The demo: one verification, typed out like a real terminal session.
   The command types character by character; output lines land whole,
   the way real output does. */

type Line = { text: string; cls: string; typed?: boolean; pause: number };

const SCRIPT: Line[] = [
  { text: '$ calma verify . "the model is 87% accurate"', cls: "p", typed: true, pause: 600 },
  { text: "  re-running the work in a sandbox ......... done", cls: "out", pause: 700 },
  { text: "  rebuilding the number from raw outputs ... 0.84", cls: "out", pause: 700 },
  { text: "  comparing  reported 0.87  vs  rebuilt 0.84", cls: "out", pause: 900 },
  { text: "", cls: "out", pause: 100 },
  { text: "  VERDICT: REFUTED — the real number is 0.84", cls: "verdict", pause: 0 },
];

export function Demo() {
  const [ref, seen] = useInView<HTMLDivElement>(0.35);
  const [run, setRun] = useState(0);
  const [lines, setLines] = useState<{ text: string; cls: string }[]>([]);
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
      setDone(true);
      return;
    }

    setLines([]);
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
      at += line.pause;
    });
    later(() => setDone(true), at);

    return () => {
      timers.current.forEach(clearTimeout);
      timers.current = [];
    };
  }, [seen, run]);

  return (
    <div className="term" ref={ref} aria-label="Demo: calma verifies a claimed number and refutes it">
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
            {l.text || " "}
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
  );
}
