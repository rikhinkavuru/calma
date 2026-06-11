"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useInView } from "./chrome";

/* The demo: one verification, typed out like a real terminal session.
   When the run finishes, four flowchart lines fan out from a single
   junction on the terminal's edge to boxes that show what happened
   inside each step. Each step shares a subtle hue between its terminal
   line and its box. */

type Line = { text: string; cls: string; typed?: boolean; pause: number };

const SCRIPT: Line[] = [
  { text: '$ calma verify . "the model is 87% accurate"', cls: "p", typed: true, pause: 600 },
  { text: "  re-running the work in a sandbox ......... done", cls: "t-rerun", pause: 900 },
  { text: "  rebuilding the number from raw outputs ... 0.84", cls: "t-recompute", pause: 900 },
  { text: "  comparing  reported 0.87  vs  rebuilt 0.84", cls: "t-compare", pause: 1000 },
  { text: "", cls: "out", pause: 100 },
  { text: "  VERDICT: REFUTED — the real number is 0.84", cls: "verdict", pause: 400 },
];

const STEPS: { key: string; kicker: string; body: ReactNode }[] = [
  {
    key: "rerun",
    kicker: "Re-run",
    body: <>The sandbox proves itself before it&apos;s trusted — network blocked, secrets unreadable. Then the work runs again from scratch.</>,
  },
  {
    key: "recompute",
    kicker: "Recompute",
    body: <>The number is rebuilt from the raw output files. The AI&apos;s report is never trusted — or even read.</>,
  },
  {
    key: "compare",
    kicker: "Compare",
    body: <>0.87 vs 0.84 is outside the calibrated tolerance — a real break, not hardware noise or rounding. When it can&apos;t be sure, it says so instead of guessing.</>,
  },
  {
    key: "verdict",
    kicker: "Verdict",
    body: <>Decided by a deterministic script, not a model&apos;s opinion. Anyone can replay the whole check with one command.</>,
  },
];

type Geom = { w: number; h: number; conns: string[] };

export function Demo() {
  const [ref, seen] = useInView<HTMLDivElement>(0.35);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const termRef = useRef<HTMLDivElement | null>(null);
  const boxRefs = useRef<(HTMLDivElement | null)[]>([]);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  const [run, setRun] = useState(0);
  const [lines, setLines] = useState<{ text: string; cls: string }[]>([]);
  const [done, setDone] = useState(false);
  const [connected, setConnected] = useState(0);
  const [geom, setGeom] = useState<Geom | null>(null);

  const measure = useCallback(() => {
    const c = containerRef.current;
    const t = termRef.current;
    if (!c || !t) return;
    if (t.offsetWidth === 0) return;
    /* offsetLeft/offsetTop are layout positions — they ignore the reveal
       transform on the boxes, so the endpoints are where the boxes LAND,
       not where they start. (getBoundingClientRect included the 14px
       slide-in offset, which is what made curves end inside the boxes.) */
    const jx = t.offsetLeft + t.offsetWidth;
    const jy = t.offsetTop + t.offsetHeight / 2;
    const conns: string[] = [];
    boxRefs.current.forEach((b) => {
      if (!b) return;
      const bx = b.offsetLeft - 0.5; /* the border's outer edge — touch, never cross */
      const by = b.offsetTop + b.offsetHeight / 2;
      const mx = jx + (bx - jx) * 0.5;
      conns.push(`M ${jx} ${jy} C ${mx} ${jy}, ${mx} ${by}, ${bx} ${by}`);
    });
    setGeom({ w: c.offsetWidth, h: c.offsetHeight, conns });
  }, []);

  useEffect(() => {
    const c = containerRef.current;
    if (!c) return;
    const ro = new ResizeObserver(() => measure());
    ro.observe(c);
    return () => ro.disconnect();
  }, [measure]);

  useEffect(() => {
    if (!seen) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setDone(false);
    setConnected(0);

    if (reduced) {
      setLines(SCRIPT.map(({ text, cls }) => ({ text, cls })));
      setDone(true);
      setConnected(STEPS.length);
      requestAnimationFrame(() => requestAnimationFrame(measure));
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

    /* terminal done → wait for the final layout (prompt line included) →
       measure → fan the connectors out one by one */
    later(() => {
      setDone(true);
      requestAnimationFrame(() => requestAnimationFrame(measure));
    }, at);
    at += 250;
    STEPS.forEach((_, i) => {
      later(() => setConnected(i + 1), at + i * 380);
    });

    return () => {
      timers.current.forEach(clearTimeout);
      timers.current = [];
    };
  }, [seen, run, measure]);

  return (
    <div className="demo" ref={(el) => { containerRef.current = el; ref.current = el; }}>
      {geom && (
        <svg
          className="demo__net"
          viewBox={`0 0 ${geom.w} ${geom.h}`}
          width={geom.w}
          height={geom.h}
          aria-hidden="true"
        >
          {/* the connectors, each drawn from the junction when its step lands */}
          {STEPS.map((s, i) => (
            <path
              key={s.key}
              className={"net__line" + (i < connected ? " is-on" : "")}
              d={geom.conns[i]}
              pathLength={1}
            />
          ))}
        </svg>
      )}

      <div className="term" ref={termRef} aria-label="Demo: calma verifies a claimed number and refutes it">
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
            key={s.key}
            ref={(el) => { boxRefs.current[i] = el; }}
            className={`dstep dstep--${s.key}` + (i < connected ? " in" : "")}
          >
            <span className="dstep__k">{`0${i + 1} — ${s.kicker}`}</span>
            <p>{s.body}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
