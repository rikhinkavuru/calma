"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useInView } from "./chrome";

/* The demo: an agent loop, not a command. The agent runs three backtests and
   reports each number; calma's zero-touch hook re-executes and recomputes every
   claim before the turn is allowed to end — two inflated numbers are blocked, one
   holds. Nobody typed a verify command. The four boxes explain the mechanism. */

type Line = { text: string; cls: string; typed?: boolean; pause: number };

const SCRIPT: Line[] = [
  { text: "agent   running 3 backtests, reporting each result as it lands", cls: "ag", typed: true, pause: 700 },
  { text: '  1  momentum      claim:  total return +14,698%', cls: "cl", pause: 520 },
  { text: "     calma auto-verify ......  REFUTED    rebuilt -32.4%", cls: "refute", pause: 950 },
  { text: '  2  mean-revert   claim:  Sharpe 2.4', cls: "cl", pause: 520 },
  { text: "     calma auto-verify ......  REFUTED    rebuilt 0.7", cls: "refute", pause: 950 },
  { text: '  3  carry         claim:  total return +31%', cls: "cl", pause: 520 },
  { text: "     calma auto-verify ......  CONFIRMED  rebuilt +31.2%", cls: "confirm", pause: 950 },
  { text: "", cls: "out", pause: 120 },
  { text: "  2 of 3 blocked before the turn ended  -  no command typed", cls: "seal", pause: 400 },
];

const STEPS: { key: string; kicker: string; body: ReactNode }[] = [
  {
    key: "rerun",
    kicker: "No command",
    body: <>You never type a verify command. The check fires on its own the moment an agent states a number — every turn, every result, in the loop or in CI.</>,
  },
  {
    key: "recompute",
    kicker: "Reads the claim",
    body: <>A precision-first sniffer lifts the metric and value straight out of the agent&apos;s own words. No SDK, no instrumentation, no change to the code under test.</>,
  },
  {
    key: "compare",
    kicker: "Re-runs it",
    body: <>The work runs again in a sandbox and the number is rebuilt from the raw outputs on deterministic kernels. The agent&apos;s report is never trusted, or even read.</>,
  },
  {
    key: "verdict",
    kicker: "Blocks the lie",
    body: <>Only a definitive refute stops the turn — the wrong number dies in the loop instead of reaching you. Confirmed and can&apos;t-confirm pass silently.</>,
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
          at += 22;
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

      <div className="term" ref={termRef} aria-label="Demo: an agent reports three backtests; calma auto-verifies each one and blocks the two wrong numbers before the turn ends">
        <div className="term__bar">
          <span className="term__dots" aria-hidden="true"><i /><i /><i /></span>
          <span className="term__title">calma — your agents, checking themselves</span>
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
              <span className="ag">agent</span>
              <span className="term__caret" />
            </div>
          )}
        </div>
      </div>

      <div className="dsteps" aria-label="How the zero-touch check works">
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
